from __future__ import annotations

from typing import Any, Optional, Union, TYPE_CHECKING
import csv
import io
import json
import logging
import asyncio
import unicodedata
import random
from html import escape
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, User as TgUser
from aiogram.utils.formatting import Bold, Code, CustomEmoji, Text, TextLink
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clan_service import ClanService
from app.config import BASE_DIR, Settings
from app.engine.core import CoreMixin
from app.enums import ActionType, GamePhase, GameStatus, LogType, Role, Team
from app.keyboards import (
    JOKER_CARD_LABELS,
    confirm_hang_keyboard,
    commissar_action_keyboard,
    commissar_target_keyboard,
    couple_request_keyboard,
    go_private_keyboard,
    go_role_private_keyboard,
    go_vote_private_keyboard,
    go_group_keyboard,
    group_url_from_chat_id,
    hero_game_keyboard,
    hero_market_buy_keyboard,
    joker_death_card_keyboard,
    joker_target_keyboard,
    joker_victim_card_keyboard,
    judge_cancel_keyboard,
    lobby_keyboard,
    miner_keyboard,
    profile_dashboard_keyboard,
    PROFILE_EMOJI_BY_FIELD,
    sorcerer_judgement_keyboard,
    sorcerer_hang_revenge_keyboard,
    target_keyboard,
    vote_keyboard,
)
from app.models import (
    ActivityScoreEvent,
    BotSetting,
    CoupleRelationship,
    CreditBlockedUser,
    DiamondGiveaway,
    DiamondTransaction,
    DollarTransaction,
    Game,
    GameLog,
    GamePlayer,
    Group,
    HangVote,
    Hero,
    NightAction,
    NightPrompt,
    PremiumGroup,
    PremiumBlockedUser,
    PremiumGroupContribution,
    SkipDecision,
    User,
    Vote,
)
from app.roles import (
    ACTIVE_ROLE_POOL,
    GAME_MODES,
    ROLE_META,
    SHOP_ROLE_BY_VALUE,
    build_role_set,
    normalize_game_mode,
    role_label,
    role_preset_label,
    role_preset_max_players,
    role_team,
)
from app.hero import (
    HERO_ADD_POINTS_AMOUNT,
    HERO_ADD_POINTS_PRICE_DIAMONDS,
    HERO_ATTACK_ROLES,
    HERO_BUY_PRICE_DIAMONDS,
    HERO_CANCEL_SALE_PRICE_DIAMONDS,
    HERO_DEFAULT_CHARGE,
    HERO_FULL_DEFENSE_PERCENT,
    HERO_DEFAULT_HP,
    HERO_DEFAULT_NAME,
    HERO_LEVELS,
    HERO_MARKET_CHANNEL_KEY,
    HERO_MAX_CHARGE,
    HERO_RECHARGE_PRICE_DOLLAR,
    HERO_RENAME_PRICE_DOLLAR,
    HERO_UPGRADE_DEFENSE_PRICE_DOLLAR,
    hero_level_for_points,
    safe_hero_name,
    sanitize_hero_name,
)
from app.group_settings import GroupSettingsManager
from app.scheduler import scheduler
from app.texts import t

WELCOME_ENABLED_KEY = "welcome_enabled"
WELCOME_TEXT_KEY = "welcome_text"
WELCOME_MEDIA_TYPE_KEY = "welcome_media_type"
WELCOME_MEDIA_FILE_ID_KEY = "welcome_media_file_id"
WELCOME_DEFAULT_TEXT = "guruhga xush kelibsiz!"
DOLLAR_EMOJI_ID = "5409048419211682843"
DIAMOND_EMOJI_ID = "5427168083074628963"
STAR_EMOJI_ID = "5370842086658546991"
GIFT_EMOJI_ID = "5199749070830197566"
SWORD_EMOJI_ID = "5408935401442267103"
TARGET_EMOJI_ID = "5350460637182993292"
SLEEP_EMOJI_ID = "5451959871257713464"
SEARCH_EMOJI_ID = "5188311512791393083"
BANK_EMOJI_ID = "5264895611517300926"
BOTTLE_EMOJI_ID = "5370900768796711127"
SNITCH_EMOJI_ID = "5370856771151730818"
DANCER_EMOJI_ID = "5190799832159100491"
MASK_EMOJI_ID = "5359441070201513074"
NOTE_EMOJI_ID = "5334882760735598374"
SYRINGE_EMOJI_ID = "5472317878801800869"
DRUG_EMOJI_ID = "5433635625217563352"
EYE_EMOJI_ID = "5426900601101374618"
CROSS_EMOJI_ID = "5465665476971471368"
WOLF_EMOJI_ID = "5276289730256842699"
ZOMBIE_EMOJI_ID = "5190680981824085932"
POLICE_EMOJI_ID = "5377754411319698237"
GUN_EMOJI_ID = "5222486447306602688"
SKULL_EMOJI_ID = "5469654973308476699"
PREMIUM_RESET_INTERVAL_MINUTES_KEY = "premium_reset_interval_minutes"
DIAMOND_LOG_LAST_SENT_ID_KEY = "diamond_log_last_sent_id"
CHANNEL_GIFTS_ENABLED_PREFIX = "channel_gifts_enabled:"
ADMIN_GROUP_ID_KEY = "admin_group_id"
TOURNAMENT_GAME_PREFIX = "tournament_game:"
TEAM_GAME_PREFIX = "team_game:"
HERO_INFO_HIDDEN_PREFIX = "hero_info_hidden:"
GAMBLE_ENABLED_KEY = "gamble_enabled"
GAMBLE_LOSS_VOICE_FILE_ID_KEY = "gamble_loss_voice_file_id"
GAMBLE_WIN_VOICE_FILE_ID_KEY = "gamble_win_voice_file_id"
GAMBLE_GROUP_ID_KEY = "gamble_group_id"
GAMBLE_GROUP_LINK_KEY = "gamble_group_link"
GAMBLE_PAID_GROUP_PREFIX = "gamble_paid_group:"
GAMBLE_GROUP_WEEK_PRICE_DIAMONDS = 15
GAMBLE_GROUP_PAY_DAYS = 7
DIAMOND_LOG_MIN_AMOUNT = 20

INVISIBLE_NAME_CHARS = {
    "\u034f", "\u061c", "\u115f", "\u1160", "\u17b4", "\u17b5", "\u180e",
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b",
    "\u202c", "\u202d", "\u202e", "\u2060", "\u2061", "\u2062", "\u2063",
    "\u2064", "\u2066", "\u2067", "\u2068", "\u2069", "\u2800", "\u3164", "\ufeff",
}

def _ce(symbol: str, emoji_id: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{symbol}</tg-emoji>'

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.engine.core import CoreMixin

class SocialOpsMixin:
    @staticmethod
    def _owned_roles_key(telegram_id: int) -> str:
        return f"owned_roles:{telegram_id}"


    @staticmethod
    def _owned_roles_cursor_key(telegram_id: int) -> str:
        return f"owned_roles_cursor:{telegram_id}"


    @staticmethod
    def _role_player_count_ok(role: Role, mode: str, player_count: int) -> bool:
        normalized = normalize_game_mode(mode)
        if role == Role.JOKER:
            if normalized == "classic":
                return player_count >= 17
            if normalized == "super":
                return player_count >= 12
            if normalized == "mega":
                return player_count >= 10
            return player_count >= 17
        if role == Role.PRANKSTER:
            return player_count >= 10
        if role == Role.MINER:
            if normalized == "classic":
                return player_count > 15
            if normalized == "mega":
                return player_count >= 10
            return player_count >= 15
        if role == Role.HOJIAKA:
            if normalized == "classic":
                return player_count > 14
            if normalized == "mega":
                return player_count >= 10
            return player_count >= 15
        return True


    async def user_has_news_bonus(self, bot: Bot, user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(self._news_bonus_channel_id(), user_id)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Unable to check news bonus subscription user_id=%s: %s", user_id, exc)
            return False
        except Exception:
            logger.exception("Unexpected error while checking news bonus subscription user_id=%s", user_id)
            return False
        return member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


    async def news_bonus_subscriber_ids(self, bot: Bot, user_ids: list[int]) -> set[int]:
        checks = await asyncio.gather(
            *(self.user_has_news_bonus(bot, user_id) for user_id in user_ids),
            return_exceptions=True,
        )
        return {
            user_id
            for user_id, subscribed in zip(user_ids, checks)
            if subscribed is True
        }


    @staticmethod
    def _format_minutes(minutes: int) -> str:
        minutes = max(0, int(minutes))
        if minutes == 0:
            return "o'chirilgan"
        hours, remainder = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        parts: list[str] = []
        if days:
            parts.append(f"{days} kun")
        if hours:
            parts.append(f"{hours} soat")
        if remainder:
            parts.append(f"{remainder} daqiqa")
        return " ".join(parts) or f"{minutes} daqiqa"


    def _news_bonus_channel_id(self) -> str:
        raw = (self.settings.news_bonus_channel or "@WorldMafiaNews").strip()
        if not raw:
            return "@WorldMafiaNews"
        if raw.startswith("@"):
            return raw
        normalized = self.normalize_telegram_url(raw)
        if normalized.startswith("https://t.me/"):
            path = normalized.removeprefix("https://t.me/").strip("/")
            if path and "/" not in path and not path.startswith("+"):
                return f"@{path}"
        return raw


    @staticmethod
    def format_user_dashboard(user: User) -> str:
        def state(value: bool) -> str:
            return "🟢 ON" if value is not False else "🔴 OFF"

        def stored_role(value: Optional[str]) -> str:
            if not value:
                return "-"
            try:
                return role_label(Role(value))
            except ValueError:
                return value

        display_name = CoreMixin.format_user_mention(user)

        vip_status = ""
        if user.vip_until:
            now = datetime.now(timezone.utc)
            vip_until = user.vip_until
            if vip_until.tzinfo is None:
                vip_until = vip_until.replace(tzinfo=timezone.utc)
            else:
                vip_until = vip_until.astimezone(timezone.utc)
            if vip_until > now:
                remaining = vip_until - now
                days = remaining.days
                vip_status = f"\n👑 VIP: ✅ ({days} kun qoldi)"
            else:
                vip_status = "\n👑 VIP: ❌ (muddati tugagan)"

        # map profile fields to premium emoji ids when available
        def pce(field: str, fallback: str) -> str:
            eid = PROFILE_EMOJI_BY_FIELD.get(field)
            return _ce(fallback, eid) if eid else fallback

        return (
            f"{pce('vip','👤')} Nik: {display_name}\n"
            f'<tg-emoji emoji-id="{STAR_EMOJI_ID}">⭐</tg-emoji> ID: <code>{user.telegram_id}</code>\n\n'
            f'{_ce("💵", DOLLAR_EMOJI_ID)} Dollar: <b>{user.dollar}</b> | '
            f'{_ce("💎", DIAMOND_EMOJI_ID)} Olmos: <b>{user.diamonds}</b>{vip_status}\n\n'
            f"{pce('use_protection','🛡')} Himoya: <b>{user.protection}</b> [{state(user.use_protection)}]\n"
            f"{pce('use_killer_protection','🧿')} Qotildan himoya: <b>{user.killer_protection}</b> [{state(user.use_killer_protection)}]\n"
            f"{pce('use_vote_protection','⚖️')} Ovozdan himoya: <b>{user.vote_protection}</b> [{state(user.use_vote_protection)}]\n"
            f"{pce('use_drug_protection','💊')} Doridan himoya: <b>{user.drug_protection}</b> [{state(user.use_drug_protection)}]\n"
            f"{pce('use_miner_protection','📦')} Sirpanishdan himoya: <b>{user.miner_protection}</b> [{state(user.use_miner_protection)}]\n"
            f"{pce('use_mask','🎭')} Maska: <b>{user.mask}</b> [{state(user.use_mask)}]\n"
            f"{pce('use_fake_document','📁')} Soxta hujjat: <b>{user.fake_document}</b> [{state(user.use_fake_document)}]\n"
            f"{pce('hero','🃏')} Keyingi rolingiz: <b>{stored_role(user.next_game_role)}</b>\n"
            f"{pce('gifts','🚫')} O'chiriladigan rol: <b>{stored_role(user.next_game_disabled_role)}</b>\n\n"
            f"{pce('premium_groups','🎯')} G'alabalar: <b>{user.wins}</b>\n"
            f"{pce('vip','🎲')} Jami o'yinlar: <b>{user.total_games}</b>"
        )


    @staticmethod
    def format_user_dashboard_entities(user: User) -> dict:
        def state(value: bool) -> str:
            return ""

        def stored_role(value: Optional[str]) -> str:
            if not value:
                return "-"
            try:
                return role_label(Role(value))
            except ValueError:
                return value

        display_name = TextLink(user.display_name or "Unknown", url=f"tg://user?id={user.telegram_id}")
        vip_status = ""
        if user.vip_until:
            now = datetime.now(timezone.utc)
            vip_until = user.vip_until
            if vip_until.tzinfo is None:
                vip_until = vip_until.replace(tzinfo=timezone.utc)
            else:
                vip_until = vip_until.astimezone(timezone.utc)
            if vip_until > now:
                remaining = vip_until - now
                days = remaining.days
                vip_status = f"\n👑 VIP: ✅ ({days} kun qoldi)"
            else:
                vip_status = "\n👑 VIP: ❌ (muddati tugagan)"
        return Text(
            f"{CustomEmoji('👤', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('vip') or STAR_EMOJI_ID)} Nik: ", display_name, "\n",
            CustomEmoji("⭐", custom_emoji_id=STAR_EMOJI_ID), " ID: ", Code(str(user.telegram_id)), "\n\n",
            CustomEmoji("💵", custom_emoji_id=DOLLAR_EMOJI_ID), " Dollar: ", Bold(str(user.dollar)), " | ",
            CustomEmoji("💎", custom_emoji_id=DIAMOND_EMOJI_ID), " Olmos: ", Bold(str(user.diamonds)), vip_status, "\n\n",
            CustomEmoji('🛡', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_protection')), " Himoya: ", Bold(str(user.protection)), f" {state(user.use_protection)}\n",
            CustomEmoji('🧿', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_killer_protection')), " Qotildan himoya: ", Bold(str(user.killer_protection)), f" {state(user.use_killer_protection)}\n",
            CustomEmoji('⚖️', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_vote_protection')), " Ovozdan himoya: ", Bold(str(user.vote_protection)), f" {state(user.use_vote_protection)}\n",
            CustomEmoji('💊', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_drug_protection')), " Doridan himoya: ", Bold(str(user.drug_protection)), f" {state(user.use_drug_protection)}\n",
            CustomEmoji('📦', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_miner_protection')), " Sirpanishdan himoya: ", Bold(str(user.miner_protection)), f" {state(user.use_miner_protection)}\n",
            CustomEmoji('🎭', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_mask')), " Maska: ", Bold(str(user.mask)), f" {state(user.use_mask)}\n",
            CustomEmoji('📁', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('use_fake_document')), " Soxta hujjat: ", Bold(str(user.fake_document)), f" {state(user.use_fake_document)}\n",
            CustomEmoji('🃏', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('hero')), " Keyingi rolingiz: ", Bold(stored_role(user.next_game_role)), "\n",
            CustomEmoji('🚫', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('gifts')), " O'chiriladigan rol: ", Bold(stored_role(user.next_game_disabled_role)), "\n\n",
            CustomEmoji('🎯', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('premium_groups')), " G'alabalar: ", Bold(str(user.wins)), "\n",
            CustomEmoji('🎲', custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get('vip')), " Jami o'yinlar: ", Bold(str(user.total_games)),
        ).as_kwargs()


    async def get_giveaway_settings(self, chat_id: int) -> dict:
        gsm = GroupSettingsManager(self.session_factory)
        gs = await gsm.get_settings(chat_id)
        return {
            "giveaway_diamond": gs.giveaway_diamond,
            "giveaway_protection": gs.giveaway_protection,
        }


    async def welcome_settings(self, chat_id: int) -> dict[str, str]:
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
                await session.commit()
            return {
                "enabled": "1" if group.welcome_enabled is not False else "0",
                "text": group.welcome_text or WELCOME_DEFAULT_TEXT,
                "media_type": group.welcome_media_type or "",
                "media_file_id": group.welcome_media_file_id or "",
            }


    async def welcome_settings_text(self, chat_id: int) -> str:
        settings = await self.welcome_settings(chat_id)
        enabled = settings["enabled"] == "1"
        status = "🟢 yoqilgan" if enabled else "🔴 o'chirilgan"
        media_type = settings["media_type"] or "yo'q"
        text = escape(settings["text"])
        return (
            "👋 <b>Guruh salomlashuvi</b>\n\n"
            f"Holat: {status}\n"
            f"Media: <b>{escape(media_type)}</b>\n\n"
            "Xabar doim user metkasi bilan boshlanadi. Admin kiritgan matn metkadan keyin chiqadi.\n\n"
            f"Joriy matn:\n<code>{text}</code>"
        )


    async def toggle_welcome_enabled(self, chat_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
            group.welcome_enabled = group.welcome_enabled is False
            enabled = group.welcome_enabled is not False
            await session.commit()
        return enabled, "✅ Salomlashuv yoqildi." if enabled else "✅ Salomlashuv o'chirildi."


    async def set_welcome_text(self, chat_id: int, text: str) -> tuple[bool, str]:
        value = " ".join((text or "").strip().split())
        if not 1 <= len(value) <= 900:
            return False, "Matn 1 dan 900 belgigacha bo'lishi kerak."
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
            group.welcome_text = value
            await session.commit()
        return True, "✅ Salomlashuv matni yangilandi."


    async def set_welcome_media(self, chat_id: int, media_type: str, file_id: str) -> tuple[bool, str]:
        if media_type not in {"photo", "video", "animation", "document"} or not file_id:
            return False, "Media noto'g'ri. Photo, video, gif yoki document yuboring."
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
            group.welcome_media_type = media_type
            group.welcome_media_file_id = file_id
            await session.commit()
        return True, "✅ Salomlashuv mediasi yangilandi."


    async def clear_welcome_media(self, chat_id: int) -> str:
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
            group.welcome_media_type = ""
            group.welcome_media_file_id = ""
            await session.commit()
        return "✅ Salomlashuv mediasi o'chirildi."


    async def send_welcome_message(self, bot: Bot, chat_id: int, tg_user: TgUser) -> None:
        settings = await self.welcome_settings(chat_id)
        if settings["enabled"] != "1":
            return
        mention = self._tg_mention(tg_user.id, tg_user.full_name)
        text = escape(settings["text"] or WELCOME_DEFAULT_TEXT)
        caption = f"{mention} {text}".strip()
        media_type = settings["media_type"]
        media_file_id = settings["media_file_id"]
        try:
            if media_type == "photo" and media_file_id:
                await bot.send_photo(chat_id, media_file_id, caption=caption)
            elif media_type == "video" and media_file_id:
                await bot.send_video(chat_id, media_file_id, caption=caption)
            elif media_type == "animation" and media_file_id:
                await bot.send_animation(chat_id, media_file_id, caption=caption)
            elif media_type == "document" and media_file_id:
                await bot.send_document(chat_id, media_file_id, caption=caption)
            else:
                await bot.send_message(chat_id, caption)
        except TelegramBadRequest:
            try:
                await bot.send_message(chat_id, caption)
            except TelegramForbiddenError:
                return
        except TelegramForbiddenError:
            return


    async def top_players(self, limit: int = 10) -> list[User]:
        async with self.session_factory() as session:
            return (
                await session.execute(select(User).order_by(User.wins.desc(), User.total_games.desc()).limit(limit))
            ).scalars().all()


    async def top_players_in_group(self, chat_id: int, limit: int = 10) -> list[tuple[str, int, int]]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        GamePlayer.display_name,
                        func.sum(case((GamePlayer.won.is_(True), 1), else_=0)).label("wins"),
                        func.count(GamePlayer.id).label("total"),
                    )
                    .join(Game, Game.id == GamePlayer.game_id)
                    .where(Game.chat_id == chat_id, Game.status == GameStatus.COMPLETED.value)
                    .group_by(GamePlayer.telegram_id, GamePlayer.display_name)
                    .order_by(func.sum(case((GamePlayer.won.is_(True), 1), else_=0)).desc(), func.count(GamePlayer.id).desc())
                    .limit(limit)
                )
            ).all()
            return [(name, int(wins or 0), int(total or 0)) for name, wins, total in rows]


    async def weekly_activity_top_text(
        self,
        bot: Bot,
        chat_id: Optional[int] = None,
        *,
        admin_limit: int = 30,
        member_limit: int = 30,
    ) -> str:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=7)
        admin_limit = max(1, min(30, int(admin_limit)))
        member_limit = max(1, min(30, int(member_limit)))
        fetch_limit = max(60, admin_limit + member_limit + 20)

        async with self.session_factory() as session:
            stmt = (
                select(
                    ActivityScoreEvent.user_telegram_id,
                    func.max(ActivityScoreEvent.user_name).label("user_name"),
                    func.coalesce(func.sum(ActivityScoreEvent.points), 0).label("score"),
                )
                .where(ActivityScoreEvent.created_at >= since)
                .group_by(ActivityScoreEvent.user_telegram_id)
                .order_by(func.coalesce(func.sum(ActivityScoreEvent.points), 0).desc())
                .limit(fetch_limit)
            )
            if chat_id is not None:
                stmt = stmt.where(ActivityScoreEvent.chat_id == chat_id)
            rows = (await session.execute(stmt)).all()

        admins: list[tuple[int, str, int]] = []
        members: list[tuple[int, str, int]] = []
        for row in rows:
            user_id = int(row.user_telegram_id)
            name = row.user_name or f"ID:{user_id}"
            score = int(row.score or 0)
            if score <= 0:
                continue

            is_admin = user_id in self.settings.admin_ids if chat_id is None else False
            if chat_id is not None:
                try:
                    member = await bot.get_chat_member(chat_id, user_id)
                    is_admin = member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
                except (TelegramBadRequest, TelegramForbiddenError):
                    is_admin = False

            bucket = admins if is_admin else members
            limit = admin_limit if is_admin else member_limit
            if len(bucket) < limit:
                bucket.append((user_id, name, score))

        lines = [
            "📊 <b>Oxirgi 7 kunlik faollik</b>",
            f"⏰ {self._activity_now_text()}",
            "",
            "👑 <b>#admins TOP:</b>",
        ]
        if admins:
            for index, (user_id, name, score) in enumerate(admins, start=1):
                lines.append(f"{index}. {self._tg_mention(user_id, name)} - {score} ⭐")
        else:
            lines.append("Hali ball yo'q.")

        lines.extend(["", "👥 <b>#members TOP:</b>"])
        if members:
            for index, (user_id, name, score) in enumerate(members, start=1):
                lines.append(f"{index}. {self._tg_mention(user_id, name)} - {score} ⭐")
        else:
            lines.append("Hali ball yo'q.")
        return "\n".join(lines)


    async def owner_diamond_top_text(self, limit: int = 30) -> str:
        safe_limit = max(1, min(int(limit or 30), 50))
        async with self.session_factory() as session:
            users = (
                await session.execute(
                    select(User)
                    .where(User.telegram_id > 0, User.diamonds > 0)
                    .order_by(User.diamonds.desc(), User.updated_at.desc(), User.id.asc())
                    .limit(safe_limit)
                )
            ).scalars().all()
            total_users = await session.scalar(
                select(func.count(User.id)).where(User.telegram_id > 0, User.diamonds > 0)
            )
            total_diamonds = await session.scalar(
                select(func.coalesce(func.sum(User.diamonds), 0)).where(User.telegram_id > 0)
            )

        if not users:
            return (
                "💎 <b>TOP 30 almaz balansi</b>\n\n"
                "Hozircha almaz balansi bor user topilmadi."
            )

        lines = [
            "💎 <b>TOP 30 almaz balansi</b>",
            "",
            f"👥 Almazli userlar: <b>{int(total_users or 0)}</b>",
            f"💎 Jami user almazlari: <b>{int(total_diamonds or 0)}</b>",
            "",
        ]
        for idx, user in enumerate(users, 1):
            mention = self._tg_mention(user.telegram_id, user.display_name or str(user.telegram_id))
            lines.append(
                f"{idx}. {mention} — "
                f"<b>{int(user.diamonds or 0)}</b> 💎 | ID: <code>{user.telegram_id}</code>"
            )
        return "\n".join(lines)


    async def owner_dollar_top_text(self, limit: int = 30) -> str:
        safe_limit = max(1, min(int(limit or 30), 50))
        async with self.session_factory() as session:
            users = (
                await session.execute(
                    select(User)
                    .where(User.telegram_id > 0, User.dollar > 0)
                    .order_by(User.dollar.desc(), User.updated_at.desc(), User.id.asc())
                    .limit(safe_limit)
                )
            ).scalars().all()
            total_users = await session.scalar(
                select(func.count(User.id)).where(User.telegram_id > 0, User.dollar > 0)
            )
            total_dollars = await session.scalar(
                select(func.coalesce(func.sum(User.dollar), 0)).where(User.telegram_id > 0)
            )

        if not users:
            return (
                "<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> <b>TOP 30 dollar balansi</b>\n\n"
                "Hozircha dollar balansi bor user topilmadi."
            )

        lines = [
            "<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> <b>TOP 30 dollar balansi</b>",
            "",
            f"👥 Dollarli userlar: <b>{int(total_users or 0)}</b>",
            f"<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> Jami user dollarlari: <b>{int(total_dollars or 0)}</b>",
            "",
        ]
        for idx, user in enumerate(users, 1):
            mention = self._tg_mention(user.telegram_id, user.display_name or str(user.telegram_id))
            lines.append(
                f"{idx}. {mention} — "
                f"<b>{int(user.dollar or 0)}</b> <tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> | "
                f"ID: <code>{user.telegram_id}</code>"
            )
        return "\n".join(lines)


    @staticmethod
    def _couple_duration_text(started_at: datetime) -> str:
        started = GameEngine._ensure_utc(started_at)
        total_seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = max(1, remainder // 60) if total_seconds < 3600 else remainder // 60
        if days:
            return f"{days} kun {hours} soat"
        if hours:
            return f"{hours} soat {minutes} daqiqa"
        return f"{minutes} daqiqa"


    async def _active_couple_for_user(
        self,
        session: AsyncSession,
        chat_id: int,
        user_id: int,
    ) -> Optional[CoupleRelationship]:
        return (
            await session.execute(
                select(CoupleRelationship).where(
                    CoupleRelationship.chat_id == chat_id,
                    CoupleRelationship.active.is_(True),
                    (
                        (CoupleRelationship.user_one_telegram_id == user_id)
                        | (CoupleRelationship.user_two_telegram_id == user_id)
                    ),
                )
            )
        ).scalar_one_or_none()


    async def create_couple_request(
        self,
        chat_id: int,
        requester_id: int,
        requester_name: str,
        target_id: int,
        target_name: str,
    ) -> tuple[bool, str, Optional[InlineKeyboardMarkup]]:
        if requester_id == target_id:
            return False, "O'zingiz bilan para bo'la olmaysiz.", None

        async with self.session_factory() as session:
            requester_pair = await self._active_couple_for_user(session, chat_id, requester_id)
            if requester_pair is not None:
                return False, "Sizda allaqachon para bor. Avval /unpara bilan uzing.", None
            target_pair = await self._active_couple_for_user(session, chat_id, target_id)
            if target_pair is not None:
                return False, "Bu foydalanuvchining allaqachon parasi bor.", None

        requester = self._tg_mention(requester_id, requester_name)
        target = self._tg_mention(target_id, target_name)
        text = (
            f"💌 {target}, {requester} siz bilan para bo'lmoqchi.\n\n"
            "Javobingizni tanlang:"
        )
        return True, text, couple_request_keyboard(chat_id, requester_id, target_id)


    async def answer_couple_request(
        self,
        chat_id: int,
        requester_id: int,
        requester_name: str,
        target_id: int,
        target_name: str,
        accepted: bool,
        actor_id: int,
    ) -> tuple[bool, str]:
        if actor_id != target_id:
            return False, "Bu so'rov faqat siz uchun emas."

        requester = self._tg_mention(requester_id, requester_name)
        target = self._tg_mention(target_id, target_name)
        if not accepted:
            return True, f"💔 {requester} para so'rovi {target} tomonidan rad etildi."

        async with self.session_factory() as session:
            requester_pair = await self._active_couple_for_user(session, chat_id, requester_id)
            target_pair = await self._active_couple_for_user(session, chat_id, target_id)
            if requester_pair is not None or target_pair is not None:
                return False, "Bu so'rov eskirgan. Ishtirokchilardan birida allaqachon para bor."

            session.add(
                CoupleRelationship(
                    chat_id=chat_id,
                    user_one_telegram_id=requester_id,
                    user_one_name=requester_name or "User",
                    user_two_telegram_id=target_id,
                    user_two_name=target_name or "User",
                    active=True,
                )
            )
            await session.commit()

        return True, f"💞 {requester} sizning para so'rovingiz {target} tomonidan qabul qilindi. Endi sizlar sheriklarsiz."


    async def couple_stats_text(self, chat_id: int) -> str:
        async with self.session_factory() as session:
            couples = (
                await session.execute(
                    select(CoupleRelationship)
                    .where(
                        CoupleRelationship.chat_id == chat_id,
                        CoupleRelationship.active.is_(True),
                    )
                    .order_by(CoupleRelationship.created_at.asc())
                )
            ).scalars().all()

        if not couples:
            return "📊 Hozircha bu guruhda aktiv paralar yo'q."

        lines = ["📊 <b>Paralar statistikasi</b>", ""]
        for index, couple in enumerate(couples, start=1):
            first = self._tg_mention(couple.user_one_telegram_id, couple.user_one_name)
            second = self._tg_mention(couple.user_two_telegram_id, couple.user_two_name)
            duration = self._couple_duration_text(couple.created_at)
            lines.append(f"{index}. {first} + {second} — {duration}dan beri para 💞")
        return "\n".join(lines)


    async def my_couple_text(self, chat_id: int, user_id: int) -> str:
        async with self.session_factory() as session:
            couple = await self._active_couple_for_user(session, chat_id, user_id)
            if couple is None:
                return "💔 Sizda bu guruhda aktiv para yo'q."
            duration = self._couple_duration_text(couple.created_at)
            if couple.user_one_telegram_id == user_id:
                partner_id = couple.user_two_telegram_id
                partner_name = couple.user_two_name
            else:
                partner_id = couple.user_one_telegram_id
                partner_name = couple.user_one_name

        partner = self._tg_mention(partner_id, partner_name)
        return f"💞 Siz {partner} bilan {duration}dan beri sheriksiz."


    async def unpair_user(self, chat_id: int, user_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            couple = await self._active_couple_for_user(session, chat_id, user_id)
            if couple is None:
                return False, "Sizda bu guruhda aktiv para yo'q."
            couple.active = False
            couple.ended_at = datetime.now(timezone.utc)
            first_name = couple.user_one_name
            first_id = couple.user_one_telegram_id
            second_name = couple.user_two_name
            second_id = couple.user_two_telegram_id
            await session.commit()

        first = self._tg_mention(first_id, first_name)
        second = self._tg_mention(second_id, second_name)
        return True, f"💔 {first} + {second} parasi uzildi. Endi ular sherik emas."


    async def can_send_private_team_message(self, telegram_id: int) -> bool:
        game_result = await self.get_player_running_game(telegram_id)
        if game_result is None:
            return False
        _, _, _, player_role, _, is_alive = game_result
        if not is_alive:
            return False
        try:
            role = Role(player_role)
        except ValueError:
            return False
        return role in {
            Role.DON,
            Role.MAFIA,
            Role.SPY,
            Role.HIRED_KILLER,
            Role.LAWYER,
            Role.DOCTOR,
            Role.COMMISSAR,
            Role.SERGEANT,
        }


    async def send_team_message_to_group(
        self,
        bot: Bot,
        telegram_id: int,
        message_text: str,
    ) -> tuple[bool, str]:
        """Forward a private bot message only to the sender's alive teammates."""
        game_result = await self.get_player_running_game(telegram_id)
        if game_result is None:
            return False, "Siz hozir aktiv o'yinda emas."
        
        game_id, chat_id, player_telegram_id, player_role, player_display_name, is_alive = game_result
        
        if not is_alive:
            return False, "O'lgan o'yinchilar dastaga xabar yuborishi mumkin emas."
        
        # Determine team and get team members
        team_members = []
        team_title = ""
        
        role = Role(player_role)
        
        # Mafia team
        if role in {Role.DON, Role.MAFIA, Role.SPY, Role.HIRED_KILLER, Role.LAWYER}:
            async with self.session_factory() as session:
                team_members = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.role.in_([
                                Role.DON.value, Role.MAFIA.value, Role.SPY.value,
                                Role.HIRED_KILLER.value, Role.LAWYER.value
                            ]),
                            GamePlayer.alive.is_(True),
                        )
                    )
                ).scalars().all()
            team_title = "🤵🏻 Mafia"
        
        # Doctors group
        elif role == Role.DOCTOR:
            async with self.session_factory() as session:
                doctors = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.role == Role.DOCTOR.value,
                            GamePlayer.alive.is_(True),
                        )
                    )
                ).scalars().all()
            if len(doctors) > 1:
                team_members = doctors
                team_title = "👨🏼‍⚕️ Doktorlar"
            else:
                return False, "Sizning dastada boshqa a'zolar yo'q."
        
        # Commissar and Sergeants group
        elif role in {Role.COMMISSAR, Role.SERGEANT}:
            async with self.session_factory() as session:
                team_members = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.role.in_([Role.COMMISSAR.value, Role.SERGEANT.value]),
                            GamePlayer.alive.is_(True),
                        )
                    )
                ).scalars().all()
            team_title = "🕵🏼 Komissar va Serjantlar"
        
        else:
            return False, "Sizning roli dastaga xabar yuborish huquqiga ega emas."
        
        recipients = [member for member in team_members if member.telegram_id != telegram_id]
        if not recipients:
            return False, "Sizning dastada boshqa tirik a'zo yo'q."
        
        safe_message = escape(message_text.strip()[:500])
        sender_name = self._tg_mention(player_telegram_id, player_display_name)
        private_message = (
            f"<b>{team_title}</b> - {role_label(role)}\n"
            f"{sender_name}: {safe_message}"
        )

        sent = 0
        failed = 0
        for member in recipients:
            try:
                await bot.send_message(
                    member.telegram_id,
                    private_message,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
                sent += 1
            except TelegramForbiddenError:
                failed += 1
            except Exception as e:
                failed += 1
                logger.exception("Failed to send private team message: %s", e)

        if sent == 0:
            return False, "Sheriklaringiz bot private chatini ochmagan."
        if failed:
            return True, f"Xabar {sent} ta sherikka yuborildi. {failed} tasiga yuborilmadi."
        return True, f"Xabar {sent} ta sherikka yuborildi."


    async def group_settings(self, chat_id: int) -> Group:
        group = await self.get_or_create_group(chat_id, "Group")
        return group


    async def group_timeout(self, chat_id: int, field: str) -> int:
        time_key_map = {
            "registration_timeout": "registration_time",
            "night_timeout": "night_time",
            "day_discussion_timeout": "day_time",
            "day_voting_timeout": "vote_time",
        }
        time_key = time_key_map.get(field)
        if time_key:
            gsm = GroupSettingsManager(self.session_factory)
            seconds = await gsm.get_time_setting(chat_id, time_key)
            if seconds > 0:
                return seconds
        defaults = {
            "registration_timeout": self.settings.registration_timeout,
            "night_timeout": self.settings.night_timeout,
            "day_discussion_timeout": self.settings.day_discussion_timeout,
            "day_voting_timeout": self.settings.day_voting_timeout,
        }
        default = defaults.get(field, 60)
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                return default
            return max(10, int(getattr(group, field, None) or default))


    async def latest_group_game_logs_text(self, chat_id: int, limit: int = 15) -> str:
        async with self.session_factory() as session:
            game = (
                await session.execute(
                    select(Game)
                    .where(Game.chat_id == chat_id)
                    .order_by(Game.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if game is None:
                return "🧾 <b>Game logs</b>\n\nBu guruhda hali o'yin topilmadi."

            logs = (
                await session.execute(
                    select(GameLog)
                    .where(GameLog.game_id == game.id)
                    .order_by(GameLog.id.desc())
                    .limit(max(1, min(limit, 30)))
                )
            ).scalars().all()

        if not logs:
            return f"🧾 <b>Game logs</b>\n\nO'yin #{game.id} uchun hali log yozilmagan."

        lines = [
            "🧾 <b>Game logs</b>",
            f"O'yin: <b>#{game.id}</b> | Holat: <b>{game.status}</b> | Faza: <b>{game.phase}</b>",
            "",
        ]
        for item in reversed(logs):
            actor_name = "-"
            target_name = "-"
            try:
                payload = json.loads(item.payload or "{}")
                actor = payload.get("actor") or {}
                target = payload.get("target") or {}
                actor_name = actor.get("display_name") or "-"
                target_name = target.get("display_name") or "-"
                day = payload.get("day_number", 0)
                night = payload.get("night_number", 0)
            except (TypeError, ValueError, AttributeError):
                day = 0
                night = 0
            created = item.created_at.strftime("%H:%M") if item.created_at else "--:--"
            lines.append(
                f"{created} | <code>{item.event_type}</code> | D:{day} N:{night} | {escape(str(actor_name))} -> {escape(str(target_name))}"
            )
        return "\n".join(lines)


    async def update_group_setting(self, chat_id: int, field: str, value: object) -> tuple[bool, str]:
        """Guruh sozlamalarini yangilash. Aktiv o'yin va registration o'zgartirilmaydi."""
        async with self.session_factory() as session:
            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(chat_id=chat_id, title="Group")
                session.add(group)
            
            if field == "registration_timeout":
                group.registration_timeout = max(10, int(value))
                await session.commit()
                return True, f"✅ Registration timeout: {group.registration_timeout} soniya"
            elif field == "night_timeout":
                group.night_timeout = max(10, int(value))
                await session.commit()
                return True, f"✅ Tun vaqti: {group.night_timeout} soniya"
            elif field == "day_discussion_timeout":
                group.day_discussion_timeout = max(10, int(value))
                await session.commit()
                return True, f"✅ Kun muhokamasi: {group.day_discussion_timeout} soniya"
            elif field == "day_voting_timeout":
                group.day_voting_timeout = max(10, int(value))
                await session.commit()
                return True, f"✅ Ovoz berish vaqti: {group.day_voting_timeout} soniya"
            elif field == "min_players":
                group.min_players = max(4, min(int(value), 30))
                await session.commit()
                return True, f"✅ Minimal o'yinchilar: {group.min_players}"
            elif field == "role_preset":
                preset = str(value)
                if preset not in GAME_MODES and preset not in {"black23", "extended35", "zombie"}:
                    return False, "❌ Noma'lum o'yin turi."

                active_game = await self.find_active_game(session, chat_id)
                if active_game is not None:
                    current_preset = active_game.role_preset or "black23"
                    comparable_current = "classic" if current_preset in {"black23", "extended35"} else current_preset
                    comparable_requested = "classic" if preset in {"black23", "extended35"} else preset
                    if comparable_current != comparable_requested:
                        current_name = role_preset_label(comparable_current)
                        phase_name = (
                            "ro'yxatdan o'tish"
                            if active_game.status == GameStatus.REGISTRATION.value
                            else "aktiv o'yin"
                        )
                        return (
                            False,
                            f"❌ {phase_name.capitalize()} davomida o'yin turini o'zgartirib bo'lmaydi.\n"
                            f"Joriy tur: <b>{current_name}</b>",
                        )

                group.role_preset = preset
                await session.commit()
                self._invalidate_group_cache(chat_id)
                return True, f"✅ O'yin turi: {role_preset_label(preset)}"
            
            return False, "❌ Noma'lum sozlama"


    def format_role_preset_settings(self, group: Group) -> str:
        preset = group.role_preset or "black23"
        display_preset = "classic" if preset in {"black23", "extended35"} else preset
        return (
            "🎮 <b>O'yin turlari</b>\n\n"
            f"Joriy tur: <b>{role_preset_label(display_preset)}</b>\n"
            f"O'yinchi limiti: <b>{role_preset_max_players(display_preset)}</b>\n\n"
            "<b>Classic</b> - eski klassik taqsimotni saqlaydi.\n"
            "<b>Super</b> - faol rollarni minimal o'yinchi soniga qarab ertaroq beradi, yetmasa Tinch aholi bilan to'ldiradi.\n"
            "<b>Mega</b> - faqat faol rollar, Tinch aholi hech qachon tushmaydi.\n"
            "<b>Zombie</b> - virus tarqalishiga asoslangan alohida jamoaviy rejim.\n\n"
            "Tanlov guruh uchun doimiy saqlanadi va keyingi o'yinlarda ishlaydi."
        )
