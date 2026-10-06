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
from sqlalchemy import case, func, select, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clan_service import ClanService
from app.config import BASE_DIR, Settings
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
    AdminAuditLog,
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
    PromoCode,
    PromoCodeRedemption,
    ScheduledBroadcast,
    SkipDecision,
    SubAdmin,
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

class AdminOpsMixin:
    @staticmethod
    def normalize_admin_username(raw: str) -> str:
        username = (raw or "").strip()
        username = username.removeprefix("https://t.me/").removeprefix("http://t.me/").removeprefix("t.me/")
        username = username.strip().lstrip("@").split("/", maxsplit=1)[0].strip()
        return username


    async def get_purchase_admin_username(self) -> str:
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "purchase_admin_username"))
            ).scalar_one_or_none()
            username = self.normalize_admin_username(setting.value if setting else self.settings.admin_username)
            return username or self.normalize_admin_username(self.settings.admin_username)


    async def set_purchase_admin_username(self, username: str) -> tuple[bool, str]:
        username = self.normalize_admin_username(username)
        if not username or len(username) < 5:
            return False, "Username noto'g'ri. Masalan: @username"
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "purchase_admin_username"))
            ).scalar_one_or_none()
            if setting is None:
                setting = BotSetting(key="purchase_admin_username", value=username)
                session.add(setting)
            else:
                setting.value = username
            await session.commit()
        return True, f"✅ Xarid admini yangilandi: @{username}"


    @staticmethod
    def normalize_telegram_url(raw: str) -> str:
        value = (raw or "").strip()
        if not value:
            return ""
        if value.startswith("@"):
            username = value.lstrip("@").strip()
            return f"https://t.me/{username}" if username else ""
        if value.startswith("t.me/"):
            path = value.removeprefix("t.me/").strip("/")
            return f"https://t.me/{path}" if path else ""
        if value.startswith("http://t.me/"):
            path = value.removeprefix("http://t.me/").strip("/")
            return f"https://t.me/{path}" if path else ""
        if value.startswith("https://t.me/"):
            path = value.removeprefix("https://t.me/").strip("/")
            return f"https://t.me/{path}" if path else ""
        return ""


    @staticmethod
    def extract_channel_identifier(raw: str) -> Optional[str | int]:
        value = (raw or "").strip()
        if not value:
            return None
        if value.lstrip("-").isdigit():
            return int(value)
        if value.startswith("@"):
            username = value.lstrip("@").strip()
            return f"@{username}" if username else None
        if value.startswith("https://t.me/"):
            path = value.removeprefix("https://t.me/").split("/")[0].strip()
            if path.startswith("+") or path.startswith("joinchat"):
                return None
            return f"@{path}" if path else None
        if value.startswith("t.me/"):
            path = value.removeprefix("t.me/").split("/")[0].strip()
            return f"@{path}" if path else None
        return f"@{value.lstrip('@')}"

    async def get_news_channel_url(self) -> Optional[str]:
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "news_channel_url"))
            ).scalar_one_or_none()
            raw_url = setting.value if setting else self.settings.news_channel_url
        return self.normalize_telegram_url(raw_url)

    async def is_news_sub_required(self) -> bool:
        async with self.session_factory() as session:
            val = await self._get_bot_setting_value(session, "news_channel_sub_required", "false")
        return str(val).lower() == "true"

    async def toggle_news_sub_required(self) -> tuple[bool, str]:
        async with self.session_factory() as session:
            current = await self._get_bot_setting_value(session, "news_channel_sub_required", "false")
            new_val = "false" if str(current).lower() == "true" else "true"
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "news_channel_sub_required"))
            ).scalar_one_or_none()
            if setting is None:
                setting = BotSetting(key="news_channel_sub_required", value=new_val)
                session.add(setting)
            else:
                setting.value = new_val
            await session.commit()

        status_str = "🟢 Yoqildi (Majburiy obuna aktiv)" if new_val == "true" else "🔴 O'chirildi (Majburiy obuna o'chirilgan)"
        return new_val == "true", f"📢 Majburiy obuna holati: {status_str}"

    async def check_user_news_subscription(self, bot: Bot, user_id: int, *, ignore_cache: bool = False) -> bool:
        if not await self.is_news_sub_required():
            return True

        if user_id in self.settings.admin_ids:
            return True

        news_url = await self.get_news_channel_url()
        if not news_url:
            return True

        channel_target = self.extract_channel_identifier(news_url)
        if not channel_target:
            return True

        now = self._monotonic()
        if not ignore_cache:
            cache = getattr(self, "_news_sub_cache", {})
            cached = cache.get(user_id)
            if cached and (now - cached[0]) < 60.0:
                return cached[1]

        try:
            member = await bot.get_chat_member(chat_id=channel_target, user_id=user_id)
            is_sub = member.status in {"creator", "administrator", "member", "restricted"}
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logging.warning("Telegram exception checking sub for user %s on %s: %s", user_id, channel_target, exc)
            is_sub = True
        except Exception as exc:
            logging.exception("Error checking channel subscription for user %s: %s", user_id, exc)
            is_sub = True

        self.update_news_sub_cache(user_id, is_sub)
        return is_sub

    def update_news_sub_cache(self, user_id: int, is_sub: bool) -> None:
        if not hasattr(self, "_news_sub_cache"):
            self._news_sub_cache = {}
        self._news_sub_cache[user_id] = (self._monotonic(), is_sub)


    async def set_news_channel_url(self, url: str) -> tuple[bool, str]:
        normalized = self.normalize_telegram_url(url)
        if not normalized:
            return False, "Link noto'g'ri. Masalan: @kanal yoki https://t.me/kanal"
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "news_channel_url"))
            ).scalar_one_or_none()
            if setting is None:
                setting = BotSetting(key="news_channel_url", value=normalized)
                session.add(setting)
            else:
                setting.value = normalized
            await session.commit()
        return True, f"✅ Yangiliklar kanali yangilandi:\n{normalized}"


    async def clear_news_channel_url(self) -> str:
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == "news_channel_url"))
            ).scalar_one_or_none()
            if setting is None:
                setting = BotSetting(key="news_channel_url", value="")
                session.add(setting)
            else:
                setting.value = ""
            await session.commit()
        return "✅ Yangiliklar kanali o'chirildi. User paneldagi tugma endi ko'rinmaydi."


    async def get_admin_group_id(self) -> int:
        async with self.session_factory() as session:
            raw = await self._get_bot_setting_value(session, ADMIN_GROUP_ID_KEY, "")
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0


    async def set_admin_group(self, bot: Bot, raw_chat_id: Union[int, str]) -> tuple[bool, str]:
        try:
            chat_id = int(str(raw_chat_id).strip())
        except (TypeError, ValueError):
            return False, "Guruh ID faqat son bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        if chat_id >= 0:
            return False, "Guruh ID manfiy bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        try:
            chat = await bot.get_chat(chat_id)
            await bot.send_message(chat_id, "✅ Admin guruh ulandi. Almaz loglari shu yerga avtomatik yuboriladi.")
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            return False, f"Bot bu guruhni topa olmadi yoki xabar yubora olmaydi: {escape(str(exc))}"
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, ADMIN_GROUP_ID_KEY, str(chat_id))
            latest_tx_id = await session.scalar(select(func.max(DiamondTransaction.id)))
            await self._set_bot_setting_value(session, DIAMOND_LOG_LAST_SENT_ID_KEY, str(int(latest_tx_id or 0)))
            await session.commit()
        title = escape(getattr(chat, "title", None) or str(chat_id))
        return True, f"✅ Admin guruh ulandi: <b>{title}</b>\nID: <code>{chat_id}</code>"


    async def clear_admin_group(self) -> str:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, ADMIN_GROUP_ID_KEY, "")
            await session.commit()
        return "✅ Admin guruh o'chirildi. Almaz loglari avtomatik yuborilmaydi."


    async def owner_stats(self) -> str:
        async with self.session_factory() as session:
            users_count = await session.scalar(select(func.count(User.id)))
            groups_count = await session.scalar(select(func.count(Group.id)))
            active_games = await session.scalar(
                select(func.count(Game.id)).where(Game.status.in_([GameStatus.REGISTRATION.value, GameStatus.ACTIVE.value]))
            )
            completed_games = await session.scalar(select(func.count(Game.id)).where(Game.status == GameStatus.COMPLETED.value))
        return (
            "📊 <b>Bot statistikasi</b>\n\n"
            f"👤 Userlar: <b>{users_count or 0}</b>\n"
            f"🏘 Guruhlar: <b>{groups_count or 0}</b>\n"
            f"🎮 Aktiv o'yinlar: <b>{active_games or 0}</b>\n"
            f"✅ Tugagan o'yinlar: <b>{completed_games or 0}</b>"
        )


    async def active_vip_users(self, limit: int = 30) -> list[User]:
        safe_limit = max(1, min(int(limit or 30), 50))
        now = self._now_utc()
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(User)
                    .where(User.telegram_id > 0, User.vip_until.is_not(None))
                    .order_by(User.vip_until.desc(), User.id.asc())
                    .limit(max(safe_limit * 3, safe_limit))
                )
            ).scalars().all()
        active: list[User] = []
        for user in rows:
            if user.vip_until and self._ensure_utc(user.vip_until) > now:
                active.append(user)
            if len(active) >= safe_limit:
                break
        return active


    async def owner_vip_users_text(self, limit: int = 30) -> str:
        users = await self.active_vip_users(limit)
        if not users:
            return "👑 <b>Aktiv VIP userlar</b>\n\nHozircha aktiv VIP user topilmadi."

        now = self._now_utc()
        lines = [
            "👑 <b>Aktiv VIP userlar</b>",
            "",
            f"Jami ko'rsatilmoqda: <b>{len(users)}</b>",
            "",
        ]
        for index, user in enumerate(users, start=1):
            vip_until = self._ensure_utc(user.vip_until)
            remaining = vip_until - now
            days = max(0, remaining.days)
            hours = max(0, remaining.seconds // 3600)
            mention = self._tg_mention(user.telegram_id, user.display_name or str(user.telegram_id))
            lines.append(
                f"{index}. {mention} — <b>{days} kun {hours} soat</b> | "
                f"ID: <code>{user.telegram_id}</code>"
            )
        lines.extend(["", "VIPni o'chirish uchun pastdagi user tugmasini bosing."])
        return "\n".join(lines)


    async def deactivate_vip_user(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user = (
                await session.execute(select(User).where(User.telegram_id == int(telegram_id)))
            ).scalar_one_or_none()
            if user is None:
                return False, "User topilmadi."
            user.vip_until = None
            await session.commit()
        name = escape(user.display_name or str(telegram_id))
        return True, f"👑 <b>{name}</b> uchun VIP aktivatsiya o'chirildi."


    @staticmethod
    def _diamond_action_label(action: str) -> str:
        labels = {
            "admin_grant": "Admin krediti",
            "admin_bust": "Admin bankrot",
            "diamond_payment": "Stars xarid",
            "diamond_to_dollar": "Dollarga almashtirish",
            "game_participation_reward": "O'yin ishtirok mukofoti",
            "game_winner_reward": "G'olib mukofoti",
            "giveaway_create": "Sovg'a ochish",
            "giveaway_refund": "Sovg'a qaytarish",
            "giveaway_win": "Sovg'a yutish",
            "hero_add_points": "Geroy ball",
            "hero_buy": "Geroy xarid",
            "hero_market_buy": "Geroy marketplace xarid",
            "hero_market_sale": "Geroy marketplace sotuv",
            "hero_sale_cancel": "Geroy sotuvdan qaytarish",
            "hojiaka_grant": "Hojiaka ehson",
            "miner_reward": "Konchi topilmasi",
            "mashka_steal_in": "Mashka o'g'irlik kirim",
            "mashka_steal_out": "Mashka o'g'irlik chiqim",
            "premium_group_contribution": "Premium guruh",
            "shop_item_buy": "Do'kon mahsulot",
            "shop_role_buy": "Rol xarid",
            "transfer_in": "O'tkazma kirim",
            "transfer_out": "O'tkazma chiqim",
        }
        return labels.get(action, action.replace("_", " "))


    @staticmethod
    def _split_report_lines(lines: list[str], max_chars: int = 3600) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len
        if current:
            chunks.append("\n".join(current))
        return chunks


    @staticmethod
    def _format_tx_time(value: Optional[datetime]) -> str:
        if value is None:
            return "--"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d.%m.%Y | %H:%M")


    @staticmethod
    def _short_text(value: Optional[str], limit: int = 140) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 1)]}…"


    async def _owner_diamond_audit_lines(self, limit: int = 15, *, title: str = "💎 <b>Almaz loglari</b>") -> list[str]:
        limit = min(max(5, int(limit)), 50)
        async with self.session_factory() as session:
            income_expr = func.coalesce(
                func.sum(case((DiamondTransaction.amount > 0, DiamondTransaction.amount), else_=0)),
                0,
            )
            expense_expr = func.coalesce(
                func.sum(case((DiamondTransaction.amount < 0, -DiamondTransaction.amount), else_=0)),
                0,
            )
            total_income, total_expense, tx_count = (
                await session.execute(
                    select(income_expr, expense_expr, func.count(DiamondTransaction.id))
                )
            ).one()
            by_action = (
                await session.execute(
                    select(
                        DiamondTransaction.action,
                        func.count(DiamondTransaction.id),
                        func.coalesce(func.sum(DiamondTransaction.amount), 0),
                        func.coalesce(
                            func.sum(case((DiamondTransaction.amount > 0, DiamondTransaction.amount), else_=0)),
                            0,
                        ),
                        func.coalesce(
                            func.sum(case((DiamondTransaction.amount < 0, -DiamondTransaction.amount), else_=0)),
                            0,
                        ),
                    )
                    .group_by(DiamondTransaction.action)
                    .order_by(func.count(DiamondTransaction.id).desc())
                    .limit(10)
                )
            ).all()
            user_income_expr = func.coalesce(
                func.sum(case((DiamondTransaction.amount > 0, DiamondTransaction.amount), else_=0)),
                0,
            ).label("income")
            user_expense_expr = func.coalesce(
                func.sum(case((DiamondTransaction.amount < 0, -DiamondTransaction.amount), else_=0)),
                0,
            ).label("expense")
            top_users = (
                await session.execute(
                    select(
                        DiamondTransaction.user_telegram_id,
                        func.max(DiamondTransaction.user_name),
                        user_income_expr,
                        user_expense_expr,
                    )
                    .group_by(DiamondTransaction.user_telegram_id)
                    .order_by(user_expense_expr.desc(), user_income_expr.desc())
                    .limit(10)
                )
            ).all()
            recent = (
                await session.execute(
                    select(DiamondTransaction)
                    .order_by(DiamondTransaction.created_at.desc(), DiamondTransaction.id.desc())
                    .limit(limit)
                )
            ).scalars().all()

        if not tx_count:
            return [
                title,
                "",
                "Hali almaz kirim-chiqim logi yozilmagan.",
            ]

        lines = [
            title,
            "",
            "Filter: <b>yo'q</b> — barcha olmos amallari ko'rsatiladi",
            f"📥 Jami kirim: <b>{int(total_income or 0)}</b>",
            f"📤 Jami sarf: <b>{int(total_expense or 0)}</b>",
            f"🧾 Amallar soni: <b>{int(tx_count or 0)}</b>",
            "",
            "📌 <b>Nimalarga sarflanmoqda / olinmoqda:</b>",
        ]
        for action, count, net, income, expense in by_action:
            label = self._diamond_action_label(str(action))
            lines.append(
                f"• {escape(label)}: kirim <b>{int(income or 0)}</b>, "
                f"sarf <b>{int(expense or 0)}</b>, net <b>{int(net or 0)}</b> ({int(count or 0)} ta)"
            )

        lines.extend(["", "👥 <b>TOP userlar:</b>"])
        for index, (telegram_id, name, income, expense) in enumerate(top_users, start=1):
            mention = self._tg_mention(int(telegram_id), str(name or telegram_id))
            lines.append(f"{index}. {mention}: kirim <b>{int(income or 0)}</b>, sarf <b>{int(expense or 0)}</b>")

        lines.extend(["", f"🕘 <b>Oxirgi {limit} amal:</b>"])
        for item in recent:
            lines.append(self._diamond_transaction_line(item))
        return lines


    async def owner_diamond_audit_text(self, limit: int = 15) -> str:
        group_id = await self.get_admin_group_id()
        group_text = f"<code>{group_id}</code>" if group_id else "<b>ulanmagan</b>"
        lines = await self._owner_diamond_audit_lines(limit)
        if len(lines) >= 2:
            lines.insert(2, f"🏠 Log guruhi: {group_text}")
        return "\n".join(lines)


    async def owner_diamond_audit_chunks(self, limit: int = 30) -> list[str]:
        lines = await self._owner_diamond_audit_lines(limit, title="💎 <b>Almaz loglari hisoboti</b>")
        chunks = self._split_report_lines(lines)
        if len(chunks) <= 1:
            return chunks
        total = len(chunks)
        return [f"{chunk}\n\n<b>Qism:</b> {index}/{total}" for index, chunk in enumerate(chunks, start=1)]


    async def send_owner_diamond_audit(self, bot: Bot, chat_id: int, limit: int = 30) -> tuple[bool, str, int]:
        if chat_id == 0:
            return False, "Admin guruh sozlanmagan. Admin paneldan <b>Admin guruh</b> bo'limida ulang.", 0
        if chat_id > 0:
            return False, "Admin guruh ID guruh/superguruh ID bo'lishi kerak. Odatda u manfiy son bo'ladi.", 0

        chunks = await self.owner_diamond_audit_chunks(limit)
        sent = 0
        try:
            chat = await bot.get_chat(chat_id)
            chat_title = getattr(chat, "title", None) or str(chat_id)
            for chunk in chunks:
                await bot.send_message(chat_id=chat_id, text=chunk)
                sent += 1
                await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            return False, "Bot admin guruhga kira olmayapti yoki xabar yuborishga ruxsati yo'q.", sent
        except TelegramBadRequest as exc:
            return False, f"Telegram xatosi: {escape(str(exc))}", sent
        return True, f"Almaz loglari <b>{escape(chat_title)}</b> guruhiga yuborildi. Xabarlar: <b>{sent}</b> ta.", sent


    async def owner_diamond_audit_csv_file(self) -> tuple[BufferedInputFile, str, int]:
        async with self.session_factory() as session:
            items = (
                await session.execute(
                    select(DiamondTransaction)
                    .order_by(DiamondTransaction.id.asc())
                )
            ).scalars().all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "created_at_utc",
                "user_telegram_id",
                "user_name",
                "amount",
                "balance_after",
                "action",
                "action_label",
                "note",
                "counterparty_telegram_id",
                "counterparty_name",
                "chat_id",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    int(item.id),
                    self._format_tx_time(item.created_at),
                    int(item.user_telegram_id),
                    item.user_name or "",
                    int(item.amount or 0),
                    int(item.balance_after or 0),
                    item.action or "",
                    self._diamond_action_label(item.action or ""),
                    item.note or "",
                    int(item.counterparty_telegram_id) if item.counterparty_telegram_id else "",
                    item.counterparty_name or "",
                    int(item.chat_id) if item.chat_id else "",
                ]
            )
        data = buffer.getvalue().encode("utf-8-sig")
        now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"diamond_logs_{now}.csv"
        return BufferedInputFile(data, filename=filename), filename, len(items)


    def _diamond_transaction_line(self, item: DiamondTransaction) -> str:
        amount = int(item.amount or 0)
        sign = "+" if amount > 0 else ""
        direction = "➕" if amount > 0 else "➖"
        label = self._diamond_action_label(item.action)
        when = self._format_tx_time(item.created_at)
        user_link = self._tg_mention(item.user_telegram_id, item.user_name)
        parts = ["━━━━━━━━━━━━", f"#{item.id} • {when}", ""]
        parts.append(f"👤 {user_link}: ID <code>{item.user_telegram_id}</code>")
        parts.append(f"{direction} <b>{sign}{amount}</b> 💎 — {escape(label)}")
        parts.append(f"💰 Balans: <b>{int(item.balance_after or 0)}</b> 💎")
        if item.counterparty_telegram_id:
            counterparty = escape(self._short_text(item.counterparty_name or str(item.counterparty_telegram_id), 64))
            parts.append(f"↔️ Qarshi tomon: {counterparty} | ID <code>{item.counterparty_telegram_id}</code>")
        if item.chat_id:
            parts.append(f"🏠 Chat: <code>{item.chat_id}</code>")
        if item.note:
            parts.extend(["", f"📝 {escape(self._short_text(item.note, 160))}"])
        parts.append("━━━━━━━━━━━━")
        return "\n".join(parts)


    async def send_pending_diamond_logs(self, bot: Bot) -> int:
        chat_id = await self.get_admin_group_id()
        if chat_id == 0:
            return 0
        if chat_id > 0:
            logger.warning("Admin group id must be a group/supergroup id, got %s", chat_id)
            return 0

        async with self.session_factory() as session:
            raw_last_id = await self._get_bot_setting_value(session, DIAMOND_LOG_LAST_SENT_ID_KEY, "0")
            try:
                last_id = max(0, int(raw_last_id))
            except (TypeError, ValueError):
                last_id = 0
            rows = (
                await session.execute(
                    select(DiamondTransaction)
                    .where(DiamondTransaction.id > last_id)
                    .order_by(DiamondTransaction.id.asc())
                    .limit(200)
                )
            ).scalars().all()

        if not rows:
            return 0

        newest_id = max(int(item.id) for item in rows)

        lines = ["💎 <b>Yangi almaz loglari</b>", ""]
        lines.append("Filter: <b>yo'q</b> — barcha olmos amallari")
        lines.append("")
        for item in rows:
            lines.extend([self._diamond_transaction_line(item), ""])
        chunks = self._split_report_lines(lines)

        sent = 0
        try:
            for chunk in chunks:
                await bot.send_message(chat_id=chat_id, text=chunk)
                sent += 1
                await asyncio.sleep(0.05)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Failed to send pending diamond logs to %s: %s", chat_id, exc)
            return sent

        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, DIAMOND_LOG_LAST_SENT_ID_KEY, str(newest_id))
            await session.commit()
        return sent


    async def broadcast(self, bot: Bot, target: str, text: str) -> tuple[int, int]:
        if target not in {"users", "groups"}:
            return 0, 0
        async with self.session_factory() as session:
            if target == "users":
                ids = (await session.execute(select(User.telegram_id))).scalars().all()
            else:
                ids = (await session.execute(select(Group.chat_id))).scalars().all()

        sent = 0
        failed = 0
        for chat_id in ids:
            try:
                await bot.send_message(chat_id, text)
                sent += 1
                await asyncio.sleep(0.04)
            except (TelegramBadRequest, TelegramForbiddenError):
                failed += 1
        return sent, failed


    async def broadcast_message(
        self,
        bot: Bot,
        target: str,
        from_chat_id: int,
        message_id: int,
    ) -> tuple[int, int]:
        if target not in {"users", "groups"}:
            return 0, 0
        async with self.session_factory() as session:
            if target == "users":
                ids = (await session.execute(select(User.telegram_id))).scalars().all()
            else:
                ids = (await session.execute(select(Group.chat_id))).scalars().all()

        sent = 0
        failed = 0
        for chat_id in ids:
            try:
                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
                sent += 1
                await asyncio.sleep(0.04)
            except (TelegramBadRequest, TelegramForbiddenError):
                failed += 1
        return sent, failed


    async def grant_balance(
        self,
        telegram_id: int,
        dollar: int = 0,
        diamonds: int = 0,
    ) -> tuple[bool, str]:
        return await self.grant_balance_by_target(telegram_id, dollar=dollar, diamonds=diamonds)

    async def grant_balance_by_target(
        self,
        target: int | str,
        dollar: int = 0,
        diamonds: int = 0,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            target_str = str(target).strip()
            user = None
            if target_str.lstrip("-").isdigit():
                tid = int(target_str)
                user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
                if user is None and tid < 0:
                    user = User(
                        telegram_id=tid,
                        display_name=f"Channel {tid}",
                        language=self.settings.default_language,
                        language_selected=False,
                    )
                    session.add(user)
                    await session.flush()
            else:
                clean_username = target_str.lstrip("@").lower()
                user = (await session.execute(
                    select(User).where(func.lower(User.username) == clean_username)
                )).scalar_one_or_none()

            if user is None:
                return False, f"❌ Foydalanuvchi topilmadi ({escape(target_str)}). U avval botdan /start o'tgan bo'lishi kerak."

            user.dollar += dollar
            user.diamonds += diamonds
            if diamonds != 0:
                self._record_diamond_transaction(
                    session,
                    user,
                    diamonds,
                    "admin_grant",
                    note=f"Admin grant: dollar={dollar}, almaz={diamonds}",
                )
            await session.commit()
            display_name = escape(user.display_name or "Unknown")
            username_info = f" (@{user.username})" if user.username else ""

        grant_items = []
        if dollar != 0:
            grant_items.append(f'<tg-emoji emoji-id="5409048419211682843">💵</tg-emoji> {dollar}')
        if diamonds != 0:
            grant_items.append(f'<tg-emoji emoji-id="5427168083074628963">💎</tg-emoji> {diamonds}')

        granted_str = ", ".join(grant_items) if grant_items else "0"
        return (
            True,
            f"✅ <b>{display_name}</b>{username_info} foydalanuvchisiga berildi: {granted_str}\n\n"
            f'📊 <b>Yangi balans:</b> <tg-emoji emoji-id="5409048419211682843">💵</tg-emoji> {user.dollar} | <tg-emoji emoji-id="5427168083074628963">💎</tg-emoji> {user.diamonds}',
        )



    async def channel_gift_balance_text(self, channel_id: int, *, auto_create: bool = False) -> tuple[bool, str]:
        if channel_id >= 0:
            return False, "Kanal ID manfiy bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == channel_id))).scalar_one_or_none()
            if user is None:
                if not auto_create:
                    return False, (
                        "Bu kanal uchun balans topilmadi.\n"
                        "Paneldan to'ldirish qiling yoki auto-create yoqilgan ko'rishdan foydalaning."
                    )
                user = User(
                    telegram_id=channel_id,
                    display_name=f"Channel {channel_id}",
                    language=self.settings.default_language,
                    language_selected=False,
                )
                session.add(user)
                await session.commit()
            return True, (
                "📺 <b>Kanal sovg'a balansi</b>\n\n"
                f"ID: <code>{channel_id}</code>\n"
                f"Nom: <b>{escape(user.display_name or str(channel_id))}</b>\n\n"
                f"<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> Dollar: <b>{int(user.dollar or 0)}</b>\n"
                f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> Olmos: <b>{int(user.diamonds or 0)}</b>"
            )


    async def grant_channel_balance(
        self,
        channel_id: int,
        *,
        dollar: int = 0,
        diamonds: int = 0,
        channel_title: str = "",
    ) -> tuple[bool, str]:
        if channel_id >= 0:
            return False, "Kanal ID manfiy bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        if dollar == 0 and diamonds == 0:
            return False, "Hech bo'lmasa bitta qiymat 0 dan katta bo'lishi kerak."
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == channel_id))).scalar_one_or_none()
            if user is None:
                user = User(
                    telegram_id=channel_id,
                    display_name=(channel_title or f"Channel {channel_id}")[:255],
                    language=self.settings.default_language,
                    language_selected=False,
                )
                session.add(user)
                await session.flush()
            else:
                if channel_title:
                    user.display_name = channel_title[:255]
            user.dollar = int(user.dollar or 0) + int(dollar)
            user.diamonds = int(user.diamonds or 0) + int(diamonds)
            self._record_diamond_transaction(
                session,
                user,
                int(diamonds),
                "admin_grant",
                note=f"Kanal kredit: dollar={dollar}, almaz={diamonds}",
            )
            await session.commit()
        return True, (
            "✅ Kanal balansi to'ldirildi.\n\n"
            f"ID: <code>{channel_id}</code>\n"
            f"<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> +{int(dollar)}\n"
            f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> +{int(diamonds)}"
        )


    async def is_channel_gifts_enabled(self, channel_id: int) -> bool:
        async with self.session_factory() as session:
            value = await self._get_bot_setting_value(session, f"{CHANNEL_GIFTS_ENABLED_PREFIX}{channel_id}", "0")
        return value == "1"


    async def enable_channel_gifts(self, bot: Bot, channel_id: int) -> tuple[bool, str]:
        if channel_id >= 0:
            return False, "Kanal ID manfiy bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        if not await self.bot_is_admin(bot, channel_id):
            return False, "Bot bu kanalda admin emas yoki kanal topilmadi."
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == channel_id))).scalar_one_or_none()
            if user is None:
                user = User(
                    telegram_id=channel_id,
                    display_name=f"Channel {channel_id}",
                    language=self.settings.default_language,
                    language_selected=False,
                )
                session.add(user)
            await self._set_bot_setting_value(session, f"{CHANNEL_GIFTS_ENABLED_PREFIX}{channel_id}", "1")
            await session.commit()
        try:
            await bot.send_message(
                channel_id,
                "✅ Almaz tarqatish yoqildi.\n\n"
                "Endi bu kanalda /send va /change komandalaridan foydalanishingiz mumkin.",
            )
        except Exception:
            pass
        return True, (
            "✅ Kanal uchun almaz tarqatish yoqildi.\n"
            f"ID: <code>{channel_id}</code>\n"
            "Kanalga tasdiq xabari yuborildi."
        )


    async def start_channel_diamond_distribution(
        self,
        bot: Bot,
        *,
        channel_id: int,
        mode: str,
        amount: int,
    ) -> tuple[bool, str]:
        if channel_id >= 0:
            return False, "Kanal ID manfiy bo'lishi kerak. Masalan: <code>-1001234567890</code>"
        if mode not in {"send", "change"}:
            return False, "Tarqatish turi noto'g'ri."
        if amount < (1 if mode == "send" else 2):
            minimum = 1 if mode == "send" else 2
            return False, f"Minimal miqdor: {minimum} olmos."
        if not await self.bot_is_admin(bot, channel_id):
            return False, "Bot bu kanalda admin emas yoki kanal topilmadi."

        async with self.session_factory() as session:
            channel_user = (
                await session.execute(select(User).where(User.telegram_id == channel_id))
            ).scalar_one_or_none()
            if channel_user is None:
                channel_user = User(
                    telegram_id=channel_id,
                    display_name=f"Channel {channel_id}",
                    language=self.settings.default_language,
                    language_selected=False,
                )
                session.add(channel_user)
                await session.flush()
            if int(channel_user.diamonds or 0) < amount:
                return False, (
                    f"Kanal balansida olmos yetarli emas.\n"
                    f"Kerak: <b>{amount}</b>, mavjud: <b>{int(channel_user.diamonds or 0)}</b>"
                )

            channel_user.diamonds = int(channel_user.diamonds or 0) - amount
            action = "send_gift_create" if mode == "send" else "giveaway_create"
            self._record_diamond_transaction(
                session,
                channel_user,
                -amount,
                action,
                note=f"Kanalda almaz tarqatish: mode={mode}, amount={amount}",
                chat_id=channel_id,
            )
            giveaway = DiamondGiveaway(
                chat_id=channel_id,
                creator_telegram_id=channel_id,
                amount=amount,
                participants_json="[]",
                status="send_active" if mode == "send" else "active",
            )
            session.add(giveaway)
            await session.flush()

            try:
                chat = await asyncio.wait_for(bot.get_chat(channel_id), timeout=8)
                channel_title = getattr(chat, "title", None) or channel_user.display_name or f"Channel {channel_id}"
                channel_user.display_name = str(channel_title)[:255]
            except Exception:
                channel_title = channel_user.display_name or f"Channel {channel_id}"
            channel_name = escape(str(channel_title))
            diamond = f'<tg-emoji emoji-id="{DIAMOND_EMOJI_ID}">💎</tg-emoji>'
            gift = f'<tg-emoji emoji-id="{GIFT_EMOJI_ID}">🎁</tg-emoji>'
            if mode == "send":
                text = (
                    f"{gift} <b>Almaz tarqatish boshlandi</b>\n\n"
                    f"📣 <b>{channel_name}</b>\n"
                    f"{diamond} Jami: <b>{amount}</b> ta\n"
                    f"📦 Qoldi: <b>{amount}</b> ta\n\n"
                    "👥 <b>Olganlar</b>\n"
                    "Hali hech kim olmadi.\n\n"
                    "👇 Pastdagi tugma orqali 1 ta olmos oling."
                )
                reply_markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🎁 1 💎 olish", callback_data=f"sendgift:claim:{giveaway.id}")]
                    ]
                )
            else:
                text = (
                    f"{channel_name} kimgadir {amount} ta "
                    f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> sovg'a qilmoqchi!\n\n"
                    "Ishtirokchilar:\n-\n\n"
                    "Ishtirokchilar soni: 0/50"
                )
                reply_markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🎁 Qatnashish", callback_data=f"giveaway:join:{giveaway.id}")],
                        [InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"giveaway:finish:{giveaway.id}")],
                    ]
                )

            try:
                sent = await asyncio.wait_for(
                    bot.send_message(channel_id, text, reply_markup=reply_markup),
                    timeout=12,
                )
            except asyncio.TimeoutError:
                await session.rollback()
                return False, "Kanalga xabar yuborish vaqti tugadi. Bot kanalga post yozish huquqiga ega ekanini tekshiring."
            except Exception as exc:
                await session.rollback()
                return False, f"Kanalga xabar yuborilmadi: {escape(str(exc))}"

            giveaway.message_id = sent.message_id
            await self._set_bot_setting_value(session, f"{CHANNEL_GIFTS_ENABLED_PREFIX}{channel_id}", "1")
            await session.commit()

        label = "tez tarqatish" if mode == "send" else "ro'yxatdan o'tish"
        return True, (
            "✅ Almaz tarqatish kanalga yuborildi.\n\n"
            f"Kanal ID: <code>{channel_id}</code>\n"
            f"Turi: <b>{label}</b>\n"
            f"Miqdor: <b>{amount}</b> 💎"
        )


    async def add_premium_group(
        self,
        title: str,
        invite_link: str,
        diamond_price: int,
        created_by: int,
    ) -> PremiumGroup:
        async with self.session_factory() as session:
            group = PremiumGroup(
                title=title.strip()[:255],
                invite_link=invite_link.strip(),
                diamond_price=max(0, diamond_price),
                created_by=created_by,
                is_active=True,
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)
            return group


    async def premium_groups(self, include_inactive: bool = False) -> list[PremiumGroup]:
        async with self.session_factory() as session:
            stmt = select(PremiumGroup).order_by(PremiumGroup.total_diamonds.desc(), PremiumGroup.id.desc())
            if not include_inactive:
                stmt = stmt.where(
                    PremiumGroup.is_active.is_(True),
                    PremiumGroup.total_diamonds > 0,
                )
            return (await session.execute(stmt)).scalars().all()


    async def premium_groups_text(self, include_inactive: bool = False) -> str:
        groups = await self.premium_groups(include_inactive=include_inactive)
        if not groups:
            return (
                "🎲 <b>Premium guruhlar</b>\n\n"
                "Hozircha guruhlar <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> almaz yubormagan.\n"
                "Guruhda <code>/gsend miqdor</code> yozib reytingga chiqish mumkin."
            )
        return "🎲 <b>Premium guruhlar</b>\n\nKerakli guruhni tanlang:"


    async def _premium_reset_interval_minutes_in_session(self, session: AsyncSession) -> int:
        raw = await self._get_bot_setting_value(session, PREMIUM_RESET_INTERVAL_MINUTES_KEY, "0")
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0


    async def get_premium_reset_interval_minutes(self) -> int:
        async with self.session_factory() as session:
            return await self._premium_reset_interval_minutes_in_session(session)


    async def premium_reset_timer_text(self) -> str:
        minutes = await self.get_premium_reset_interval_minutes()
        if minutes <= 0:
            return "⏱ Premium timer: <b>o'chirilgan</b>"
        async with self.session_factory() as session:
            next_reset = await session.scalar(
                select(func.min(PremiumGroup.reset_at)).where(
                    PremiumGroup.is_active.is_(True),
                    PremiumGroup.total_diamonds > 0,
                    PremiumGroup.reset_at.is_not(None),
                )
            )
        if next_reset:
            remaining = max(0, int((self._ensure_utc(next_reset) - self._now_utc()).total_seconds() // 60))
            return (
                f"⏱ Premium timer: <b>{self._format_minutes(minutes)}</b>\n"
                f"⏳ Keyingi bankrot: taxminan <b>{self._format_minutes(remaining)}</b>"
            )
        return f"⏱ Premium timer: <b>{self._format_minutes(minutes)}</b>"


    async def set_premium_reset_interval_minutes(self, raw_minutes: Union[int, str]) -> tuple[bool, str]:
        try:
            minutes = int(str(raw_minutes).strip())
        except (TypeError, ValueError):
            return False, "Timer faqat son bo'lishi kerak. Masalan: <code>1440</code>"
        if minutes < 0:
            return False, "Timer manfiy bo'lmaydi. O'chirish uchun <code>0</code> yuboring."
        if minutes > 525600:
            return False, "Timer juda katta. Eng ko'pi: <code>525600</code> daqiqa (1 yil)."

        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, PREMIUM_RESET_INTERVAL_MINUTES_KEY, str(minutes))
            active_groups = (
                await session.execute(
                    select(PremiumGroup).where(
                        PremiumGroup.is_active.is_(True),
                        PremiumGroup.total_diamonds > 0,
                    )
                )
            ).scalars().all()
            reset_at = self._now_utc() + timedelta(minutes=minutes) if minutes > 0 else None
            for group in active_groups:
                group.reset_at = reset_at
            await session.commit()

        if minutes == 0:
            return True, "✅ Premium timer o'chirildi. Guruhlar avtomatik bankrot qilinmaydi."
        return (
            True,
            f"✅ Premium timer yangilandi: <b>{self._format_minutes(minutes)}</b>.\n"
            "Aktiv premium guruhlar uchun vaqt hozirdan qayta hisoblandi.",
        )


    async def _clear_premium_group_balance(self, session: AsyncSession, group: PremiumGroup) -> None:
        group.total_diamonds = 0
        group.diamond_price = 0
        group.top_sender_telegram_id = None
        group.top_sender_name = None
        group.top_sender_diamonds = 0
        group.reset_at = None
        group.is_active = False
        contributions = (
            await session.execute(
                select(PremiumGroupContribution).where(PremiumGroupContribution.premium_group_id == group.id)
            )
        ).scalars().all()
        for contribution in contributions:
            await session.delete(contribution)


    async def reset_expired_premium_groups(self) -> int:
        async with self.session_factory() as session:
            interval_minutes = await self._premium_reset_interval_minutes_in_session(session)
            if interval_minutes <= 0:
                return 0
            now = self._now_utc()
            expired_groups = (
                await session.execute(
                    select(PremiumGroup).where(
                        PremiumGroup.is_active.is_(True),
                        PremiumGroup.total_diamonds > 0,
                        PremiumGroup.reset_at.is_not(None),
                        PremiumGroup.reset_at <= now,
                    )
                )
            ).scalars().all()
            for group in expired_groups:
                await self._clear_premium_group_balance(session, group)
            await session.commit()
        return len(expired_groups)


    async def premium_reset_watchdog(self) -> None:
        reset_count = await self.reset_expired_premium_groups()
        if reset_count:
            logger.info("Premium group timer reset %s group(s)", reset_count)


    async def owner_premium_groups_manage_text(self) -> str:
        groups = await self.premium_groups(include_inactive=True)
        timer_text = await self.premium_reset_timer_text()
        if not groups:
            return f"🎲 <b>Premium guruhlar boshqaruvi</b>\n\n{timer_text}\n\nHozircha ro'yxatda guruh yo'q."
        lines = [
            "🎲 <b>Premium guruhlar boshqaruvi</b>",
            "",
            timer_text,
            "",
            "Bankrot qilish uchun guruh tugmasini bosing:",
            "",
        ]
        for group in groups:
            status = "aktiv" if group.is_active and (group.total_diamonds or 0) > 0 else "bankrot"
            if status == "aktiv" and group.reset_at:
                remaining = max(0, int((self._ensure_utc(group.reset_at) - self._now_utc()).total_seconds() // 60))
                status = f"{status}, {self._format_minutes(remaining)} qoldi"
            lines.append(f"<b>{group.title}</b> | <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {group.total_diamonds or 0} | {status}")
        return "\n".join(lines)


    async def premium_blocked_users_text(self) -> str:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(PremiumBlockedUser).order_by(PremiumBlockedUser.created_at.desc()).limit(50)
                )
            ).scalars().all()
        if not rows:
            return "🚷 <b>Bloklangan userlar</b>\n\nHozircha bloklangan user yo'q."
        lines = ["🚷 <b>Bloklangan userlar</b>\n"]
        for idx, row in enumerate(rows, 1):
            reason = f" | {escape(row.reason)}" if row.reason else ""
            lines.append(f"{idx}. {self._tg_mention(row.telegram_id, row.display_name)} - <code>{row.telegram_id}</code>{reason}")
        return "\n".join(lines)


    async def bankrupt_premium_group(self, raw_group_id: str) -> tuple[bool, str]:
        raw_group_id = raw_group_id.strip()
        if not raw_group_id.isdigit():
            return False, "Guruh ID raqam bo'lishi kerak. Ro'yxatdan IDni yuboring."
        group_id = int(raw_group_id)
        async with self.session_factory() as session:
            group = (
                await session.execute(select(PremiumGroup).where(PremiumGroup.id == group_id))
            ).scalar_one_or_none()
            if group is None:
                return False, "Bunday premium guruh topilmadi."
            title = group.title
            group.total_diamonds = 0
            group.diamond_price = 0
            group.top_sender_telegram_id = None
            group.top_sender_name = None
            group.top_sender_diamonds = 0
            group.reset_at = None
            group.is_active = False
            await self._clear_premium_group_balance(session, group)
            await session.commit()
        return True, f"🧨 <b>{escape(title)}</b> bankrot qilindi va premium ro'yxatdan olib tashlandi."


    async def bankrupt_premium_group_by_chat(self, chat_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            group = (
                await session.execute(select(PremiumGroup).where(PremiumGroup.group_chat_id == chat_id))
            ).scalar_one_or_none()
            if group is None or (group.total_diamonds or 0) <= 0:
                return False, "Bu guruh premium ro'yxatda topilmadi."
            group_id = group.id
        return await self.bankrupt_premium_group(str(group_id))


    async def _find_user_by_identifier(self, session: AsyncSession, raw_identifier: str) -> Optional[User]:
        identifier = raw_identifier.strip()
        if not identifier:
            return None
        if identifier.lstrip("-").isdigit():
            return (
                await session.execute(select(User).where(User.telegram_id == int(identifier)))
            ).scalar_one_or_none()
        username = self.normalize_admin_username(identifier).lower()
        if not username:
            return None
        users = (
            await session.execute(select(User).where(User.username.is_not(None)))
        ).scalars().all()
        return next((user for user in users if (user.username or "").lower().lstrip("@") == username), None)


    async def block_premium_user(self, raw: str, blocked_by: int) -> tuple[bool, str]:
        parts = raw.strip().split(maxsplit=1)
        if not parts:
            return False, "User ID yoki username yuboring. Masalan: <code>@username reklama</code>"
        reason = parts[1].strip() if len(parts) > 1 else None
        async with self.session_factory() as session:
            user = await self._find_user_by_identifier(session, parts[0])
            if user is None:
                return False, "User topilmadi. U avval botda /start qilgan bo'lishi kerak."
            telegram_id = user.telegram_id
            display_name = user.display_name
            row = (
                await session.execute(select(PremiumBlockedUser).where(PremiumBlockedUser.telegram_id == telegram_id))
            ).scalar_one_or_none()
            if row is None:
                row = PremiumBlockedUser(
                    telegram_id=telegram_id,
                    display_name=display_name,
                    reason=reason,
                    blocked_by=blocked_by,
                )
                session.add(row)
            else:
                row.display_name = display_name
                row.reason = reason
                row.blocked_by = blocked_by
            await session.commit()
        self.invalidate_blocked_user_cache(telegram_id)
        return True, f"🚫 User bloklandi: {self._tg_mention(telegram_id, display_name)}"


    async def unblock_premium_user(self, raw: str) -> tuple[bool, str]:
        raw = raw.strip().split(maxsplit=1)[0] if raw.strip() else ""
        if not raw:
            return False, "Blokdan chiqarish uchun user ID yoki username yuboring."
        async with self.session_factory() as session:
            user = await self._find_user_by_identifier(session, raw)
            telegram_id = user.telegram_id if user else int(raw) if raw.lstrip("-").isdigit() else None
            if telegram_id is None:
                return False, "User topilmadi. ID yoki username'ni tekshiring."
            row = (
                await session.execute(select(PremiumBlockedUser).where(PremiumBlockedUser.telegram_id == telegram_id))
            ).scalar_one_or_none()
            if row is None:
                return False, "Bu user bloklanganlar ro'yxatida yo'q."
            await session.delete(row)
            await session.commit()
        self.invalidate_blocked_user_cache(telegram_id)
        return True, f"✅ User blokdan chiqarildi: <code>{telegram_id}</code>"


    async def is_premium_user_blocked(self, telegram_id: int) -> bool:
        now = self._monotonic()
        cached = self._blocked_users_cache.get(telegram_id)
        if cached is not None:
            expire_time, result = cached
            if expire_time > now:
                return result
        async with self.session_factory() as session:
            row = (
                await session.execute(select(PremiumBlockedUser.telegram_id).where(PremiumBlockedUser.telegram_id == telegram_id))
            ).scalar_one_or_none()
        is_blocked = row is not None
        self._blocked_users_cache[telegram_id] = (now + self._blocked_users_cache_ttl, is_blocked)
        self._prune_cache_if_needed(self._blocked_users_cache)  # type: ignore[arg-type]
        return is_blocked


    async def contribute_premium_group(
        self,
        bot: Bot,
        chat_id: int,
        chat_title: str,
        tg_user: TgUser,
        diamonds: int,
    ) -> tuple[bool, str]:
        if diamonds <= 0:
            return False, "Miqdor musbat bo'lishi kerak. Masalan: /gsend 10"
        if await self.is_premium_user_blocked(tg_user.id):
            return False, "Siz premium guruh reytingiga almaz yuborishdan bloklangansiz."

        user = await self.ensure_user(tg_user)
        invite_link = await self.group_return_url(bot, chat_id)
        async with self.session_factory() as session:
            fresh_user = (
                await session.execute(select(User).where(User.telegram_id == user.telegram_id))
            ).scalar_one_or_none()
            if fresh_user is None:
                return False, "Avval /start bosing."
            if (fresh_user.diamonds or 0) < diamonds:
                return False, f"Balans yetarli emas. Kerak: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {diamonds}"

            group = (
                await session.execute(
                    select(PremiumGroup).where(PremiumGroup.group_chat_id == chat_id)
                )
            ).scalar_one_or_none()
            if group is None:
                group = PremiumGroup(
                    title=(chat_title or "Group")[:255],
                    invite_link=invite_link,
                    diamond_price=0,
                    total_diamonds=0,
                    group_chat_id=chat_id,
                    created_by=tg_user.id,
                    is_active=True,
                )
                session.add(group)
                await session.flush()
            else:
                group.title = (chat_title or group.title or "Group")[:255]
                group.invite_link = invite_link
                group.is_active = True

            contribution = (
                await session.execute(
                    select(PremiumGroupContribution).where(
                        PremiumGroupContribution.premium_group_id == group.id,
                        PremiumGroupContribution.user_telegram_id == tg_user.id,
                    )
                )
            ).scalar_one_or_none()
            if contribution is None:
                contribution = PremiumGroupContribution(
                    premium_group_id=group.id,
                    user_telegram_id=tg_user.id,
                    user_name=fresh_user.display_name,
                    diamonds=0,
                )
                session.add(contribution)

            fresh_user.diamonds -= diamonds
            self._record_diamond_transaction(
                session,
                fresh_user,
                -diamonds,
                "premium_group_contribution",
                note=f"Premium guruh reytingi: {chat_title or chat_id}",
                chat_id=chat_id,
            )
            group.total_diamonds = int(group.total_diamonds or 0) + diamonds
            group.diamond_price = group.total_diamonds
            reset_interval_minutes = await self._premium_reset_interval_minutes_in_session(session)
            group.reset_at = (
                self._now_utc() + timedelta(minutes=reset_interval_minutes)
                if reset_interval_minutes > 0
                else None
            )
            contribution.user_name = fresh_user.display_name
            contribution.diamonds = int(contribution.diamonds or 0) + diamonds

            top = (
                await session.execute(
                    select(PremiumGroupContribution).where(
                        PremiumGroupContribution.premium_group_id == group.id
                    )
                )
            ).scalars().all()
            top_contributor = max(top, key=lambda item: item.diamonds, default=contribution)
            if contribution.diamonds >= top_contributor.diamonds:
                top_contributor = contribution
            group.top_sender_telegram_id = top_contributor.user_telegram_id
            group.top_sender_name = top_contributor.user_name
            group.top_sender_diamonds = top_contributor.diamonds

            await session.commit()
            total = group.total_diamonds
            user_total = contribution.diamonds

        return (
            True,
            f"✅ {self._tg_mention(tg_user.id, user.display_name)} guruh reytingi uchun <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {diamonds} almaz yubordi.\n"
            f"🎲 Guruh jami: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {total}\n"
            f"👤 Siz yuborgan jami: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {user_total}",
        )


    async def buy_premium_group(self, telegram_id: int, premium_group_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            group = (
                await session.execute(
                    select(PremiumGroup).where(
                        PremiumGroup.id == premium_group_id,
                        PremiumGroup.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if group is None:
                return False, "Premium guruh topilmadi yoki o'chirilgan."
            return (
                True,
                f"🎲 <b>{group.title}</b>\n\n"
                f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> Kirish narxi: <b>{group.diamond_price}</b>\n"
                f"🔗 Guruh linki: {group.invite_link}",
            )

    # ------------------- Sub-Admin & Permissions System -------------------
    async def get_sub_admin_role(self, user_id: int) -> Optional[str]:
        if user_id in self.settings.admin_ids:
            return "super_admin"
        async with self.session_factory() as session:
            sub = (await session.execute(
                select(SubAdmin).where(SubAdmin.user_telegram_id == user_id)
            )).scalar_one_or_none()

            if sub is None:
                # Check if this user is registered in User table with a username matching a SubAdmin entry
                u = (await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )).scalar_one_or_none()
                if u and u.username:
                    clean = u.username.lstrip("@").strip()
                    if clean:
                        sub = (await session.execute(
                            select(SubAdmin).where(
                                func.lower(SubAdmin.username) == clean.lower()
                            )
                        )).scalars().first()
                        if sub:
                            if sub.user_telegram_id == 0 or sub.user_telegram_id != user_id:
                                sub.user_telegram_id = user_id
                                await session.commit()

            return sub.role if sub else None

    async def has_admin_permission(self, user_id: int, required_role: str = "any") -> bool:
        role = await self.get_sub_admin_role(user_id)
        if not role:
            return False
        if role == "super_admin":
            return True
        if required_role == "any":
            return True
        return role == required_role

    async def set_sub_admin(
        self,
        admin_id: int,
        target_user_id: int,
        username: Optional[str],
        role: str,
        bot: Optional[Bot] = None,
    ) -> tuple[bool, str]:
        if not await self.has_admin_permission(admin_id, "super_admin"):
            return False, "❌ Faqat Super Admin (Owner) moderator qo'sha oladi!"
        if role not in {"super_admin", "finance_admin", "moderator", "media_manager"}:
            return False, "❌ Noto'g'ri rol parametri berildi."

        clean_user = username.lstrip("@").strip() if username else None

        async with self.session_factory() as session:
            if not target_user_id and clean_user:
                u = (await session.execute(
                    select(User).where(func.lower(User.username) == clean_user.lower())
                )).scalar_one_or_none()
                if u:
                    target_user_id = u.telegram_id

            sub = None
            if target_user_id:
                sub = (await session.execute(
                    select(SubAdmin).where(SubAdmin.user_telegram_id == target_user_id)
                )).scalar_one_or_none()

            if sub is None and clean_user:
                sub = (await session.execute(
                    select(SubAdmin).where(func.lower(SubAdmin.username) == clean_user.lower())
                )).scalars().first()

            if sub is None:
                sub = SubAdmin(
                    user_telegram_id=target_user_id or 0,
                    username=clean_user,
                    role=role,
                    created_by=admin_id,
                )
                session.add(sub)
            else:
                if target_user_id:
                    sub.user_telegram_id = target_user_id
                sub.role = role
                if clean_user:
                    sub.username = clean_user
            await session.commit()

        role_labels = {
            "super_admin": "🛡 Super Admin",
            "finance_admin": "💳 Moliya Admini",
            "moderator": "👮 Moderator",
            "media_manager": "📢 Media / Reklama Admini",
        }
        lbl = role_labels.get(role, role)
        disp_target = f"@{clean_user}" if clean_user else f"ID: {target_user_id}"
        await self.log_admin_action(
            admin_id=admin_id,
            admin_name=str(admin_id),
            action_type="set_sub_admin",
            details=f"Target: {disp_target} (ID: {target_user_id}), Role: {role}",
            bot=bot,
        )
        return True, f"✅ Foydalanuvchi {disp_target} ga <b>{lbl}</b> huquqi berildi."

    async def remove_sub_admin(
        self,
        admin_id: int,
        target_user_id: int,
        bot: Optional[Bot] = None,
    ) -> tuple[bool, str]:
        if not await self.has_admin_permission(admin_id, "super_admin"):
            return False, "❌ Faqat Super Admin (Owner) moderatorni o'chira oladi!"
        async with self.session_factory() as session:
            sub = (await session.execute(
                select(SubAdmin).where(
                    or_(
                        SubAdmin.user_telegram_id == target_user_id,
                        SubAdmin.user_telegram_id == 0,
                    )
                )
            )).scalars().first()
            if sub is None:
                return False, "❌ Ushbu foydalanuvchi sub-adminlar ro'yxatida topilmadi."
            await session.delete(sub)
            await session.commit()

        await self.log_admin_action(
            admin_id=admin_id,
            admin_name=str(admin_id),
            action_type="remove_sub_admin",
            details=f"Removed sub-admin target: {target_user_id}",
            bot=bot,
        )
        return True, f"✅ Sub-admin <code>{target_user_id}</code> ro'yxatdan olib tashlandi."

    async def list_sub_admins(self) -> list[SubAdmin]:
        async with self.session_factory() as session:
            return (await session.execute(
                select(SubAdmin).order_by(SubAdmin.created_at.desc())
            )).scalars().all()

    # ------------------- Admin Audit Log System -------------------
    async def log_admin_action(
        self,
        admin_id: int,
        admin_name: str,
        action_type: str,
        details: Optional[str] = None,
        bot: Optional[Bot] = None,
    ) -> None:
        async with self.session_factory() as session:
            log_entry = AdminAuditLog(
                admin_telegram_id=admin_id,
                admin_name=admin_name[:255],
                action_type=action_type[:64],
                details=details,
            )
            session.add(log_entry)
            await session.commit()

        if bot:
            admin_group_id = await self.get_admin_group_id()
            if admin_group_id < 0:
                msg = (
                    f"🛡 <b>Admin Audit Log</b>\n\n"
                    f"👤 Admin: {self._tg_mention(admin_id, admin_name)} (ID: <code>{admin_id}</code>)\n"
                    f"⚡️ Harakat: <b>{escape(action_type)}</b>\n"
                    f"📝 Tafsilot: {escape(details or '—')}\n"
                    f"⏰ Vaqt: <code>{datetime.now(timezone.utc).strftime('%H:%M:%S %d.%m.%Y')}</code>"
                )
                try:
                    await bot.send_message(admin_group_id, msg)
                except Exception as exc:
                    logger.warning("Failed to send admin audit log to %s: %s", admin_group_id, exc)

    # ------------------- Promo Code System -------------------
    async def create_promo_code(
        self,
        code: str,
        dollar: int = 0,
        diamond: int = 0,
        max_uses: int = 100,
        expires_in_hours: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> tuple[bool, str]:
        clean_code = code.strip().upper()
        if not clean_code or len(clean_code) < 3:
            return False, "❌ Promokod kamida 3 belgidan iborat bo'lishi kerak."
        if dollar <= 0 and diamond <= 0:
            return False, "❌ Kamida bitta mukofot (dollar yoki olmos) 0 dan katta bo'lishi kerak."

        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours) if expires_in_hours else None

        async with self.session_factory() as session:
            existing = (await session.execute(
                select(PromoCode).where(func.upper(PromoCode.code) == clean_code)
            )).scalar_one_or_none()
            if existing:
                return False, f"❌ <b>{clean_code}</b> nomli promokod allaqachon mavjud."

            promo = PromoCode(
                code=clean_code,
                reward_dollar=max(0, dollar),
                reward_diamond=max(0, diamond),
                max_uses=max(1, max_uses),
                current_uses=0,
                is_active=True,
                expires_at=expires_at,
                created_by=created_by,
            )
            session.add(promo)
            await session.commit()

        exp_str = expires_at.strftime("%d.%m.%Y %H:%M") if expires_at else "Cheksiz"
        return True, (
            f"🎟 <b>Yangi promokod yaratildi!</b>\n\n"
            f"🔑 Kod: <code>{clean_code}</code>\n"
            f"💵 Mukofot: <b>{dollar}</b> $\n"
            f"💎 Mukofot: <b>{diamond}</b> olmos\n"
            f"👥 Maksimal ishlatish: <b>{max_uses}</b> ta\n"
            f"⏳ Amal qilish muddati: <b>{exp_str}</b>"
        )

    async def redeem_promo_code(
        self,
        user_telegram_id: int,
        user_display_name: str,
        code_str: str,
    ) -> tuple[bool, str]:
        clean_code = code_str.strip().upper()
        now = datetime.now(timezone.utc)

        async with self.session_factory() as session:
            promo = (await session.execute(
                select(PromoCode).where(func.upper(PromoCode.code) == clean_code)
            )).scalar_one_or_none()

            if not promo or not promo.is_active:
                return False, "❌ Promokod topilmadi yoki faol emas."
            if promo.max_uses > 0 and promo.current_uses >= promo.max_uses:
                return False, "❌ Promokod ishlatish limiti tugagan."
            if promo.expires_at and self._ensure_utc(promo.expires_at) < now:
                return False, "❌ Promokod muddati o'tgan."

            redemption = (await session.execute(
                select(PromoCodeRedemption).where(
                    PromoCodeRedemption.promo_id == promo.id,
                    PromoCodeRedemption.user_telegram_id == user_telegram_id,
                )
            )).scalar_one_or_none()
            if redemption:
                return False, "❌ Siz ushbu promokodni allaqachon ishlatgansiz."

            user = (await session.execute(
                select(User).where(User.telegram_id == user_telegram_id)
            )).scalar_one_or_none()
            if not user:
                return False, "❌ Foydalanuvchi topilmadi. Botdan /start o'ting."

            promo.current_uses += 1
            session.add(PromoCodeRedemption(promo_id=promo.id, user_telegram_id=user_telegram_id))

            reward_dollar = promo.reward_dollar
            reward_diamond = promo.reward_diamond

            user.dollar += reward_dollar
            user.diamonds += reward_diamond

            if reward_diamond != 0:
                self._record_diamond_transaction(
                    session,
                    user,
                    reward_diamond,
                    "promo_code",
                    note=f"Promokod ishlatildi: {clean_code}",
                )
            if reward_dollar != 0:
                self._record_dollar_transaction(
                    session,
                    user,
                    reward_dollar,
                    "promo_code",
                    note=f"Promokod ishlatildi: {clean_code}",
                )

            await session.commit()

        rewards = []
        if reward_dollar > 0:
            rewards.append(f"💵 {reward_dollar} $")
        if reward_diamond > 0:
            rewards.append(f"💎 {reward_diamond} olmos")
        rewards_text = " va ".join(rewards)

        return True, f"🎉 <b>Tabriklaymiz!</b> Promokod muvaffaqiyatli ishlatildi.\nSizga berildi: <b>{rewards_text}</b>"

    async def list_active_promo_codes(self) -> list[PromoCode]:
        async with self.session_factory() as session:
            return (await session.execute(
                select(PromoCode).order_by(PromoCode.created_at.desc())
            )).scalars().all()

    # ------------------- 2X Event Mode (Happy Hours) -------------------
    async def is_2x_event_active(self) -> bool:
        async with self.session_factory() as session:
            val = await self._get_bot_setting_value(session, "event_2x_active", "false")
        return str(val).lower() == "true"

    async def toggle_2x_event(self, bot: Optional[Bot] = None, admin_id: int = 0) -> tuple[bool, str]:
        async with self.session_factory() as session:
            current = await self._get_bot_setting_value(session, "event_2x_active", "false")
            new_val = "false" if str(current).lower() == "true" else "true"
            setting = (await session.execute(
                select(BotSetting).where(BotSetting.key == "event_2x_active")
            )).scalar_one_or_none()
            if setting is None:
                setting = BotSetting(key="event_2x_active", value=new_val)
                session.add(setting)
            else:
                setting.value = new_val
            await session.commit()

        is_on = new_val == "true"
        status_str = "🔥 <b>2X EVENT REJIM YOQILDI! (Happy Hours)</b>\nBarcha o'yin mukofotlari 2 BARAVAR oshirildi!" if is_on else "🔴 <b>2X Event rejim o'chirildi.</b>"

        if admin_id > 0:
            await self.log_admin_action(
                admin_id=admin_id,
                admin_name=str(admin_id),
                action_type="toggle_2x_event",
                details=f"2X Event state: {new_val}",
                bot=bot,
            )

        return is_on, status_str

    # ------------------- Scheduled Broadcast System -------------------
    async def schedule_broadcast(
        self,
        target: str,
        from_chat_id: int,
        message_id: int,
        scheduled_at: datetime,
        pin_message: bool = False,
        created_by: Optional[int] = None,
    ) -> tuple[bool, str]:
        if target not in {"users", "groups"}:
            return False, "❌ Target 'users' yoki 'groups' bo'lishi kerak."

        async with self.session_factory() as session:
            broadcast_item = ScheduledBroadcast(
                target=target,
                from_chat_id=from_chat_id,
                message_id=message_id,
                pin_message=pin_message,
                status="pending",
                scheduled_at=scheduled_at,
                created_by=created_by,
            )
            session.add(broadcast_item)
            await session.commit()

        dt_str = scheduled_at.strftime("%d.%m.%Y %H:%M")
        target_str = "Foydalanuvchilarga" if target == "users" else "Guruhlarga"
        pin_str = "Ha" if pin_message else "Yo'q"
        return True, (
            f"📅 <b>Reklama vaqt bo'yicha rejalashtirildi!</b>\n\n"
            f"🎯 Nishon: <b>{target_str}</b>\n"
            f"⏰ Rejalashtirilgan vaqt: <b>{dt_str}</b>\n"
            f"📌 Xabarni qadash (Pin): <b>{pin_str}</b>"
        )

    async def process_due_scheduled_broadcasts(self, bot: Bot) -> int:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            due_items = (await session.execute(
                select(ScheduledBroadcast).where(
                    ScheduledBroadcast.status == "pending",
                    ScheduledBroadcast.scheduled_at <= now,
                )
            )).scalars().all()

            if not due_items:
                return 0

            for item in due_items:
                item.status = "processing"
            await session.commit()

        processed_count = 0
        for item in due_items:
            sent, failed = await self.broadcast_message(
                bot=bot,
                target=item.target,
                from_chat_id=item.from_chat_id,
                message_id=item.message_id,
            )

            async with self.session_factory() as session:
                db_item = (await session.execute(
                    select(ScheduledBroadcast).where(ScheduledBroadcast.id == item.id)
                )).scalar_one_or_none()
                if db_item:
                    db_item.status = "completed"
                    db_item.sent_count = sent
                    db_item.failed_count = failed
                await session.commit()

            processed_count += 1
            logger.info("Processed scheduled broadcast #%s: sent=%s, failed=%s", item.id, sent, failed)

        return processed_count

    # ------------------- DAU / MAU & Growth Analytics -------------------
    async def get_dau_mau_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        thirty_days_ago = now - timedelta(days=30)

        async with self.session_factory() as session:
            total_users = await session.scalar(select(func.count(User.id))) or 0
            total_groups = await session.scalar(select(func.count(Group.id))) or 0
            total_games = await session.scalar(select(func.count(Game.id)).where(Game.status == GameStatus.COMPLETED.value)) or 0

            dau = await session.scalar(
                select(func.count(User.id)).where(User.updated_at >= one_day_ago)
            ) or 0

            mau = await session.scalar(
                select(func.count(User.id)).where(User.updated_at >= thirty_days_ago)
            ) or 0

            new_today = await session.scalar(
                select(func.count(User.id)).where(User.created_at >= one_day_ago)
            ) or 0

        return {
            "total_users": total_users,
            "total_groups": total_groups,
            "total_games": total_games,
            "dau": dau,
            "mau": mau,
            "new_today": new_today,
        }

    async def analytics_dashboard_text(self) -> str:
        stats = await self.get_dau_mau_stats()
        event_2x = await self.is_2x_event_active()
        event_status = "🔥 Yoqilgan (2x)" if event_2x else "⚪️ O'chirilgan"

        return (
            "📈 <b>Bot Analitikasi va O'sish Ko'rsatkichlari</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{stats['total_users']:,}</b>\n"
            f"GB Jami guruhlar: <b>{stats['total_groups']:,}</b>\n"
            f"🎮 O'tkazilgan o'yinlar: <b>{stats['total_games']:,}</b>\n\n"
            f"⚡️ <b>DAU (Kunlik Aktiv Userlar):</b> <b>{stats['dau']:,}</b>\n"
            f"📅 <b>MAU (Oylik Aktiv Userlar):</b> <b>{stats['mau']:,}</b>\n"
            f"🆕 <b>Bugungi yangi foydalanuvchilar:</b> <b>+{stats['new_today']:,}</b>\n\n"
            f"🔥 2X Event Mode: <b>{event_status}</b>"
        )

    # ------------------- Auto Weekly Top Reward Watchdog -------------------
    async def run_weekly_top_reward_distribution(self, bot: Bot) -> str:
        async with self.session_factory() as session:
            top_users = (await session.execute(
                select(User).order_by(User.wins.desc()).limit(3)
            )).scalars().all()

            if not top_users:
                return "Haftalik top o'yinchilar topilmadi."

            rewards = [
                (500, 100, "🥇 1-o'rin"),
                (300, 50, "🥈 2-o'rin"),
                (100, 20, "🥉 3-o'rin"),
            ]

            report_lines = ["🏆 <b>Haftalik Top O'yinchilar Avto-Mukofotlandi!</b>\n"]
            for idx, user in enumerate(top_users):
                if idx >= len(rewards):
                    break
                dollar, diamond, title = rewards[idx]
                user.dollar += dollar
                user.diamonds += diamond

                self._record_dollar_transaction(
                    session, user, dollar, "weekly_top_reward", note=f"Haftalik Top {title}"
                )
                self._record_diamond_transaction(
                    session, user, diamond, "weekly_top_reward", note=f"Haftalik Top {title}"
                )

                mention = self._tg_mention(user.telegram_id, user.display_name)
                report_lines.append(f"{title}: {mention} — 💵 +{dollar} $, 💎 +{diamond} olmos")

                try:
                    await bot.send_message(
                        user.telegram_id,
                        f"🎉 <b>Tabriklaymiz!</b> Siz haftalik top o'yinchilar reytingida <b>{title}</b>ni egalladingiz!\n"
                        f"Sizga 💵 {dollar} $ va 💎 {diamond} olmos mukofot berildi!"
                    )
                except Exception:
                    pass

            await session.commit()

        text = "\n".join(report_lines)
        admin_group_id = await self.get_admin_group_id()
        if admin_group_id < 0:
            try:
                await bot.send_message(admin_group_id, text)
            except Exception as exc:
                logger.warning("Failed to send weekly top reward notification to admin group: %s", exc)

        return text



