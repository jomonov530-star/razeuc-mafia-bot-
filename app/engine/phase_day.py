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

class DayPhaseMixin:
    async def start_voting(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return
            game.phase = GamePhase.DAY_VOTING.value
            alive = await self._alive_players(session, game_id)
            for player in alive:
                player.hero_defense_active = False
                player.hero_defense_amount = 0
            self._add_game_log(
                session,
                game,
                "voting_started",
                alive_count=len(alive),
                timeout=await self.group_timeout(game.chat_id, "day_voting_timeout"),
            )
            await session.commit()
            choices = [(p.telegram_id, p.display_name) for p in alive]
            lang = await self.get_group_language(game.chat_id)
            voting_timeout = await self.group_timeout(game.chat_id, "day_voting_timeout")

        if len(choices) <= 1:
            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
            return

        scheduler.add_job(
            self.resolve_voting,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=voting_timeout),
            args=[bot, game_id],
            id=f"vote_end_{game_id}",
            replace_existing=True,
        )
        await self._safe_send_message(
            bot,
            await self._game_chat_id(game_id),
            "Aybdorlarni aniqlash va jazolash vaqti keldi.\n"
            f"Ovoz berish uchun {voting_timeout} sekund.",
            reply_markup=go_vote_private_keyboard(self.settings, game_id),
        )
        for player_id, _ in choices:
            ok, _ = await self.send_private_vote_menu(bot, game_id, player_id)
            if not ok:
                continue


    async def cast_vote(
        self,
        bot: Bot,
        game_id: int,
        voter_id: int,
        target_id: int,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.DAY_VOTING.value:
                return False, t(self.settings.default_language, "callback_expired")

            voter = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.telegram_id == voter_id))
            ).scalar_one_or_none()
            target = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.telegram_id == target_id))
            ).scalar_one_or_none()
            if voter is None or not voter.alive:
                return False, t(self.settings.default_language, "not_alive")
            if self._is_day_blocked(voter, game):
                return False, "Kezuvchi sabab bugun ovoz bera olmaysiz."
            if target is None or not target.alive:
                return False, "Nishon o'lik yoki topilmadi."
            target_display_name = target.display_name or "Unknown"
            skipped = (
                await session.execute(
                    select(SkipDecision.id).where(
                        SkipDecision.game_id == game_id,
                        SkipDecision.phase == "vote",
                        SkipDecision.day_number == game.day_number,
                        SkipDecision.night_number == game.night_number,
                        SkipDecision.user_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            if skipped is not None:
                return False, "Siz ovoz berishni o'tkazib yuborgansiz."

            exists = (
                await session.execute(
                    select(Vote).where(
                        Vote.game_id == game_id,
                        Vote.day_number == game.day_number,
                        Vote.voter_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False, t(self.settings.default_language, "vote_already")

            session.add(
                Vote(
                    game_id=game_id,
                    day_number=game.day_number,
                    voter_telegram_id=voter_id,
                    target_telegram_id=target_id,
                )
            )
            self._add_game_log(session, game, "vote_cast", actor=voter, target=target)
            await session.commit()
            chat_id = game.chat_id
            voter_name = self._tg_mention(voter.telegram_id, voter.display_name)
            target_name = self._tg_mention(target.telegram_id, target_display_name)

        await bot.send_message(chat_id, f"{voter_name} ovoz berdi {target_name} ga")
        return True, f"Siz {target_display_name} ni tanladingiz."


    async def send_private_vote_menu(self, bot: Bot, game_id: int, voter_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.DAY_VOTING.value:
                return False, t(self.settings.default_language, "callback_expired")
            voter = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == voter_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if voter is None:
                return False, t(self.settings.default_language, "not_alive")
            if self._is_day_blocked(voter, game):
                return False, "Kezuvchi sabab bugun ovoz bera olmaysiz."
            already_voted = (
                await session.execute(
                    select(Vote.id).where(
                        Vote.game_id == game_id,
                        Vote.day_number == game.day_number,
                        Vote.voter_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            if already_voted is not None:
                return False, t(self.settings.default_language, "vote_already")
            already_skipped = (
                await session.execute(
                    select(SkipDecision.id).where(
                        SkipDecision.game_id == game_id,
                        SkipDecision.phase == "vote",
                        SkipDecision.day_number == game.day_number,
                        SkipDecision.night_number == game.night_number,
                        SkipDecision.user_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            if already_skipped is not None:
                return False, "Siz ovoz berishni o'tkazib yuborgansiz."
            alive = await self._alive_players(session, game_id)

        choices = [(p.telegram_id, p.display_name) for p in alive if p.telegram_id != voter_id]
        sent = await self._safe_send_message(
            bot,
            voter_id,
            "🗳 <b>Ovoz berish</b>\n\nKimni kunduzgi yig'ilishda osamiz?",
            reply_markup=vote_keyboard(game_id, choices),
        )
        if sent is None:
            return False, "Ovoz berish ro'yxati yuborilmadi."
        return True, "Ovoz berish ro'yxati yuborildi."


    async def set_last_words(self, telegram_id: int, words: str) -> tuple[bool, str]:
        cleaned = words.strip()
        if not cleaned:
            return False, "Xabar bo'sh bo'lmasin."
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(GamePlayer, Game)
                    .join(Game, Game.id == GamePlayer.game_id)
                    .where(
                        Game.status == GameStatus.ACTIVE.value,
                        GamePlayer.telegram_id == telegram_id,
                    )
                    .order_by(Game.id.desc())
                )
            ).first()
            if row is None:
                return False, "Siz aktiv o'yinda emassiz."
            player, game = row
            player.last_words = cleaned[:500]
            player.awaiting_last_words = False
            self._add_game_log(
                session,
                game,
                "last_words_saved",
                actor=player,
                text_length=len(player.last_words),
            )
            await session.commit()
            return True, "So'nggi xabaringiz saqlandi."


    async def handle_pending_last_words(self, bot: Bot, telegram_id: int, words: str) -> bool:
        cleaned = words.strip()
        if not cleaned:
            return False
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(GamePlayer, Game)
                    .join(Game, Game.id == GamePlayer.game_id)
                    .where(
                        Game.status == GameStatus.ACTIVE.value,
                        GamePlayer.telegram_id == telegram_id,
                        GamePlayer.awaiting_last_words.is_(True),
                    )
                    .order_by(Game.id.desc())
                )
            ).first()
            if row is None:
                return False
            player, game = row
            player.last_words = cleaned[:500]
            player.awaiting_last_words = False
            line = self._last_words_line(player, player.last_words)
            chat_id = game.chat_id
            self._add_game_log(
                session,
                game,
                "last_words_sent",
                actor=player,
                text_length=len(player.last_words),
            )
            await session.commit()

        await bot.send_message(chat_id, line)
        return True


    async def resolve_voting(self, bot: Bot, game_id: int) -> None:
        if await self._is_zombie_game_id(game_id):
            await self.resolve_zombie_voting(bot, game_id)
            return

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return
            if game.phase != GamePhase.DAY_VOTING.value:
                return

            votes = (
                await session.execute(
                    select(Vote).where(Vote.game_id == game_id, Vote.day_number == game.day_number)
                )
            ).scalars().all()
            alive = await self._alive_players(session, game_id)
            alive_map = {p.telegram_id: p for p in alive}

            counter = Counter(v.target_telegram_id for v in votes)
            chat_id = game.chat_id
            if not counter:
                self._add_game_log(session, game, "voting_resolved", result="no_votes", votes_count=0)
                await self._safe_send_message(
                    bot,
                    chat_id,
                    "<b>Ovoz berish natijalari:</b>\n"
                    "0 👍  |  0 👎\n\n"
                    "Aholi janjallashib uylariga tarqashdi.",
                )
                await self._apply_inactivity_after_vote(bot, session, game, votes)
                winner = await self.check_winner(game_id)
                if winner:
                    await self.finish_game(bot, game_id, winner)
                    return
                game.phase = GamePhase.NIGHT.value
                game.night_number += 1
                await session.commit()
                await self.start_night(bot, game_id)
                return

            top_count = counter.most_common(1)[0][1]
            top_targets = [target_id for target_id, count in counter.items() if count == top_count]
            if len(top_targets) > 1:
                self._add_game_log(
                    session,
                    game,
                    "voting_resolved",
                    result="tie",
                    top_targets=top_targets,
                    top_count=top_count,
                )
                await self._safe_send_message(bot, chat_id, "Aholi janjallashib uylariga tarqashdi.")
                await self._apply_inactivity_after_vote(bot, session, game, votes)
                winner = await self.check_winner(game_id)
                if winner:
                    await self.finish_game(bot, game_id, winner)
                    return
                game.phase = GamePhase.NIGHT.value
                game.night_number += 1
                await session.commit()
                await self.start_night(bot, game_id)
                return

            target_id = top_targets[0]
            target = alive_map.get(target_id)
            if target is None:
                return
            judges = [
                player
                for player in alive
                if Role(player.role) == Role.JUDGE and not player.judge_cancel_used
            ]
            game.phase = GamePhase.DAY_CONFIRM.value
            self._add_game_log(
                session,
                game,
                "hang_confirmation_started",
                target=target,
                votes_count=len(votes),
                top_count=top_count,
                judges_count=len(judges),
            )
            await session.commit()
            confirm_message = await self._safe_send_message(
                bot,
                chat_id,
                f"Rostdan xam {self._tg_mention(target.telegram_id, target.display_name)}ni osmoqchimisiz?",
                reply_markup=confirm_hang_keyboard(game_id, target.telegram_id),
            )
            scheduler.add_job(
                self.resolve_hang_confirmation,
                "date",
                run_date=datetime.now(timezone.utc) + timedelta(seconds=30),
                args=[bot, game_id, target.telegram_id, confirm_message.message_id if confirm_message else None],
                id=f"hang_confirm_{game_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )
            for judge in judges:
                try:
                    await bot.send_message(
                        judge.telegram_id,
                        "🧑‍⚖️ <b>Sudya qarori</b>\n\n"
                        f"Aholi {self._tg_mention(target.telegram_id, target.display_name)}ni osmoqchi. "
                        "O'yinda bir marta bu hukmni bekor qilishingiz mumkin.",
                        reply_markup=judge_cancel_keyboard(
                            game_id,
                            target.telegram_id,
                            judge.telegram_id,
                            confirm_message.message_id,
                        ),
                    )
                except TelegramForbiddenError:
                    pass
            return


    async def _apply_inactivity_after_vote(
        self,
        bot: Bot,
        session: AsyncSession,
        game: Game,
        votes: list[Vote],
    ) -> None:
        return


    async def resolve_zombie_voting(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if (
                game is None
                or game.status != GameStatus.ACTIVE.value
                or game.phase != GamePhase.DAY_VOTING.value
                or not self._is_zombie_game(game)
            ):
                return

            votes = (
                await session.execute(
                    select(Vote).where(Vote.game_id == game_id, Vote.day_number == game.day_number)
                )
            ).scalars().all()
            alive = await self._alive_players(session, game_id)
            alive_map = {player.telegram_id: player for player in alive}
            counter = Counter(vote.target_telegram_id for vote in votes)
            chat_id = game.chat_id

            if not counter:
                self._add_game_log(session, game, "zombie_voting_resolved", result="no_votes", votes_count=0)
                game.phase = GamePhase.NIGHT.value
                game.night_number += 1
                await session.commit()
                await self._safe_send_message(
                    bot,
                    chat_id,
                    "<b>Ovoz berish natijalari:</b>\n"
                    "Hech kim ovoz bermadi. Insonlar tarqaldi...",
                )
                await self.start_night(bot, game_id)
                return

            top_count = counter.most_common(1)[0][1]
            top_targets = [target_id for target_id, count in counter.items() if count == top_count]
            if len(top_targets) > 1:
                self._add_game_log(
                    session,
                    game,
                    "zombie_voting_resolved",
                    result="tie",
                    top_targets=top_targets,
                    top_count=top_count,
                )
                game.phase = GamePhase.NIGHT.value
                game.night_number += 1
                await session.commit()
                await self._safe_send_message(bot, chat_id, "Ovozlar teng chiqdi. Hech kim chiqarilmadi.")
                await self.start_night(bot, game_id)
                return

            target = alive_map.get(top_targets[0])
            if target is None:
                return

            target.alive = False
            target.death_day = game.day_number
            self._add_game_log(
                session,
                game,
                "zombie_player_hanged",
                target=target,
                votes_count=top_count,
            )
            day_dead_ids = {target.telegram_id}
            couple_day_lines = await self._expand_tournament_couple_deaths(
                session,
                game,
                alive,
                day_dead_ids,
            )
            for player in alive:
                if player.telegram_id in day_dead_ids and player.alive:
                    player.alive = False
                    player.death_day = game.day_number
            await session.commit()
            target_line = (
                f"🗳 {self._tg_mention(target.telegram_id, target.display_name)} "
                "kunduzgi ovoz bilan o'yindan chiqarildi.\n"
                f"U edi {role_label(target.role)}."
            )

        await self._safe_send_message(bot, chat_id, target_line)
        for line in couple_day_lines:
            await self._safe_send_message(bot, chat_id, line)
        winner = await self.check_winner(game_id)
        if winner:
            await self.finish_game(bot, game_id, winner)
            return

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return
            game.phase = GamePhase.NIGHT.value
            game.night_number += 1
            await session.commit()

        await self.start_night(bot, game_id)


    async def confirm_hang(
        self,
        bot: Bot,
        game_id: int,
        target_id: int,
        confirmed: bool,
        voter_id: int,
    ) -> tuple[bool, str, Optional[object]]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.DAY_CONFIRM.value:
                return False, t(self.settings.default_language, "callback_expired"), None
            voter = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == voter_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if voter is None:
                return False, "Siz bu o'yinda tirik ishtirokchi emassiz.", None
            if self._is_day_blocked(voter, game):
                return False, "Kezuvchi sabab bugun osish bo'yicha ovoz bera olmaysiz.", None
            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == target_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return False, "Nomzod topilmadi yoki allaqachon o'lgan.", None
            if voter_id == target_id:
                return False, "O'zingiz uchun ovoz bera olmaysiz.", None
            skipped = (
                await session.execute(
                    select(SkipDecision.id).where(
                        SkipDecision.game_id == game_id,
                        SkipDecision.phase == "hang",
                        SkipDecision.day_number == game.day_number,
                        SkipDecision.night_number == game.night_number,
                        SkipDecision.user_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            if skipped is not None:
                return False, "Siz osish tanlovini o'tkazib yuborgansiz.", None
            existing = (
                await session.execute(
                    select(HangVote).where(
                        HangVote.game_id == game_id,
                        HangVote.day_number == game.day_number,
                        HangVote.voter_telegram_id == voter_id,
                    )
                )
            ).scalar_one_or_none()
            vote_changed = False
            if existing:
                vote_changed = existing.approve != confirmed or existing.target_telegram_id != target_id
                existing.target_telegram_id = target_id
                existing.approve = confirmed
            else:
                session.add(
                    HangVote(
                        game_id=game_id,
                        day_number=game.day_number,
                        target_telegram_id=target_id,
                        voter_telegram_id=voter_id,
                        approve=confirmed,
                    )
                )
            hang_votes = (
                await session.execute(
                    select(HangVote).where(
                        HangVote.game_id == game_id,
                        HangVote.day_number == game.day_number,
                        HangVote.target_telegram_id == target_id,
                    )
                )
            ).scalars().all()
            yes_count = sum(1 for vote in hang_votes if vote.approve)
            no_count = sum(1 for vote in hang_votes if not vote.approve)
            self._add_game_log(
                session,
                game,
                "hang_vote_cast",
                actor=voter,
                target=target,
                confirmed=confirmed,
                changed=vote_changed,
                yes_count=yes_count,
                no_count=no_count,
            )
            chat_id = game.chat_id
            target_display_name = target.display_name
            await session.commit()
            keyboard = confirm_hang_keyboard(game_id, target_id, yes_count=yes_count, no_count=no_count)
            try:
                await bot.send_message(
                    voter_id,
                    "Ovozingiz yangilandi." if vote_changed else "Siz ovoz berdingiz.",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
            return True, "Ovozingiz yangilandi." if vote_changed else "Ovozingiz qabul qilindi.", keyboard


    async def judge_cancel_hang(
        self,
        bot: Bot,
        game_id: int,
        target_id: int,
        judge_id: int,
        confirm_message_id: Optional[int] = None,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.DAY_CONFIRM.value:
                return False, t(self.settings.default_language, "callback_expired")
            judge = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == judge_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if judge is None or Role(judge.role) != Role.JUDGE:
                return False, "Bu qaror faqat Sudya uchun."
            if self._is_day_blocked(judge, game):
                return False, "Kezuvchi sabab bugun hech qanday amal bajara olmaysiz."
            if judge.judge_cancel_used:
                return False, "Sudya hukmni faqat bir marta bekor qila oladi."
            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == target_id,
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return False, "Nomzod topilmadi."

            votes = (
                await session.execute(
                    select(Vote).where(Vote.game_id == game_id, Vote.day_number == game.day_number)
                )
            ).scalars().all()
            chat_id = game.chat_id
            judge_name = self._tg_mention(judge.telegram_id, judge.display_name)

            await self._apply_inactivity_after_vote(bot, session, game, votes)
            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
                return True, "O'yin yakunlandi."

            judge.judge_cancel_used = True
            judge.inactive_rounds = 0
            game.phase = GamePhase.NIGHT.value
            game.night_number += 1
            self._add_game_log(
                session,
                game,
                "hang_cancelled_by_judge",
                actor=judge,
                target=target,
            )
            await session.commit()

        job = scheduler.get_job(f"hang_confirm_{game_id}")
        if job:
            job.remove()
        if confirm_message_id:
            await self._safe_edit_message_reply_markup(
                bot,
                chat_id=chat_id,
                message_id=confirm_message_id,
                reply_markup=None,
            )
        await self._safe_send_message(
            bot,
            chat_id,
            "🧑‍⚖️ Sudya  kunduzgi hukmni bekor qildi.\n"
            "Hukm bekor qilindi. Aholi tarqaldi...",
        )
        await self._safe_send_message(
            bot,
            judge_id,
            f"Siz {target.display_name} uchun kunduzgi hukmni bekor qildingiz.",
            reply_markup=await self.group_return_keyboard(bot, chat_id),
        )
        await self.start_night(bot, game_id)
        return True, "Sudya qarori qabul qilindi."


    async def resolve_hang_confirmation(
        self,
        bot: Bot,
        game_id: int,
        target_id: int,
        message_id: Optional[int] = None,
    ) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.DAY_CONFIRM.value:
                return
            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == target_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return
            votes = (
                await session.execute(
                    select(Vote).where(Vote.game_id == game_id, Vote.day_number == game.day_number)
                )
            ).scalars().all()
            hang_votes = (
                await session.execute(
                    select(HangVote).where(
                        HangVote.game_id == game_id,
                        HangVote.day_number == game.day_number,
                        HangVote.target_telegram_id == target_id,
                    )
                )
            ).scalars().all()
            chat_id = game.chat_id
            yes_confirm = sum(1 for vote in hang_votes if vote.approve)
            no_confirm = sum(1 for vote in hang_votes if not vote.approve)

            if message_id:
                await self._safe_edit_message_reply_markup(
                    bot,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=None,
                )

            if yes_confirm > no_confirm:
                yes_votes = sum(1 for vote in votes if vote.target_telegram_id == target_id)
                target_user = (
                    await session.execute(select(User).where(User.telegram_id == target.telegram_id))
                ).scalar_one_or_none()
                if target_user is not None and target_user.use_vote_protection is not False and (target_user.vote_protection or 0) > 0:
                    target_user.vote_protection -= 1
                    self._add_game_log(
                        session,
                        game,
                        "hang_blocked_by_vote_protection",
                        target=target,
                        remaining_vote_protection=target_user.vote_protection,
                    )
                    await session.commit()
                    await self._safe_send_message(
                        bot,
                        chat_id,
                        f"⚖️ {self._tg_mention(target.telegram_id, target.display_name)} o'z himoyasini ishlatdi. Osishni bekor qildi.",
                    )
                    try:
                        await bot.send_message(
                            target.telegram_id,
                            "⚖️ Ovoz himoyasi sizni osilishdan saqlab qoldi.",
                            reply_markup=await self.group_return_keyboard(bot, chat_id),
                        )
                    except TelegramForbiddenError:
                        pass
                else:
                    target.alive = False
                    target.death_day = game.day_number
                    if Role(target.role) == Role.JESTER:
                        target.won = True
                    self._add_game_log(
                        session,
                        game,
                        "player_hanged",
                        target=target,
                        yes_confirm=yes_confirm,
                        no_confirm=no_confirm,
                        vote_count=yes_votes,
                    )
                    vote_text = (
                        "<b>Ovoz berish natijalari:</b>\n"
                        f"{yes_votes} 👍  |  {no_confirm} 👎\n\n"
                        f"{self._tg_mention(target.telegram_id, target.display_name)} O'tkazilgan kunduzgi yiģilishda osildi!\n"
                        f"U edi {role_label(target.role)}.."
                    )
                    all_players_for_day_death = (
                        await session.execute(
                            select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                        )
                    ).scalars().all()
                    day_dead_ids = {target.telegram_id}
                    couple_day_lines = await self._expand_tournament_couple_deaths(
                        session,
                        game,
                        all_players_for_day_death,
                        day_dead_ids,
                    )
                    for player in all_players_for_day_death:
                        if player.telegram_id in day_dead_ids and player.alive:
                            player.alive = False
                            player.death_day = game.day_number
                    await session.commit()
                    await self._safe_send_message(bot, chat_id, vote_text)
                    for line in couple_day_lines:
                        await self._safe_send_message(bot, chat_id, line)

                    if Role(target.role) == Role.JESTER:
                        await self._safe_send_message(
                            bot,
                            chat_id,
                            f"🎭 Masxaraboz {self._tg_mention(target.telegram_id, target.display_name)} "
                            "o'z xohishiga yetdi va alohida g'olib bo'ldi!"
                        )

                    succession_events = self._apply_role_successions(
                        all_players_for_day_death,
                        day_dead_ids,
                    )
                    if succession_events:
                        await session.commit()
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

                    if Role(target.role) == Role.SORCERER:
                        extra_day_dead = set()
                        alive_now = await self._alive_players(session, game_id)
                        candidates = [(p.telegram_id, p.display_name) for p in alive_now if p.telegram_id != target.telegram_id]
                        if candidates:
                            await session.commit()
                            await self._safe_send_message(
                                bot,
                                target.telegram_id,
                                "🧞‍♂️ Siz osildingiz. Endi o'zingiz bilan birga kimni olib ketishni tanlang:",
                                reply_markup=sorcerer_hang_revenge_keyboard(
                                    game_id=game_id,
                                    sorcerer_id=target.telegram_id,
                                    choices=candidates,
                                ),
                            )
                            await self._safe_send_message(
                                bot,
                                chat_id,
                                f"🧞‍♂️ {self._tg_mention(target.telegram_id, target.display_name)} qasos uchun nishon tanlayapti...",
                            )
                    else:
                        extra_day_dead = set()

                    all_players = (
                        await session.execute(
                            select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                        )
                    ).scalars().all()
                    extra_successions = self._apply_role_successions(all_players, extra_day_dead)
                    if extra_successions:
                        await session.commit()
                    for line, heir_id, new_role in extra_successions:
                        await self._safe_send_message(bot, chat_id, line)
                        try:
                            await bot.send_message(
                                heir_id,
                                self._private_role_text(new_role),
                                reply_markup=await self.group_return_keyboard(bot, chat_id),
                            )
                        except TelegramForbiddenError:
                            pass
            else:
                self._add_game_log(
                    session,
                    game,
                    "hang_rejected",
                    target=target,
                    yes_confirm=yes_confirm,
                    no_confirm=no_confirm,
                )
                await self._safe_send_message(bot, chat_id, "Aholi janjallashib uylariga tarqashdi.")

            await self._apply_inactivity_after_vote(bot, session, game, votes)
            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
                return

            game.phase = GamePhase.NIGHT.value
            game.night_number += 1
            await session.commit()

        await self.start_night(bot, game_id)


    async def resolve_sorcerer_hang_revenge(
        self,
        bot: Bot,
        game_id: int,
        sorcerer_id: int,
        target_id: int,
    ) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return False, t(self.settings.default_language, "callback_expired")

            sorcerer = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == sorcerer_id,
                    )
                )
            ).scalar_one_or_none()
            if sorcerer is None or Role(sorcerer.role) != Role.SORCERER or sorcerer.alive:
                return False, "Bu amal hozir mavjud emas."
            if sorcerer.sorcerer_revenge_used:
                return False, "Qasos allaqachon ishlatilgan."

            target = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == target_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None or target.telegram_id == sorcerer_id:
                return False, "Nishon noto'g'ri."

            target.alive = False
            target.death_day = game.day_number
            sorcerer.sorcerer_revenge_used = True
            all_players = (
                await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            revenge_dead_ids = {target.telegram_id}
            couple_revenge_lines = await self._expand_tournament_couple_deaths(
                session,
                game,
                all_players,
                revenge_dead_ids,
            )
            for player in all_players:
                if player.telegram_id in revenge_dead_ids and player.alive:
                    player.alive = False
                    player.death_day = game.day_number
            self._add_game_log(
                session,
                game,
                "sorcerer_revenge_after_hang",
                actor=sorcerer,
                target=target,
            )
            await session.commit()

            await self._safe_send_message(
                bot,
                game.chat_id,
                f"{_ce('💣', SKULL_EMOJI_ID)} Afsungar afsun qildi va {self._tg_mention(target.telegram_id, target.display_name)}ni jahannamga olib ketdi!\n\n"
                f"U edi {role_label(target.role)}",
            )
            for line in couple_revenge_lines:
                await self._safe_send_message(bot, game.chat_id, line)

            extra_successions = self._apply_role_successions(all_players, revenge_dead_ids)
            if extra_successions:
                await session.commit()
            for line, heir_id, new_role in extra_successions:
                await self._safe_send_message(bot, game.chat_id, line)
                try:
                    await bot.send_message(
                        heir_id,
                        self._private_role_text(new_role),
                        reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                    )
                except TelegramForbiddenError:
                    pass

            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
            else:
                await session.commit()
        return True, "Qasos bajarildi."


    async def resolve_sorcerer_judgement(
        self,
        bot: Bot,
        game_id: int,
        sorcerer_id: int,
        attacker_id: int,
        action: str,
    ) -> tuple[bool, str]:
        if action not in {"forgive", "kill"}:
            return False, "Noma'lum amal."

        pending_key = (game_id, sorcerer_id, attacker_id)
        pending = self._pending_sorcerer_judgements.get(pending_key)
        if pending is None:
            return False, "Bu tanlov eskirgan yoki allaqachon qabul qilingan."
        expires_at, attacker_role_name = pending
        if expires_at <= self._monotonic():
            self._pending_sorcerer_judgements.pop(pending_key, None)
            return False, "Bu tanlov muddati tugagan."

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return False, t(self.settings.default_language, "callback_expired")

            sorcerer = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == sorcerer_id,
                    )
                )
            ).scalar_one_or_none()
            attacker = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == attacker_id,
                    )
                )
            ).scalar_one_or_none()
            if sorcerer is None or Role(sorcerer.role) != Role.MAQ:
                self._pending_sorcerer_judgements.pop(pending_key, None)
                return False, "Bu tanlov bekor bo'lgan."
            if attacker is None:
                self._pending_sorcerer_judgements.pop(pending_key, None)
                return False, "Nishon topilmadi."

            chat_id = game.chat_id
            self._pending_sorcerer_judgements.pop(pending_key, None)

            if action == "forgive":
                await self._safe_send_message(
                    bot,
                    chat_id,
                    f"🕊 Sehrgar {role_label(attacker.role)} xatosini kechirdi.",
                )
                return True, "Kechirildi."

            if not attacker.alive:
                await self._safe_send_message(
                    bot,
                    chat_id,
                    f"💀 Sehrgar {self._tg_mention(attacker.telegram_id, attacker.display_name)} "
                    f"({role_label(attacker.role)}) xatosini kechirmadi, lekin u allaqachon o'lgan edi.",
                )
                return True, "Nishon allaqachon o'lgan."

            attacker.alive = False
            attacker.death_day = game.day_number
            all_players = (
                await session.execute(
                    select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            judgement_dead_ids = {attacker.telegram_id}
            couple_judgement_lines = await self._expand_tournament_couple_deaths(
                session,
                game,
                all_players,
                judgement_dead_ids,
            )
            for player in all_players:
                if player.telegram_id in judgement_dead_ids and player.alive:
                    player.alive = False
                    player.death_day = game.day_number
            await session.commit()

            await self._safe_send_message(
                bot,
                chat_id,
                f"💀 Sehrgar {self._tg_mention(attacker.telegram_id, attacker.display_name)} "
                f"({role_label(attacker.role)}) xatosini kechirmadi va oldirdi!",
            )
            for line in couple_judgement_lines:
                await self._safe_send_message(bot, chat_id, line)

            extra_successions = self._apply_role_successions(all_players, judgement_dead_ids)
            if extra_successions:
                await session.commit()
            for line, heir_id, new_role in extra_successions:
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
            return True, "Oldirish bajarildi."


    async def resolve_joker_card_pick(
        self,
        bot: Bot,
        game_id: int,
        target_id: int,
        actor_id: int,
        picked_card: int,
    ) -> tuple[bool, str]:
        if picked_card not in {1, 2, 3, 4}:
            return False, "Noto'g'ri karta."
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return False, t(self.settings.default_language, "callback_expired")
            prank_action = (
                await session.execute(
                    select(NightAction).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == game.night_number,
                        NightAction.actor_telegram_id == actor_id,
                        NightAction.action_type == ActionType.PRANK.value,
                        NightAction.target_telegram_id == target_id,
                    )
                )
            ).scalar_one_or_none()
            if prank_action is None:
                return False, "Bu karta tanlovi eskirgan."
            try:
                details = json.loads(prank_action.details or "{}")
            except (TypeError, ValueError):
                details = {}
            if details.get("target_card") is not None:
                return False, "Karta allaqachon tanlangan."
            death_card = int(details.get("death_card", 1))
            is_dead = picked_card == death_card
            details["target_card"] = picked_card
            details["result"] = "dead" if is_dead else "safe"
            details["announced"] = True
            prank_action.details = json.dumps(details)
            target_player = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == target_id,
                    )
                )
            ).scalar_one_or_none()
            if target_player is None:
                return False, "Nishon topilmadi."
            if not target_player.alive:
                return False, "Bu o'yinchi allaqachon o'lgan."
            couple_joker_lines: list[str] = []
            if is_dead:
                target_player.alive = False
                target_player.death_day = max(0, int(game.day_number or 0))
                all_players = (
                    await session.execute(
                        select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc())
                    )
                ).scalars().all()
                joker_dead_ids = {target_player.telegram_id}
                couple_joker_lines = await self._expand_tournament_couple_deaths(
                    session,
                    game,
                    all_players,
                    joker_dead_ids,
                )
                for player in all_players:
                    if player.telegram_id in joker_dead_ids and player.alive:
                        player.alive = False
                        player.death_day = max(0, int(game.day_number or 0))
            actor_player = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            await session.commit()
            picked_label = JOKER_CARD_LABELS.get(picked_card, str(picked_card))
            death_label = JOKER_CARD_LABELS.get(death_card, str(death_card))
            try:
                await bot.send_message(
                    target_id,
                    (
                        f"💀 Siz {picked_label} o'lim kartasini tanladingiz va o'ldingiz."
                        if is_dead else
                        f"🍀 Siz {picked_label} kartasini tanladingiz. Omadingiz keldi."
                    ),
                    reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                )
            except TelegramForbiddenError:
                pass
            if actor_player is not None:
                try:
                    await bot.send_message(
                        actor_id,
                        (
                            f"🃏 {self._tg_mention(target_id, target_player.display_name if target_player else str(target_id))} "
                            f"{death_label} o'lim kartasini tanladi."
                        ) if is_dead else (
                            f"🃏 {self._tg_mention(target_id, target_player.display_name if target_player else str(target_id))} omon qoldi."
                        ),
                        reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                    )
                except TelegramForbiddenError:
                    pass
        await self._announce_immediate_joker_result(bot, game, target_player, is_dead)
        for line in couple_joker_lines:
            await self._safe_send_message(bot, game.chat_id, line)
        if is_dead:
            winner = await self.check_winner(game_id)
            if winner:
                await self.finish_game(bot, game_id, winner)
        return True, "Karta tanlandi."


