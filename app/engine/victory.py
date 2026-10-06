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

class VictoryMixin:
    @staticmethod
    def _winner_from_alive_snapshot(alive: list[GamePlayer]) -> Optional[Team]:
        if not alive:
            return Team.CITY

        mafia_count = sum(1 for p in alive if p.team == Team.MAFIA.value)
        killer_count = sum(1 for p in alive if p.team == Team.KILLER.value)
        neutral_count = sum(1 for p in alive if p.team == Team.NEUTRAL.value)
        city_count = len(alive) - mafia_count - killer_count - neutral_count
        passive_survivor_count = sum(1 for p in alive if p.role in {Role.HOJIAKA.value, Role.MINER.value})
        singleton_count = killer_count + neutral_count
        blocking_singleton_count = max(0, singleton_count - passive_survivor_count)

        if city_count == 0 and mafia_count == 0 and singleton_count > 0:
            return Team.KILLER if neutral_count == 0 else Team.NEUTRAL

        if mafia_count == 0 and blocking_singleton_count == 0:
            return Team.CITY

        if len(alive) == 1 and alive[0].team == Team.KILLER.value:
            return Team.KILLER

        if len(alive) == 1 and alive[0].team == Team.NEUTRAL.value:
            return Team.NEUTRAL

        if len(alive) == 2 and mafia_count == 1 and killer_count == 0:
            return Team.MAFIA

        if city_count == 0 and mafia_count > 0:
            other_players = killer_count + neutral_count
            if other_players == 0:
                return Team.MAFIA
            if killer_count > 0 and neutral_count == 0:
                return Team.KILLER if killer_count >= mafia_count else Team.MAFIA
            if neutral_count > 0 and killer_count == 0:
                return Team.MAFIA if mafia_count >= neutral_count else Team.NEUTRAL
            if killer_count > 0 and neutral_count > 0:
                if killer_count >= mafia_count and killer_count >= neutral_count:
                    return Team.KILLER
                if neutral_count >= mafia_count and neutral_count >= killer_count:
                    return Team.NEUTRAL
                return Team.MAFIA

        if city_count == 1 and mafia_count == 1 and blocking_singleton_count == 1:
            return None

        if city_count == 0 and mafia_count >= 2 and blocking_singleton_count == 1 and killer_count == 0:
            return Team.MAFIA

        non_mafia_fighting = city_count + max(0, neutral_count - passive_survivor_count)
        if mafia_count > 0 and mafia_count >= non_mafia_fighting and killer_count == 0:
            return Team.MAFIA

        return None


    async def check_winner(self, game_id: int) -> Optional[Team]:
        """
        O'yin xulosasini tekshiradi - kim yutdi?

        Qoida:
        1. Mafia nol qolsa → CITY wins
        2. Qotil o'z qolsa → KILLER wins
        3. Suidsid o'ldirilib ketsa → NEUTRAL wins
        4. 2 kishi qolsa va 1 ta mafia bo'lsa → MAFIA wins (final duel)
        5. Mafia soni ≥ non-mafia soni bo'lsa → MAFIA wins
        6. Faqat singletonlar qolsa → tirik singletonlar yutadi
        7. Boshqa holda o'yin davom etadi
        """
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            alive = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.alive.is_(True)))
            ).scalars().all()

            if not alive:
                return Team.CITY

            if self._is_zombie_game(game):
                zombie_count = sum(1 for player in alive if player.team == Team.ZOMBIE.value)
                human_count = len(alive) - zombie_count
                if zombie_count <= 0:
                    return Team.CITY
                if human_count <= 1:
                    return Team.ZOMBIE
                return None

            return self._winner_from_alive_snapshot(alive)


    async def finish_game(self, bot: Bot, game_id: int, winner_team: Team) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None:
                return
            if game.status in {GameStatus.COMPLETED.value, GameStatus.CANCELLED.value}:
                return

            players = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc()))
            ).scalars().all()
            users = {
                u.telegram_id: u
                for u in (
                    await session.execute(select(User).where(User.telegram_id.in_([p.telegram_id for p in players])))
                ).scalars().all()
            }

            game.status = GameStatus.COMPLETED.value
            game.phase = GamePhase.ENDED.value
            game.active_key = None
            game.winner_team = winner_team.value
            game.ended_at = datetime.now(timezone.utc)

            winners: list[GamePlayer] = []
            losers: list[GamePlayer] = []
            reward_by_user: dict[int, tuple[int, int, bool]] = {}
            news_bonus_ids = await self.news_bonus_subscriber_ids(bot, [p.telegram_id for p in players])
            is_tournament = await self._is_tournament_game_in_session(session, game_id)
            is_teamgame = await self._is_team_game_in_session(session, game_id)
            arsonist_forced_win = any(
                Role(p.role) == Role.ARSONIST and bool(p.won)
                for p in players
                if p.role is not None
            )
            singleton_final = any(
                p.alive and p.team in {Team.KILLER.value, Team.NEUTRAL.value}
                for p in players
            ) and not any(
                p.alive and p.team in {Team.CITY.value, Team.MAFIA.value}
                for p in players
            )

            def base_winner(player: GamePlayer) -> bool:
                is_win = bool(player.won) or (player.team == winner_team.value and player.alive)
                if singleton_final and player.alive and player.team in {Team.KILLER.value, Team.NEUTRAL.value}:
                    is_win = True
                if player.role == Role.MINER.value and player.alive:
                    is_win = True
                if player.role == Role.HOJIAKA.value and player.alive:
                    is_win = True
                if player.role == Role.SORCERER.value:
                    is_win = bool(player.won)
                if arsonist_forced_win:
                    is_win = bool(player.won)
                if player.left_game:
                    is_win = False
                return is_win

            tournament_couple_winner_ids: set[int] = set()
            teamgame_winner_keys: set[str] = set()
            if is_teamgame:
                teamgame_winner_keys = {
                    player.transformed_to_team
                    for player in players
                    if player.transformed_to_team in {"blue", "red"} and base_winner(player)
                }
            if is_tournament:
                player_ids = {player.telegram_id for player in players}
                base_winner_ids = {
                    player.telegram_id
                    for player in players
                    if base_winner(player)
                }
                active_couples = (
                    await session.execute(
                        select(CoupleRelationship).where(
                            CoupleRelationship.chat_id == game.chat_id,
                            CoupleRelationship.active.is_(True),
                        )
                    )
                ).scalars().all()
                for couple in active_couples:
                    first_id = couple.user_one_telegram_id
                    second_id = couple.user_two_telegram_id
                    if first_id not in player_ids or second_id not in player_ids:
                        continue
                    if first_id in base_winner_ids or second_id in base_winner_ids:
                        tournament_couple_winner_ids.update({first_id, second_id})

            is_2x_active = await self.is_2x_event_active()

            for p in players:
                # O'yin davomida o'lganlar yakunda mag'lub hisoblanadi.
                # Faqat Suidsid kabi alohida shart bilan yutgan rollar p.won orqali g'olib bo'lib qoladi.
                is_winner = base_winner(p)
                if (
                    is_tournament
                    and p.telegram_id in tournament_couple_winner_ids
                    and not p.left_game
                ):
                    is_winner = True
                if (
                    is_teamgame
                    and p.transformed_to_team in teamgame_winner_keys
                    and not p.left_game
                ):
                    is_winner = True
                p.won = is_winner
                bonus_multiplier = 2 if p.telegram_id in news_bonus_ids else 1
                if is_2x_active:
                    bonus_multiplier *= 2
                reward_dollar = (
                    self.settings.winner_reward_dollar
                    if is_winner
                    else self.settings.loser_reward_dollar
                ) * bonus_multiplier
                reward_diamond = (
                    self.settings.winner_reward_diamond
                    if is_winner
                    else self.settings.loser_reward_diamond
                ) * bonus_multiplier
                reward_by_user[p.telegram_id] = (
                    reward_dollar,
                    reward_diamond,
                    p.telegram_id in news_bonus_ids,
                )
                user = users.get(p.telegram_id)
                if user:
                    user.total_games += 1
                    bonus_note = " (kanal 2x bonus)" if bonus_multiplier == 2 else ""
                    if is_winner:
                        user.wins += 1
                        user.dollar += reward_dollar
                        user.diamonds += reward_diamond
                        self._record_dollar_transaction(
                            session,
                            user,
                            reward_dollar,
                            "game_winner_reward",
                            note=f"O'yin #{game.id}: g'olib mukofoti{bonus_note}",
                            chat_id=game.chat_id,
                        )
                        self._record_diamond_transaction(
                            session,
                            user,
                            reward_diamond,
                            "game_winner_reward",
                            note=f"O'yin #{game.id}: g'olib mukofoti{bonus_note}",
                            chat_id=game.chat_id,
                        )
                    else:
                        user.dollar += reward_dollar
                        user.diamonds += reward_diamond
                        self._record_dollar_transaction(
                            session,
                            user,
                            reward_dollar,
                            "game_participation_reward",
                            note=f"O'yin #{game.id}: ishtirok mukofoti{bonus_note}",
                            chat_id=game.chat_id,
                        )
                        self._record_diamond_transaction(
                            session,
                            user,
                            reward_diamond,
                            "game_participation_reward",
                            note=f"O'yin #{game.id}: ishtirok mukofoti{bonus_note}",
                            chat_id=game.chat_id,
                        )
                (winners if is_winner else losers).append(p)

            self._add_game_log(
                session,
                game,
                "game_finished",
                winner_team=winner_team.value,
                winners=[p.telegram_id for p in winners],
                losers=[p.telegram_id for p in losers],
                news_bonus_ids=sorted(news_bonus_ids),
                players_count=len(players),
            )
            await session.commit()

            # Award Clan Game XP & Stats
            try:
                clan_results = [(p.telegram_id, bool(p.won)) for p in players]
                await self.clan_service.award_clan_game_xp(game_id, clan_results)
            except Exception:
                logger.exception("Failed to award clan game XP for game_id=%s", game_id)

            chat_id = game.chat_id
            if game.ended_at and game.started_at:
                ended_at = self._ensure_utc(game.ended_at)
                started_at = self._ensure_utc(game.started_at)
                duration_seconds = max(0, int((ended_at - started_at).total_seconds()))
            else:
                duration_seconds = 0

        self._cleanup_jobs(game_id)
        self._invalidate_game_cache(chat_id)

        def result_player_line(idx: int, player: GamePlayer) -> str:
            team_emoji = self._tournament_team_emoji(player.transformed_to_team) if (is_tournament or is_teamgame) else ""
            name = self._tg_mention(player.telegram_id, player.display_name)
            if team_emoji:
                name = f"{team_emoji} {name}"
            return f"{idx}. {name} - {role_label(player.role)}"

        winner_lines = [
            result_player_line(idx, p)
            for idx, p in enumerate(winners, 1)
        ]
        loser_start = len(winner_lines) + 1
        loser_lines = [
            result_player_line(idx, p)
            for idx, p in enumerate(losers, loser_start)
        ]
        winners_block = "\n".join(winner_lines) if winner_lines else "-"
        losers_block = "\n".join(loser_lines) if loser_lines else "-"

        news_channel = self._news_bonus_channel_id()
        bonus_hint = f"\n\n📰 <i>{news_channel} kanaliga obuna bo'ling va 2x mukofot oling!</i>"

        text = (
            "<b>O'yin tugadi!</b>\n\n"
            "G'oliblar:\n"
            f"{winners_block}\n\n"
            "Mag'lublar:\n"
            f"{losers_block}\n\n"
            f"O'yin: {self._format_duration(duration_seconds)} davom etdi"
            f"{bonus_hint}"
        )
        await bot.send_message(chat_id, text)

        async with self.session_factory() as session:
            users = {
                u.telegram_id: u
                for u in (
                    await session.execute(select(User).where(User.telegram_id.in_([p.telegram_id for p in players])))
                ).scalars().all()
            }

        player_ids = [p.telegram_id for p in players]
        news_url_task = self.get_news_channel_url()
        raw_news_url, *hero_results = await asyncio.gather(
            news_url_task, *(self.user_has_hero(pid) for pid in player_ids),
            return_exceptions=True,
        )
        news_url = raw_news_url if isinstance(raw_news_url, str) else self.settings.news_channel_url
        hero_map = {
            pid: res if isinstance(res, bool) else False
            for pid, res in zip(player_ids, hero_results)
        }


        for p in players:
            user = users.get(p.telegram_id)
            if user is None:
                continue
            result_title = "you_win" if p.won else "you_lose"
            reward_dollar, reward_diamond, used_news_bonus = reward_by_user.get(
                p.telegram_id,
                (
                    self.settings.winner_reward_dollar if p.won else self.settings.loser_reward_dollar,
                    self.settings.winner_reward_diamond if p.won else self.settings.loser_reward_diamond,
                    False,
                ),
            )
            bonus_text = "\n📰 Kanal obunasi: <b>2x mukofot berildi!</b>" if used_news_bonus else ""
            body = (
                f"{t(user.language, result_title, dollar=reward_dollar, diamond=reward_diamond)}{bonus_text}\n\n"
                f"{self.format_user_dashboard(user)}"
            )
            try:
                await bot.send_message(
                    p.telegram_id,
                    body,
                    reply_markup=profile_dashboard_keyboard(
                        self.settings,
                        user=user,
                        is_admin=bool(await self.get_sub_admin_role(p.telegram_id)),
                        news_url=news_url,
                        has_hero=hero_map.get(p.telegram_id, False),
                    ),
                )
            except TelegramForbiddenError:
                pass


    @staticmethod
    def _format_duration(seconds: int) -> str:
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} soat {minutes} daqiqa {sec} soniya"
        if minutes:
            return f"{minutes} daqiqa {sec} soniya"
        return f"{sec} soniya"


