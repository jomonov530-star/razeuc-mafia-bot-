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

class EconomyOpsMixin:
    @staticmethod
    def _record_diamond_transaction(
        session: AsyncSession,
        user: User,
        amount: int,
        action: str,
        *,
        note: str = "",
        counterparty: Optional[User] = None,
        chat_id: Optional[int] = None,
    ) -> None:
        if amount == 0:
            return
        session.add(
            DiamondTransaction(
                user_telegram_id=user.telegram_id,
                user_name=(user.display_name or "User")[:255],
                amount=int(amount),
                balance_after=int(user.diamonds or 0),
                action=action[:64],
                note=(note or None),
                counterparty_telegram_id=counterparty.telegram_id if counterparty else None,
                counterparty_name=(counterparty.display_name or "User")[:255] if counterparty else None,
                chat_id=chat_id,
            )
        )


    async def is_gamble_enabled(self) -> bool:
        async with self.session_factory() as session:
            value = await self._get_bot_setting_value(session, GAMBLE_ENABLED_KEY, "1")
        return value != "0"


    async def set_gamble_enabled(self, enabled: bool) -> None:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, GAMBLE_ENABLED_KEY, "1" if enabled else "0")
            await session.commit()


    async def get_gamble_loss_voice_file_id(self) -> str:
        voices = await self.get_gamble_loss_voice_file_ids()
        return random.choice(voices) if voices else ""


    async def get_gamble_win_voice_file_id(self) -> str:
        voices = await self.get_gamble_win_voice_file_ids()
        return random.choice(voices) if voices else ""


    @staticmethod
    def _parse_voice_file_ids(raw: str) -> list[str]:
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return [raw]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
        return []


    async def _get_gamble_voice_file_ids(self, key: str) -> list[str]:
        async with self.session_factory() as session:
            raw = await self._get_bot_setting_value(session, key, "")
        return self._parse_voice_file_ids(raw)


    async def get_gamble_loss_voice_file_ids(self) -> list[str]:
        return await self._get_gamble_voice_file_ids(GAMBLE_LOSS_VOICE_FILE_ID_KEY)


    async def get_gamble_win_voice_file_ids(self) -> list[str]:
        return await self._get_gamble_voice_file_ids(GAMBLE_WIN_VOICE_FILE_ID_KEY)


    async def _add_gamble_voice_file_id(self, key: str, file_id: str) -> int:
        async with self.session_factory() as session:
            raw = await self._get_bot_setting_value(session, key, "")
            voices = self._parse_voice_file_ids(raw)
            if file_id not in voices:
                voices.append(file_id)
            await self._set_bot_setting_value(session, key, json.dumps(voices, ensure_ascii=False))
            await session.commit()
            return len(voices)


    async def set_gamble_loss_voice_file_id(self, file_id: str) -> tuple[bool, str]:
        file_id = (file_id or "").strip()
        if not file_id:
            return False, "Voice file_id topilmadi. Ovozli xabar yuboring."
        count = await self._add_gamble_voice_file_id(GAMBLE_LOSS_VOICE_FILE_ID_KEY, file_id)
        return True, f"✅ Kuyganda chiqadigan voice ro'yxatga qo'shildi. Jami: <b>{count}</b> ta."


    async def set_gamble_win_voice_file_id(self, file_id: str) -> tuple[bool, str]:
        file_id = (file_id or "").strip()
        if not file_id:
            return False, "Voice file_id topilmadi. Ovozli xabar yuboring."
        count = await self._add_gamble_voice_file_id(GAMBLE_WIN_VOICE_FILE_ID_KEY, file_id)
        return True, f"✅ Yutuqda chiqadigan voice ro'yxatga qo'shildi. Jami: <b>{count}</b> ta."


    async def clear_gamble_loss_voice_file_id(self) -> str:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, GAMBLE_LOSS_VOICE_FILE_ID_KEY, "")
            await session.commit()
        return "🗑 Qimorda pul kuyganda chiqadigan voice xabari o'chirildi."


    async def clear_gamble_win_voice_file_id(self) -> str:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, GAMBLE_WIN_VOICE_FILE_ID_KEY, "")
            await session.commit()
        return "🗑 Qimorda yutuq bo'lganda chiqadigan voice xabari o'chirildi."


    async def get_gamble_group(self) -> tuple[Optional[int], str]:
        async with self.session_factory() as session:
            raw_id = await self._get_bot_setting_value(session, GAMBLE_GROUP_ID_KEY, "")
            link = await self._get_bot_setting_value(session, GAMBLE_GROUP_LINK_KEY, "")
        chat_id: Optional[int] = None
        if raw_id and raw_id.lstrip("-").isdigit():
            chat_id = int(raw_id)
        return chat_id, link


    async def is_configured_gamble_group(self, chat_id: int) -> bool:
        configured_id, _link = await self.get_gamble_group()
        return configured_id is not None and int(chat_id) == int(configured_id)


    async def set_gamble_group(self, chat_id: int, link: str) -> None:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, GAMBLE_GROUP_ID_KEY, str(int(chat_id)))
            await self._set_bot_setting_value(session, GAMBLE_GROUP_LINK_KEY, (link or "").strip())
            await session.commit()


    async def clear_gamble_group(self) -> None:
        async with self.session_factory() as session:
            await self._set_bot_setting_value(session, GAMBLE_GROUP_ID_KEY, "")
            await self._set_bot_setting_value(session, GAMBLE_GROUP_LINK_KEY, "")
            await session.commit()


    async def get_gamble_paid_until(self, chat_id: int) -> Optional[datetime]:
        if chat_id >= 0:
            return None
        async with self.session_factory() as session:
            raw = await self._get_bot_setting_value(session, f"{GAMBLE_PAID_GROUP_PREFIX}{chat_id}", "")
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


    async def is_gamble_paid_group(self, chat_id: int) -> bool:
        until = await self.get_gamble_paid_until(chat_id)
        if until is None:
            return False
        return until > datetime.now(timezone.utc)


    async def pay_for_gamble_group(
        self,
        user_telegram_id: int,
        chat_id: int,
        chat_title: str = "",
    ) -> tuple[bool, str, Optional[datetime]]:
        if chat_id >= 0:
            return False, "Bu guruh emas.", None
        price = GAMBLE_GROUP_WEEK_PRICE_DIAMONDS
        async with self.session_factory() as session:
            user = (
                await session.execute(select(User).where(User.telegram_id == user_telegram_id))
            ).scalar_one_or_none()
            if user is None:
                return False, "Foydalanuvchi topilmadi. Avval /start bosing.", None
            if int(user.diamonds or 0) < price:
                return (
                    False,
                    f"❌ Almaz yetarli emas. Kerak: 💎 {price}, Sizda: 💎 {int(user.diamonds or 0)}",
                    None,
                )
            now = datetime.now(timezone.utc)
            key = f"{GAMBLE_PAID_GROUP_PREFIX}{chat_id}"
            existing_raw = await self._get_bot_setting_value(session, key, "")
            existing_until: Optional[datetime] = None
            if existing_raw:
                try:
                    existing_until = datetime.fromisoformat(existing_raw)
                    if existing_until.tzinfo is None:
                        existing_until = existing_until.replace(tzinfo=timezone.utc)
                except ValueError:
                    existing_until = None
            base = existing_until if (existing_until and existing_until > now) else now
            new_until = base + timedelta(days=GAMBLE_GROUP_PAY_DAYS)
            user.diamonds = int(user.diamonds or 0) - price
            self._record_diamond_transaction(
                session,
                user,
                -price,
                "gamble_group_pay",
                note=f"Qimor guruh ochish ({GAMBLE_GROUP_PAY_DAYS} kun): {chat_title or chat_id}",
                chat_id=chat_id,
            )
            await self._set_bot_setting_value(session, key, new_until.isoformat())
            await session.commit()
        return True, "ok", new_until


    async def gamble_chat_check(self, chat_id: int) -> tuple[bool, str]:
        """Returns (allowed, configured_group_link).

        - Private chats (positive chat_id) are always allowed.
        - Designated group (set by owner) is always allowed.
        - Paid groups (active 1-week subscription) are allowed.
        - If no designated group is set AND group has not paid, fallback allow
          (backward compatible until owner configures).
        - Otherwise blocked; caller can offer the official link and a pay button.
        """
        if chat_id > 0:
            return True, ""
        configured_id, link = await self.get_gamble_group()
        if configured_id is not None and chat_id == configured_id:
            return True, link
        if await self.is_gamble_paid_group(chat_id):
            return True, link
        if configured_id is None:
            return True, link
        return False, link


    async def gamble_settings_text(self) -> tuple[str, bool, bool, bool, bool]:
        enabled = await self.is_gamble_enabled()
        loss_voice_file_ids = await self.get_gamble_loss_voice_file_ids()
        win_voice_file_ids = await self.get_gamble_win_voice_file_ids()
        has_loss_voice = bool(loss_voice_file_ids)
        has_win_voice = bool(win_voice_file_ids)
        group_id, group_link = await self.get_gamble_group()
        has_group = group_id is not None
        status = "🟢 <b>YOQILGAN</b>" if enabled else "🔴 <b>O'CHIRILGAN</b>"
        loss_voice_status = f"✅ <b>{len(loss_voice_file_ids)} ta</b>" if has_loss_voice else "❌ <b>Yuklanmagan</b>"
        win_voice_status = f"✅ <b>{len(win_voice_file_ids)} ta</b>" if has_win_voice else "❌ <b>Yuklanmagan</b>"
        if has_group:
            link_part = f"\n🔗 Link: {group_link}" if group_link else ""
            group_status = f"✅ <code>{group_id}</code>{link_part}"
        else:
            group_status = "❌ <b>Belgilanmagan</b> (qimor barcha guruhlarda ishlaydi)"
        text = (
            "🎰 <b>Qimor sozlamalari</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"Holat: {status}\n\n"
            f"🏠 Qimor guruhi: {group_status}\n\n"
            f"💣 Pul kuyganda voice: {loss_voice_status}\n"
            f"🏆 Yutuq bo'lganda voice: {win_voice_status}\n\n"
            "Qimor guruhi belgilansa, /qimor faqat o'sha guruhda ishlaydi. "
            "Boshqa guruhlarda foydalanuvchilarga belgilangan guruh linki ko'rsatiladi."
        )
        return text, enabled, has_loss_voice, has_win_voice, has_group


    async def check_weapon_enabled(self, chat_id: int, weapon_key: str) -> bool:
        gsm = GroupSettingsManager(self.session_factory)
        return await gsm.get_weapon_enabled(chat_id, weapon_key)


    async def transfer_diamonds(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
        *,
        note: str = "",
    ) -> tuple[bool, str]:
        if amount <= 0:
            return False, "Miqdor musbat bo'lishi kerak."
        clean_note = self._short_text(note, 180)
        out_note = "Userga almaz o'tkazma"
        in_note = "Userdan almaz qabul qilindi"
        if clean_note:
            out_note = f"{out_note}. Izoh: {clean_note}"
            in_note = f"{in_note}. Izoh: {clean_note}"
        async with self.session_factory() as session:
            sender = (await session.execute(select(User).where(User.telegram_id == from_user_id))).scalar_one_or_none()
            receiver = (await session.execute(select(User).where(User.telegram_id == to_user_id))).scalar_one_or_none()
            if sender is None or receiver is None:
                return False, "Foydalanuvchi topilmadi."
            if sender.diamonds < amount:
                return False, "Balans yetarli emas."
            sender.diamonds -= amount
            receiver.diamonds += amount
            self._record_diamond_transaction(
                session,
                sender,
                -amount,
                "transfer_out",
                note=out_note,
                counterparty=receiver,
            )
            self._record_diamond_transaction(
                session,
                receiver,
                amount,
                "transfer_in",
                note=in_note,
                counterparty=sender,
            )
            await session.commit()
            return True, "ok"


    @staticmethod
    def _record_dollar_transaction(
        session: AsyncSession,
        user: User,
        amount: int,
        action: str,
        *,
        note: str = "",
        counterparty: Optional[User] = None,
        chat_id: Optional[int] = None,
    ) -> None:
        if amount == 0:
            return
        session.add(
            DollarTransaction(
                user_telegram_id=user.telegram_id,
                user_name=(user.display_name or "User")[:255],
                amount=int(amount),
                balance_after=int(user.dollar or 0),
                action=action[:64],
                note=(note or None),
                counterparty_telegram_id=counterparty.telegram_id if counterparty else None,
                counterparty_name=(counterparty.display_name or "User")[:255] if counterparty else None,
                chat_id=chat_id,
            )
        )


    async def transfer_dollars(self, from_user_id: int, to_user_id: int, amount: int) -> tuple[bool, str]:
        if amount <= 0:
            return False, "Miqdor musbat bo'lishi kerak."
        async with self.session_factory() as session:
            sender = (await session.execute(select(User).where(User.telegram_id == from_user_id))).scalar_one_or_none()
            receiver = (await session.execute(select(User).where(User.telegram_id == to_user_id))).scalar_one_or_none()
            if sender is None or receiver is None:
                return False, "Foydalanuvchi topilmadi."
            if (sender.dollar or 0) < amount:
                return False, "Balans yetarli emas."
            sender.dollar -= amount
            receiver.dollar += amount
            self._record_dollar_transaction(
                session,
                sender,
                -amount,
                "transfer_out",
                note="Userga dollar o'tkazma",
                counterparty=receiver,
            )
            self._record_dollar_transaction(
                session,
                receiver,
                amount,
                "transfer_in",
                note="Userdan dollar qabul qilindi",
                counterparty=sender,
            )
            await session.commit()
            return True, "ok"


    async def exchange_diamonds_to_dollars(self, telegram_id: int, diamonds: Union[int, str]) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing."

            if diamonds == "all":
                amount = int(user.diamonds or 0)
            else:
                amount = int(diamonds)

            if amount <= 0:
                return False, "Almashtirish uchun kamida 💎 1 almaz kerak."
            if (user.diamonds or 0) < amount:
                return False, f"Balans yetarli emas. Kerak: 💎 {amount}"

            dollars = amount * 500
            user.diamonds -= amount
            user.dollar += dollars
            self._record_diamond_transaction(
                session,
                user,
                -amount,
                "diamond_to_dollar",
                note=f"Almaz dollarga almashtirildi: {dollars} dollar",
            )
            await session.commit()

        return True, f"✅ 💎 {amount} almaz → 💵 {dollars} dollar almashtirildi."


    async def get_owned_roles(self, telegram_id: int) -> list[str]:
        key = self._owned_roles_key(telegram_id)
        async with self.session_factory() as session:
            raw = (await session.execute(select(BotSetting.value).where(BotSetting.key == key))).scalar_one_or_none()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        roles: list[str] = []
        for value in parsed if isinstance(parsed, list) else []:
            try:
                role = Role(str(value))
            except ValueError:
                continue
            roles.append(role.value)
        return roles


    async def get_user_selected_next_role(self, telegram_id: int) -> Optional[str]:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None or not user.next_game_role:
                return None
            return user.next_game_role


    async def select_owned_role_for_next_game(self, telegram_id: int, role_value: str) -> tuple[bool, str]:
        try:
            selected_role = Role(role_value)
        except ValueError:
            return False, "Noto'g'ri rol."
        owned = await self.get_owned_roles(telegram_id)
        if selected_role.value not in owned:
            return False, "Bu rol sizning ro'yxatingizda yo'q."
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing."
            user.next_game_role = selected_role.value
            await session.commit()
        return True, f"✅ Keyingi o'yin uchun tanlandi: {role_label(selected_role)}"


    async def buy_shop_item(self, telegram_id: int, item_key: str) -> tuple[bool, str]:
        prices: dict[str, tuple[int, str, str, Union[int, str]]] = {
            "protection": (100, "dollar", "protection", 1),
            "vote_protection": (1, "diamonds", "vote_protection", 1),
            "drug_protection": (100, "dollar", "drug_protection", 1),
            "mask": (100, "dollar", "mask", 1),
            "killer_protection": (2, "diamonds", "killer_protection", 1),
            "miner_protection": (300, "dollar", "miner_protection", 1),
        }
        if item_key.startswith("role:"):
            role_value = item_key.split(":", maxsplit=1)[1]
            shop_role = SHOP_ROLE_BY_VALUE.get(role_value)
            if shop_role is None:
                return False, "Bunday rol do'konda topilmadi."
            async with self.session_factory() as session:
                user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
                if user is None:
                    return False, "Avval /start bosing."
                balance = user.diamonds if shop_role.currency == "diamonds" else user.dollar
                icon = "💎" if shop_role.currency == "diamonds" else "💵"
                if balance < shop_role.price:
                    return False, f"Balans yetarli emas. Kerak: {icon} {shop_role.price}"
                if shop_role.currency == "diamonds":
                    user.diamonds -= shop_role.price
                    self._record_diamond_transaction(
                        session,
                        user,
                        -shop_role.price,
                        "shop_role_buy",
                        note=f"Keyingi o'yin roli: {role_label(shop_role.role)}",
                    )
                else:
                    user.dollar -= shop_role.price
                roles_key = self._owned_roles_key(telegram_id)
                raw_owned = (await session.execute(select(BotSetting).where(BotSetting.key == roles_key))).scalar_one_or_none()
                if raw_owned is None:
                    owned_roles: list[str] = []
                    raw_owned = BotSetting(key=roles_key, value="[]")
                    session.add(raw_owned)
                else:
                    try:
                        owned_roles = json.loads(raw_owned.value or "[]")
                    except (TypeError, ValueError):
                        owned_roles = []
                normalized_owned: list[str] = []
                for rv in owned_roles if isinstance(owned_roles, list) else []:
                    try:
                        normalized_owned.append(Role(str(rv)).value)
                    except ValueError:
                        continue
                # Allow multiple copies — each purchase is one single-use token.
                normalized_owned.append(shop_role.role.value)
                raw_owned.value = json.dumps(normalized_owned, ensure_ascii=True)
                count = normalized_owned.count(shop_role.role.value)
                if not user.next_game_role:
                    user.next_game_role = shop_role.role.value
                await session.commit()
            owned_note = "Ro'yxatdagi rollar o'yinda ishlatilgandan keyin sumkadan o'chiriladi."
            return True, (
                f"✅ {role_label(shop_role.role)} roli sotib olindi!\n"
                f"Sumkangizda bu roldan: <b>{count} ta</b>\n"
                f"{owned_note}"
            )

        if item_key.startswith("disable_role:"):
            role_value = item_key.split(":", maxsplit=1)[1]
            try:
                disabled_role = Role(role_value)
            except ValueError:
                return False, "Bunday faol rol topilmadi."
            if disabled_role not in ACTIVE_ROLE_POOL:
                return False, "Bu rolni faol role pool'dan o'chirib bo'lmaydi."
            async with self.session_factory() as session:
                user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
                if user is None:
                    return False, "Avval /start bosing."
                if user.next_game_disabled_role:
                    return False, "Keyingi o'yin uchun faol rol allaqachon o'chirilgan."
                if user.dollar < 100:
                    return False, "Balans yetarli emas. Kerak: 💵 100"
                user.dollar -= 100
                user.next_game_disabled_role = disabled_role.value
                await session.commit()
            return True, f"✅ Keyingi o'yinda {role_label(disabled_role)} pool'dan olib tashlanadi."

        item = prices.get(item_key)
        if item is None:
            return False, "Bunday mahsulot topilmadi."
        price, currency, field_name, value = item
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing."
            balance = user.diamonds if currency == "diamonds" else user.dollar
            icon = "💎" if currency == "diamonds" else "💵"
            if balance < price:
                return False, f"Balans yetarli emas. Kerak: {icon} {price}"
            if currency == "diamonds":
                user.diamonds -= price
                self._record_diamond_transaction(
                    session,
                    user,
                    -price,
                    "shop_item_buy",
                    note=f"Do'kon mahsuloti: {item_key}",
                )
            else:
                user.dollar -= price
            if field_name == "next_game_role":
                user.next_game_role = str(value)
            else:
                current = int(getattr(user, field_name) or 0)
                setattr(user, field_name, current + int(value))
            await session.commit()
        return True, "✅ Xarid muvaffaqiyatli amalga oshirildi."


