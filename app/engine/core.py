from __future__ import annotations

from typing import Any, Optional, Union
import json
import logging
import asyncio
import unicodedata
from html import escape
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clan_service import ClanService
from app.config import Settings
from app.enums import Role
from app.utils.rate_limiter import global_rate_limiter, per_chat_limiter

from app.keyboards import (
    go_group_keyboard,
    group_url_from_chat_id,
)
from app.models import (
    ActivityScoreEvent,
    BotSetting,
    CreditBlockedUser,
    Game,
    GameLog,
    GamePlayer,
    Group,
    User,
)

logger = logging.getLogger(__name__)

INVISIBLE_NAME_CHARS = {
    "\u034f", "\u061c", "\u115f", "\u1160", "\u17b4", "\u17b5", "\u180e",
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b",
    "\u202c", "\u202d", "\u202e", "\u2060", "\u2061", "\u2062", "\u2063",
    "\u2064", "\u2066", "\u2067", "\u2068", "\u2069", "\u2800", "\u3164", "\ufeff",
}

# Global semaphore capping simultaneous outbound Telegram API calls.
_OUTBOUND_SEM: asyncio.Semaphore | None = None


def _get_outbound_sem() -> asyncio.Semaphore:
    """Return the module-level outbound semaphore, creating it on first use."""
    global _OUTBOUND_SEM
    if _OUTBOUND_SEM is None:
        _OUTBOUND_SEM = asyncio.Semaphore(30)
    return _OUTBOUND_SEM


class CoreMixin:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clan_service = ClanService(session_factory)
        self._group_language_cache: dict[int, tuple[float, str]] = {}
        self._group_return_url_cache: dict[int, tuple[float, str]] = {}
        self._active_participants_cache: dict[int, tuple[float, Optional[int], frozenset[int]]] = {}
        self._chat_permission_cache: dict[tuple[int, str], tuple[float, str]] = {}
        self._blocked_users_cache: dict[int, tuple[float, bool]] = {}
        self._credit_blocked_cache: dict[int, tuple[float, bool]] = {}

        self._cache_ttl_seconds = 10.0
        self._return_url_cache_ttl_seconds = 3600.0
        self._chat_permission_cache_ttl = 5.0
        self._blocked_users_cache_ttl = 30.0
        self._cache_limit = 20000
        self._inactive_elimination_rounds = 2
        self._night_inactivity_exempt_roles = {
            Role.COMMISSAR,
            Role.DON,
            Role.HOJIAKA,
            Role.MASHKA,
            Role.DOCTOR,
        }
        self._pending_sorcerer_judgements: dict[tuple[int, int, int], tuple[float, str]] = {}

    def _monotonic(self) -> float:
        return asyncio.get_running_loop().time()

    def _prune_cache_if_needed(self, cache: dict[int, tuple[float, object]]) -> None:
        if len(cache) < self._cache_limit:
            return
        now = self._monotonic()
        expired_keys = [key for key, value in cache.items() if value[0] <= now]
        for key in expired_keys:
            cache.pop(key, None)
        if len(cache) < self._cache_limit:
            return
        for key in list(cache)[: max(1, self._cache_limit // 10)]:
            cache.pop(key, None)

    def _invalidate_group_cache(self, chat_id: int) -> None:
        self._group_language_cache.pop(chat_id, None)
        self._group_return_url_cache.pop(chat_id, None)

    def _invalidate_game_cache(self, chat_id: int) -> None:
        self._active_participants_cache.pop(chat_id, None)

    def invalidate_chat_permission_cache(self, chat_id: int) -> None:
        for phase in ("night", "day"):
            self._chat_permission_cache.pop((chat_id, phase), None)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def get_effective_display_name(user: Optional[User]) -> str:
        if not user:
            return "Unknown"
        now = datetime.now(timezone.utc)
        vip_until = user.vip_until
        if vip_until is not None:
            if vip_until.tzinfo is None:
                vip_until = vip_until.replace(tzinfo=timezone.utc)
            else:
                vip_until = vip_until.astimezone(timezone.utc)
        is_vip = vip_until is not None and vip_until > now

        if not is_vip:
            return escape(user.display_name or "Unknown")

        raw_nick = (user.vip_nickname or "").strip() or (user.display_name or "Unknown")
        safe_nick = escape(raw_nick[:30])
        style = getattr(user, "vip_style", "bold") or "bold"
        if style == "bold":
            styled_nick = f"<b>{safe_nick}</b>"
        elif style == "italic":
            styled_nick = f"<i>{safe_nick}</i>"
        elif style == "code":
            styled_nick = f"<code>{safe_nick}</code>"
        elif style == "underline":
            styled_nick = f"<u>{safe_nick}</u>"
        elif style == "strikethrough":
            styled_nick = f"<s>{safe_nick}</s>"
        else:
            styled_nick = safe_nick

        badge_html = ""
        if user.vip_badge:
            b_val = str(user.vip_badge).strip()
            if b_val.isdigit():
                badge_html = f'<tg-emoji emoji-id="{b_val}">⭐</tg-emoji>'
            else:
                badge_html = escape(b_val)

        pos = getattr(user, "vip_badge_pos", "before") or "before"
        if badge_html:
            if pos == "after":
                return f"{styled_nick} {badge_html}"
            else:
                return f"{badge_html} {styled_nick}"
        return styled_nick

    @staticmethod
    def format_user_mention(user: Optional[User], user_id: Optional[int] = None, fallback_name: str = "Unknown") -> str:
        if not user:
            uid = user_id or 0
            return f'<a href="tg://user?id={uid}">{escape(fallback_name)}</a>'

        now = datetime.now(timezone.utc)
        vip_until = user.vip_until
        if vip_until is not None:
            if vip_until.tzinfo is None:
                vip_until = vip_until.replace(tzinfo=timezone.utc)
            else:
                vip_until = vip_until.astimezone(timezone.utc)
        is_vip = vip_until is not None and vip_until > now

        uid = user.telegram_id
        if not is_vip:
            safe_name = escape(user.display_name or fallback_name)
            return f'<a href="tg://user?id={uid}">{safe_name}</a>'

        raw_nick = (user.vip_nickname or "").strip() or (user.display_name or fallback_name)
        safe_nick = escape(raw_nick[:30])

        style = getattr(user, "vip_style", "bold") or "bold"
        if style == "bold":
            styled_nick = f"<b>{safe_nick}</b>"
        elif style == "italic":
            styled_nick = f"<i>{safe_nick}</i>"
        elif style == "code":
            styled_nick = f"<code>{safe_nick}</code>"
        elif style == "underline":
            styled_nick = f"<u>{safe_nick}</u>"
        elif style == "strikethrough":
            styled_nick = f"<s>{safe_nick}</s>"
        else:
            styled_nick = safe_nick

        link_html = f'<a href="tg://user?id={uid}">{styled_nick}</a>'

        if user.vip_badge:
            b_val = str(user.vip_badge).strip()
            badge_html = f'<tg-emoji emoji-id="{b_val}">⭐</tg-emoji>' if b_val.isdigit() else escape(b_val)
            pos = getattr(user, "vip_badge_pos", "before") or "before"
            if pos == "after":
                return f"{link_html} {badge_html}"
            else:
                return f"{badge_html} {link_html}"

        return link_html

    @staticmethod
    def _tg_mention(user_id: int, display_name: str) -> str:
        name = display_name or "Unknown"
        if "<tg-emoji" in name:
            parts = name.split("<tg-emoji", maxsplit=1)
            before = parts[0].strip()
            rest = "<tg-emoji" + parts[1]
            emoji_parts = rest.split("</tg-emoji>", maxsplit=1)
            badge_html = emoji_parts[0] + "</tg-emoji>"
            after = emoji_parts[1].strip() if len(emoji_parts) > 1 else ""

            nick_part = (before + " " + after).strip()
            link = f'<a href="tg://user?id={user_id}">{nick_part}</a>'
            if before:
                return f"{link} {badge_html}"
            return f"{badge_html} {link}"

        if "<" in name and ">" in name:
            safe_name = name
        else:
            safe_name = escape(name)
        return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

    @staticmethod
    def _activity_now_text() -> str:
        uz_time = datetime.now(timezone(timedelta(hours=5)))
        return uz_time.strftime("%d.%m.%Y %H:%M")

    def _add_activity_points(
        self,
        session: AsyncSession,
        game: Game,
        player: GamePlayer,
        points: int,
        source: str = "daily",
    ) -> None:
        if points <= 0:
            return
        session.add(
            ActivityScoreEvent(
                chat_id=game.chat_id,
                game_id=game.id,
                user_telegram_id=player.telegram_id,
                user_name=player.display_name or "User",
                points=points,
                source=source,
            )
        )

    async def _safe_send_message(self, bot: Bot, chat_id: int, text: str, **kwargs: Any) -> Any | None:
        await global_rate_limiter.acquire()
        await per_chat_limiter.acquire(chat_id)
        async with _get_outbound_sem():
            try:
                return await asyncio.wait_for(bot.send_message(chat_id, text, **kwargs), timeout=12)
            except TelegramRetryAfter as exc:
                wait_secs = min(getattr(exc, "retry_after", 5) + 1, 30)
                logger.warning(
                    "TelegramRetryAfter on send to chat_id=%s, waiting %ss then retrying",
                    chat_id, wait_secs,
                )
                await asyncio.sleep(wait_secs)
                try:
                    return await asyncio.wait_for(bot.send_message(chat_id, text, **kwargs), timeout=12)
                except Exception as retry_exc:
                    logger.warning("Send failed after RetryAfter retry chat_id=%s: %s", chat_id, retry_exc)
                    return None
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.warning("Unable to send message to chat_id=%s: %s", chat_id, exc)
                return None
            except asyncio.TimeoutError:
                logger.warning("Timed out sending message to chat_id=%s", chat_id)
                return None
            except Exception:
                logger.exception("Unexpected error while sending message to chat_id=%s", chat_id)
                return None

    async def _safe_edit_message_reply_markup(
        self,
        bot: Bot,
        *,
        chat_id: int,
        message_id: int,
        reply_markup: object | None = None,
    ) -> bool:
        await global_rate_limiter.acquire()
        await per_chat_limiter.acquire(chat_id)
        async with _get_outbound_sem():
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
                )
                return True
            except TelegramRetryAfter as exc:
                wait_secs = min(getattr(exc, "retry_after", 5) + 1, 30)
                logger.warning(
                    "TelegramRetryAfter on edit_markup chat_id=%s msg=%s, waiting %ss",
                    chat_id, message_id, wait_secs,
                )
                await asyncio.sleep(wait_secs)
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
                    )
                    return True
                except Exception as retry_exc:
                    logger.warning("Edit reply_markup failed after RetryAfter chat_id=%s msg=%s: %s", chat_id, message_id, retry_exc)
                    return False
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.warning("Unable to edit reply_markup chat_id=%s msg=%s: %s", chat_id, message_id, exc)
                return False

            except Exception:
                logger.exception("Unexpected error editing reply_markup chat_id=%s msg=%s", chat_id, message_id)
                return False


    async def _get_bot_setting_value(self, session: AsyncSession, key: str, default: str = "") -> str:
        setting = (await session.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        return str(setting.value) if setting and setting.value is not None else default

    async def _set_bot_setting_value(self, session: AsyncSession, key: str, value: str) -> None:
        setting = (await session.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
        if setting is None:
            session.add(BotSetting(key=key, value=value))
        else:
            setting.value = value

    @staticmethod
    def _display_name_from_tg(tg_user: TgUser) -> str:
        first = tg_user.first_name or ""
        last = tg_user.last_name or ""
        name = f"{first} {last}".strip() or tg_user.username or "User"
        return name

    @staticmethod
    def _profile_name_from_tg(tg_user: TgUser) -> str:
        first = (tg_user.first_name or "").strip()
        last = (tg_user.last_name or "").strip()
        name = f"{first} {last}".strip() or (tg_user.username or "").strip() or "User"
        return name

    @staticmethod
    def _has_visible_nickname(name: str) -> bool:
        for char in name:
            if char in INVISIBLE_NAME_CHARS or char.isspace():
                continue
            category = unicodedata.category(char)
            if category[0] in {"L", "N", "P", "S"}:
                return True
        return False


    async def ensure_user(self, tg_user: TgUser, language: Optional[str] = None) -> User:
        async with self.session_factory() as session:
            stmt = select(User).where(User.telegram_id == tg_user.id)
            user = (await session.execute(stmt)).scalar_one_or_none()
            full_name = self._display_name_from_tg(tg_user)
            if user is None:
                user = User(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    display_name=full_name,
                    language=language or self.settings.default_language,
                    language_selected=bool(language),
                    diamonds=0,
                    dollar=0,
                )
                session.add(user)
            else:
                user.username = tg_user.username
                user.display_name = full_name
                if language:
                    user.language = language
                    user.language_selected = True
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self.session_factory() as session:
            return (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()

    async def get_or_create_group(self, chat_id: int, title: str) -> Group:
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(
                    chat_id=chat_id,
                    title=title,
                    language=self.settings.default_language,
                    registration_timeout=self.settings.registration_timeout,
                    night_timeout=self.settings.night_timeout,
                    day_discussion_timeout=self.settings.day_discussion_timeout,
                    day_voting_timeout=self.settings.day_voting_timeout,
                    min_players=self.settings.min_players,
                )
                session.add(group)
            else:
                group.title = title
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
                if group is None:
                    raise
                group.title = title
                await session.commit()
            await session.refresh(group)
            self._invalidate_group_cache(chat_id)
            return group

    async def set_user_language(self, telegram_id: int, language: str) -> None:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                user = User(
                    telegram_id=telegram_id,
                    display_name="Unknown",
                    language=language,
                    language_selected=True,
                )
                session.add(user)
            else:
                user.language = language
                user.language_selected = True
            await session.commit()

    async def set_group_language(self, chat_id: int, language: str) -> None:
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group", language=language)
                session.add(group)
            else:
                group.language = language
            await session.commit()
        self._invalidate_group_cache(chat_id)

    async def get_user_language(self, telegram_id: int) -> str:
        user = await self.get_user(telegram_id)
        if user and user.language:
            return user.language
        return self.settings.default_language

    async def get_group_language(self, chat_id: int) -> str:
        now = self._monotonic()
        cached = self._group_language_cache.get(chat_id)
        if cached and cached[0] > now:
            return cached[1]
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            language = group.language if group else self.settings.default_language
        self._prune_cache_if_needed(self._group_language_cache)
        self._group_language_cache[chat_id] = (now + self._cache_ttl_seconds, language)
        return language

    async def group_return_url(self, bot: Bot, chat_id: int) -> str:
        now = self._monotonic()
        cached = self._group_return_url_cache.get(chat_id)
        if cached and cached[0] > now:
            return cached[1]

        url = group_url_from_chat_id(chat_id)
        try:
            chat = await bot.get_chat(chat_id)
            username = getattr(chat, "username", None)
            if username:
                url = f"https://t.me/{username}"
                self._prune_cache_if_needed(self._group_return_url_cache)
                self._group_return_url_cache[chat_id] = (now + self._return_url_cache_ttl_seconds, url)
                return url

            invite_link = getattr(chat, "invite_link", None)
            if invite_link:
                url = invite_link
                self._prune_cache_if_needed(self._group_return_url_cache)
                self._group_return_url_cache[chat_id] = (now + self._return_url_cache_ttl_seconds, url)
                return url

            try:
                url = await bot.export_chat_invite_link(chat_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

        self._prune_cache_if_needed(self._group_return_url_cache)
        self._group_return_url_cache[chat_id] = (now + self._return_url_cache_ttl_seconds, url)
        return url

    async def group_return_keyboard(self, bot: Bot, chat_id: int):
        return go_group_keyboard(chat_id, await self.group_return_url(bot, chat_id))

    async def log(self, game_id: int, event_type: str, payload: str) -> None:
        async with self.session_factory() as session:
            session.add(GameLog(game_id=game_id, event_type=event_type, payload=payload))
            await session.commit()

    @staticmethod
    def _player_log_snapshot(player: Optional[GamePlayer]) -> Optional[dict[str, object]]:
        if player is None:
            return None
        return {
            "telegram_id": player.telegram_id,
            "display_name": player.display_name,
            "role": player.role,
            "team": player.team,
            "alive": player.alive,
        }

    def _build_log_payload(
        self,
        game: Game,
        *,
        actor: Optional[GamePlayer] = None,
        target: Optional[GamePlayer] = None,
        **metadata: object,
    ) -> str:
        payload = {
            "chat_id": game.chat_id,
            "status": game.status,
            "phase": game.phase,
            "day_number": game.day_number,
            "night_number": game.night_number,
            "actor": self._player_log_snapshot(actor),
            "target": self._player_log_snapshot(target),
            "metadata": metadata,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _add_game_log(
        self,
        session: AsyncSession,
        game: Game,
        event_type: str,
        *,
        actor: Optional[GamePlayer] = None,
        target: Optional[GamePlayer] = None,
        **metadata: object,
    ) -> None:
        session.add(
            GameLog(
                game_id=game.id,
                event_type=event_type,
                payload=self._build_log_payload(game, actor=actor, target=target, **metadata),
            )
        )

    async def is_credit_blocked(self, telegram_id: int) -> bool:
        now = self._monotonic()
        cached = self._credit_blocked_cache.get(telegram_id)
        if cached is not None:
            expire_time, result = cached
            if expire_time > now:
                return result
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(CreditBlockedUser.telegram_id).where(
                        CreditBlockedUser.telegram_id == telegram_id
                    )
                )
            ).scalar_one_or_none()
        is_blocked = row is not None
        self._credit_blocked_cache[telegram_id] = (now + self._blocked_users_cache_ttl, is_blocked)
        self._prune_cache_if_needed(self._credit_blocked_cache)  # type: ignore[arg-type]
        return is_blocked

    def invalidate_credit_blocked_cache(self, telegram_id: int) -> None:
        self._credit_blocked_cache.pop(telegram_id, None)

    def invalidate_blocked_user_cache(self, telegram_id: int) -> None:
        self._blocked_users_cache.pop(telegram_id, None)
