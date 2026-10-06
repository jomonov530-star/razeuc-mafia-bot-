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

class RegistrationMixin:
    async def find_active_game(self, session: AsyncSession, chat_id: int) -> Optional[Game]:
        stmt = select(Game).where(
            Game.chat_id == chat_id,
            Game.status.in_([GameStatus.REGISTRATION.value, GameStatus.ACTIVE.value]),
        ).order_by(Game.id.desc())
        return (await session.execute(stmt)).scalars().first()


    @staticmethod
    def _tournament_game_key(game_id: int) -> str:
        return f"{TOURNAMENT_GAME_PREFIX}{game_id}"


    @staticmethod
    def _team_game_key(game_id: int) -> str:
        return f"{TEAM_GAME_PREFIX}{game_id}"


    async def _is_tournament_game_in_session(self, session: AsyncSession, game_id: int) -> bool:
        value = (
            await session.execute(
                select(BotSetting.value).where(BotSetting.key == self._tournament_game_key(game_id))
            )
        ).scalar_one_or_none()
        return value == "1"


    async def _is_team_game_in_session(self, session: AsyncSession, game_id: int) -> bool:
        value = (
            await session.execute(
                select(BotSetting.value).where(BotSetting.key == self._team_game_key(game_id))
            )
        ).scalar_one_or_none()
        return value == "1"


    async def _set_tournament_game_in_session(self, session: AsyncSession, game_id: int) -> None:
        key = self._tournament_game_key(game_id)
        row = (
            await session.execute(select(BotSetting).where(BotSetting.key == key))
        ).scalar_one_or_none()
        if row is None:
            session.add(BotSetting(key=key, value="1"))
        else:
            row.value = "1"


    async def _set_team_game_in_session(self, session: AsyncSession, game_id: int) -> None:
        key = self._team_game_key(game_id)
        row = (
            await session.execute(select(BotSetting).where(BotSetting.key == key))
        ).scalar_one_or_none()
        if row is None:
            session.add(BotSetting(key=key, value="1"))
        else:
            row.value = "1"


    async def _clear_tournament_game_in_session(self, session: AsyncSession, game_id: int) -> None:
        row = (
            await session.execute(select(BotSetting).where(BotSetting.key == self._tournament_game_key(game_id)))
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
        await session.execute(
            update(GamePlayer)
            .where(GamePlayer.game_id == game_id)
            .values(transformed_to_team=None)
        )


    async def _clear_team_game_in_session(self, session: AsyncSession, game_id: int) -> None:
        row = (
            await session.execute(select(BotSetting).where(BotSetting.key == self._team_game_key(game_id)))
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
        await session.execute(
            update(GamePlayer)
            .where(GamePlayer.game_id == game_id)
            .values(transformed_to_team=None)
        )


    async def _expand_tournament_couple_deaths(
        self,
        session: AsyncSession,
        game: Game,
        players: list[GamePlayer],
        dead_ids: set[int],
        *,
        death_causes: Optional[dict[int, str]] = None,
        death_visitors: Optional[dict[int, str]] = None,
    ) -> list[str]:
        """In /turnir (couple tournament), if one partner dies or loses,

        their surviving partner must immediately exit / be eliminated as well.
        Returns notification lines describing the tragedy.
        """
        is_tournament = await self._is_tournament_game_in_session(session, game.id)
        if not is_tournament or not dead_ids:
            return []

        couples = (
            await session.execute(
                select(CoupleRelationship).where(
                    CoupleRelationship.chat_id == game.chat_id,
                    CoupleRelationship.active.is_(True),
                )
            )
        ).scalars().all()

        if not couples:
            return []

        player_map = {p.telegram_id: p for p in players}
        lines: list[str] = []

        current_dead_ids = list(dead_ids)
        for dead_id in current_dead_ids:
            couple = next(
                (
                    c for c in couples
                    if dead_id in (c.user_one_telegram_id, c.user_two_telegram_id)
                ),
                None,
            )
            if couple is None:
                continue

            partner_id = (
                couple.user_two_telegram_id
                if couple.user_one_telegram_id == dead_id
                else couple.user_one_telegram_id
            )

            if partner_id in player_map and partner_id not in dead_ids:
                partner_player = player_map[partner_id]
                dead_player = player_map.get(dead_id)

                if partner_player.alive:
                    dead_ids.add(partner_id)
                    partner_player.alive = False
                    partner_player.death_day = max(1, int(game.day_number or 1))

                    dead_name_raw = dead_player.display_name if dead_player else "sevgilisi"
                    if death_causes is not None:
                        death_causes[partner_id] = "couple"
                    if death_visitors is not None:
                        death_visitors[partner_id] = dead_name_raw

                    dead_name = self._tg_mention(dead_id, dead_name_raw)
                    partner_name = self._tg_mention(partner_id, partner_player.display_name)
                    r_label = role_label(partner_player.role) if partner_player.role else "O'yinchi"

                    line = (
                        f"💔 <b>Turnir fojiasi!</b> {dead_name} o'yinda halok bo'lgach (yutqazgach), "
                        f"uning vafodor parasi {partner_name} sevgilisiz bu dunyoda qola olmasligini aytib, "
                        f"o'yinni o'sha zahoti yakunladi!\n"
                        f"U edi <b>{r_label}</b>."
                    )
                    lines.append(line)

        return lines



    async def create_game_registration(
        self,
        bot: Bot,
        chat_id: int,
        chat_title: str,
        creator_id: int,
        *,
        tournament: bool = False,
        teamgame: bool = False,
        regular: bool = False,
        role_preset: Optional[str] = None,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            active = await self.find_active_game(session, chat_id)
            lang = await self.get_group_language(chat_id)
            if active is not None:
                if active.status == GameStatus.REGISTRATION.value:
                    current_end = self._ensure_utc(active.registration_ends_at) if active.registration_ends_at else self._now_utc()
                    if current_end < self._now_utc():
                        current_end = self._now_utc()
                    existing_is_tournament = await self._is_tournament_game_in_session(session, active.id)
                    existing_is_teamgame = await self._is_team_game_in_session(session, active.id)
                    if tournament and not existing_is_tournament:
                        players_count = await session.scalar(
                            select(func.count(GamePlayer.id)).where(GamePlayer.game_id == active.id)
                        )
                        if players_count:
                            return False, "Avvalgi oddiy ro'yxatda o'yinchilar bor. Turnir boshlash uchun o'yinni /stop qilib, /turnir ni qayta bering."
                    if teamgame and not existing_is_teamgame:
                        players_count = await session.scalar(
                            select(func.count(GamePlayer.id)).where(GamePlayer.game_id == active.id)
                        )
                        if players_count:
                            return False, "Avvalgi ro'yxatda o'yinchilar bor. Jamoaviy o'yin boshlash uchun o'yinni /stop qilib, /teamgame ni qayta bering."
                    if regular and existing_is_tournament:
                        await self._clear_tournament_game_in_session(session, active.id)
                        existing_is_tournament = False
                    if regular and existing_is_teamgame:
                        await self._clear_team_game_in_session(session, active.id)
                        existing_is_teamgame = False
                    active.registration_ends_at = current_end + timedelta(seconds=30)
                    active.creator_telegram_id = creator_id
                    if role_preset:
                        active.role_preset = role_preset
                    if tournament:
                        if existing_is_teamgame:
                            await self._clear_team_game_in_session(session, active.id)
                            existing_is_teamgame = False
                        await self._set_tournament_game_in_session(session, active.id)
                    if teamgame:
                        if existing_is_tournament:
                            await self._clear_tournament_game_in_session(session, active.id)
                            existing_is_tournament = False
                        await self._set_team_game_in_session(session, active.id)
                    is_tournament = tournament or existing_is_tournament
                    is_teamgame = teamgame or existing_is_teamgame
                    self._add_game_log(
                        session,
                        active,
                        "registration_extended_by_game_command",
                        seconds=30,
                        registration_ends_at=active.registration_ends_at.isoformat(),
                        tournament=is_tournament,
                        teamgame=is_teamgame,
                        role_preset=active.role_preset,
                    )
                    old_msg_id = active.lobby_message_id
                    if old_msg_id:
                        try:
                            await bot.delete_message(chat_id, old_msg_id)
                        except (TelegramBadRequest, TelegramForbiddenError):
                            pass
                    text = await self._build_lobby_text(
                        session,
                        active.id,
                        lang,
                        ended=False,
                        tournament=is_tournament,
                        teamgame=is_teamgame,
                    )
                    msg = await bot.send_message(
                        chat_id,
                        text,
                        reply_markup=lobby_keyboard(
                            lang=lang,
                            game_id=active.id,
                            bot_username=self.settings.bot_username,
                            chat_id=chat_id,
                            active=True,
                            tournament=is_tournament,
                            teamgame=is_teamgame,
                        ),
                    )
                    active.lobby_message_id = msg.message_id
                    game_id = active.id
                    await session.commit()

                    try:
                        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
                    except TelegramBadRequest:
                        pass
                    try:
                        await self.schedule_registration_jobs(bot, game_id)
                    except Exception:
                        logger.exception("Failed to reschedule registration jobs for game_id=%s", game_id)
                    return True, t(lang, "extended")
                return False, t(lang, "active_game_exists")

            group = (await session.execute(select(Group).where(Group.chat_id == chat_id))).scalar_one_or_none()
            if group is None:
                group = Group(
                    chat_id=chat_id,
                    title=chat_title,
                    language=self.settings.default_language,
                    registration_timeout=self.settings.registration_timeout,
                    night_timeout=self.settings.night_timeout,
                    day_discussion_timeout=self.settings.day_discussion_timeout,
                    day_voting_timeout=self.settings.day_voting_timeout,
                    min_players=self.settings.min_players,
                )
                session.add(group)
                await session.flush()
            else:
                group.title = chat_title

            timeout = max(30, group.registration_timeout or self.settings.registration_timeout)
            ends_at = self._now_utc() + timedelta(seconds=timeout)

            game = Game(
                chat_id=chat_id,
                creator_telegram_id=creator_id,
                status=GameStatus.REGISTRATION.value,
                phase=GamePhase.REGISTRATION.value,
                active_key=1,
                registration_ends_at=ends_at,
                role_preset=role_preset or group.role_preset or "black23",
            )
            session.add(game)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return False, t(lang, "active_game_exists")
            if tournament:
                await self._set_tournament_game_in_session(session, game.id)
            if teamgame:
                await self._set_team_game_in_session(session, game.id)

            text = await self._build_lobby_text(
                session,
                game.id,
                lang,
                ended=False,
                tournament=tournament,
                teamgame=teamgame,
            )
            msg = await bot.send_message(
                chat_id,
                text,
                reply_markup=lobby_keyboard(
                    lang=lang,
                    game_id=game.id,
                    bot_username=self.settings.bot_username,
                    chat_id=chat_id,
                    active=True,
                    tournament=tournament,
                    teamgame=teamgame,
                ),
            )
            game.lobby_message_id = msg.message_id
            self._add_game_log(
                session,
                game,
                "registration_started",
                creator_id=creator_id,
                registration_timeout=timeout,
                registration_ends_at=ends_at.isoformat(),
                tournament=tournament,
                teamgame=teamgame,
            )
            await session.commit()

        self._invalidate_group_cache(chat_id)
        self._invalidate_game_cache(chat_id)
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        except TelegramBadRequest:
            await bot.send_message(chat_id, "⚠️ Pin qilishga ruxsat yo'q, lekin o'yin davom etadi.")

        try:
            await self.schedule_registration_jobs(bot, game.id)
        except Exception:
            logger.exception("Failed to schedule registration jobs for game_id=%s", game.id)
        return True, t(await self.get_group_language(chat_id), "registration_started")


    @staticmethod
    def _tournament_team_emoji(team_key: Optional[str]) -> str:
        if team_key == "blue":
            return "🔵"
        if team_key == "red":
            return "🔴"
        return ""


    def _format_tournament_lobby_players(self, players: list[GamePlayer]) -> str:
        numbered_players = list(enumerate(players, 1))

        def team_block(team_key: str) -> str:
            emoji = self._tournament_team_emoji(team_key)
            lines = [
                f"{idx}. {emoji} {self._tg_mention(player.telegram_id, player.display_name)}"
                for idx, player in numbered_players
                if player.transformed_to_team == team_key
            ]
            if not lines:
                lines = ["-"]
            return f"{emoji} -jamoa\n" + "\n".join(lines)

        return f"{team_block('blue')}\n\n{team_block('red')}"


    async def _format_couple_tournament_lobby_players(
        self,
        session: AsyncSession,
        chat_id: int,
        players: list[GamePlayer],
    ) -> str:
        if not players:
            return "-"

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
        player_ids = {player.telegram_id for player in players}
        player_by_id = {player.telegram_id: player for player in players}
        seen: set[int] = set()
        lines: list[str] = []

        for player in players:
            if player.telegram_id in seen:
                continue
            couple = next(
                (
                    item
                    for item in couples
                    if player.telegram_id in {item.user_one_telegram_id, item.user_two_telegram_id}
                ),
                None,
            )
            if couple is None:
                lines.append(f"{len(lines) + 1}. {self._tg_mention(player.telegram_id, player.display_name)} — 💔 para topilmadi")
                seen.add(player.telegram_id)
                continue

            first_id = couple.user_one_telegram_id
            second_id = couple.user_two_telegram_id
            first_name = player_by_id[first_id].display_name if first_id in player_by_id else couple.user_one_name
            second_name = player_by_id[second_id].display_name if second_id in player_by_id else couple.user_two_name
            first = self._tg_mention(first_id, first_name)
            second = self._tg_mention(second_id, second_name)
            if first_id in player_ids and second_id in player_ids:
                lines.append(f"{len(lines) + 1}. {first} + {second} ✅")
            else:
                waiting_id = second_id if first_id in player_ids else first_id
                waiting_name = second_name if waiting_id == second_id else first_name
                waiting = self._tg_mention(waiting_id, waiting_name)
                lines.append(f"{len(lines) + 1}. {first} + {second} ⏳ {waiting} kutilmoqda")
            seen.update({first_id, second_id})

        return "\n".join(lines) if lines else "-"


    async def _tournament_incomplete_couple_lines(
        self,
        session: AsyncSession,
        chat_id: int,
        players: list[GamePlayer],
    ) -> list[str]:
        if not players:
            return []

        couples = (
            await session.execute(
                select(CoupleRelationship).where(
                    CoupleRelationship.chat_id == chat_id,
                    CoupleRelationship.active.is_(True),
                )
            )
        ).scalars().all()
        couple_by_user: dict[int, CoupleRelationship] = {}
        for couple in couples:
            couple_by_user[couple.user_one_telegram_id] = couple
            couple_by_user[couple.user_two_telegram_id] = couple

        player_ids = {player.telegram_id for player in players}
        player_by_id = {player.telegram_id: player for player in players}
        missing_lines: list[str] = []
        seen_pairs: set[int] = set()
        for player in players:
            couple = couple_by_user.get(player.telegram_id)
            if couple is None:
                missing_lines.append(f"• {self._tg_mention(player.telegram_id, player.display_name)} — para topilmadi")
                continue
            if couple.id in seen_pairs:
                continue
            seen_pairs.add(couple.id)
            first_joined = couple.user_one_telegram_id in player_ids
            second_joined = couple.user_two_telegram_id in player_ids
            if first_joined and second_joined:
                continue
            missing_id = couple.user_two_telegram_id if first_joined else couple.user_one_telegram_id
            missing_name = couple.user_two_name if missing_id == couple.user_two_telegram_id else couple.user_one_name
            present_id = couple.user_one_telegram_id if first_joined else couple.user_two_telegram_id
            present_name = player_by_id[present_id].display_name if present_id in player_by_id else (
                couple.user_one_name if present_id == couple.user_one_telegram_id else couple.user_two_name
            )
            missing_lines.append(
                f"• {self._tg_mention(present_id, present_name)} sherigi "
                f"{self._tg_mention(missing_id, missing_name)} kutilmoqda"
            )
        return missing_lines


    async def _build_lobby_text(
        self,
        session: AsyncSession,
        game_id: int,
        lang: str,
        ended: bool,
        tournament: bool = False,
        teamgame: bool = False,
    ) -> str:
        players = (
            await session.execute(
                select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
            )
        ).scalars().all()
        if ended:
            title = t(lang, "lobby_ended_title")
        elif players:
            title = t(lang, "lobby_title")
        else:
            return t(lang, "lobby_started_title")

        if players and teamgame:
            names = self._format_tournament_lobby_players(players)
        elif players and tournament:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            chat_id = game.chat_id if game is not None else 0
            names = await self._format_couple_tournament_lobby_players(session, chat_id, players)
        elif players:
            names = ", ".join(
                self._tg_mention(p.telegram_id, p.display_name)
                for p in players
            )
        else:
            names = t(lang, "lobby_empty")
        tournament_note = (
            "💞 Turnirga faqat aktiv parasi borlar qo'shila oladi.\n"
            "O'yinga qo'shilganingizda sherigingiz ham avtomatik birga ro'yxatdan o'tadi.\n"
            if tournament
            else ""
        )
        return (
            f"{title}\n"
            f"{t(lang, 'lobby_registered')}\n\n"
            f"{names}\n\n"
            f"{tournament_note}"
            f"{t(lang, 'lobby_total', count=len(players))}"
        )


    async def update_lobby(self, bot: Bot, game_id: int, ended: bool = False) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.lobby_message_id is None:
                return
            lang = await self.get_group_language(game.chat_id)
            is_tournament = await self._is_tournament_game_in_session(session, game.id)
            is_teamgame = await self._is_team_game_in_session(session, game.id)
            text = await self._build_lobby_text(
                session,
                game.id,
                lang,
                ended,
                tournament=is_tournament,
                teamgame=is_teamgame,
            )
            kb = lobby_keyboard(
                lang=lang,
                game_id=game.id,
                bot_username=self.settings.bot_username,
                chat_id=game.chat_id,
                active=(not ended),
                tournament=is_tournament,
                teamgame=is_teamgame,
            )

        try:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.lobby_message_id,
                text=text,
                reply_markup=kb,
            )
        except TelegramBadRequest:
            logger.warning("Unable to update lobby message for game %s", game_id)


    async def schedule_registration_jobs(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.registration_ends_at is None:
                return
            ends_at = self._ensure_utc(game.registration_ends_at)

        now = self._now_utc()
        seconds_left = int((ends_at - now).total_seconds())
        if seconds_left <= 0:
            await self.close_registration(bot, game_id)
            return

        if seconds_left > 900:
            scheduler.add_job(
                self.send_registration_warning,
                "date",
                run_date=ends_at - timedelta(seconds=900),
                args=[bot, game_id, 900],
                id=f"reg_warn_900_{game_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )

        if seconds_left > 300:
            scheduler.add_job(
                self.send_registration_warning,
                "date",
                run_date=ends_at - timedelta(seconds=300),
                args=[bot, game_id, 300],
                id=f"reg_warn_300_{game_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )

        if seconds_left > 60:
            scheduler.add_job(
                self.send_registration_warning,
                "date",
                run_date=ends_at - timedelta(seconds=60),
                args=[bot, game_id, 60],
                id=f"reg_warn_60_{game_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )

        scheduler.add_job(
            self.close_registration,
            "date",
            run_date=ends_at,
            args=[bot, game_id],
            id=f"reg_close_{game_id}",
            replace_existing=True,
            misfire_grace_time=120,
        )


    async def send_registration_warning(self, bot: Bot, game_id: int, seconds_left: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.REGISTRATION.value:
                return
            lang = await self.get_group_language(game.chat_id)
            key = "timer_60" if seconds_left == 60 else "timer_30"
        await self.update_lobby(bot, game_id)
        await self.log(game_id, LogType.GAME_EVENT.value, f"Registration warning {seconds_left}s")
        await bot.send_message(game.chat_id, t(lang, key))


    async def join_game(
        self,
        bot: Bot,
        game_id: int,
        tg_user: TgUser,
        tournament_team: Optional[str] = None,
    ) -> tuple[bool, str]:
        if not self._has_visible_nickname(self._profile_name_from_tg(tg_user)):
            return (
                False,
                "Nikingiz ko'rinmayapti. O'yinda qatnashish uchun Telegram ismingizni ko'rinadigan qilib o'zgartiring va qayta urinib ko'ring.",
            )
        if tournament_team not in {None, "blue", "red"}:
            return False, "Komanda noto'g'ri tanlandi."
        user = await self.ensure_user(tg_user)
        locked_until = self._ensure_utc(user.play_locked_until) if user.play_locked_until else None
        now = self._now_utc()
        if locked_until and locked_until > now:
            remaining = int((locked_until - now).total_seconds())
            minutes = max(1, (remaining + 59) // 60)
            return False, f"⏳ Siz o'yindan chiqib ketgansiz. {minutes} daqiqadan keyin qayta qo'shilishingiz mumkin."
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None:
                return False, t(self.settings.default_language, "callback_expired")
            lang = await self.get_group_language(game.chat_id)
            if game.status != GameStatus.REGISTRATION.value:
                return False, t(lang, "registration_closed_cb")
            is_tournament = await self._is_tournament_game_in_session(session, game_id)
            is_teamgame = await self._is_team_game_in_session(session, game_id)
            if tournament_team is not None and not (is_tournament or is_teamgame):
                return False, "Bu oddiy ro'yxatdan o'tish. Turnir komandasi tanlanmaydi."
            if is_teamgame and tournament_team is None:
                return False, "Jamoaviy o'yinda 🔵 yoki 🔴 komandadan birini tanlang."
            partner_user = None
            partner_id = None
            partner_name = ""
            if is_tournament:
                couple = await self._active_couple_for_user(session, game.chat_id, tg_user.id)
                if couple is None:
                    return False, "💞 Turnirga faqat parasi borlar qo'shila oladi. Avval reply qilib /para orqali para olib keling."
                partner_id = couple.user_two_telegram_id if couple.user_one_telegram_id == tg_user.id else couple.user_one_telegram_id
                partner_name = couple.user_two_name if couple.user_one_telegram_id == tg_user.id else couple.user_one_name
                partner_user = (await session.execute(select(User).where(User.telegram_id == partner_id))).scalar_one_or_none()
                if partner_user is None:
                    partner_user = User(
                        telegram_id=partner_id,
                        display_name=partner_name,
                        language=self.settings.default_language,
                    )
                    session.add(partner_user)
                    await session.flush()

            preset = game.role_preset or "black23"
            max_players = role_preset_max_players(preset)
            current_count = await session.scalar(select(func.count(GamePlayer.id)).where(GamePlayer.game_id == game_id)) or 0

            needed_slots = 1
            if is_tournament and partner_id:
                partner_already = (await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.telegram_id == partner_id)
                )).scalar_one_or_none()
                if partner_already is None:
                    needed_slots = 2

            if current_count + needed_slots > max_players:
                return False, f"Bu role preset uchun limit: {max_players} o'yinchi."

            exists = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == tg_user.id,
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                if (is_tournament or is_teamgame) and tournament_team and exists.transformed_to_team != tournament_team:
                    exists.transformed_to_team = tournament_team
                    self._add_game_log(
                        session,
                        game,
                        "tournament_team_changed",
                        actor=exists,
                        tournament_team=tournament_team,
                    )
                    chat_id = game.chat_id
                    await session.commit()
                    self._invalidate_game_cache(chat_id)
                    await self.update_lobby(bot, game_id)
                    emoji = self._tournament_team_emoji(tournament_team)
                    return True, f"{emoji} Komandangiz o'zgartirildi."
                return False, t(lang, "already_joined")

            player = GamePlayer(
                game_id=game_id,
                user_id=user.id,
                telegram_id=tg_user.id,
                display_name=self.get_effective_display_name(user),
                transformed_to_team=tournament_team if (is_tournament or is_teamgame) else None,
            )
            session.add(player)

            auto_joined_partner = False
            partner_player = None
            if is_tournament and partner_id and partner_user:
                partner_player = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.telegram_id == partner_id,
                        )
                    )
                ).scalar_one_or_none()
                if partner_player is None:
                    partner_player = GamePlayer(
                        game_id=game_id,
                        user_id=partner_user.id,
                        telegram_id=partner_id,
                        display_name=self.get_effective_display_name(partner_user),
                        transformed_to_team=tournament_team if (is_tournament or is_teamgame) else None,
                    )
                    session.add(partner_player)
                    auto_joined_partner = True

            try:
                await session.flush()
                self._add_game_log(
                    session,
                    game,
                    "player_joined",
                    actor=player,
                    tournament_team=tournament_team if (is_tournament or is_teamgame) else None,
                )
                if auto_joined_partner and partner_player:
                    self._add_game_log(
                        session,
                        game,
                        "player_joined_auto_couple",
                        actor=partner_player,
                        tournament_team=tournament_team if (is_tournament or is_teamgame) else None,
                    )
                chat_id = game.chat_id
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, t(lang, "already_joined")

        self._invalidate_game_cache(chat_id)
        await self.update_lobby(bot, game_id)
        if is_tournament and partner_user:
            partner_disp = self._tg_mention(partner_id, partner_user.display_name or partner_name)
            return True, f"💞 Siz va sherigingiz ({partner_disp}) turnirga avtomatik birga qo'shildingiz!"
        if tournament_team:
            return True, f"{self._tournament_team_emoji(tournament_team)} Siz turnir komandasiga qo'shildingiz."
        return True, t(await self.get_user_language(tg_user.id), "joined")



    async def join_game_by_deeplink(
        self,
        bot: Bot,
        game_id: int,
        chat_id: int,
        tg_user: TgUser,
        tournament_team: Optional[str] = None,
    ) -> tuple[bool, str]:
        if not self._has_visible_nickname(self._profile_name_from_tg(tg_user)):
            return (
                False,
                "Nikingiz ko'rinmayapti. O'yinda qatnashish uchun Telegram ismingizni ko'rinadigan qilib o'zgartiring va qayta urinib ko'ring.",
            )
        await self.ensure_user(tg_user)
        async with self.session_factory() as session:
            game = (
                await session.execute(
                    select(Game).where(Game.id == game_id, Game.chat_id == chat_id)
                )
            ).scalar_one_or_none()
            lang = await self.get_group_language(chat_id)
            if game is None:
                return False, t(lang, "callback_expired")
            if game.status != GameStatus.REGISTRATION.value:
                return False, t(lang, "registration_closed_cb")

        return await self.join_game(
            bot=bot,
            game_id=game_id,
            tg_user=tg_user,
            tournament_team=tournament_team,
        )


    async def leave_game(self, bot: Bot, game_id: int, tg_user_id: int) -> tuple[bool, str]:
        check_winner_after = False
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None:
                return False, t(self.settings.default_language, "no_active_game")
            lang = await self.get_group_language(game.chat_id)
            chat_id = game.chat_id

            gsm = GroupSettingsManager(self.session_factory)
            gs = await gsm.get_settings(chat_id)
            if not gs.leave_allowed:
                return False, "❌ Bu guruhda /leave buyrug'i o'chirilgan."
            leave_lock_minutes = max(0, int(getattr(gs, "leave_lock_minutes", 30) or 0))

            player = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == tg_user_id,
                    )
                )
            ).scalar_one_or_none()
            if player is None:
                return False, t(lang, "not_joined")

            is_tournament = await self._is_tournament_game_in_session(session, game.id)
            couple = await self._active_couple_for_user(session, chat_id, tg_user_id) if is_tournament else None
            partner_player = None
            partner_id = None
            if couple is not None and is_tournament:
                partner_id = couple.user_two_telegram_id if couple.user_one_telegram_id == tg_user_id else couple.user_one_telegram_id
                partner_player = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.telegram_id == partner_id,
                        )
                    )
                ).scalar_one_or_none()

            if game.status == GameStatus.REGISTRATION.value:
                self._add_game_log(session, game, "player_left", actor=player)
                await session.delete(player)
                partner_left = False
                if partner_player is not None:
                    self._add_game_log(session, game, "player_left", actor=partner_player)
                    await session.delete(partner_player)
                    partner_left = True

                user = (
                    await session.execute(select(User).where(User.telegram_id == tg_user_id))
                ).scalar_one_or_none()
                if user is not None:
                    user.play_locked_until = self._now_utc() + timedelta(minutes=leave_lock_minutes) if leave_lock_minutes > 0 else None

                if partner_left:
                    partner_user = (
                        await session.execute(select(User).where(User.telegram_id == partner_id))
                    ).scalar_one_or_none()
                    if partner_user is not None:
                        partner_user.play_locked_until = self._now_utc() + timedelta(minutes=leave_lock_minutes) if leave_lock_minutes > 0 else None

                await session.commit()
                self._invalidate_game_cache(chat_id)
                await self.update_lobby(bot, game_id)
                if leave_lock_minutes > 0:
                    return True, f"🚪 Siz o'yindan chiqdingiz. Sherigingiz ham o'yindan chiqdi. {leave_lock_minutes} daqiqa davomida boshqa o'yinga qo'shila olmaysiz."
                if partner_left:
                    return True, "🚪 Siz o'yindan chiqdingiz. Sherigingiz ham o'yindan chiqdi."
                return True, "🚪 Siz o'yindan chiqdingiz."

            if game.status != GameStatus.ACTIVE.value:
                return False, t(lang, "cannot_leave_running")

            if not player.alive:
                return False, "Siz allaqachon o'yindan chetlatilgansiz."

            player.alive = False
            player.left_game = True
            player.death_day = game.day_number
            self._add_game_log(session, game, "player_left_active", actor=player)
            partner_left = False
            partner_ids = {tg_user_id}
            if is_tournament and partner_player is not None and partner_player.alive and not partner_player.left_game:
                partner_player.alive = False
                partner_player.left_game = True
                partner_player.death_day = game.day_number
                self._add_game_log(session, game, "player_left_active", actor=partner_player)
                partner_left = True
                partner_ids.add(partner_player.telegram_id)

            all_players = (
                await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            succession_events = self._apply_role_successions(all_players, partner_ids)
            succession_notices = list(succession_events)

            user = (
                await session.execute(select(User).where(User.telegram_id == tg_user_id))
            ).scalar_one_or_none()
            if user is not None:
                user.play_locked_until = self._now_utc() + timedelta(minutes=leave_lock_minutes) if leave_lock_minutes > 0 else None

            if partner_left:
                partner_user = (
                    await session.execute(select(User).where(User.telegram_id == partner_id))
                ).scalar_one_or_none()
                if partner_user is not None:
                    partner_user.play_locked_until = self._now_utc() + timedelta(minutes=leave_lock_minutes) if leave_lock_minutes > 0 else None

            await session.commit()
            check_winner_after = True

        self._invalidate_game_cache(chat_id)
        try:
            p_mention = self._tg_mention(player.telegram_id, player.display_name)
            p_role = role_label(player.role) if player.role else ""
            if partner_left and partner_player:
                partner_mention = self._tg_mention(partner_player.telegram_id, partner_player.display_name)
                part_role = role_label(partner_player.role) if partner_player.role else ""
                role_info = f"\n({p_mention} — {p_role}, {partner_mention} — {part_role})" if p_role else ""
                await bot.send_message(
                    chat_id,
                    f"🚪💔 <b>Turnir:</b> {p_mention} o'yindan chiqqani sababli, turnir qoidasiga ko'ra uning sherigi {partner_mention} ham o'yinni o'sha zahoti yakunladi!{role_info}",
                )
            else:
                role_info = f" ({p_role})" if p_role else ""
                await bot.send_message(
                    chat_id,
                    f"🚪 {p_mention}{role_info} o'yindan chiqib ketdi va o'yindan chetlatildi.",
                )
        except Exception:
            pass

        for line, heir_id, new_role in succession_notices:
            await bot.send_message(chat_id, line)
            try:
                await bot.send_message(
                    heir_id,
                    self._private_role_text(new_role),
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        if check_winner_after:
            try:
                winner = await self.check_winner(game_id)
                if winner:
                    await self.finish_game(bot, game_id, winner)
            except Exception:
                logger.exception("check_winner after leave failed")

        if leave_lock_minutes > 0:
            return True, f"🚪 Siz o'yindan chiqdingiz. {leave_lock_minutes} daqiqa davomida boshqa o'yinga qo'shila olmaysiz."
        return True, "🚪 Siz o'yindan chiqdingiz."


    async def admin_remove_player_by_number(
        self,
        bot: Bot,
        chat_id: int,
        admin_id: int,
        player_number: int,
    ) -> tuple[bool, str]:
        if player_number < 1:
            return False, "Raqam 1 dan katta bo'lishi kerak."

        async with self.session_factory() as session:
            game = await self.find_active_game(session, chat_id)
            if game is None:
                lang = await self.get_group_language(chat_id)
                return False, t(lang, "no_active_game")
            if game.status != GameStatus.ACTIVE.value:
                return False, "Bu buyruq faqat davom etayotgan o'yinda ishlaydi."

            allowed = await self.is_admin_or_creator(bot, chat_id, admin_id, game.creator_telegram_id)
            if not allowed:
                lang = await self.get_group_language(chat_id)
                return False, t(lang, "no_permission")

            alive_players = await self._alive_players(session, game.id)
            if not alive_players:
                return False, "Tirik o'yinchilar topilmadi."
            if player_number > len(alive_players):
                return False, f"Noto'g'ri raqam. Hozir {len(alive_players)} ta tirik o'yinchi bor."

            target = alive_players[player_number - 1]
            target.alive = False
            target.left_game = True
            target.death_day = game.day_number
            target.awaiting_last_words = False
            target.last_words = None

            is_tournament = await self._is_tournament_game_in_session(session, game.id)
            partner_removed = False
            partner_target = None
            removed_ids = {target.telegram_id}
            if is_tournament:
                couple = await self._active_couple_for_user(session, chat_id, target.telegram_id)
                if couple:
                    partner_id = (
                        couple.user_two_telegram_id
                        if couple.user_one_telegram_id == target.telegram_id
                        else couple.user_one_telegram_id
                    )
                    partner_target = next(
                        (p for p in alive_players if p.telegram_id == partner_id and p.alive),
                        None,
                    )
                    if partner_target:
                        partner_target.alive = False
                        partner_target.left_game = True
                        partner_target.death_day = game.day_number
                        partner_target.awaiting_last_words = False
                        partner_target.last_words = None
                        partner_removed = True
                        removed_ids.add(partner_id)

            self._add_game_log(
                session,
                game,
                "player_removed_by_admin",
                actor=target,
                admin_id=admin_id,
                player_number=player_number,
            )

            all_players = (
                await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game.id).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            succession_events = self._apply_role_successions(all_players, removed_ids)
            await session.commit()
            game_id = game.id
            target_mention = self._tg_mention(target.telegram_id, target.display_name)

        self._invalidate_game_cache(chat_id)
        if partner_removed and partner_target:
            partner_mention = self._tg_mention(partner_target.telegram_id, partner_target.display_name)
            await self._safe_send_message(
                bot,
                chat_id,
                f"⛔️💔 <b>Turnir:</b> Admin qarori bilan {target_mention} ({role_label(target.role)}) o'yindan chetlatildi.\n"
                f"Turnir qoidasiga ko'ra, uning parasi {partner_mention} ({role_label(partner_target.role)}) ham o'yinni tark etdi!",
            )
        else:
            await self._safe_send_message(
                bot,
                chat_id,
                f"⛔️ Admin qarori bilan {player_number}-raqamli o'yinchi {target_mention} o'yindan chetlatildi.\n"
                f"U edi {role_label(target.role)}.",
            )

        for line, heir_id, new_role in succession_events:
            await self._safe_send_message(bot, chat_id, line)
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
        return True, "O'yinchi chetlatildi."


    async def extend_registration(self, bot: Bot, game_id: int, seconds: int) -> tuple[bool, str]:
        if seconds >= 300:
            seconds = 300
        elif seconds >= 60:
            seconds = 60
        else:
            seconds = 30
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None:
                return False, t(self.settings.default_language, "no_active_game")
            lang = await self.get_group_language(game.chat_id)
            if game.status != GameStatus.REGISTRATION.value:
                return False, t(lang, "registration_closed_cb")
            current_end = self._ensure_utc(game.registration_ends_at) if game.registration_ends_at else self._now_utc()
            if current_end < self._now_utc():
                current_end = self._now_utc()
            game.registration_ends_at = current_end + timedelta(seconds=seconds)
            self._add_game_log(
                session,
                game,
                "registration_extended",
                seconds=seconds,
                registration_ends_at=game.registration_ends_at.isoformat(),
            )
            await session.commit()

        try:
            await self.schedule_registration_jobs(bot, game_id)
        except Exception:
            logger.exception("Failed to reschedule registration jobs for game_id=%s", game_id)
        return True, t(await self.get_group_language(game.chat_id), "extended")


    async def stop_game(self, bot: Bot, game_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None:
                return False, t(self.settings.default_language, "no_active_game")
            game.status = GameStatus.CANCELLED.value
            game.phase = GamePhase.ENDED.value
            game.active_key = None
            game.ended_at = datetime.now(timezone.utc)
            self._add_game_log(session, game, "game_cancelled", reason="manual_stop")
            await session.commit()
            chat_id = game.chat_id
            lang = await self.get_group_language(game.chat_id)

        self._invalidate_game_cache(chat_id)
        await self.update_lobby(bot, game_id, ended=True)
        self._cleanup_jobs(game_id)
        return True, t(lang, "game_cancelled")


    def _cleanup_jobs(self, game_id: int) -> None:
        for prefix in [
            "reg_warn_60_",
            "reg_warn_30_",
            "reg_close_",
            "night_end_",
            "discussion_end_",
            "vote_end_",
            "hang_confirm_",
        ]:
            job_id = f"{prefix}{game_id}"
            job = scheduler.get_job(job_id)
            if job:
                job.remove()


    async def close_registration(self, bot: Bot, game_id: int, force: bool = False) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.REGISTRATION.value:
                return
            lobby_message_id = game.lobby_message_id

            group = (await session.execute(select(Group).where(Group.chat_id == game.chat_id))).scalar_one_or_none()
            min_players = max(4, group.min_players if group else self.settings.min_players)
            players = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc()))
            ).scalars().all()
            lang = await self.get_group_language(game.chat_id)
            is_tournament = await self._is_tournament_game_in_session(session, game_id)
            removed_unpaired_names: list[str] = []
            if is_tournament and players:
                active_couples = (
                    await session.execute(
                        select(CoupleRelationship).where(
                            CoupleRelationship.chat_id == game.chat_id,
                            CoupleRelationship.active.is_(True),
                        )
                    )
                ).scalars().all()
                paired_ids = {
                    user_id
                    for couple in active_couples
                    for user_id in (couple.user_one_telegram_id, couple.user_two_telegram_id)
                }
                valid_players: list[GamePlayer] = []
                for player in players:
                    if player.telegram_id in paired_ids:
                        valid_players.append(player)
                    else:
                        removed_unpaired_names.append(self._tg_mention(player.telegram_id, player.display_name))
                        await session.delete(player)
                if removed_unpaired_names:
                    players = valid_players
                    self._add_game_log(
                        session,
                        game,
                        "tournament_unpaired_players_removed",
                        removed=removed_unpaired_names,
                    )
                    await session.commit()
                    await self._safe_send_message(
                        bot,
                        game.chat_id,
                        "💞 Turnirga parasi yo'q o'yinchilar ro'yxatdan chiqarildi:\n"
                        + "\n".join(removed_unpaired_names),
                    )
                incomplete_couples = await self._tournament_incomplete_couple_lines(session, game.chat_id, players)
                if incomplete_couples:
                    if game.registration_ends_at is not None:
                        game.registration_ends_at = None
                    self._add_game_log(
                        session,
                        game,
                        "tournament_waiting_complete_couples",
                        missing=incomplete_couples,
                    )
                    await session.commit()
                    self._invalidate_game_cache(game.chat_id)
                    self._cleanup_jobs(game_id)
                    await self.update_lobby(bot, game_id)
                    await self._safe_send_message(
                        bot,
                        game.chat_id,
                        "💞 Turnirni boshlash uchun barcha paralar to'liq ro'yxatdan o'tishi kerak.\n\n"
                        + "\n".join(incomplete_couples),
                    )
                    return
            gsm = GroupSettingsManager(self.session_factory)
            admin_start_confirm = await gsm.get_extra_enabled(game.chat_id, "admin_start_confirm")

            if admin_start_confirm and not force:
                if game.registration_ends_at is not None:
                    game.registration_ends_at = None
                    self._add_game_log(
                        session,
                        game,
                        "registration_waiting_admin_confirmation",
                        players_count=len(players),
                        min_players=min_players,
                    )
                    await session.commit()
                self._invalidate_game_cache(game.chat_id)
                self._cleanup_jobs(game_id)
                await self._safe_send_message(
                    bot,
                    game.chat_id,
                    "🛡 Admin tasdiqi yoqilgan.\nRo'yxatdan o'tish davom etadi. O'yin admin /start berganda boshlanadi.",
                )
                return

            if len(players) < min_players:
                game.status = GameStatus.CANCELLED.value
                game.phase = GamePhase.ENDED.value
                game.active_key = None
                game.ended_at = datetime.now(timezone.utc)
                self._add_game_log(
                    session,
                    game,
                    "game_cancelled",
                    reason="insufficient_players",
                    players_count=len(players),
                    min_players=min_players,
                )
                await session.commit()
                self._invalidate_game_cache(game.chat_id)
                await self.update_lobby(bot, game_id, ended=True)
                await bot.send_message(game.chat_id, t(lang, "insufficient_players"))
                self._cleanup_jobs(game_id)
                return

            game.status = GameStatus.ACTIVE.value
            game.phase = GamePhase.NIGHT.value
            game.started_at = datetime.now(timezone.utc)
            game.night_number = 1
            self._add_game_log(
                session,
                game,
                "registration_closed",
                players_count=len(players),
                min_players=min_players,
            )
            await session.commit()
            self._invalidate_game_cache(game.chat_id)
            is_zombie_mode = game.role_preset == "zombie"

        await self.update_lobby(bot, game_id, ended=True)
        chat_id = await self._game_chat_id(game_id)
        if lobby_message_id is not None:
            try:
                await bot.unpin_chat_message(chat_id=chat_id, message_id=lobby_message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
        await self._safe_send_message(bot, chat_id, t(lang, "registration_ended"))
        await self.assign_roles_and_notify(bot, game_id)
        start_text = (
            "🧟 <b>Zombie mode boshlandi!</b>\n\n"
            "Zombi taraf har tunda bitta insonni virus bilan o'z tarafiga o'tkazishga urinadi.\n"
            "Insonlar kunduzgi ovoz berishda zombielarni topib chiqarib yuborishi kerak."
            if is_zombie_mode
            else "<b>O'yin boshlandi!</b>"
        )
        await self._safe_send_message(
            bot,
            chat_id,
            start_text,
            reply_markup=go_role_private_keyboard(self.settings, game_id),
        )
        await self.start_night(bot, game_id)


    async def _game_chat_id(self, game_id: int) -> int:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
            return game.chat_id


    async def cleanup_stale_games_on_startup(self) -> None:
        async with self.session_factory() as session:
            stale = (
                await session.execute(
                    select(Game).where(Game.status.in_([GameStatus.REGISTRATION.value, GameStatus.ACTIVE.value]))
                )
            ).scalars().all()
            for game in stale:
                game.status = GameStatus.CANCELLED.value
                game.phase = GamePhase.ENDED.value
                game.active_key = None
                game.ended_at = datetime.now(timezone.utc)
            await session.commit()


    async def registration_watchdog(self, bot: Bot) -> None:
        now = self._now_utc()
        async with self.session_factory() as session:
            games = (
                await session.execute(
                    select(Game).where(
                        Game.status == GameStatus.REGISTRATION.value,
                        Game.registration_ends_at.is_not(None),
                        Game.registration_ends_at <= now,
                    )
                )
            ).scalars().all()
            game_ids = [game.id for game in games]
        # Close all expired registrations concurrently so a slow game (e.g. many
        # tournament validations) doesn't block the others from starting.
        if game_ids:
            results = await asyncio.gather(
                *(self.close_registration(bot, gid) for gid in game_ids),
                return_exceptions=True,
            )
            for gid, exc in zip(game_ids, results):
                if isinstance(exc, Exception):
                    logger.exception(
                        "registration_watchdog: close_registration failed for game_id=%s: %s",
                        gid, exc,
                    )


    async def is_admin_or_creator(self, bot: Bot, chat_id: int, user_id: int, game_creator_id: Optional[int] = None) -> bool:
        if game_creator_id and user_id == game_creator_id:
            return True
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            return member.status in {"administrator", "creator"}
        except TelegramBadRequest:
            return False


    async def bot_is_admin(self, bot: Bot, chat_id: int) -> bool:
        try:
            me = await asyncio.wait_for(bot.get_me(), timeout=8)
            member = await asyncio.wait_for(bot.get_chat_member(chat_id, me.id), timeout=8)
            return member.status in {"administrator", "creator"}
        except (TelegramBadRequest, TelegramForbiddenError, asyncio.TimeoutError) as exc:
            logger.warning("Unable to check bot admin status chat_id=%s: %s", chat_id, exc)
            return False


    async def check_command_permission(self, bot: Bot, chat_id: int, user_id: int, command_key: str) -> tuple[bool, str]:
        gsm = GroupSettingsManager(self.session_factory)
        level = await gsm.get_command_permission(chat_id, command_key)
        if level == "user":
            return True, ""
        if level == "admin":
            if await self.is_admin_or_creator(bot, chat_id, user_id):
                return True, ""
            return False, "❌ Sizda bu buyruqni ishlatish huquqi yo'q."
        if level == "owner":
            if user_id == self.settings.owner_id:
                return True, ""
            return False, "❌ Sizda bu buyruqni ishlatish huquqi yo'q."
        return True, ""


    async def _get_cached_chat_permission(self, chat_id: int, phase: str) -> str:
        cache_key = (chat_id, phase)
        now = self._monotonic()
        cached = self._chat_permission_cache.get(cache_key)
        if cached:
            expire_time, permission = cached
            if expire_time > now:
                return permission
            del self._chat_permission_cache[cache_key]
        gsm = GroupSettingsManager(self.session_factory)
        permission = await gsm.get_chat_permission(chat_id, phase)
        self._chat_permission_cache[cache_key] = (now + self._chat_permission_cache_ttl, permission)
        if len(self._chat_permission_cache) > self._cache_limit:
            expired_keys = [k for k, v in self._chat_permission_cache.items() if v[0] <= now]
            for k in expired_keys:
                self._chat_permission_cache.pop(k, None)
            if len(self._chat_permission_cache) > self._cache_limit:
                for k in list(self._chat_permission_cache.keys())[: max(1, self._cache_limit // 10)]:
                    self._chat_permission_cache.pop(k, None)
        return permission


    async def check_chat_write_permission(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        if await self.is_vip_user_active(user_id):
            return True
        active = await self.active_game_for_chat(chat_id)
        if active is None or active.status != GameStatus.ACTIVE.value:
            return True
        phase = "night" if active.phase == GamePhase.NIGHT.value else "day"
        permission = await self._get_cached_chat_permission(chat_id, phase)
        if permission == "all":
            return True
        if permission == "owner":
            return user_id == self.settings.owner_id
        if permission == "admin":
            return await self.is_admin_or_creator(bot, chat_id, user_id)
        if permission in ("alive_players", "players"):
            async with self.session_factory() as session:
                player = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == active.id,
                            GamePlayer.telegram_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if player is None:
                    return False
                if permission == "alive_players":
                    return bool(player.alive)
                return True
        return True


    async def should_delete_message_for_non_player(self, chat_id: int, user_id: int) -> bool:
        if await self.is_vip_user_active(user_id):
            return False

        now = self._monotonic()
        cached = self._active_participants_cache.get(chat_id)
        if cached and cached[0] > now:
            _, game_id, participant_ids = cached
            if game_id is None:
                return False
            return user_id not in participant_ids

        async with self.session_factory() as session:
            game = await self.find_active_game(session, chat_id)
            if game is None or game.status != GameStatus.ACTIVE.value:
                self._prune_cache_if_needed(self._active_participants_cache)
                self._active_participants_cache[chat_id] = (
                    now + self._cache_ttl_seconds,
                    None,
                    frozenset(),
                )
                return False
            participant_ids = frozenset(
                (
                    await session.execute(
                        select(GamePlayer.telegram_id).where(GamePlayer.game_id == game.id)
                    )
                ).scalars().all()
            )

        self._prune_cache_if_needed(self._active_participants_cache)
        self._active_participants_cache[chat_id] = (
            now + self._cache_ttl_seconds,
            game.id,
            participant_ids,
        )
        return user_id not in participant_ids


    async def get_player_running_game(self, telegram_id: int) -> Optional[tuple[int, GamePlayer, str]]:
        """Get the player's currently active game info and their player record.
        Returns: (game_id, game_chat_id, player)
        """
        async with self.session_factory() as session:
            result = (
                await session.execute(
                    select(Game, GamePlayer)
                    .join(GamePlayer, GamePlayer.game_id == Game.id)
                    .where(
                        Game.status == GameStatus.ACTIVE.value,
                        GamePlayer.telegram_id == telegram_id,
                    )
                    .order_by(Game.id.desc())
                )
            ).first()
            if result is None:
                return None
            game, player = result
            # Detach and return only necessary data
            return (game.id, game.chat_id, player.telegram_id, player.role, player.display_name, player.alive)

    async def user_in_running_game(self, telegram_id: int) -> bool:
        async with self.session_factory() as session:
            player_id = (
                await session.execute(
                    select(GamePlayer.id)
                    .join(Game, Game.id == GamePlayer.game_id)
                    .where(
                        Game.status == GameStatus.ACTIVE.value,
                        GamePlayer.telegram_id == telegram_id,
                        GamePlayer.alive.is_(True),
                    )
                    .order_by(Game.id.desc())
                )
            ).scalar_one_or_none()
            return player_id is not None

    async def active_game_for_chat(self, chat_id: int) -> Optional[Game]:
        async with self.session_factory() as session:
            return await self.find_active_game(session, chat_id)

    async def is_vip_user_active(self, user_id: int) -> bool:
        async with self.session_factory() as session:
            user = (
                await session.execute(
                    select(User.vip_until).where(User.telegram_id == user_id)
                )
            ).scalar_one_or_none()
        if user is None:
            return False
        vip_until = user
        if vip_until.tzinfo is None:
            vip_until = vip_until.replace(tzinfo=timezone.utc)
        else:
            vip_until = vip_until.astimezone(timezone.utc)
        return vip_until > self._now_utc()



