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

class HeroOpsMixin:
    async def user_has_hero(self, telegram_id: int) -> bool:
        async with self.session_factory() as session:
            hero_id = (
                await session.execute(
                    select(Hero.id)
                    .join(User, User.id == Hero.owner_user_id)
                    .where(User.telegram_id == telegram_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return hero_id is not None


    async def _set_active_hero(self, session: AsyncSession, owner_user_id: int, hero: Hero) -> None:
        heroes = (
            await session.execute(select(Hero).where(Hero.owner_user_id == owner_user_id))
        ).scalars().all()
        for item in heroes:
            item.is_active = item.id == hero.id


    @staticmethod
    def _sync_hero_level(hero: Hero) -> None:
        info = hero_level_for_points(int(hero.points or 0))
        hero.level = info.level
        hero.max_defense = HERO_FULL_DEFENSE_PERCENT
        hero.current_defense = min(int(hero.current_defense or 0), HERO_FULL_DEFENSE_PERCENT)
        hero.max_charge = HERO_MAX_CHARGE
        hero.charge = min(int(hero.charge or 0), HERO_MAX_CHARGE)


    @staticmethod
    def _hero_panel_text(hero: Hero) -> str:
        info = hero_level_for_points(int(hero.points or 0))
        fmt = lambda value: f"{int(value or 0):,}".replace(",", " ")
        diamond = f'<tg-emoji emoji-id="{DIAMOND_EMOJI_ID}">💎</tg-emoji>'
        money = f'<tg-emoji emoji-id="{DOLLAR_EMOJI_ID}">💵</tg-emoji>'
        sword = f'<tg-emoji emoji-id="{SWORD_EMOJI_ID}">⚔️</tg-emoji>'
        power_text = "MAX" if info.max_hit else info.power_text
        next_text = (
            f"{info.next_level}-daraja uchun {fmt(info.next_points)} ball"
            if info.next_level and info.next_points is not None
            else "Maksimal daraja"
        )
        sale_text = ""
        if hero.is_for_sale:
            sale_text = f"\n🏷 <b>Sotuvda:</b> {diamond} <b>{fmt(hero.sale_price_diamonds)}</b>"
        return (
            "🥷 <b>GEROY MA'LUMOTI</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Geroy:</b> <b>{safe_hero_name(hero.name)}</b>\n"
            f"⭐️ <b>Daraja:</b> <b>{info.level}</b>\n"
            f"🏆 <b>Jami ball:</b> <b>{fmt(hero.points)}</b>\n\n"
            f"{sword} <b>Kuch:</b> <b>{power_text}</b>\n"
            f"🛡 <b>Himoya:</b> <b>{int(hero.current_defense or 0)}% / {HERO_FULL_DEFENSE_PERCENT}%</b>\n"
            f"🩸 <b>Zaryad:</b> <b>{int(hero.charge or 0)} ta</b>\n\n"
            f"🚀 <b>Keyingi daraja:</b> <b>{next_text}</b>"
            f"{sale_text}\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🛒 <b>Upgrade & Xaridlar</b>\n\n"
            f"➕ <b>+{fmt(HERO_ADD_POINTS_AMOUNT)} Ball</b> - {diamond} <b>{fmt(HERO_ADD_POINTS_PRICE_DIAMONDS)}</b>\n"
            f"🛡 <b>To'liq himoya</b> - {money} <b>{fmt(HERO_UPGRADE_DEFENSE_PRICE_DOLLAR)}</b>\n"
            f"🩸 <b>Qurol zaryadi</b> - {money} <b>{fmt(HERO_RECHARGE_PRICE_DOLLAR)}</b>\n"
            f"🖋 <b>Nomni o'zgartirish</b> - {money} <b>{fmt(HERO_RENAME_PRICE_DOLLAR)}</b>\n"
            "━━━━━━━━━━━━━━━"
        )


    @staticmethod
    def _hero_info_hidden_key(telegram_id: int) -> str:
        return f"{HERO_INFO_HIDDEN_PREFIX}{telegram_id}"


    async def _is_hero_info_hidden(self, session: AsyncSession, telegram_id: int) -> bool:
        value = (
            await session.execute(
                select(BotSetting.value).where(BotSetting.key == self._hero_info_hidden_key(telegram_id))
            )
        ).scalar_one_or_none()
        return value == "1"


    async def set_hero_info_hidden(self, telegram_id: int, hidden: bool) -> str:
        async with self.session_factory() as session:
            key = self._hero_info_hidden_key(telegram_id)
            row = (await session.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
            if row is None:
                session.add(BotSetting(key=key, value="1" if hidden else "0"))
            else:
                row.value = "1" if hidden else "0"
            await session.commit()
        if hidden:
            return "🥷 Geroy ma'lumotlari yashirildi. Endi admin /geroyinfo qilsa ham geroy ko'rinmaydi."
        return "🥷 Geroy ma'lumotlari qayta ochildi. Endi admin /geroyinfo orqali ko'ra oladi."


    def _admin_hero_info_text(self, user: User, hero: Hero) -> str:
        self._sync_hero_level(hero)
        info = hero_level_for_points(int(hero.points or 0))
        fmt = lambda value: f"{int(value or 0):,}".replace(",", " ")
        diamond = f'<tg-emoji emoji-id="{DIAMOND_EMOJI_ID}">💎</tg-emoji>'
        sword = f'<tg-emoji emoji-id="{SWORD_EMOJI_ID}">⚔️</tg-emoji>'
        owner = self._tg_mention(user.telegram_id, user.display_name or str(user.telegram_id))
        power_text = "MAX" if info.max_hit else info.power_text
        next_text = (
            f"{info.next_level}-daraja uchun {fmt(info.next_points)} ball"
            if info.next_level and info.next_points is not None
            else "Maksimal daraja"
        )
        sale_text = (
            f"\n🏷 <b>Sotuvda:</b> {diamond} <b>{fmt(hero.sale_price_diamonds)}</b>"
            if hero.is_for_sale
            else ""
        )
        active_text = "✅ Aktiv" if hero.is_active else "▫️ Aktiv emas"
        return (
            "🥷 <b>GEROY MA'LUMOTI</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Egasi:</b> {owner}\n"
            f"🥷 <b>Geroy:</b> <b>{safe_hero_name(hero.name)}</b>\n"
            f"⭐️ <b>Daraja:</b> <b>{info.level}</b>\n"
            f"🏆 <b>Jami ball:</b> <b>{fmt(hero.points)}</b>\n"
            f"📌 <b>Holat:</b> <b>{active_text}</b>\n\n"
            f"{sword} <b>Kuch:</b> <b>{power_text}</b>\n"
            f"🛡 <b>Himoya:</b> <b>{int(hero.current_defense or 0)}% / {HERO_FULL_DEFENSE_PERCENT}%</b>\n"
            f"🩸 <b>Zaryad:</b> <b>{int(hero.charge or 0)} / {HERO_MAX_CHARGE}</b>\n"
            f"🚀 <b>Keyingi daraja:</b> <b>{next_text}</b>"
            f"{sale_text}\n\n"
            "━━━━━━━━━━━━━━━"
        )


    async def admin_hero_info_text(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            if await self._is_hero_info_hidden(session, telegram_id):
                return False, "❌ Bu userda hali geroy sotib olinmagan."
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Bu userda hali geroy sotib olinmagan."
            text = self._admin_hero_info_text(user, hero)
            await session.commit()
            return True, text


    async def hero_panel_data(self, telegram_id: int) -> tuple[bool, str, bool]:
        async with self.session_factory() as session:
            _, row = await self._hero_owner_row(session, telegram_id)
            if row is None:
                return False, "❌ Sizda hali geroy yo'q. Do'kondan <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> 100 almazga sotib olishingiz mumkin.", False
            self._sync_hero_level(row)
            await session.commit()
            return True, self._hero_panel_text(row), bool(row.is_for_sale)


    async def hero_list_text(self, telegram_id: int) -> tuple[bool, str, list[Hero]]:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing.", []
            heroes = (
                await session.execute(
                    select(Hero)
                    .where(Hero.owner_user_id == user.id)
                    .order_by(Hero.is_active.desc(), Hero.level.desc(), Hero.id.desc())
                )
            ).scalars().all()
            if not heroes:
                return False, "❌ Sizda hali geroy yo'q.", []
            active = next((hero for hero in heroes if hero.is_active), None)
            if active is None:
                active = heroes[0]
                await self._set_active_hero(session, user.id, active)
                await session.commit()
            for hero in heroes:
                self._sync_hero_level(hero)
            await session.commit()
            lines = ["🥷 <b>Mening geroylarim</b>", "━━━━━━━━━━━━━━━", ""]
            for idx, hero in enumerate(heroes, 1):
                mark = "✅ " if hero.is_active else ""
                lines.append(
                    f"{idx}. {mark}<b>{safe_hero_name(hero.name)}</b> | ⭐ <b>{int(hero.level or 1)}</b> | "
                    f"🏆 <b>{int(hero.points or 0)}</b>"
                )
            lines.append("\nPastdan aktiv ishlatiladigan geroyni tanlang.")
            return True, "\n".join(lines), heroes


    async def hero_select_active(self, telegram_id: int, hero_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing."
            hero = (
                await session.execute(select(Hero).where(Hero.id == hero_id, Hero.owner_user_id == user.id))
            ).scalar_one_or_none()
            if hero is None:
                return False, "Bu geroy sizga tegishli emas."
            if hero.is_for_sale:
                return False, "Sotuvdagi geroyni aktiv qilib bo'lmaydi. Avval sotuvdan qaytaring."
            await self._set_active_hero(session, user.id, hero)
            await session.commit()
            return True, f"✅ Aktiv geroy tanlandi: {safe_hero_name(hero.name)}"


    async def hero_info_text(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            _, hero = await self._hero_owner_row(session, telegram_id)
            if hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            self._sync_hero_level(hero)
            await session.commit()
            return True, self._hero_panel_text(hero)


    async def transfer_active_hero(self, bot: Bot, from_telegram_id: int, target_tg: TgUser) -> tuple[bool, str]:
        if int(target_tg.id) == int(from_telegram_id):
            return False, "O'zingizga geroy sovg'a qila olmaysiz."
        async with self.session_factory() as session:
            sender, hero = await self._hero_owner_row(session, from_telegram_id)
            if sender is None or hero is None:
                return False, "❌ Sizda sovg'a qiladigan aktiv geroy yo'q."
            if hero.is_for_sale:
                return False, "Sotuvdagi geroyni sovg'a qilib bo'lmaydi. Avval sotuvdan qaytaring."
            receiver = (
                await session.execute(select(User).where(User.telegram_id == target_tg.id))
            ).scalar_one_or_none()
            if receiver is None:
                receiver = User(
                    telegram_id=target_tg.id,
                    username=target_tg.username,
                    display_name=(target_tg.full_name or "User")[:255],
                    language="uz",
                )
                session.add(receiver)
                await session.flush()
            else:
                receiver.username = target_tg.username
                receiver.display_name = (target_tg.full_name or receiver.display_name or "User")[:255]
            receiver_has_active = (
                await session.execute(select(Hero.id).where(Hero.owner_user_id == receiver.id, Hero.is_active.is_(True)).limit(1))
            ).scalar_one_or_none()
            old_owner_id = sender.id
            hero_name = safe_hero_name(hero.name)
            hero.owner_user_id = receiver.id
            hero.is_active = receiver_has_active is None
            hero.is_for_sale = False
            hero.sale_price_diamonds = None
            hero.sale_channel_message_id = None
            next_sender_hero = (
                await session.execute(
                    select(Hero)
                    .where(Hero.owner_user_id == old_owner_id, Hero.id != hero.id)
                    .order_by(Hero.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if next_sender_hero is not None:
                next_sender_hero.is_active = True
            await session.commit()

        receiver_link = self._tg_mention(target_tg.id, target_tg.full_name or str(target_tg.id))
        sender_link = self._tg_mention(from_telegram_id, sender.display_name if sender else str(from_telegram_id))
        try:
            await bot.send_message(
                target_tg.id,
                "🎁 <b>Sizga geroy sovg'a qilindi!</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"🥷 Geroy: <b>{hero_name}</b>\n"
                f"👤 Yuboruvchi: {sender_link}\n"
                "━━━━━━━━━━━━━━━\n"
                "Aktiv geroyni tanlash uchun botda 🥷 Mening geroylarim bo'limidan foydalaning.",
            )
            dm = "✅ Userga xabar yuborildi."
        except (TelegramBadRequest, TelegramForbiddenError):
            dm = "⚠️ Userga private xabar yuborilmadi."
        return True, f"🎁 <b>{hero_name}</b> geroyi {receiver_link}ga sovg'a qilindi.\n{dm}"


    async def buy_hero(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                return False, "Avval /start bosing."
            has_active = (
                await session.execute(select(Hero.id).where(Hero.owner_user_id == user.id, Hero.is_active.is_(True)).limit(1))
            ).scalar_one_or_none()
            if int(user.diamonds or 0) < HERO_BUY_PRICE_DIAMONDS:
                return False, f"❌ Almaz yetarli emas. Kerak: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {HERO_BUY_PRICE_DIAMONDS}, Sizda: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {user.diamonds or 0}"
            user.diamonds -= HERO_BUY_PRICE_DIAMONDS
            self._record_diamond_transaction(
                session,
                user,
                -HERO_BUY_PRICE_DIAMONDS,
                "hero_buy",
                note="Geroy sotib olish",
            )
            hero = Hero(
                owner_user_id=user.id,
                name=HERO_DEFAULT_NAME,
                points=0,
                level=1,
                current_defense=0,
                max_defense=HERO_FULL_DEFENSE_PERCENT,
                charge=HERO_DEFAULT_CHARGE,
                max_charge=HERO_MAX_CHARGE,
                is_active=has_active is None,
            )
            session.add(hero)
            await session.commit()
        return True, "✅ Tabriklaymiz! Siz 🥷 Geroy sotib oldingiz."


    async def hero_add_points(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Sizda hali geroy yo'q. Do'kondan <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> 100 almazga sotib olishingiz mumkin."
            if int(user.diamonds or 0) < HERO_ADD_POINTS_PRICE_DIAMONDS:
                return False, f"❌ Almaz yetarli emas. Kerak: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {HERO_ADD_POINTS_PRICE_DIAMONDS}, Sizda: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {user.diamonds or 0}"
            old_level = int(hero.level or 1)
            user.diamonds -= HERO_ADD_POINTS_PRICE_DIAMONDS
            self._record_diamond_transaction(
                session,
                user,
                -HERO_ADD_POINTS_PRICE_DIAMONDS,
                "hero_add_points",
                note=f"Geroyga +{HERO_ADD_POINTS_AMOUNT} ball qo'shish",
            )
            hero.points = int(hero.points or 0) + HERO_ADD_POINTS_AMOUNT
            self._sync_hero_level(hero)
            await session.commit()
            level_line = f"\n⭐️ Daraja oshdi: {old_level} → {hero.level}" if hero.level != old_level else ""
            return True, f"✅ +{HERO_ADD_POINTS_AMOUNT} ball qo'shildi. Jami: {hero.points} ball.{level_line}"


    async def hero_upgrade_defense(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            self._sync_hero_level(hero)
            if int(hero.current_defense or 0) >= HERO_FULL_DEFENSE_PERCENT:
                return False, "Himoya maksimal."
            if int(user.dollar or 0) < HERO_UPGRADE_DEFENSE_PRICE_DOLLAR:
                return False, f"❌ Mablag' yetarli emas. Kerak: 💶 {HERO_UPGRADE_DEFENSE_PRICE_DOLLAR}, Sizda: 💶 {user.dollar or 0}"
            user.dollar -= HERO_UPGRADE_DEFENSE_PRICE_DOLLAR
            hero.max_defense = HERO_FULL_DEFENSE_PERCENT
            hero.current_defense = HERO_FULL_DEFENSE_PERCENT
            await session.commit()
            return True, f"🛡 Himoya to'liq yangilandi: 🖤 {hero.current_defense}/{HERO_FULL_DEFENSE_PERCENT}%"


    async def hero_recharge(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            if int(hero.charge or 0) >= HERO_MAX_CHARGE:
                return False, "Qurol zaryadi to'liq."
            if int(user.dollar or 0) < HERO_RECHARGE_PRICE_DOLLAR:
                return False, f"❌ Mablag' yetarli emas. Kerak: 💶 {HERO_RECHARGE_PRICE_DOLLAR}, Sizda: 💶 {user.dollar or 0}"
            user.dollar -= HERO_RECHARGE_PRICE_DOLLAR
            hero.charge = HERO_MAX_CHARGE
            hero.max_charge = HERO_MAX_CHARGE
            await session.commit()
            return True, "🩸 Qurol zaryadi to'liq 10 ga qaytarildi."


    async def hero_rename(self, telegram_id: int, raw_name: str) -> tuple[bool, str]:
        ok, name_or_error = sanitize_hero_name(raw_name)
        if not ok:
            return False, name_or_error
        async with self.session_factory() as session:
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            if int(user.dollar or 0) < HERO_RENAME_PRICE_DOLLAR:
                return False, f"❌ Mablag' yetarli emas. Kerak: 💶 {HERO_RENAME_PRICE_DOLLAR}, Sizda: 💶 {user.dollar or 0}"
            hero.name = name_or_error
            user.dollar -= HERO_RENAME_PRICE_DOLLAR
            await session.commit()
        return True, f"✅ Geroy nomi yangilandi: {safe_hero_name(name_or_error)}"


    async def _hero_owner_row(self, session: AsyncSession, telegram_id: int) -> tuple[Optional[User], Optional[Hero]]:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        if user is None:
            return None, None
        heroes = (
            await session.execute(
                select(Hero)
                .where(Hero.owner_user_id == user.id)
                .order_by(Hero.is_active.desc(), Hero.id.desc())
            )
        ).scalars().all()
        hero = heroes[0] if heroes else None
        if hero is not None and not hero.is_active:
            await self._set_active_hero(session, user.id, hero)
        return user, hero


    async def get_hero_market_channel_id(self) -> Optional[str]:
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == HERO_MARKET_CHANNEL_KEY))
            ).scalar_one_or_none()
            value = (setting.value if setting else "").strip()
            return value or None


    async def set_hero_market_channel(self, bot: Bot, raw_channel: str) -> tuple[bool, str]:
        channel = (raw_channel or "").strip()
        if not channel:
            return False, "Kanal ID yoki @username yuboring."
        if not (channel.startswith("@") or channel.startswith("-100") or channel.lstrip("-").isdigit()):
            return False, "Kanal @username yoki kanal ID bo'lishi kerak."
        try:
            chat = await bot.get_chat(channel)
            me = await bot.get_me()
            member = await bot.get_chat_member(chat.id, me.id)
        except Exception as exc:
            return False, f"❌ Kanal topilmadi yoki bot kira olmaydi: {exc}"
        if member.status not in {"administrator", "creator"}:
            return False, "❌ Bot o'sha kanalda admin bo'lishi kerak."
        value = str(chat.id)
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == HERO_MARKET_CHANNEL_KEY))
            ).scalar_one_or_none()
            if setting is None:
                session.add(BotSetting(key=HERO_MARKET_CHANNEL_KEY, value=value))
            else:
                setting.value = value
            await session.commit()
        return True, f"✅ Geroy savdo kanali ulandi: <code>{value}</code>"


    async def clear_hero_market_channel(self) -> str:
        async with self.session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == HERO_MARKET_CHANNEL_KEY))
            ).scalar_one_or_none()
            if setting is None:
                session.add(BotSetting(key=HERO_MARKET_CHANNEL_KEY, value=""))
            else:
                setting.value = ""
            await session.commit()
        return "✅ Geroy savdo kanali o'chirildi."


    def _hero_market_text(self, hero: Hero) -> str:
        info = hero_level_for_points(int(hero.points or 0))
        return (
            "🥷 <b>GEROY SOTUVDA!</b>\n\n"
            f"🥷 Geroy: {safe_hero_name(hero.name)}\n"
            f"⭐️ Daraja: {info.level}\n"
            f"👊 Kuch: {info.power_text}\n"
            f"🖤 Himoya: {int(hero.current_defense or 0)}%\n"
            f"♥️ Max himoya: {HERO_FULL_DEFENSE_PERCENT}%\n"
            f"🩸 Zaryad miqdori: {int(hero.charge or 0)}\n"
            f"☑️ Jami ballari: {int(hero.points or 0)} ball\n\n"
            f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> Narxi: {int(hero.sale_price_diamonds or 0)} almaz"
        )


    async def hero_put_for_sale(self, bot: Bot, telegram_id: int, price: int) -> tuple[bool, str]:
        if price < 1 or price > 1_000_000:
            return False, "Narx 1 dan 1 000 000 almazgacha bo'lishi kerak."
        channel_id = await self.get_hero_market_channel_id()
        if not channel_id:
            return False, "❌ Geroy savdo kanali hali admin tomonidan ulanmagan."
        async with self.session_factory() as session:
            _, hero = await self._hero_owner_row(session, telegram_id)
            if hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            hero.is_for_sale = True
            hero.sale_price_diamonds = price
            self._sync_hero_level(hero)
            await session.commit()
            hero_id = hero.id
            text = self._hero_market_text(hero)
        try:
            sent = await bot.send_message(channel_id, text, reply_markup=hero_market_buy_keyboard(hero_id))
        except Exception as exc:
            async with self.session_factory() as session:
                hero = (await session.execute(select(Hero).where(Hero.id == hero_id))).scalar_one_or_none()
                if hero:
                    hero.is_for_sale = False
                    hero.sale_price_diamonds = None
                    await session.commit()
            return False, f"❌ Kanalga post yuborilmadi: {exc}"
        async with self.session_factory() as session:
            hero = (await session.execute(select(Hero).where(Hero.id == hero_id))).scalar_one_or_none()
            if hero:
                hero.sale_channel_message_id = sent.message_id
                await session.commit()
        return True, f"✅ Geroyingiz sotuvga qo'yildi. Narx: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {price}"


    async def hero_cancel_sale(self, bot: Bot, telegram_id: int) -> tuple[bool, str]:
        channel_id = await self.get_hero_market_channel_id()
        async with self.session_factory() as session:
            user, hero = await self._hero_owner_row(session, telegram_id)
            if user is None or hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            if not hero.is_for_sale:
                return False, "Geroy sotuvda emas."
            if int(user.diamonds or 0) < HERO_CANCEL_SALE_PRICE_DIAMONDS:
                return False, "❌ Sotuvdan qaytarish uchun <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> 1 almaz kerak."
            user.diamonds -= HERO_CANCEL_SALE_PRICE_DIAMONDS
            self._record_diamond_transaction(
                session,
                user,
                -HERO_CANCEL_SALE_PRICE_DIAMONDS,
                "hero_sale_cancel",
                note="Geroyni sotuvdan qaytarish",
            )
            message_id = hero.sale_channel_message_id
            hero.is_for_sale = False
            hero.sale_price_diamonds = None
            hero.sale_channel_message_id = None
            await session.commit()
        if channel_id and message_id:
            try:
                await bot.edit_message_text("❌ Geroy sotuvdan olindi.", chat_id=channel_id, message_id=message_id)
            except Exception:
                pass
        return True, "✅ Geroy sotuvdan qaytarildi. Xizmat narxi: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> 1 almaz."


    async def hero_update_sale_price(self, bot: Bot, telegram_id: int, price: int) -> tuple[bool, str]:
        if price < 1 or price > 1_000_000:
            return False, "Narx 1 dan 1 000 000 almazgacha bo'lishi kerak."
        channel_id = await self.get_hero_market_channel_id()
        async with self.session_factory() as session:
            _, hero = await self._hero_owner_row(session, telegram_id)
            if hero is None:
                return False, "❌ Sizda hali geroy yo'q."
            if not hero.is_for_sale:
                return False, "Geroy sotuvda emas."
            hero.sale_price_diamonds = price
            message_id = hero.sale_channel_message_id
            text = self._hero_market_text(hero)
            hero_id = hero.id
            await session.commit()
        if channel_id and message_id:
            try:
                await bot.edit_message_text(text, chat_id=channel_id, message_id=message_id, reply_markup=hero_market_buy_keyboard(hero_id))
            except Exception:
                pass
        return True, f"✅ Geroy narxi yangilandi: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {price}"


    async def hero_market_buy(self, bot: Bot, buyer_telegram_id: int, hero_id: int) -> tuple[bool, str]:
        channel_id = await self.get_hero_market_channel_id()
        seller_telegram_id: Optional[int] = None
        buyer_text = "✅ Siz geroyni sotib oldingiz."
        seller_text = ""
        message_id: Optional[int] = None
        async with self.session_factory() as session:
            buyer = (await session.execute(select(User).where(User.telegram_id == buyer_telegram_id))).scalar_one_or_none()
            if buyer is None:
                return False, "Avval /start bosing."
            hero = (
                await session.execute(select(Hero).where(Hero.id == hero_id).with_for_update())
            ).scalar_one_or_none()
            if hero is None or not hero.is_for_sale or not hero.sale_price_diamonds:
                return False, "Geroy sotuvda emas yoki allaqachon sotilgan."
            seller = (await session.execute(select(User).where(User.id == hero.owner_user_id))).scalar_one_or_none()
            if seller is None:
                return False, "Sotuvchi topilmadi."
            if seller.telegram_id == buyer_telegram_id:
                return False, "O'z geroyingizni sotib ololmaysiz."
            price = int(hero.sale_price_diamonds or 0)
            if int(buyer.diamonds or 0) < price:
                return False, f"❌ Almaz yetarli emas. Kerak: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {price}, Sizda: <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {buyer.diamonds or 0}"
            buyer.diamonds -= price
            seller.diamonds += price
            self._record_diamond_transaction(
                session,
                buyer,
                -price,
                "hero_market_buy",
                note=f"Geroy #{hero.id} sotib olindi",
                counterparty=seller,
            )
            self._record_diamond_transaction(
                session,
                seller,
                price,
                "hero_market_sale",
                note=f"Geroy #{hero.id} sotildi",
                counterparty=buyer,
            )
            seller_telegram_id = seller.telegram_id
            seller_text = f"✅ Geroyingiz sotildi. Hisobingizga <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {price} almaz qo'shildi."
            message_id = hero.sale_channel_message_id
            seller_owner_id = seller.id
            was_seller_active = bool(hero.is_active)
            buyer_has_active = (
                await session.execute(select(Hero.id).where(Hero.owner_user_id == buyer.id, Hero.is_active.is_(True)).limit(1))
            ).scalar_one_or_none()
            hero.owner_user_id = buyer.id
            hero.is_active = buyer_has_active is None
            hero.is_for_sale = False
            hero.sale_price_diamonds = None
            hero.sale_channel_message_id = None
            if was_seller_active:
                next_seller_hero = (
                    await session.execute(
                        select(Hero)
                        .where(Hero.owner_user_id == seller_owner_id, Hero.id != hero.id)
                        .order_by(Hero.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if next_seller_hero is not None:
                    next_seller_hero.is_active = True
            await session.commit()
        if channel_id and message_id:
            try:
                await bot.edit_message_text("✅ <b>SOTILDI</b>", chat_id=channel_id, message_id=message_id)
            except Exception:
                pass
        if seller_telegram_id:
            try:
                await bot.send_message(seller_telegram_id, seller_text)
            except Exception:
                pass
        return True, buyer_text


    async def _hero_game_context(
        self,
        session: AsyncSession,
        telegram_id: int,
        *,
        require_charge: bool = False,
    ) -> tuple[bool, str, Optional[Game], Optional[GamePlayer], Optional[User], Optional[Hero]]:
        row = (
            await session.execute(
                select(Game, GamePlayer, User, Hero)
                .join(GamePlayer, GamePlayer.game_id == Game.id)
                .join(User, User.telegram_id == GamePlayer.telegram_id)
                .join(Hero, Hero.owner_user_id == User.id)
                .where(
                    Game.status == GameStatus.ACTIVE.value,
                    GamePlayer.telegram_id == telegram_id,
                    Hero.is_active.is_(True),
                )
                .order_by(Game.id.desc())
            )
        ).first()
        if row is None:
            return False, "❌ Siz hozir aktiv o'yinda emassiz.", None, None, None, None
        game, player, user, hero = row
        if game.phase != GamePhase.DAY_DISCUSSION.value:
            if game.phase in {GamePhase.DAY_VOTING.value, GamePhase.DAY_CONFIRM.value}:
                return False, "❌ Geroydan foydalanish vaqti tugagan. Ovoz berish boshlandi.", game, player, user, hero
            return False, "❌ Geroy faqat tong otgandan keyin, ovoz berish boshlanguncha ishlaydi.", game, player, user, hero
        if not player.alive:
            return False, "❌ Siz tirik emassiz.", game, player, user, hero
        if hero.is_for_sale:
            return False, "❌ Sotuvdagi geroy locked. Sotuvdan qaytarmaguncha o'yinda ishlata olmaysiz.", game, player, user, hero
        if require_charge and int(hero.charge or 0) <= 0:
            return False, "❌ Geroy quroli zaryadsiz. Do'kondan zaryadlang.", game, player, user, hero
        self._sync_hero_level(hero)
        return True, "", game, player, user, hero


    async def hero_game_panel_text(self, telegram_id: int) -> tuple[bool, str, bool]:
        async with self.session_factory() as session:
            ok, text, _, player, _, hero = await self._hero_game_context(session, telegram_id)
            if not ok:
                return False, text, False
            can_attack = Role(player.role) in HERO_ATTACK_ROLES
            return True, (
                "🥷 Siz geroyingizdan foydalanishingiz mumkin.\n"
                "Ovoz berish boshlanguncha vaqtingiz bor.\n\n"
                f"🎭 Rol: {role_label(player.role)}\n"
                f"🩸 Zaryad: {int(hero.charge or 0)}/{HERO_MAX_CHARGE}\n"
                f"🖤 Himoya: {int(hero.current_defense or 0)}/{HERO_FULL_DEFENSE_PERCENT}%"
            ), can_attack


    async def hero_game_targets(self, telegram_id: int) -> tuple[bool, str, list[GamePlayer]]:
        async with self.session_factory() as session:
            ok, text, game, player, _, _ = await self._hero_game_context(session, telegram_id, require_charge=True)
            if not ok or game is None or player is None:
                return False, text, []
            if Role(player.role) not in HERO_ATTACK_ROLES:
                return False, "❌ Bu rol geroy bilan zarba bera olmaydi. Faqat himoyalanish mumkin.", []
            targets = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game.id,
                        GamePlayer.alive.is_(True),
                        GamePlayer.telegram_id != player.telegram_id,
                    ).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            return True, "<tg-emoji emoji-id=\"5408935401442267103\">⚔️</tg-emoji> Kimga zarba berasiz?", targets


    async def hero_game_hp_text(self, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            ok, text, game, _, _, _ = await self._hero_game_context(session, telegram_id)
            if not ok or game is None:
                return False, text
            players = (
                await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game.id).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            lines = ["📊 <b>O'yinchilar joni:</b>"]
            for idx, player in enumerate(players, 1):
                mark = " ☠️" if not player.alive or int(player.hero_hp or 0) <= 0 else ""
                lines.append(
                    f"{idx}. {self._tg_mention(player.telegram_id, player.display_name)} — "
                    f"♥️ {int(player.hero_hp or 0)}/{int(player.hero_max_hp or HERO_DEFAULT_HP)}{mark}"
                )
            return True, "\n".join(lines)


    async def hero_game_defend(self, telegram_id: int, amount_raw: str = "max") -> tuple[bool, str]:
        async with self.session_factory() as session:
            ok, text, _, player, _, hero = await self._hero_game_context(session, telegram_id)
            if not ok or player is None or hero is None:
                return False, text
            current = int(hero.current_defense or 0)
            if current <= 0:
                return False, "Himoya mavjud emas. Do'kondan himoyani yangilang."
            amount = current
            player.hero_defense_active = True
            player.hero_defense_amount = amount
            await session.commit()
            return True, f"🛡 Himoya avtomatik to'liq yoqildi: 🖤 {amount}/{HERO_FULL_DEFENSE_PERCENT}%"


    async def hero_damage_prompt(self, telegram_id: int, target_player_id: int) -> tuple[bool, str, bool]:
        async with self.session_factory() as session:
            ok, text, game, player, _, hero = await self._hero_game_context(session, telegram_id, require_charge=True)
            if not ok or game is None or player is None or hero is None:
                return False, text, False
            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.id == target_player_id,
                        GamePlayer.game_id == game.id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return False, "Target topilmadi yoki tirik emas.", False
            if target.telegram_id == player.telegram_id:
                return False, "O'zingizni ura olmaysiz.", False
            if Role(player.role) not in HERO_ATTACK_ROLES:
                return False, "❌ Bu rol geroy bilan zarba bera olmaydi. Faqat himoyalanish mumkin.", False
            info = hero_level_for_points(int(hero.points or 0))
            if info.max_hit:
                return True, "<tg-emoji emoji-id=\"5408935401442267103\">⚔️</tg-emoji> Maksimal zarba beriladi.", True
            return True, f"<tg-emoji emoji-id=\"5408935401442267103\">⚔️</tg-emoji> Geroyingiz {info.power_text} oralig'ida random zarba beradi.", False


    async def hero_game_attack(
        self,
        bot: Bot,
        attacker_telegram_id: int,
        target_player_id: int,
        damage_raw: str,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            ok, text, game, attacker, _, hero = await self._hero_game_context(
                session,
                attacker_telegram_id,
                require_charge=True,
            )
            if not ok or game is None or attacker is None or hero is None:
                return False, text
            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.id == target_player_id,
                        GamePlayer.game_id == game.id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return False, "Target topilmadi yoki tirik emas."
            if target.telegram_id == attacker.telegram_id:
                return False, "O'zingizni ura olmaysiz."
            if Role(attacker.role) not in HERO_ATTACK_ROLES:
                return False, "❌ Bu rol geroy bilan zarba bera olmaydi. Faqat himoyalanish mumkin."

            info = hero_level_for_points(int(hero.points or 0))
            target_hp = int(target.hero_hp or HERO_DEFAULT_HP)
            target_defense = int(target.hero_defense_amount or 0) if target.hero_defense_active else 0
            target_hero = None
            if target_defense > 0:
                target_hero = (
                    await session.execute(
                        select(Hero)
                        .join(User, User.id == Hero.owner_user_id)
                        .where(User.telegram_id == target.telegram_id, Hero.is_active.is_(True))
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if info.max_hit:
                entered_damage = max(1, target_hp + target_defense)
            else:
                min_power = int(HERO_LEVELS[int(hero.level)]["power_min"])  # type: ignore[index]
                max_power = int(HERO_LEVELS[int(hero.level)]["power_max"])  # type: ignore[index]
                entered_damage = random.randint(min_power, max_power)

            hero.charge = max(0, int(hero.charge or 0) - 1)
            remaining_damage = entered_damage
            if target.hero_defense_active and int(target.hero_defense_amount or 0) > 0:
                absorbed = min(int(target.hero_defense_amount or 0), remaining_damage)
                target.hero_defense_amount = int(target.hero_defense_amount or 0) - absorbed
                if target_hero is not None:
                    target_hero.current_defense = max(0, int(target_hero.current_defense or 0) - absorbed)
                remaining_damage -= absorbed
                if int(target.hero_defense_amount or 0) <= 0:
                    target.hero_defense_active = False
                    target.hero_defense_amount = 0
            if remaining_damage > 0:
                target.hero_hp = max(0, int(target.hero_hp or HERO_DEFAULT_HP) - remaining_damage)

            killed = target.hero_hp <= 0
            kill_text = ""
            succession_events: list[tuple[str, int, Role]] = []
            couple_hero_lines: list[str] = []
            if killed:
                target.alive = False
                target.killed_by_hero = True
                target.death_day = game.day_number
                if Role(target.role) == Role.SORCERER:
                    target.sorcerer_revenge_used = True
                    target.won = True
                all_players = (
                    await session.execute(
                        select(GamePlayer).where(GamePlayer.game_id == game.id).order_by(GamePlayer.id.asc())
                    )
                ).scalars().all()
                hero_dead_ids = {target.telegram_id}
                couple_hero_lines = await self._expand_tournament_couple_deaths(
                    session,
                    game,
                    all_players,
                    hero_dead_ids,
                )
                for player in all_players:
                    if player.telegram_id in hero_dead_ids and player.alive:
                        player.alive = False
                        player.death_day = game.day_number
                succession_events = self._apply_role_successions(all_players, hero_dead_ids)
                target_name = self._tg_mention(target.telegram_id, target.display_name)
                kill_text = (
                    f"⚰️ {role_label(target.role)} {target_name}ni {role_label(attacker.role)} "
                    "o'zining jasur geroyi bilan yer tishlatdi!"
                )
                self._add_game_log(
                    session,
                    game,
                    "hero_kill",
                    actor_role=attacker.role,
                    target=target,
                    damage=entered_damage,
                )
                self._add_activity_points(session, game, attacker, 30, "hero_kill")
            else:
                self._add_game_log(
                    session,
                    game,
                    "hero_attack",
                    actor_role=attacker.role,
                    target=target,
                    damage=entered_damage,
                    hp=target.hero_hp,
                )
            await session.commit()
            chat_id = game.chat_id
            target_id = target.telegram_id
            target_hp_after = int(target.hero_hp or 0)
            target_max_hp = int(target.hero_max_hp or HERO_DEFAULT_HP)
            game_id = game.id

        if killed:
            await bot.send_message(chat_id, kill_text)
            for line in couple_hero_lines:
                await self._safe_send_message(bot, chat_id, line)
            for line, heir_id, new_role in succession_events:
                await bot.send_message(chat_id, line)
                try:
                    await bot.send_message(
                        heir_id,
                        self._private_role_text(new_role),
                        reply_markup=await self.group_return_keyboard(bot, chat_id),
                    )
                except TelegramForbiddenError:
                    pass
            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
            return True, "<tg-emoji emoji-id=\"5408935401442267103\">⚔️</tg-emoji> Zarba berildi. Target o'yindan chetlatildi."
        try:
            await bot.send_message(
                target_id,
                f"💥 Sizga noma'lum geroy tomonidan zarba berildi. Qolgan jon: ♥️ {target_hp_after}/{target_max_hp}",
                reply_markup=await self.group_return_keyboard(bot, chat_id),
            )
        except TelegramForbiddenError:
            pass
        return True, f"<tg-emoji emoji-id=\"5408935401442267103\">⚔️</tg-emoji> Zarba berildi. Target joni: ♥️ {target_hp_after}/{target_max_hp}"


    async def send_hero_phase_prompts(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Game, GamePlayer, User, Hero)
                    .join(GamePlayer, GamePlayer.game_id == Game.id)
                    .join(User, User.telegram_id == GamePlayer.telegram_id)
                    .join(Hero, Hero.owner_user_id == User.id)
                    .where(
                        Game.id == game_id,
                        Game.status == GameStatus.ACTIVE.value,
                        Game.phase == GamePhase.DAY_DISCUSSION.value,
                        GamePlayer.alive.is_(True),
                        Hero.is_active.is_(True),
                        Hero.is_for_sale.is_(False),
                    )
                )
            ).all()
            chat_id = rows[0][0].chat_id if rows else None
        if not rows:
            return
        sent_any = False
        for _, player, _, _ in rows:
            try:
                await bot.send_message(
                    player.telegram_id,
                    "🥷 Siz geroyingizdan foydalanishingiz mumkin. Ovoz berish boshlanguncha vaqtingiz bor.",
                    reply_markup=hero_game_keyboard(can_attack=Role(player.role) in HERO_ATTACK_ROLES),
                )
                sent_any = True
            except TelegramForbiddenError:
                pass
        if chat_id and sent_any:
            await bot.send_message(chat_id, "🥷 Geroy egalari bot shaxsiy xabaridan foydalanishi mumkin.")


