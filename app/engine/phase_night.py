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

from app.engine.core import _get_outbound_sem
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

class NightPhaseMixin:
    def _format_alive_players(
        self,
        players: list[GamePlayer],
        tournament: bool = False,
    ) -> str:
        if not players:
            return "-"
        return "\n".join(
            f"{idx}. {self._tournament_team_emoji(player.transformed_to_team)} {self._tg_mention(player.telegram_id, player.display_name)}"
            if tournament and self._tournament_team_emoji(player.transformed_to_team)
            else f"{idx}. {self._tg_mention(player.telegram_id, player.display_name)}"
            for idx, player in enumerate(players, 1)
        )


    @staticmethod
    def _format_role_group(title: str, count: int, players: list[GamePlayer]) -> str:
        if count == 0:
            return ""
        role_counter = Counter(player.role for player in players)
        role_lines = []
        for role_value, role_count in role_counter.items():
            suffix = f" - {role_count}" if role_count > 1 else ""
            role_lines.append(f"{role_label(role_value)}{suffix}")
        return f"{title} - <b>{count}</b>\n{', '.join(role_lines)}"


    @staticmethod
    def _is_zombie_game(game: Optional[Game]) -> bool:
        return bool(game and (game.role_preset or "").lower() == "zombie")


    @staticmethod
    def _zombie_roles_for_player_count(player_count: int) -> list[Role]:
        roles = [Role.BOSS_ZOMBIE] + [Role.HUMAN] * max(0, player_count - 1)
        thresholds: list[tuple[int, Role]] = [
            (5, Role.ZOMBIE_RESCUER),
            (6, Role.VIROLOGIST),
            (8, Role.QUARANTINE_OFFICER),
            (10, Role.IMMUNE),
            (12, Role.VACCINATOR),
            (14, Role.MUTANT_ZOMBIE),
            (16, Role.INFECTOR),
            (18, Role.ZOMBIE_RESCUER),
            (20, Role.VIROLOGIST),
            (22, Role.IMMUNE),
            (24, Role.QUARANTINE_OFFICER),
            (26, Role.VACCINATOR),
            (28, Role.MUTANT_ZOMBIE),
            (32, Role.INFECTOR),
        ]
        replace_index = 1
        for threshold, role in thresholds:
            if player_count < threshold or replace_index >= len(roles):
                continue
            roles[replace_index] = role
            replace_index += 1
        return roles[:player_count]


    def _format_death_line(self, player: GamePlayer, cause: Optional[str] = None) -> str:
        name = self._tg_mention(player.telegram_id, player.display_name)
        base = f"Tunda {role_label(player.role)} {name}"
        if cause == "mafia":
            return f"{base} Mafiya tomonidan vaxshiylarcha o'ldirildi..."
        if cause == "killer":
            return f"{base} Qotil tomonidan vaxshiylarcha o'ldirildi..."
        if cause == "commissar":
            return f"{base} Komissar Katani o'qidan halok bo'ldi..."
        if cause == "sorcerer":
            return f"{base} Afsungar qasosi bilan o'ldirildi..."
        if cause == "mashka":
            return f"{base} Mashka hujumi oqibatida halok bo'ldi..."
        if cause == "miner":
            return f"{base} o'lim koniga qulab tushdi..."
        if cause == "arsonist":
            return f"{base} G'azabkor alangasida kuyib ketdi..."
        if cause == "joker":
            return f"{base} Joker karta o'yinida halok bo'ldi..."
        return f"{base} vaxshiylarcha o'ldirildi..."


    def _death_story_line(
        self,
        player: GamePlayer,
        cause: Optional[str] = None,
        visitor_label: Optional[str] = None,
    ) -> str:
        name = self._tg_mention(player.telegram_id, player.display_name)
        role = role_label(player.role)
        if visitor_label:
            visitor = visitor_label
        elif cause == "mafia":
            visitor = "🤵🏻 Don yoki Mafiya"
        elif cause == "killer":
            visitor = "🔪 Qotil"
        elif cause == "commissar":
            visitor = "🕵🏼 Komissar Katani"
        elif cause == "sorcerer":
            visitor = "🧙‍ Sehrgar qasosi"
        elif cause == "mashka":
            visitor = "🧤 Mashka"
        elif cause == "miner":
            visitor = "👷 o'lim koni"
        elif cause == "arsonist":
            visitor = f"{_ce('🧟', ZOMBIE_EMOJI_ID)} G'azabkor alangasi"
        elif cause == "joker":
            visitor = "🃏 Joker"
        elif cause == "inactive":
            visitor = "😴 uyqu"
        elif cause == "couple":
            visitor = "💔 Para qismati"
        else:
            visitor = "noma'lum mehmon"
        if cause == "inactive":
            return (
                f"O'limidan oldin kimdir {name} qichqirganini eshitdi:\n"
                "Men o'yin payti boshqa uxlamayma-a-a-a-n\n"
                f"U edi {role}"
            )
        if cause == "couple":
            partner_info = f" ({visitor_label})" if visitor_label else ""
            return (
                f"💔 <b>Turnir fojiasi!</b> {name} o'z sevgilisi{partner_info}ning fojiali o'limiga bardosh bera olmadi "
                f"va qayg'udan o'yinni tark etdi (halok bo'ldi)!\n"
                f"U edi <b>{role}</b>."
            )
        return f"Tunda {role} {name}...\nvaxshiylarcha o'ldirildi. Aytishlaricha unikiga {visitor} kelgan."


    @staticmethod
    def _death_visitor_label(cause: Optional[str] = None, visitor_label: Optional[str] = None) -> str:
        if visitor_label:
            return visitor_label
        if cause == "mafia":
            return "🤵🏻 Don yoki Mafiya"
        if cause == "killer":
            return "🔪 Qotil"
        if cause == "commissar":
            return "🕵🏼 Komissar Katani"
        if cause == "sorcerer":
            return "🧙‍ Sehrgar qasosi"
        if cause == "mashka":
            return "🧤 Mashka"
        if cause == "miner":
            return "👷 o'lim koni"
        if cause == "arsonist":
            return f"{_ce('🧟', ZOMBIE_EMOJI_ID)} G'azabkor alangasi"
        if cause == "joker":
            return "🃏 Joker"
        if cause == "couple":
            return "💞 Para qismati"
        return "noma'lum mehmon"


    def _build_alive_status_text(
        self,
        alive_players: list[GamePlayer],
        game: Optional[Game] = None,
        tournament: bool = False,
    ) -> str:
        if self._is_zombie_game(game):
            zombie_players = [player for player in alive_players if player.team == Team.ZOMBIE.value]
            human_players = [player for player in alive_players if player.team != Team.ZOMBIE.value]
            groups_text = "\n\n".join(
                block
                for block in [
                    f"🧟 <b>Zombielar</b> - <b>{len(zombie_players)}</b>" if zombie_players else "",
                    self._format_role_group("🧍 <b>Insonlar</b>", len(human_players), human_players),
                ]
                if block
            )
            return (
                "<b>Tirik o'yinchilar:</b>\n"
                f"{self._format_alive_players(alive_players, tournament=tournament)}\n\n"
                f"{groups_text}\n\n"
                f"<b>Jami:</b> {len(alive_players)}"
            )

        city_players = [player for player in alive_players if player.team == Team.CITY.value]
        mafia_players = [player for player in alive_players if player.team == Team.MAFIA.value]
        singleton_players = [
            player
            for player in alive_players
            if player.team in {Team.KILLER.value, Team.NEUTRAL.value}
        ]

        group_blocks = [
            self._format_role_group("🤵🏻 <b>Mafiya</b>", len(mafia_players), mafia_players),
            self._format_role_group("🏘 <b>Tinch aholilar</b>", len(city_players), city_players),
            self._format_role_group("👨🏼 <b>Singleton</b>", len(singleton_players), singleton_players),
        ]
        groups_text = "\n\n".join(block for block in group_blocks if block)
        result = (
            "<b>Tirik o'yinchilar:</b>\n"
            f"{self._format_alive_players(alive_players, tournament=tournament)}\n\n"
            f"{groups_text}"
        )
        result += f"\n\n<b>Jami:</b> {len(alive_players)}"
        return result


    @staticmethod
    def _build_day_intro_text(day_number: int) -> str:
        return (
            "Xayrli tong🌝 \n"
            f"🌄<b>Kun: {day_number}</b>\n"
            "Shamollar tundagi mish-mishlarni butun shaharga yetkazmoqda..\n\n"
            "Endi kechaning natijalarini muhokama qilish, sabablari va oqibatlarini tushunish vaqti keldi ..."
        )


    def _build_night_story_messages(
        self,
        dead_players: list[GamePlayer],
        transformed: list[str],
        night_activity_lines: list[str],
        night_event_lines: list[str],
        death_causes: Optional[dict[int, str]] = None,
        death_visitors: Optional[dict[int, str]] = None,
    ) -> list[str]:
        death_causes = death_causes or {}
        death_visitors = death_visitors or {}
        messages: list[str] = []

        def add_once(line: str) -> None:
            clean = line.strip()
            if clean and clean not in messages:
                messages.append(clean)

        for line in night_activity_lines:
            add_once(line)
        if dead_players:
            # Afsungar tunda o'ldirilgan va qasos olgan holatda:
            # avval afsungarning o'limi, keyin qasos qurboni ko'rsatiladi.
            ordered_dead_players = sorted(
                dead_players,
                key=lambda p: (
                    0 if Role(p.role) == Role.SORCERER and death_causes.get(p.telegram_id) != "sorcerer"
                    else 1 if death_causes.get(p.telegram_id) == "sorcerer"
                    else 2
                ),
            )
            death_lines = [
                self._death_story_line(
                    player,
                    death_causes.get(player.telegram_id),
                    death_visitors.get(player.telegram_id),
                )
                for player in ordered_dead_players
            ]
            add_once("\n\n".join(death_lines))
        else:
            add_once("Ishonish qiyin, lekin bu tunda hech kim o'lmadi...")

        for line in transformed:
            add_once(f"🔁 {line}")
        return messages


    @staticmethod
    def _private_role_text(role: Role) -> str:
        meta = ROLE_META[role]
        return f"Siz - {meta.emoji} <b>{meta.title_uz}</b>siz!\n{meta.short_desc_uz}"


    def _zombie_team_private_text(self, player: GamePlayer, alive_players: list[GamePlayer]) -> str:
        if player.team != Team.ZOMBIE.value:
            return ""
        zombies = [
            zombie
            for zombie in alive_players
            if zombie.alive and zombie.team == Team.ZOMBIE.value and zombie.role is not None
        ]
        if not zombies:
            return ""
        lines = ["🧟 <b>Zombi safdoshlari</b>"]
        for index, zombie in enumerate(zombies, 1):
            label = role_label(zombie.role)
            lines.append(f"{index}. {self._tg_mention(zombie.telegram_id, zombie.display_name)} — <b>{label}</b>")
        return "\n".join(lines)


    def _commissar_check_result_text(self, target: GamePlayer, seen_role: Role) -> str:
        return f"{self._tg_mention(target.telegram_id, target.display_name)} - {role_label(seen_role)}"


    @staticmethod
    def _is_day_blocked(player: GamePlayer, game: Game) -> bool:
        return bool(player.blocked_until_day and player.blocked_until_day >= game.day_number)


    @staticmethod
    def _night_activity_line(role: Role, action_key: Optional[str]) -> Optional[str]:
        if role == Role.BOSS_ZOMBIE:
            return "🦠 Tunda virus soyasi yangi qurbon izlab yurdi..."
        if role == Role.INFECTOR:
            return "🦠 Tunda virus izlari jim yoyildi..."
        if role == Role.MUTANT_ZOMBIE:
            return "🧟 Zombi tarafi soyada harakat qildi..."
        if role == Role.ZOMBIE_RESCUER:
            return "🩺 Qutqaruvchi tun bo'yi virusga qarshi kurashdi..."
        if role == Role.VIROLOGIST:
            return "🔬 Virusolog namunalarni tekshirishga ketdi..."
        if role == Role.QUARANTINE_OFFICER:
            return "🛡 Karantinchi kimnidir izolyatsiyaga oldi..."
        if role == Role.VACCINATOR:
            return "💉 Vaktsinator so'nggi imkoniyatini tayyorladi..."
        if role == Role.DOCTOR:
            return "👨🏼‍⚕️️Doktor tungi navbatchilikga ketdi..."
        if role == Role.GUARD:
            return "🛡 Qo'riqchi tun bo'yi bir odamni himoya qilishga ketdi..."
        if role == Role.WATCHER:
            return f"{_ce('🔍', SEARCH_EMOJI_ID)} Kuzatuvchi qorong'ida izlarni sanadi..."
        if role == Role.MISTRESS:
            return f"{_ce('💃', DANCER_EMOJI_ID)} Kezuvchining qandaydir mehmoni bor ekan..."
        if role == Role.DON:
            return "🤵🏻 Don navbatdagi o'ljasini tanladi..."
        if role == Role.MAFIA:
            return "🤵🏼 Mafiya bugungi o'ljasini tanladi..."
        if role == Role.SPY:
            return "🕴 Josus qorong'ida iz qoldirmay harakat qildi..."
        if role == Role.JOURNALIST:
            return "👩🏼‍💻 Jurnalist intervyu olish uchun ketti..."
        if role == Role.HIRED_KILLER:
            return "🥷 Yollanma qotil o'ljasini tanladi..."
        if role == Role.COMMISSAR:
            if action_key == "shoot":
                return f"{_ce('🔫', GUN_EMOJI_ID)} Komissar katani katani pistoletini o'qladi..."
            return "🕵🏼 Komissar katani katani yovuzlarni qidirishga ketdi..."
        if role == Role.LAWYER:
            return "👨🏼‍💼 Advokat Mafiani ximoya qilish uchun qidiryapti..."
        if role == Role.KILLER:
            return "🔪 Qotil navbatdagi qurbonini tanladi..."
        if role == Role.BUM:
            return f"{_ce('🍾', BOTTLE_EMOJI_ID)} Daydi kimnikigadir ichkilik butilka olish uchun ketdi..."
        if role == Role.CROOK:
            return "🤹🏻 Aferist o'ljasini tanladi."
        if role == Role.MINER:
            if action_key == "mine_protect":
                return "👷 Konchi o'zini himoyalashga qaror qildi..."
            return "👷 Konchi konlardan biriga yo'l oldi..."
        if role == Role.PRANKSTER:
            return "😂 Hazilkash kimnidir chalg'itish uchun yo'lga tushdi..."
        if role == Role.JOKER:
            return "🃏 Joker karta o'yini uchun nishon tanladi..."
        if role == Role.HOJIAKA:
            return "🕌 Hojiaka ehson ulashish uchun yo'lga tushdi..."
        if role == Role.MASHKA:
            return "🧤 Mashka kimnidir hamyonini nishonga oldi..."
        if role == Role.ARSONIST:
            return f"{_ce('🧟', ZOMBIE_EMOJI_ID)} G'azabkor o'zining navbatdagi nishonini belgiladi..."
        if role == Role.SNITCH:
            return None
        return None


    @staticmethod
    def _prank_message_for_role(role: Role) -> str:
        messages = {
            Role.DON: "😂 Bugun kimnidir yo'q qilishga buyruq bermoqchi edingiz, lekin Hazilkash sizga qurol o'rniga yaltiroq qoshiq ushlatib ketdi. Buyruq bekor bo'ldi.",
            Role.MAFIA: "😂 Bugun qorong'ida ish bitirmoqchi edingiz, lekin Hazilkash niqobingizni bayram shapkasi bilan almashtirib ketdi. Yurishingiz bekor bo'ldi.",
            Role.SPY: "😂 Bugun razvedkaga chiqmoqchi edingiz, lekin Hazilkash maxfiy daftaringiz o'rniga bolalar rangli kitobini berib ketdi.",
            Role.HIRED_KILLER: "😂 Bugun yashirin ovga chiqmoqchi edingiz, lekin Hazilkash qurolingizni o'yinchoq qilichga almashtirib ketdi.",
            Role.LAWYER: "😂 Bugun Mafiyani himoya qilmoqchi edingiz, lekin Hazilkash papkangizga hujjat o'rniga bo'sh qog'oz solib ketdi.",
            Role.COMMISSAR: "😂 Bugun kimnidir tekshirmoqchi edingiz, lekin Hazilkash lupangizni banan bilan almashtirib ketdi. Tekshiruv bekor bo'ldi.",
            Role.SERGEANT: "😂 Bugun Komissarga yordam bermoqchi edingiz, lekin Hazilkash ratsiyangizga faqat kulgi ovozlarini yozib ketdi.",
            Role.DOCTOR: "😂 Bugun kimnidir davolamoqchi edingiz, lekin Hazilkash dorilarni shakar bilan almashtirib ketdi. Davolash bekor bo'ldi.",
            Role.GUARD: "😂 Bugun kimnidir qo'riqlamoqchi edingiz, lekin Hazilkash qalqoningizni kartondan yasab qo'yibdi.",
            Role.MISTRESS: "😂 Bugun kimnidir uxlatmoqchi edingiz, lekin Hazilkash ichimligingizni oddiy mors bilan almashtirib qo'yibdi.",
            Role.JOURNALIST: "😂 Bugun intervyu olmoqchi edingiz, lekin Hazilkash mikrofoningizni sabzi bilan almashtirib ketdi.",
            Role.HOJIAKA: "😂 Bugun ehson tarqatmoqchi edingiz, lekin Hazilkash sovg'a qutingizga paypoq solib ketibdi.",
            Role.MASHKA: "😂 Bugun kimningdir hamyoniga ko'z olaytirgandingiz, lekin Hazilkash sizga cho'ntak o'rniga tikilgan yostiq ko'rsatib ketdi.",
            Role.KILLER: "😂 Bugun pichog'ingiz bilan kimnidir ovlamoqchi edingiz, lekin Hazilkash sizga qoshiq ushlatib ketdi.",
            Role.SORCERER: "😂 Bugun afsunlaringizni ishga solmoqchi edingiz, lekin Hazilkash sehrli kitobingizga osh retsepti yozib ketdi.",
            Role.MAQ: "😂 Bugun sehr bilan javob bermoqchi edingiz, lekin Hazilkash tayoqchangizni qalamga almashtirib ketdi.",
            Role.MINER: "😂 Bugun konga bormoqchi edingiz, lekin Hazilkash belkuragingizni o'yinchoq qilib qo'yibdi.",
            Role.JOKER: "😂 Bugun karta o'yinini boshlamoqchi edingiz, lekin Hazilkash kartalaringizni UNO bilan almashtirib ketdi.",
            Role.ARSONIST: "😂 Bugun alangani yoqmoqchi edingiz, lekin Hazilkash gugurtingizni namlab qo'yibdi.",
            Role.WOLF: "😂 Bugun ovga chiqmoqchi edingiz, lekin Hazilkash uvillashingizni mushuk miyoviga almashtirib ketdi.",
            Role.BUM: "😂 Bugun kimnidir kuzatmoqchi edingiz, lekin Hazilkash butilkangizga kompot quyib ketibdi.",
            Role.CROOK: "😂 Bugun kimnidir chalg'itmoqchi edingiz, lekin Hazilkash sizning o'zingizni chalg'itib ketdi.",
            Role.LUCKY: "😂 Bugun omadingizga ishonib yotgandingiz, lekin Hazilkash omad tumoringizni muzlatkich magnitiga almashtirib ketdi.",
            Role.JESTER: "😂 Bugun sahnani o'zingizniki qilmoqchi edingiz, lekin Hazilkash sizdan oldin kuldirib ketdi.",
            Role.CITIZEN: "😂 Siz bugun tinchgina uxlamoqchi edingiz, lekin Hazilkash yostig'ingiz ostiga chiyillaydigan o'yinchoq qo'yib ketdi.",
            Role.WATCHER: "😂 Bugun kimnidir poylamoqchi edingiz, lekin Hazilkash durbiningizga rangli shisha o'rnatib ketdi.",
            Role.SNITCH: "😂 Bugun kimningdir sirini sotmoqchi edingiz, lekin Hazilkash yozuvlaringizni teskari qilib qo'yibdi.",
            Role.MAYOR: "😂 Bugun obro'yingizga suyanmoqchi edingiz, lekin Hazilkash nutqingizni latifalar bilan almashtirib ketdi.",
            Role.PRANKSTER: "😂 Bugun o'zingiz hazil qilmoqchi edingiz, lekin Hazilkash sizni ham hazilga aylantirib ketdi.",
        }
        return messages.get(role, "😂 Hazilkash bugungi rejangizni kulgili prankka aylantirib yubordi.")


    def _last_words_line(self, player: GamePlayer, words: str) -> str:
        safe_words = escape(words.strip()[:500])
        name = self._tg_mention(player.telegram_id, player.display_name)
        return f"O'limidan oldin {name} qichqirganini eshitdi:\n{safe_words}"


    def _apply_role_successions(self, players: list[GamePlayer], dead_ids: set[int]) -> list[tuple[str, int, Role]]:
        successions: list[tuple[str, int, Role]] = []
        dead_players = [player for player in players if player.telegram_id in dead_ids]

        if any(Role(player.role) == Role.DON for player in dead_players):
            heir = next(
                (
                    player
                    for player in players
                    if player.telegram_id not in dead_ids
                    and player.alive
                    and Role(player.role) == Role.MAFIA
                ),
                None,
            )
            if heir:
                heir.role = Role.DON.value
                heir.team = Team.MAFIA.value
                successions.append((
                    "🤵🏻 Don mafiyaga meros qoldirdi.",
                    heir.telegram_id,
                    Role.DON,
                ))

        if any(Role(player.role) == Role.COMMISSAR for player in dead_players):
            heir = next(
                (
                    player
                    for player in players
                    if player.telegram_id not in dead_ids and Role(player.role) == Role.SERGEANT
                    and player.alive
                ),
                None,
            )
            if heir:
                heir.role = Role.COMMISSAR.value
                heir.team = Team.CITY.value
                successions.append((
                    "👮🏻‍♂ Serjant Komissar Katani vazifasini davom ettiradi.",
                    heir.telegram_id,
                    Role.COMMISSAR,
                ))

        return successions


    async def assign_roles_and_notify(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            players = (
                await session.execute(select(GamePlayer).where(GamePlayer.game_id == game_id).order_by(GamePlayer.id.asc()))
            ).scalars().all()
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
            group = (await session.execute(select(Group).where(Group.chat_id == game.chat_id))).scalar_one_or_none()
            role_preset = game.role_preset or (group.role_preset if group else "black23")
            users = {
                user.telegram_id: user
                for user in (
                    await session.execute(select(User).where(User.telegram_id.in_([p.telegram_id for p in players])))
                ).scalars().all()
            }
            if role_preset == "zombie":
                zombie_roles = self._zombie_roles_for_player_count(len(players))
                random.shuffle(zombie_roles)
                if Role.BOSS_ZOMBIE not in zombie_roles:
                    zombie_roles[0] = Role.BOSS_ZOMBIE
                for player, role in zip(players, zombie_roles):
                    player.role = role.value
                    player.team = role_team(role).value
                    player.transformed_to_role = None
                    player.transformed_to_team = None
                    self._add_game_log(
                        session,
                        game,
                        "zombie_role_assigned",
                        actor=player,
                        role=player.role,
                        team=player.team,
                    )
                await session.commit()
                lang = await self.get_group_language(game.chat_id)
                chat_id = game.chat_id

                for player in players:
                    role = Role(player.role)
                    text = self._private_role_text(role)
                    zombie_team_text = self._zombie_team_private_text(player, players)
                    if zombie_team_text:
                        text = f"{text}\n\n{zombie_team_text}"
                    sent = await self._safe_send_message(
                        bot,
                        player.telegram_id,
                        text,
                        reply_markup=await self.group_return_keyboard(bot, chat_id),
                    )
                    if sent is None:
                        await self._safe_send_message(bot, chat_id, f"{player.display_name}: {t(lang, 'need_start_for_role')}")
                return

            disabled_roles: set[Role] = set()
            for user in users.values():
                if not user.next_game_disabled_role:
                    continue
                try:
                    disabled_roles.add(Role(user.next_game_disabled_role))
                except ValueError:
                    user.next_game_disabled_role = None
            gsm = GroupSettingsManager(self.session_factory)
            group_disabled_role_keys = await gsm.get_disabled_roles(game.chat_id)
            for rk in group_disabled_role_keys:
                try:
                    disabled_roles.add(Role(rk))
                except ValueError:
                    pass
            roles = build_role_set(len(players), role_preset, disabled_roles=disabled_roles)
            logger.info(
                "role_generation mode=%s player_count=%s selected_roles=%s disabled_roles=%s",
                normalize_game_mode(role_preset),
                len(players),
                [role.value for role in roles],
                [role.value for role in sorted(disabled_roles, key=lambda r: r.value)],
            )
            assigned = dict(zip([p.telegram_id for p in players], roles))
            owned_role_keys = [self._owned_roles_key(p.telegram_id) for p in players]
            cursor_keys = [self._owned_roles_cursor_key(p.telegram_id) for p in players]
            owned_settings = (
                await session.execute(
                    select(BotSetting).where(BotSetting.key.in_(owned_role_keys + cursor_keys))
                )
            ).scalars().all()
            owned_by_key = {row.key: row for row in owned_settings}

            for player in players:
                user = users.get(player.telegram_id)
                if user is None:
                    continue
                desired: Optional[Role] = None
                selected_manually = bool(user.next_game_role)
                cursor_idx_to_consume: Optional[int] = None

                # Load owned roles upfront — needed for both manual and cursor paths
                owned_row = owned_by_key.get(self._owned_roles_key(player.telegram_id))
                cursor_row = owned_by_key.get(self._owned_roles_cursor_key(player.telegram_id))
                try:
                    raw_roles = json.loads(owned_row.value) if owned_row and owned_row.value else []
                except (TypeError, ValueError):
                    raw_roles = []
                owned_roles: list[Role] = []
                for value in raw_roles if isinstance(raw_roles, list) else []:
                    try:
                        owned_roles.append(Role(str(value)))
                    except ValueError:
                        continue

                if user.next_game_role:
                    try:
                        desired = Role(user.next_game_role)
                    except ValueError:
                        user.next_game_role = None
                        desired = None
                elif owned_roles:
                    cursor = 0
                    if cursor_row and cursor_row.value and cursor_row.value.lstrip("-").isdigit():
                        cursor = max(0, int(cursor_row.value))
                    idx = cursor % len(owned_roles)
                    desired = owned_roles[idx]
                    cursor_idx_to_consume = idx

                if desired is None:
                    continue
                if desired in disabled_roles or not self._role_player_count_ok(desired, role_preset, len(players)):
                    if selected_manually:
                        # Qo'lda tanlangan rol o'yinchilar soni yetmagani uchun ishlamasa, keyingi o'yinlar uchun saqlanadi.
                        pass
                    else:
                        # Avto rejimda bu tur rol mos bo'lmasa oddiy taqsimot qo'llanadi.
                        pass
                    continue
                if desired not in roles:
                    continue
                holder = next((p for p in players if assigned[p.telegram_id] == desired), None)
                if holder is not None and holder.telegram_id != player.telegram_id:
                    assigned[holder.telegram_id] = assigned[player.telegram_id]
                assigned[player.telegram_id] = desired

                # ── Consume the role from inventory ──
                if selected_manually:
                    user.next_game_role = None
                    # Also remove one copy from owned_roles (the role was purchased and now used)
                    if desired in owned_roles and owned_row is not None:
                        owned_roles.remove(desired)  # removes first occurrence
                        owned_row.value = json.dumps([r.value for r in owned_roles], ensure_ascii=True)
                elif cursor_idx_to_consume is not None and owned_row is not None:
                    # Cursor path: remove the used slot and reset cursor
                    owned_roles.pop(cursor_idx_to_consume)
                    owned_row.value = json.dumps([r.value for r in owned_roles], ensure_ascii=True)
                    if cursor_row is None:
                        cursor_row = BotSetting(key=self._owned_roles_cursor_key(player.telegram_id), value="0")
                        session.add(cursor_row)
                        owned_by_key[cursor_row.key] = cursor_row
                    else:
                        cursor_row.value = "0"

            for player, role in zip(players, roles):
                user = users.get(player.telegram_id)
                if user is not None:
                    user.next_game_disabled_role = None
                final_role = assigned[player.telegram_id]
                player.role = final_role.value
                player.team = role_team(final_role).value
                self._add_game_log(
                    session,
                    game,
                    "role_assigned",
                    actor=player,
                    role=final_role.value,
                    team=player.team,
                )
            await session.commit()

            lang = await self.get_group_language(game.chat_id)

        for player in players:
            role = Role(player.role)
            sent = await self._safe_send_message(
                bot,
                player.telegram_id,
                self._private_role_text(role),
                reply_markup=await self.group_return_keyboard(bot, game.chat_id),
            )
            if sent is None:
                await self._safe_send_message(bot, game.chat_id, f"{player.display_name}: {t(lang, 'need_start_for_role')}")

        # Send team messages for Mafia
        mafia_team = [player for player in players if player.team == Team.MAFIA.value]
        if mafia_team:
            mafia_lines = [
                f"{idx}. {role_label(player.role)} - {self._tg_mention(player.telegram_id, player.display_name)}"
                for idx, player in enumerate(mafia_team, 1)
            ]
            mafia_text = "<b>Mafia jamoasi:</b>\n" + "\n".join(mafia_lines)
            for player in mafia_team:
                await self._safe_send_message(
                    bot,
                    player.telegram_id,
                    mafia_text,
                    reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                )

        # Send team messages for Doctors
        doctors = [player for player in players if Role(player.role) == Role.DOCTOR]
        if doctors and len(doctors) > 1:
            doctor_lines = [
                f"{idx}. {self._tg_mention(player.telegram_id, player.display_name)}"
                for idx, player in enumerate(doctors, 1)
            ]
            doctor_text = "<b>👨🏼‍⚕️ Doktor jamoasi:</b>\n" + "\n".join(doctor_lines)
            for player in doctors:
                await self._safe_send_message(
                    bot,
                    player.telegram_id,
                    doctor_text,
                    reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                )

        # Send team messages for Commissar and Sergeant
        commissars = [player for player in players if Role(player.role) == Role.COMMISSAR]
        sergeants = [player for player in players if Role(player.role) == Role.SERGEANT]
        if commissars and sergeants:
            commissar_text = "<b>🕵🏼 Komissar Katani va Serjantlar:</b>\n"
            lines = [
                f"🕵🏼 {self._tg_mention(c.telegram_id, c.display_name)}" for c in commissars
            ] + [
                f"👮🏼 {self._tg_mention(s.telegram_id, s.display_name)}" for s in sergeants
            ]
            commissar_text += "\n".join(lines)
            
            for player in commissars + sergeants:
                await self._safe_send_message(
                    bot,
                    player.telegram_id,
                    commissar_text,
                    reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                )


    def _night_prompt_for_player(
        self,
        game_id: int,
        night_number: int,
        player: GamePlayer,
        alive_players: list[GamePlayer],
        miner_visits: Optional[dict[int, set[int]]] = None,
        arson_marks: Optional[dict[int, set[int]]] = None,
        dead_players: Optional[list[GamePlayer]] = None,
        fairy_revive_used: bool = False,
    ) -> Optional[tuple[str, object]]:
        role = Role(player.role)
        all_choices = [(p.telegram_id, p.display_name) for p in alive_players]
        targets = [(tid, name) for tid, name in all_choices if tid != player.telegram_id]
        mafia_targets = [
            (p.telegram_id, p.display_name)
            for p in alive_players
            if p.telegram_id != player.telegram_id and p.team != Team.MAFIA.value
        ]
        human_targets = [
            (p.telegram_id, p.display_name)
            for p in alive_players
            if p.telegram_id != player.telegram_id and p.team != Team.ZOMBIE.value
        ]
        zombie_targets = [
            (p.telegram_id, p.display_name)
            for p in alive_players
            if p.team == Team.ZOMBIE.value
        ]

        if role == Role.BOSS_ZOMBIE:
            if not human_targets:
                return None
            return "🧟‍♂️ Kimga virus yuqtiramiz?", target_keyboard("infect", game_id, player.telegram_id, human_targets)
        if role == Role.INFECTOR:
            if night_number % 2 != 0 or not human_targets:
                return None
            return "🦠 Kimga yashirin virus yuqtirasiz?", target_keyboard("infect", game_id, player.telegram_id, human_targets)
        if role == Role.MUTANT_ZOMBIE:
            if not zombie_targets:
                return None
            return "🧠 Kimni tekshiruvdan yashirasiz?", target_keyboard("zhide", game_id, player.telegram_id, zombie_targets)
        if role == Role.ZOMBIE_RESCUER:
            return "🩺 Kimni virusdan qutqarasiz?", target_keyboard("zsave", game_id, player.telegram_id, all_choices)
        if role == Role.VIROLOGIST:
            return "🔬 Kimni virusga tekshirasiz?", target_keyboard("zscan", game_id, player.telegram_id, targets)
        if role == Role.QUARANTINE_OFFICER:
            return "🛡 Kimni karantinga olasiz?", target_keyboard("zquarantine", game_id, player.telegram_id, all_choices)
        if role == Role.VACCINATOR and not player.self_heal_used:
            return "💉 Kimga vaktsina ishlatasiz?", target_keyboard("zvaccinate", game_id, player.telegram_id, targets)
        if role in {Role.MAFIA, Role.DON, Role.SPY, Role.HIRED_KILLER}:
            return "🌚 Kimni yo'q qilamiz?", target_keyboard("kill", game_id, player.telegram_id, mafia_targets)
        if role == Role.DOCTOR:
            return (
                "👨🏼‍⚕️️ Kimni davolaymiz?",
                target_keyboard("heal", game_id, player.telegram_id, all_choices),
            )
        if role == Role.GUARD:
            return "🛡 Kimni tunda himoya qilasiz?", target_keyboard("guard", game_id, player.telegram_id, all_choices)
        if role == Role.WATCHER:
            return "🔎 Kimni kuzatasiz? Unga kim kelganini bilasiz.", target_keyboard("watch", game_id, player.telegram_id, targets)
        if role == Role.COMMISSAR:
            return (
                "🕵🏼 Komissar katani",
                commissar_action_keyboard(
                    game_id=game_id,
                    actor_id=player.telegram_id,
                    can_shoot=night_number >= 2,
                ),
            )
        if role == Role.MISTRESS:
            return "💃 Kimni harakatdan to'xtatasiz?", target_keyboard("block", game_id, player.telegram_id, targets)
        if role == Role.LAWYER:
            return "👨‍💼 Kimni himoya qilasiz?", target_keyboard("defend", game_id, player.telegram_id, targets)
        if role == Role.KILLER:
            return "🔪 Kimni o'ldirasiz?", target_keyboard("killer", game_id, player.telegram_id, targets)
        if role == Role.BUM:
            return "🧙‍♂ Kimni kuzatasiz?", target_keyboard("visit", game_id, player.telegram_id, targets)
        if role == Role.JOURNALIST:
            return "👩🏼‍💻 Kimdan intervyu olasiz?", target_keyboard("watch", game_id, player.telegram_id, targets)
        if role == Role.CROOK:
            return "🤹🏻 Kimni chalg'itasiz?", target_keyboard("block", game_id, player.telegram_id, targets)
        if role == Role.PRANKSTER:
            return "😂 Kimni hazil bilan chalg'itasiz?", target_keyboard("prank", game_id, player.telegram_id, targets)
        if role == Role.JOKER:
            return "🃏 4 kartadan birini o'lim kartasi sifatida tanlang.", joker_death_card_keyboard(game_id, player.telegram_id)
        if role == Role.SNITCH:
            return "🤓 Kimni tekshirasiz?", target_keyboard("check", game_id, player.telegram_id, targets)
        if role == Role.HOJIAKA:
            return "🕌 Kimga ehson qilamiz?", target_keyboard("grant", game_id, player.telegram_id, targets)
        if role == Role.MASHKA:
            return "🧤 Kimdan o'g'irlaymiz?", target_keyboard("steal", game_id, player.telegram_id, targets)
        if role == Role.FAIRY:
            if fairy_revive_used:
                return None
            revival_targets = [
                (p.telegram_id, p.display_name)
                for p in (dead_players or [])
                if p.telegram_id != player.telegram_id
            ]
            if not revival_targets:
                return None
            return "👼 Qaysi o'yinchini qayta tiriltirasiz?", target_keyboard("revive", game_id, player.telegram_id, revival_targets)
        if role == Role.ARSONIST:
            marked_ids = arson_marks.get(player.telegram_id, set()) if arson_marks else set()
            marked_targets = [(tid, f"✅ {name}") for tid, name in targets if tid in marked_ids]
            unmarked_targets = [(tid, name) for tid, name in targets if tid not in marked_ids]
            visible_targets = marked_targets + unmarked_targets
            if len(marked_ids) >= 3:
                return (
                    "🧟 Siz 3 nishonni belgilab bo'ldingiz.\n"
                    "Tanlanganlar yuqorida ko'rsatilgan; endi o'zingizni tanlasangiz, belgilanganlar bilan birga portlaysiz.",
                    target_keyboard(
                        "arson",
                        game_id,
                        player.telegram_id,
                        [(player.telegram_id, "🔥 O'zimni tanlayman")] + visible_targets,
                    ),
                )
            if visible_targets:
                return (
                    f"🧟 {len(marked_ids)}/3 nishon belgilangan.\nTanlanganlar va mavjud nishonlar quyida ko'rsatilgan. Bugun kimni belgilaysiz?",
                    target_keyboard("arson", game_id, player.telegram_id, visible_targets),
                )
            return None
        if role == Role.MINER:
            visited = miner_visits.get(player.telegram_id, set()) if miner_visits else set()
            return "Qaysi konga borasiz?", miner_keyboard(game_id, player.telegram_id, visited)
        return None


    async def send_private_role_menu(self, bot: Bot, game_id: int, telegram_id: int) -> tuple[bool, str]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status not in {GameStatus.ACTIVE.value, GameStatus.COMPLETED.value}:
                return False, "Bu o'yin topilmadi yoki hali boshlanmagan."

            player = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == telegram_id,
                    )
                )
            ).scalar_one_or_none()
            if player is None or player.role is None:
                return False, "Siz bu o'yinda ro'yxatdan o'tmagansiz."

            alive = await self._alive_players(session, game_id)
            dead_players = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.alive.is_(False),
                    ).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            prompt = None
            if game.phase == GamePhase.NIGHT.value and player.alive:
                existing_action = (
                    await session.execute(
                        select(NightAction.id).where(
                            NightAction.game_id == game_id,
                            NightAction.night_number == game.night_number,
                            NightAction.actor_telegram_id == telegram_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_action is None:
                    arson_rows = (
                        await session.execute(
                            select(NightAction.target_telegram_id).where(
                                NightAction.game_id == game_id,
                                NightAction.actor_telegram_id == telegram_id,
                                NightAction.details == "arson",
                                NightAction.target_telegram_id.is_not(None),
                            )
                        )
                    ).scalars().all()
                    arson_marks = {telegram_id: {tid for tid in arson_rows if tid and tid != telegram_id}}
                    fairy_revive_used = (
                        await session.execute(
                            select(NightAction.id).where(
                                NightAction.game_id == game_id,
                                NightAction.actor_telegram_id == telegram_id,
                                NightAction.action_type == ActionType.REVIVE.value,
                            )
                        )
                    ).scalar_one_or_none() is not None if player.role == Role.FAIRY.value else False
                    prompt = self._night_prompt_for_player(
                        game_id,
                        game.night_number,
                        player,
                        alive,
                        arson_marks=arson_marks,
                        dead_players=dead_players,
                        fairy_revive_used=fairy_revive_used,
                    )
            is_night = game.phase == GamePhase.NIGHT.value
            is_alive = player.alive
            night_number = game.night_number

        if prompt:
            text, keyboard = prompt
            zombie_team_text = self._zombie_team_private_text(player, alive)
            if zombie_team_text:
                text = f"{zombie_team_text}\n\n{text}"
            prompt_message = await self._safe_send_message(bot, telegram_id, text, reply_markup=keyboard)
            if prompt_message is not None:
                await self._remember_night_prompt(
                    game_id=game_id,
                    night_number=night_number,
                    user_telegram_id=telegram_id,
                    message_id=prompt_message.message_id,
                )
        elif is_night and is_alive:
            zombie_team_text = self._zombie_team_private_text(player, alive)
            await self._safe_send_message(
                bot,
                telegram_id,
                (
                    f"{zombie_team_text}\n\n"
                    "🌚 Bu tun uchun faol tanlov mavjud emas yoki tanlovingiz allaqachon qabul qilingan."
                    if zombie_team_text
                    else "🌚 Bu tun uchun faol tanlov mavjud emas yoki tanlovingiz allaqachon qabul qilingan."
                ),
            )
        else:
            zombie_team_text = self._zombie_team_private_text(player, alive)
            await self._safe_send_message(
                bot,
                telegram_id,
                (
                    f"{zombie_team_text}\n\n🎭 Rolingiz o'yin boshida bir marta yuborilgan. Hozir faol tanlov bosqichi emas."
                    if zombie_team_text
                    else "🎭 Rolingiz o'yin boshida bir marta yuborilgan. Hozir faol tanlov bosqichi emas."
                ),
            )
        return True, "Bot private chatiga kerakli ma'lumot yuborildi."


    async def _send_phase_media(
        self,
        bot: Bot,
        chat_id: int,
        is_night: bool,
        lang: str,
        game_id: Optional[int] = None,
        caption_override: Optional[str] = None,
    ) -> None:
        caption = caption_override or (t(lang, "night_title") if is_night else t(lang, "day_title"))
        kb = go_role_private_keyboard(self.settings, game_id, "Bot-ga o'tish ↗") if game_id else go_private_keyboard(self.settings)
        file_id = self.settings.night_media_file_id if is_night else self.settings.day_media_file_id
        local_path_str = self.settings.night_media_local if is_night else self.settings.day_media_local

        if file_id:
            try:
                await bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption, reply_markup=kb)
                return
            except TelegramBadRequest:
                try:
                    await bot.send_video(
                        chat_id=chat_id,
                        video=file_id,
                        caption=caption,
                        reply_markup=kb,
                        supports_streaming=True,
                    )
                    return
                except TelegramBadRequest:
                    logger.warning("Media file_id invalid, fallback to local: %s", file_id)

        local_path = Path(local_path_str)
        if not local_path.is_absolute():
            local_path = BASE_DIR / local_path
        if not local_path.exists():
            logger.warning("Media file not found: %s", local_path)
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
            return

        try:
            if local_path.suffix.lower() == ".mp4":
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(str(local_path)),
                    caption=caption,
                    reply_markup=kb,
                    supports_streaming=True,
                )
            else:
                await bot.send_animation(
                    chat_id=chat_id,
                    animation=FSInputFile(str(local_path)),
                    caption=caption,
                    reply_markup=kb,
                )
        except TelegramBadRequest:
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)


    async def start_night(self, bot: Bot, game_id: int) -> None:
        winner = await self.check_winner(game_id)
        if winner:
            await self.finish_game(bot, game_id, winner)
            return

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return
            game.phase = GamePhase.NIGHT.value
            chat_id = game.chat_id
            lang = await self.get_group_language(chat_id)
            alive_players = await self._alive_players(session, game_id)
            is_tournament = await self._is_tournament_game_in_session(session, game_id)
            is_teamgame = await self._is_team_game_in_session(session, game_id)
            alive_status = self._build_alive_status_text(alive_players, game, tournament=(is_tournament or is_teamgame))
            self._add_game_log(
                session,
                game,
                "night_started",
                alive_count=len(alive_players),
            )
            await session.commit()

        night_timeout = await self.group_timeout(chat_id, "night_timeout")
        run_at = datetime.now(timezone.utc) + timedelta(seconds=night_timeout)
        scheduler.add_job(
            self.resolve_night,
            "date",
            run_date=run_at,
            args=[bot, game_id],
            id=f"night_end_{game_id}",
            replace_existing=True,
            misfire_grace_time=120,
        )
        try:
            await self._send_phase_media(
                bot,
                chat_id,
                is_night=True,
                lang=lang,
                game_id=game_id,
            )
        except Exception:
            logger.exception("Failed to send night phase media game_id=%s", game_id)
        await self._safe_send_message(bot, chat_id, alive_status)
        await self.send_night_prompts(bot, game_id)


    async def _alive_players(self, session: AsyncSession, game_id: int) -> list[GamePlayer]:
        return (
            await session.execute(
                select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.alive.is_(True)).order_by(GamePlayer.id.asc())
            )
        ).scalars().all()


    async def _announce_immediate_joker_result(
        self,
        bot: Bot,
        game: Game,
        target_player: GamePlayer,
        is_dead: bool,
    ) -> None:
        if is_dead:
            death_text = "\n".join(
                [
                    "🃏 Joker bugun hursand chunki karta o'yinida golib boldi.",
                    self._death_story_line(
                        target_player,
                        cause="joker",
                        visitor_label=role_label(Role.JOKER),
                    ),
                ]
            )
        else:
            death_text = "🃏 Joker bugun hafa chunki karta o'yinida golib bolmadi."
        await self._safe_send_message(bot, game.chat_id, death_text)


    async def _remember_night_prompt(
        self,
        game_id: int,
        night_number: int,
        user_telegram_id: int,
        message_id: int,
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                NightPrompt(
                    game_id=game_id,
                    night_number=night_number,
                    user_telegram_id=user_telegram_id,
                    message_id=message_id,
                )
            )
            await session.commit()


    async def _clear_night_prompt_buttons(self, bot: Bot, game_id: int, night_number: int) -> None:
        async with self.session_factory() as session:
            prompts = (
                await session.execute(
                    select(NightPrompt).where(
                        NightPrompt.game_id == game_id,
                        NightPrompt.night_number == night_number,
                        NightPrompt.cleared.is_(False),
                    )
                )
            ).scalars().all()

        for prompt in prompts:
            await self._safe_edit_message_reply_markup(
                bot,
                chat_id=prompt.user_telegram_id,
                message_id=prompt.message_id,
                reply_markup=None,
            )

        if prompts:
            async with self.session_factory() as session:
                prompt_ids = [prompt.id for prompt in prompts]
                rows = (
                    await session.execute(select(NightPrompt).where(NightPrompt.id.in_(prompt_ids)))
                ).scalars().all()
                for row in rows:
                    row.cleared = True
                await session.commit()


    async def send_night_prompts(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
            night = game.night_number
            alive = await self._alive_players(session, game_id)
            dead_players = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.alive.is_(False),
                    ).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            mine_rows = (
                await session.execute(
                    select(NightAction.actor_telegram_id, NightAction.target_telegram_id).where(
                        NightAction.game_id == game_id,
                        NightAction.action_type == ActionType.MINE.value,
                        NightAction.target_telegram_id.is_not(None),
                    )
                )
            ).all()
            miner_visits: dict[int, set[int]] = defaultdict(set)
            for actor_id, mine_number in mine_rows:
                if mine_number is not None:
                    miner_visits[actor_id].add(mine_number)
            arson_rows = (
                await session.execute(
                    select(NightAction.actor_telegram_id, NightAction.target_telegram_id).where(
                        NightAction.game_id == game_id,
                        NightAction.details == "arson",
                        NightAction.target_telegram_id.is_not(None),
                    )
                )
            ).all()
            arson_marks: dict[int, set[int]] = defaultdict(set)
            for actor_id, target_id in arson_rows:
                if target_id is not None and actor_id != target_id:
                    arson_marks[actor_id].add(target_id)
            # BUG FIX: fetch fairy_revive_used_ids INSIDE the session context;
            # the previous code accessed `session` after the `async with` block
            # had already closed it, which is a use-after-close error.
            fairy_revive_used_ids = {
                row.actor_telegram_id
                for row in (
                    await session.execute(
                        select(NightAction.actor_telegram_id).where(
                            NightAction.game_id == game_id,
                            NightAction.action_type == ActionType.REVIVE.value,
                        )
                    )
                ).all()
            }

        chat_id = await self._game_chat_id(game_id)

        # Build per-player prompt data while still holding all query results in memory.
        # Then dispatch all private messages concurrently so a single slow Telegram call
        # (e.g. user's phone offline) doesn't delay all other players.
        tasks = [
            self._send_one_night_prompt(
                bot,
                game_id,
                night,
                player,
                alive,
                miner_visits,
                arson_marks,
                dead_players,
                fairy_revive_used_ids,
                chat_id,
            )
            for player in alive
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for exc in results:
            if isinstance(exc, Exception):
                logger.exception(
                    "Unhandled exception in _send_one_night_prompt game_id=%s: %s", game_id, exc
                )


    async def _send_one_night_prompt(
        self,
        bot: Bot,
        game_id: int,
        night: int,
        player: "GamePlayer",
        alive: list["GamePlayer"],
        miner_visits: dict[int, set[int]],
        arson_marks: dict[int, set[int]],
        dead_players: list["GamePlayer"],
        fairy_revive_used_ids: set[int],
        chat_id: int,
    ) -> None:
        """Send the night-action prompt to a single player.

        Runs inside asyncio.gather, so failures are caught as return values
        (return_exceptions=True) rather than propagating to cancel siblings.
        """
        prompt = self._night_prompt_for_player(
            game_id,
            night,
            player,
            alive,
            miner_visits,
            arson_marks,
            dead_players=dead_players,
            fairy_revive_used=player.telegram_id in fairy_revive_used_ids,
        )
        if prompt is None:
            zombie_team_text = self._zombie_team_private_text(player, alive)
            if zombie_team_text:
                try:
                    async with _get_outbound_sem():
                        await bot.send_message(
                            player.telegram_id,
                            zombie_team_text,
                            reply_markup=await self.group_return_keyboard(bot, chat_id),
                        )
                except TelegramForbiddenError:
                    await self._safe_send_message(
                        bot, chat_id, f"{player.display_name}: /start orqali botga kiring."
                    )
                except Exception:
                    logger.exception(
                        "Failed to send zombie team list game_id=%s user_id=%s",
                        game_id, player.telegram_id,
                    )
            return
        text, keyboard = prompt
        zombie_team_text = self._zombie_team_private_text(player, alive)
        if zombie_team_text:
            text = f"{zombie_team_text}\n\n{text}"

        try:
            async with _get_outbound_sem():
                prompt_message = await bot.send_message(player.telegram_id, text, reply_markup=keyboard)
            await self._remember_night_prompt(
                game_id=game_id,
                night_number=night,
                user_telegram_id=player.telegram_id,
                message_id=prompt_message.message_id,
            )
        except TelegramForbiddenError:
            await self._safe_send_message(
                bot, chat_id, f"{player.display_name}: /start orqali botga kiring."
            )
        except Exception:
            logger.exception(
                "Failed to send night prompt game_id=%s user_id=%s",
                game_id, player.telegram_id,
            )



    async def _is_zombie_game_id(self, game_id: int) -> bool:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            return self._is_zombie_game(game)


    async def resolve_zombie_night(self, bot: Bot, game_id: int) -> None:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if (
                game is None
                or game.status != GameStatus.ACTIVE.value
                or game.phase != GamePhase.NIGHT.value
                or not self._is_zombie_game(game)
            ):
                return

            night = game.night_number
            alive_players = await self._alive_players(session, game_id)
            player_map = {player.telegram_id: player for player in alive_players}
            actions = (
                await session.execute(
                    select(NightAction)
                    .where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == night,
                    )
                    .order_by(NightAction.id.asc())
                )
            ).scalars().all()

            quarantined_ids = {
                int(action.target_telegram_id)
                for action in actions
                if action.action_type == ActionType.QUARANTINE.value and action.target_telegram_id
            }
            rescued_ids = {
                int(action.target_telegram_id)
                for action in actions
                if action.action_type == ActionType.ZOMBIE_RESCUE.value
                and action.actor_telegram_id not in quarantined_ids
                and action.target_telegram_id
            }
            hidden_zombie_ids = {
                int(action.target_telegram_id)
                for action in actions
                if action.action_type == ActionType.MUTANT_HIDE.value
                and action.actor_telegram_id not in quarantined_ids
                and action.target_telegram_id
                and (player_map.get(int(action.target_telegram_id)) is not None)
                and player_map[int(action.target_telegram_id)].team == Team.ZOMBIE.value
            }

            vaccine_lines: list[str] = []
            vaccine_private_lines: list[tuple[int, str]] = []
            scan_results: list[tuple[int, str]] = []
            fairy_revive_lines: list[str] = []
            fairy_revive_notices: list[tuple[int, str]] = []
            fairy_revive_used = False
            zombie_team_changed = False
            for action in actions:
                if action.action_type != ActionType.VACCINATE.value or not action.target_telegram_id:
                    continue
                actor = player_map.get(action.actor_telegram_id)
                target = player_map.get(action.target_telegram_id)
                if actor is None or target is None or not actor.alive or not target.alive:
                    continue
                if actor.role != Role.VACCINATOR.value or action.actor_telegram_id in quarantined_ids:
                    continue
                if target.role == Role.BOSS_ZOMBIE.value:
                    vaccine_private_lines.append((actor.telegram_id, "💉 Vaktsina bu safar ta'sir qilmadi."))
                    continue
                if target.team == Team.ZOMBIE.value:
                    target.role = Role.HUMAN.value
                    target.team = Team.CITY.value
                    target.transformed_to_role = Role.HUMAN.value
                    target.transformed_to_team = Team.CITY.value
                    zombie_team_changed = True
                    vaccine_lines.append(
                        f"💉 Vaktsina ishladi: {self._tg_mention(target.telegram_id, target.display_name)} yana insonlar tarafiga qaytdi."
                    )
                    vaccine_private_lines.append((target.telegram_id, "💉 Sizga vaktsina ishlatildi. Endi siz yana 🧍 Inson tarafidasiz."))
                else:
                    vaccine_private_lines.append((actor.telegram_id, "💉 Vaktsina insonda ishlatildi va kuchi sarflandi."))

            infected_player: Optional[GamePlayer] = None
            blocked_infection_lines: list[str] = []
            immune_private_lines: list[tuple[int, str]] = []
            infect_actions = [
                action
                for action in actions
                if action.action_type == ActionType.INFECT.value and action.target_telegram_id
            ]
            infect_actions.sort(
                key=lambda action: 0 if (player_map.get(action.actor_telegram_id) and player_map[action.actor_telegram_id].role == Role.BOSS_ZOMBIE.value) else 1
            )
            for action in infect_actions:
                actor = player_map.get(action.actor_telegram_id)
                target = player_map.get(action.target_telegram_id or 0)
                if (
                    actor is None
                    or target is None
                    or not actor.alive
                    or not target.alive
                    or target.team == Team.ZOMBIE.value
                ):
                    continue
                if actor.role == Role.INFECTOR.value and night % 2 != 0:
                    continue
                if actor.role not in {Role.BOSS_ZOMBIE.value, Role.INFECTOR.value}:
                    continue
                if actor.telegram_id in quarantined_ids:
                    blocked_infection_lines.append(
                        f"🛡 {role_label(actor.role)} karantinda qoldi va virus tarqata olmadi."
                    )
                    continue
                if target.telegram_id in quarantined_ids:
                    blocked_infection_lines.append(
                        f"🛡 {self._tg_mention(target.telegram_id, target.display_name)} karantin sabab virusdan omon qoldi."
                    )
                    continue
                if target.telegram_id in rescued_ids:
                    blocked_infection_lines.append(
                        f"🩺 Qutqaruvchi {self._tg_mention(target.telegram_id, target.display_name)}ni virusdan saqlab qoldi."
                    )
                    continue
                if target.role == Role.IMMUNE.value and not target.self_heal_used:
                    target.self_heal_used = True
                    immune_private_lines.append((target.telegram_id, "🧬 Immunitetingiz birinchi virus hujumini qaytardi."))
                    blocked_infection_lines.append(
                        f"🧬 Kimningdir immuniteti virusni qaytardi."
                    )
                    continue
                infected_player = target
                target.role = Role.ZOMBIE.value
                target.team = Team.ZOMBIE.value
                target.transformed_to_role = Role.ZOMBIE.value
                target.transformed_to_team = Team.ZOMBIE.value
                zombie_team_changed = True
                actor.inactive_rounds = 0
                self._add_activity_points(session, game, actor, 10, "zombie_infect")
                self._add_game_log(
                    session,
                    game,
                    "zombie_infected",
                    actor=actor,
                    target=target,
                    night_number=night,
                )
                break

            for action in actions:
                if action.action_type != ActionType.ZOMBIE_SCAN.value or not action.target_telegram_id:
                    continue
                actor = player_map.get(action.actor_telegram_id)
                target = player_map.get(action.target_telegram_id)
                if actor is None or target is None or not actor.alive or actor.role != Role.VIROLOGIST.value:
                    continue
                if actor.telegram_id in quarantined_ids:
                    scan_results.append((actor.telegram_id, "🛡 Karantin sabab bu tun tekshiruv qila olmadingiz."))
                    continue
                seen_zombie = target.team == Team.ZOMBIE.value and target.telegram_id not in hidden_zombie_ids
                status = "🧟 Zombie tarafida" if seen_zombie else "🧍 Inson tarafida"
                scan_results.append((
                    actor.telegram_id,
                    f"🔬 Tekshiruv natijasi: {self._tg_mention(target.telegram_id, target.display_name)} — <b>{status}</b>.",
                ))

            dead_players = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.alive.is_(False),
                    ).order_by(GamePlayer.id.asc())
                )
            ).scalars().all()
            dead_ids = {p.telegram_id for p in dead_players}

            for action in actions:
                if fairy_revive_used or action.action_type != ActionType.REVIVE.value or action.target_telegram_id is None:
                    continue
                actor = player_map.get(action.actor_telegram_id)
                target = player_map.get(action.target_telegram_id)
                if actor is None or target is None or actor.role != Role.FAIRY.value:
                    continue
                if action.target_telegram_id not in dead_ids:
                    continue
                fairy_revive_used = True
                target.alive = True
                target.death_day = None
                fairy_revive_lines.append(
                    f"👼 Farishta {self._tg_mention(target.telegram_id, target.display_name)}ni qayta tiriltirdi."
                )
                fairy_revive_notices.append(
                    (action.actor_telegram_id, f"👼 Siz {self._tg_mention(target.telegram_id, target.display_name)}ni qayta tiriltirdingiz.")
                )
                fairy_revive_notices.append(
                    (target.telegram_id, "👼 Siz o'limdan qaytdingiz! Bu tunda yana o'yinda ishtirok etasiz.")
                )

            game.phase = GamePhase.DAY_DISCUSSION.value
            game.day_number += 1
            self._add_game_log(
                session,
                game,
                "zombie_night_resolved",
                night_number=night,
                infected_id=infected_player.telegram_id if infected_player else None,
                quarantined_ids=sorted(quarantined_ids),
                rescued_ids=sorted(rescued_ids),
                hidden_zombie_ids=sorted(hidden_zombie_ids),
            )
            await session.commit()

            chat_id = game.chat_id
            lang = await self.get_group_language(chat_id)
            alive_after = await self._alive_players(session, game_id)
            alive_status = self._build_alive_status_text(alive_after, game)
            day_caption = self._build_day_intro_text(game.day_number)
            infected_notice = (
                "🦠 Virus tarqalmadi. Insonlar bu tongni omon kutib oldi."
                if infected_player is None
                else "🦠 Tunda virus tarqaldi. Kimdir zombi tarafga o'tdi."
            )
            infected_private_id = infected_player.telegram_id if infected_player else None
            zombie_team_private_lines: list[tuple[int, str]] = []
            if zombie_team_changed:
                current_zombies = [
                    player
                    for player in player_map.values()
                    if player.alive and player.team == Team.ZOMBIE.value
                ]
                for zombie in current_zombies:
                    zombie_team_text = self._zombie_team_private_text(zombie, current_zombies)
                    if zombie_team_text:
                        zombie_team_private_lines.append((
                            zombie.telegram_id,
                            f"🦠 <b>Zombi safi yangilandi</b>\n\n{zombie_team_text}",
                        ))
            private_notices = list(vaccine_private_lines) + list(immune_private_lines) + list(scan_results) + list(fairy_revive_notices)
            group_lines = vaccine_lines + blocked_infection_lines + list(fairy_revive_lines)

        await self._clear_night_prompt_buttons(bot, game_id, night)
        try:
            await self._send_phase_media(
                bot,
                chat_id,
                is_night=False,
                lang=lang,
                game_id=game_id,
                caption_override=day_caption,
            )
        except Exception:
            logger.exception("Failed to send zombie day phase media game_id=%s", game_id)
        await self._safe_send_message(bot, chat_id, alive_status)
        for line in dict.fromkeys(group_lines):
            await self._safe_send_message(bot, chat_id, line)
        await self._safe_send_message(bot, chat_id, infected_notice)
        for telegram_id, text in private_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
        if infected_private_id is not None:
            try:
                await bot.send_message(
                    infected_private_id,
                    "🦠 Sizga virus yuqdi. Endi siz 🧟 <b>Zombie</b> tarafidasiz!",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
        for telegram_id, text in zombie_team_private_lines:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        winner = await self.check_winner(game_id)
        if winner:
            await self.finish_game(bot, game_id, winner)
            return

        discussion_timeout = await self.group_timeout(chat_id, "day_discussion_timeout")
        scheduler.add_job(
            self.start_voting,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=discussion_timeout),
            args=[bot, game_id],
            id=f"discussion_end_{game_id}",
            replace_existing=True,
            misfire_grace_time=120,
        )


    async def record_action(
        self,
        bot: Bot,
        game_id: int,
        actor_id: int,
        action_key: str,
        target_id: int,
    ) -> tuple[bool, str]:
        action_map = {
            "infect": ActionType.INFECT,
            "zsave": ActionType.ZOMBIE_RESCUE,
            "zscan": ActionType.ZOMBIE_SCAN,
            "zquarantine": ActionType.QUARANTINE,
            "zvaccinate": ActionType.VACCINATE,
            "zhide": ActionType.MUTANT_HIDE,
            "kill": ActionType.KILL,
            "heal": ActionType.HEAL,
            "check": ActionType.CHECK,
            "shoot": ActionType.SHOOT,
            "block": ActionType.BLOCK,
            "defend": ActionType.DEFEND,
            "guard": ActionType.GUARD,
            "watch": ActionType.WATCH,
            "killer": ActionType.KILL,
            "visit": ActionType.VISIT,
            "revenge": ActionType.REVENGE_PICK,
            "mine": ActionType.MINE,
            "mine_protect": ActionType.MINE_PROTECT,
            "prank": ActionType.PRANK,
            "joker_card": ActionType.PRANK,
            "joker_target": ActionType.PRANK,
            "grant": ActionType.GRANT,
            "steal": ActionType.STEAL,
            "revive": ActionType.REVIVE,
            "arson": ActionType.CHECK,
        }
        action_type = action_map.get(action_key)
        if action_type is None:
            return False, "Unknown action"

        success_text = t(self.settings.default_language, "action_saved")
        chat_id: Optional[int] = None
        mafia_notice_ids: list[int] = []
        mafia_notice_text: Optional[str] = None
        group_activity_line: Optional[str] = None
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.NIGHT.value:
                return False, t(self.settings.default_language, "callback_expired")
            chat_id = game.chat_id

            actor = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            if actor is None or not actor.alive:
                return False, t(self.settings.default_language, "not_alive")
            actor_role = Role(actor.role)
            night_blocked = (
                await session.execute(
                    select(NightAction.action_type).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == game.night_number,
                        NightAction.action_type == ActionType.BLOCK.value,
                        NightAction.target_telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            if night_blocked is not None:
                return False, "Kezuvchi sabab bu tunda hech qanday amal bajara olmaysiz."

            allowed_actions: dict[Role, set[str]] = {
                Role.BOSS_ZOMBIE: {"infect"},
                Role.INFECTOR: {"infect"},
                Role.MUTANT_ZOMBIE: {"zhide"},
                Role.ZOMBIE_RESCUER: {"zsave"},
                Role.VIROLOGIST: {"zscan"},
                Role.QUARANTINE_OFFICER: {"zquarantine"},
                Role.VACCINATOR: {"zvaccinate"},
                Role.DON: {"kill"},
                Role.MAFIA: {"kill"},
                Role.SPY: {"kill"},
                Role.HIRED_KILLER: {"kill"},
                Role.DOCTOR: {"heal"},
                Role.GUARD: {"guard"},
                Role.WATCHER: {"watch"},
                Role.JOURNALIST: {"watch"},
                Role.COMMISSAR: {"check", "shoot"},
                Role.MISTRESS: {"block"},
                Role.CROOK: {"block"},
                Role.LAWYER: {"defend"},
                Role.KILLER: {"killer"},
                Role.BUM: {"visit"},
                Role.SORCERER: {"revenge"},
                Role.MINER: {"mine", "mine_protect"},
                Role.PRANKSTER: {"prank"},
                Role.JOKER: {"joker_card", "joker_target"},
                Role.SNITCH: {"check"},
                Role.HOJIAKA: {"grant"},
                Role.MASHKA: {"steal"},
                Role.FAIRY: {"revive"},
                Role.ARSONIST: {"arson"},
            }
            role_allowed = allowed_actions.get(actor_role, set())
            if action_key not in role_allowed:
                return False, "Bu amal sizning rolingiz uchun mavjud emas."
            zombie_action_types = {
                ActionType.INFECT,
                ActionType.ZOMBIE_RESCUE,
                ActionType.ZOMBIE_SCAN,
                ActionType.QUARANTINE,
                ActionType.VACCINATE,
                ActionType.MUTANT_HIDE,
            }
            if action_type in zombie_action_types and game.role_preset != "zombie":
                return False, "Bu amal faqat Zombie mode uchun mavjud."
            if actor_role == Role.INFECTOR and action_type == ActionType.INFECT and game.night_number % 2 != 0:
                return False, "Infektor faqat juft tunlarda virus yuqtira oladi."
            if action_type == ActionType.MINE and not 1 <= target_id <= 10:
                return False, "Kon noto'g'ri."
            if action_type == ActionType.MINE:
                already_visited_mine = (
                    await session.execute(
                        select(NightAction.id).where(
                            NightAction.game_id == game_id,
                            NightAction.actor_telegram_id == actor_id,
                            NightAction.action_type == ActionType.MINE.value,
                            NightAction.target_telegram_id == target_id,
                        )
                    )
                ).scalar_one_or_none()
                if already_visited_mine is not None:
                    return False, "Bu konga oldin tashrif buyurgansiz. Boshqa kon tanlang."
            if action_type == ActionType.HEAL and target_id == actor_id and actor.self_heal_used:
                return False, "Siz o'zingizni yana davolay olmaysiz."


            if actor_role == Role.ARSONIST:
                if target_id != actor_id:
                    already_marked = (
                        await session.execute(
                            select(NightAction.id).where(
                                NightAction.game_id == game_id,
                                NightAction.actor_telegram_id == actor_id,
                                NightAction.details == "arson",
                                NightAction.target_telegram_id == target_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if already_marked is not None:
                        return False, "Bu o'yinchini oldin belgilagansiz. Boshqasini tanlang."
                marked_count = (
                    await session.execute(
                        select(func.count(NightAction.id)).where(
                            NightAction.game_id == game_id,
                            NightAction.actor_telegram_id == actor_id,
                            NightAction.details == "arson",
                            NightAction.target_telegram_id.is_not(None),
                            NightAction.target_telegram_id != actor_id,
                        )
                    )
                ).scalar_one()
                if target_id == actor_id and int(marked_count or 0) < 3:
                    return False, "Avval 3 xil o'yinchini belgilang, keyin o'zingizni tanlashingiz mumkin."

            if action_type in {ActionType.MINE, ActionType.MINE_PROTECT} or (
                actor_role == Role.JOKER and action_key == "joker_card"
            ):
                target = actor
            elif action_type == ActionType.REVIVE:
                target = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.telegram_id == target_id,
                        )
                    )
                ).scalar_one_or_none()
                if target is None:
                    return False, "Nishon noto'g'ri."
                if target.alive:
                    return False, "Farishta faqat o'lik o'yinchini tiriltira oladi."
            else:
                target = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.telegram_id == target_id,
                        )
                    )
                ).scalar_one_or_none()
                if target is None or not target.alive:
                    return False, "Nishon noto'g'ri."
            if action_type == ActionType.REVIVE:
                revive_exists = (
                    await session.execute(
                        select(NightAction.id).where(
                            NightAction.game_id == game_id,
                            NightAction.action_type == ActionType.REVIVE.value,
                        )
                    )
                ).scalar_one_or_none()
                if revive_exists is not None:
                    return False, "Bu o'yinda Farishta allaqachon bitta o'yinchini qayta tiriltirdi."
            if action_type == ActionType.INFECT:
                if target.telegram_id == actor.telegram_id:
                    return False, "O'zingizga virus yuqtira olmaysiz."
                if target.team == Team.ZOMBIE.value:
                    return False, "Bu o'yinchi allaqachon zombi tarafida."
            if action_type == ActionType.MUTANT_HIDE and target.team != Team.ZOMBIE.value:
                return False, "Mutant faqat zombi tarafdoshini yashira oladi."
            if action_type == ActionType.VACCINATE and actor.self_heal_used:
                return False, "Vaktsina kuchi allaqachon ishlatilgan."
            if actor_role == Role.JOKER and action_key == "joker_card":
                if target_id not in {1, 2, 3, 4}:
                    return False, "Karta noto'g'ri."
                existing_prank = (
                    await session.execute(
                        select(NightAction).where(
                            NightAction.game_id == game_id,
                            NightAction.night_number == game.night_number,
                            NightAction.actor_telegram_id == actor_id,
                            NightAction.action_type == ActionType.PRANK.value,
                        )
                    )
                ).scalar_one_or_none()
                if existing_prank is not None:
                    return False, t(self.settings.default_language, "action_already")
                session.add(
                    NightAction(
                        game_id=game_id,
                        night_number=game.night_number,
                        actor_telegram_id=actor_id,
                        target_telegram_id=None,
                        action_type=ActionType.PRANK.value,
                        details=json.dumps({"death_card": target_id}),
                    )
                )
                await session.commit()
                alive = await self._alive_players(session, game_id)
                target_choices = [(p.telegram_id, p.display_name) for p in alive if p.telegram_id != actor_id]
                try:
                    await bot.send_message(
                        actor_id,
                        "🃏 Endi kimga kartalar yuborishni tanlang.",
                        reply_markup=joker_target_keyboard(game_id, actor_id, target_choices),
                    )
                except TelegramForbiddenError:
                    pass
                return True, "O'lim kartasi saqlandi."
            if actor_role == Role.JOKER and action_key == "joker_target":
                prank_action = (
                    await session.execute(
                        select(NightAction).where(
                            NightAction.game_id == game_id,
                            NightAction.night_number == game.night_number,
                            NightAction.actor_telegram_id == actor_id,
                            NightAction.action_type == ActionType.PRANK.value,
                        )
                    )
                ).scalar_one_or_none()
                if prank_action is None:
                    return False, "Avval o'lim kartasini tanlang."
                try:
                    details = json.loads(prank_action.details or "{}")
                except (TypeError, ValueError):
                    details = {}
                if prank_action.target_telegram_id:
                    return False, t(self.settings.default_language, "action_already")
                prank_action.target_telegram_id = target_id
                prank_action.details = json.dumps(
                    {"death_card": int(details.get("death_card", 1)), "target_card": None, "result": None}
                )
                await session.commit()
                try:
                    await bot.send_message(
                        target_id,
                        "🃏 Joker sizga kartalar yubordi. 4 kartadan birini tanlang:",
                        reply_markup=joker_victim_card_keyboard(game_id, target_id, actor_id),
                    )
                except TelegramForbiddenError:
                    pass
                return True, f"Siz - {target.display_name} ni tanladingiz."
            if action_key == "kill" and actor.team == Team.MAFIA.value and target.team == Team.MAFIA.value:
                return False, "Mafiya o'z sherigiga zarar yetkaza olmaydi."
            if actor_role == Role.COMMISSAR and action_key == "check":
                success_text = f"Siz {target.display_name}ning uyiga tekshiruvga borishni tanladingiz."
            elif action_key == "infect":
                success_text = f"Siz {target.display_name}ga virus yuqtirishni tanladingiz."
            elif action_key == "zsave":
                success_text = f"Siz {target.display_name}ni virusdan himoya qilishni tanladingiz."
            elif action_key == "zscan":
                success_text = f"Siz {target.display_name}ni virusga tekshirishni tanladingiz."
            elif action_key == "zquarantine":
                success_text = f"Siz {target.display_name}ni karantinga olishni tanladingiz."
            elif action_key == "zvaccinate":
                success_text = f"Siz {target.display_name}ga vaktsina ishlatishni tanladingiz."
            elif action_key == "zhide":
                success_text = f"Siz {target.display_name}ni tekshiruvdan yashirishni tanladingiz."
            elif actor_role == Role.COMMISSAR and action_key == "shoot":
                success_text = f"Siz {target.display_name}ni o'yindan chetlatishni tanladingiz."
            elif action_key == "kill" and actor_role in {Role.MAFIA, Role.SPY, Role.HIRED_KILLER}:
                success_text = f"Siz - {target.display_name} ni tanladingiz. Don qaror qilmasa, tanlovingiz ishlaydi."
            elif action_type == ActionType.MINE:
                success_text = f"Siz {target_id:02d}-konni tanladingiz."
            elif action_type == ActionType.MINE_PROTECT:
                success_text = "Siz himoyalanishni tanladingiz."
            elif action_type == ActionType.GRANT:
                success_text = f"Siz {target.display_name}ga ehson qilishni tanladingiz."
            elif action_type == ActionType.STEAL:
                success_text = f"Siz {target.display_name}dan o'g'irlashni tanladingiz."
            elif action_type == ActionType.REVIVE:
                success_text = f"Siz {target.display_name}ni qayta tiriltirishni tanladingiz."
            elif action_key == "joker_card":
                success_text = "Siz o'lim kartasini tanladingiz."
            elif action_key == "joker_target":
                success_text = f"Siz {target.display_name}ga kartalar yubordingiz."
            elif action_key == "prank":
                success_text = f"Siz {target.display_name}ni hazil bilan chalg'itishni tanladingiz."
            elif action_key == "arson":
                if target_id == actor_id:
                    success_text = "Siz o'zingizni tanladingiz. G'azabkor alangasi yoqiladi."
                else:
                    success_text = f"Siz {target.display_name}ni belgiladingiz."
            else:
                success_text = f"Siz - {target.display_name} ni tanladingiz."
            group_activity_line = self._night_activity_line(actor_role, action_key)

            existing = (
                await session.execute(
                    select(NightAction).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == game.night_number,
                        NightAction.actor_telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False, t(self.settings.default_language, "action_already")

            session.add(
                NightAction(
                    game_id=game_id,
                    night_number=game.night_number,
                    actor_telegram_id=actor_id,
                    target_telegram_id=target_id if action_type != ActionType.MINE_PROTECT else None,
                    action_type=action_type.value,
                    details=action_key,
                )
            )

            if action_type == ActionType.HEAL and actor.telegram_id == target_id:
                actor.self_heal_used = True
            if action_type == ActionType.VACCINATE:
                actor.self_heal_used = True
            if action_type == ActionType.REVIVE:
                actor.self_heal_used = True

            self._add_game_log(
                session,
                game,
                "night_action_saved",
                actor=actor,
                target=target,
                action_type=action_type.value,
                action_key=action_key,
            )
            if action_key == "kill" and actor_role in {Role.MAFIA, Role.SPY, Role.HIRED_KILLER}:
                mafia_team = (
                    await session.execute(
                        select(GamePlayer).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.alive.is_(True),
                            GamePlayer.team == Team.MAFIA.value,
                            GamePlayer.telegram_id != actor_id,
                        )
                    )
                ).scalars().all()
                mafia_notice_ids = [member.telegram_id for member in mafia_team]
                mafia_notice_text = f"{actor.display_name} -- {target.display_name} ga ovoz berdi"
                group_activity_line = None

            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, t(self.settings.default_language, "action_already")

        if chat_id is not None:
            try:
                await bot.send_message(
                    actor_id,
                    success_text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
            if group_activity_line:
                await bot.send_message(chat_id, group_activity_line)
            if mafia_notice_text:
                for member_id in mafia_notice_ids:
                    try:
                        await bot.send_message(
                            member_id,
                            mafia_notice_text,
                            reply_markup=await self.group_return_keyboard(bot, chat_id),
                        )
                    except TelegramForbiddenError:
                        pass
        return True, success_text


    async def commissar_targets_keyboard(
        self,
        game_id: int,
        actor_id: int,
        action_key: str,
    ) -> tuple[bool, str, Optional[object]]:
        if action_key not in {"check", "shoot"}:
            return False, "Noma'lum amal.", None
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.NIGHT.value:
                return False, t(self.settings.default_language, "callback_expired"), None
            actor = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == actor_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if actor is None or Role(actor.role) != Role.COMMISSAR:
                return False, "Bu amal faqat Komissar Katani uchun.", None
            existing = (
                await session.execute(
                    select(NightAction.id).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == game.night_number,
                        NightAction.actor_telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False, t(self.settings.default_language, "action_already"), None
            alive = await self._alive_players(session, game_id)

        choices = [(p.telegram_id, p.display_name) for p in alive if p.telegram_id != actor_id]
        title = "Tekshirish" if action_key == "check" else "Otish"
        return True, title, commissar_target_keyboard(action_key, game_id, actor_id, choices)


    async def commissar_action_menu_keyboard(
        self,
        game_id: int,
        actor_id: int,
    ) -> tuple[bool, str, Optional[object]]:
        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value or game.phase != GamePhase.NIGHT.value:
                return False, t(self.settings.default_language, "callback_expired"), None
            actor = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == actor_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if actor is None or Role(actor.role) != Role.COMMISSAR:
                return False, "Bu amal faqat Komissar Katani uchun.", None
            existing = (
                await session.execute(
                    select(NightAction.id).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == game.night_number,
                        NightAction.actor_telegram_id == actor_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False, t(self.settings.default_language, "action_already"), None
            can_shoot = game.night_number >= 2
        return True, "🕵🏼 Komissar katani", commissar_action_keyboard(game_id, actor_id, can_shoot=can_shoot)


    async def skip_choice(
        self,
        bot: Bot,
        game_id: int,
        user_id: int,
        scope: str,
    ) -> tuple[bool, str]:
        if scope not in {"night", "vote", "hang", "judge"}:
            return False, "Noma'lum tanlov."

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return False, t(self.settings.default_language, "callback_expired")

            player = (
                await session.execute(
                    select(GamePlayer).where(
                        GamePlayer.game_id == game_id,
                        GamePlayer.telegram_id == user_id,
                        GamePlayer.alive.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if player is None:
                return False, t(self.settings.default_language, "not_alive")

            if scope == "night":
                if game.phase != GamePhase.NIGHT.value:
                    return False, t(self.settings.default_language, "callback_expired")
                night_blocked = (
                    await session.execute(
                        select(NightAction.action_type).where(
                            NightAction.game_id == game_id,
                            NightAction.night_number == game.night_number,
                            NightAction.action_type == ActionType.BLOCK.value,
                            NightAction.target_telegram_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if night_blocked is not None:
                    return False, "Kezuvchi sabab bu tunda hech qanday amal bajara olmaysiz."
                existing = (
                    await session.execute(
                        select(NightAction.id).where(
                            NightAction.game_id == game_id,
                            NightAction.night_number == game.night_number,
                            NightAction.actor_telegram_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return False, t(self.settings.default_language, "action_already")
                session.add(
                    NightAction(
                        game_id=game_id,
                        night_number=game.night_number,
                        actor_telegram_id=user_id,
                        target_telegram_id=None,
                        action_type=ActionType.SKIP.value,
                        details="skip",
                    )
                )
            elif scope == "vote":
                if game.phase != GamePhase.DAY_VOTING.value:
                    return False, t(self.settings.default_language, "callback_expired")
                if self._is_day_blocked(player, game):
                    return False, "Kezuvchi sabab bugun ovoz bera olmaysiz."
                existing_vote = (
                    await session.execute(
                        select(Vote.id).where(
                            Vote.game_id == game_id,
                            Vote.day_number == game.day_number,
                            Vote.voter_telegram_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_vote is not None:
                    return False, t(self.settings.default_language, "vote_already")
            elif scope == "hang":
                if game.phase != GamePhase.DAY_CONFIRM.value:
                    return False, t(self.settings.default_language, "callback_expired")
                if self._is_day_blocked(player, game):
                    return False, "Kezuvchi sabab bugun osish bo'yicha ovoz bera olmaysiz."
                existing_hang = (
                    await session.execute(
                        select(HangVote.id).where(
                            HangVote.game_id == game_id,
                            HangVote.day_number == game.day_number,
                            HangVote.voter_telegram_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_hang is not None:
                    return False, "Siz allaqachon tanlov qilgansiz."
            elif scope == "judge":
                if game.phase != GamePhase.DAY_CONFIRM.value:
                    return False, t(self.settings.default_language, "callback_expired")
                if Role(player.role) != Role.JUDGE:
                    return False, "Bu tugma faqat Sudya uchun."
                if self._is_day_blocked(player, game):
                    return False, "Kezuvchi sabab bugun hech qanday amal bajara olmaysiz."

            existing_skip = (
                await session.execute(
                    select(SkipDecision.id).where(
                        SkipDecision.game_id == game_id,
                        SkipDecision.phase == scope,
                        SkipDecision.day_number == game.day_number,
                        SkipDecision.night_number == game.night_number,
                        SkipDecision.user_telegram_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_skip is not None:
                return False, "Siz allaqachon o'tkazib yuborgansiz."

            session.add(
                SkipDecision(
                    game_id=game_id,
                    phase=scope,
                    day_number=game.day_number,
                    night_number=game.night_number,
                    user_telegram_id=user_id,
                )
            )
            self._add_game_log(session, game, f"{scope}_skipped", actor=player)
            await session.commit()
            chat_id = game.chat_id
            player_name = self._tg_mention(player.telegram_id, player.display_name)

        if scope == "night":
            if Role(player.role) == Role.COMMISSAR:
                group_text = "🕵🏼 Komissar katani hech kimni tekshirmadi yoki otmaslikkaga qaror qildi."
                user_message = "Siz hech kimni tekshirmadi yoki otmaslikkaga qaror qildingiz."
            else:
                group_text = f"🚷 {role_label(player.role)} hech narsa qilmaslikka qaror qildi"
                user_message = "Siz hech narsa qilmaslikka qaror qildingiz."
        else:
            group_text = f"🚷 {player_name} hech kimni tanlamaslikka qaror qildi"
            user_message = "Siz hech narsa qilmaslikka qaror qildingiz."

        await bot.send_message(chat_id, group_text)
        try:
            await bot.send_message(
                user_id,
                user_message,
                reply_markup=await self.group_return_keyboard(bot, chat_id),
            )
        except TelegramForbiddenError:
            pass
        return True, "O'tkazib yuborildi."


    async def resolve_night(self, bot: Bot, game_id: int) -> None:
        if await self._is_zombie_game_id(game_id):
            await self.resolve_zombie_night(bot, game_id)
            return

        async with self.session_factory() as session:
            game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
            if game is None or game.status != GameStatus.ACTIVE.value:
                return
            if game.phase != GamePhase.NIGHT.value:
                return

            night = game.night_number
            alive_players = await self._alive_players(session, game_id)
            alive_ids = {p.telegram_id for p in alive_players}
            player_map = {p.telegram_id: p for p in alive_players}
            users_by_tg = {
                user.telegram_id: user
                for user in (
                    await session.execute(select(User).where(User.telegram_id.in_(alive_ids)))
                ).scalars().all()
            }

            actions = (
                await session.execute(
                    select(NightAction).where(
                        NightAction.game_id == game_id,
                        NightAction.night_number == night,
                    ).order_by(NightAction.id.asc())
                )
            ).scalars().all()
            blocked: set[int] = set()
            defended: set[int] = set()
            guarded: set[int] = set()
            healed: set[int] = set()
            doctor_heal_targets: dict[int, int] = {}
            mistress_visit_targets: set[int] = set()
            visited: dict[int, int] = {}
            watched: dict[int, int] = {}
            visitors_by_target: dict[int, list[int]] = defaultdict(list)
            dead: set[int] = set()
            protected_group_lines: list[str] = []
            prank_notices: list[tuple[int, str]] = []
            prank_blocked_targets: set[int] = set()

            for act in actions:
                if act.actor_telegram_id not in alive_ids:
                    continue
                actor = player_map[act.actor_telegram_id]
                if not actor.alive:
                    continue
                if act.action_type == ActionType.BLOCK.value and act.target_telegram_id:
                    target = player_map.get(act.target_telegram_id)
                    target_user = users_by_tg.get(act.target_telegram_id)
                    if (
                        target_user
                        and target_user.use_drug_protection is not False
                        and (target_user.drug_protection or 0) > 0
                    ):
                        target_user.drug_protection -= 1
                        protected_group_lines.append(f"{_ce('💊', DRUG_EMOJI_ID)} Kimdir doridan himoyasini ishlatdi.")
                        self._add_game_log(
                            session,
                            game,
                            "drug_protection_used",
                            actor=target,
                            remaining_drug_protection=target_user.drug_protection,
                        )
                        continue
                    blocked.add(act.target_telegram_id)
                    mistress_visit_targets.add(act.target_telegram_id)
                    if target:
                        target.blocked_until_day = game.day_number + 1
                    actor_role_value = Role(actor.role)
                    if actor_role_value == Role.MISTRESS:
                        pass
                    elif actor_role_value == Role.CROOK:
                        protected_group_lines.append(
                            "🤹🏻 Bu tunda Qaroqchi kimnidir chalg'itib qo'ydi."
                        )
                elif act.action_type == ActionType.PRANK.value and act.target_telegram_id:
                    actor_role_value = Role(actor.role)
                    if actor_role_value != Role.PRANKSTER:
                        continue
                    target = player_map.get(act.target_telegram_id)
                    if target is None or not target.alive:
                        continue
                    if act.target_telegram_id in prank_blocked_targets:
                        continue
                    blocked.add(act.target_telegram_id)
                    prank_blocked_targets.add(act.target_telegram_id)
                    protected_group_lines.append("😂 Hazilkash bu tunda kimningdir rejasini buzib qo'ydi.")
                    prank_notices.append((act.target_telegram_id, self._prank_message_for_role(Role(target.role))))

            for act in actions:
                if act.actor_telegram_id in blocked:
                    continue
                if act.action_type == ActionType.HEAL.value and act.target_telegram_id:
                    heal_actor = player_map.get(act.actor_telegram_id)
                    heal_target = player_map.get(act.target_telegram_id)
                    if (
                        heal_actor is not None
                        and heal_actor.alive
                        and heal_actor.role == Role.DOCTOR.value
                        and heal_target is not None
                        and heal_target.alive
                        and act.target_telegram_id not in dead
                    ):
                        healed.add(act.target_telegram_id)
                        doctor_heal_targets[act.actor_telegram_id] = act.target_telegram_id
                elif act.action_type == ActionType.DEFEND.value and act.target_telegram_id:
                    defended.add(act.target_telegram_id)
                elif act.action_type == ActionType.GUARD.value and act.target_telegram_id:
                    guarded.add(act.target_telegram_id)
                elif act.action_type == ActionType.WATCH.value and act.target_telegram_id:
                    watched[act.actor_telegram_id] = act.target_telegram_id
                elif act.action_type == ActionType.VISIT.value and act.target_telegram_id:
                    visited[act.actor_telegram_id] = act.target_telegram_id
                elif act.action_type == ActionType.MINE_PROTECT.value:
                    guarded.add(act.actor_telegram_id)

                if (
                    act.target_telegram_id
                    and act.actor_telegram_id != act.target_telegram_id
                    and act.action_type not in {ActionType.WATCH.value, ActionType.MINE.value}
                ):
                    visitors_by_target[act.target_telegram_id].append(act.actor_telegram_id)

            don_kills = []
            mafia_fallback_kills = []
            killer_kills = []
            commissar_shots = []
            checks = []
            hojiaka_grants: list[tuple[int, int]] = []
            mashka_steals: list[tuple[int, int]] = []
            joker_actions: list[NightAction] = []
            mine_actions: list[tuple[NightAction, int]] = []
            miner_protectors: set[int] = set()
            arson_actions: list[tuple[int, int]] = []
            night_activity_lines: list[str] = []

            for act in actions:
                if act.actor_telegram_id in blocked:
                    continue
                actor = player_map.get(act.actor_telegram_id)
                if actor is None:
                    continue
                role = Role(actor.role)
                target_id = act.target_telegram_id
                if target_id is None:
                    continue

                if act.action_type == ActionType.KILL.value and role == Role.DON:
                    don_kills.append(target_id)
                elif act.action_type == ActionType.KILL.value and role in {Role.MAFIA, Role.SPY, Role.HIRED_KILLER}:
                    mafia_fallback_kills.append(target_id)
                elif act.action_type == ActionType.KILL.value and role == Role.KILLER:
                    killer_kills.append(target_id)
                elif act.action_type == ActionType.SHOOT.value and role == Role.COMMISSAR:
                    commissar_shots.append(target_id)
                elif act.action_type == ActionType.CHECK.value and role == Role.COMMISSAR:
                    checks.append((act.actor_telegram_id, target_id))
                elif act.action_type == ActionType.CHECK.value and role == Role.SNITCH:
                    pass  # handled separately below
                elif act.action_type == ActionType.GRANT.value and role == Role.HOJIAKA:
                    hojiaka_grants.append((act.actor_telegram_id, target_id))
                elif act.action_type == ActionType.STEAL.value and role == Role.MASHKA:
                    mashka_steals.append((act.actor_telegram_id, target_id))
                elif act.action_type == ActionType.PRANK.value and role == Role.JOKER:
                    joker_actions.append(act)
                elif act.details == "arson" and role == Role.ARSONIST:
                    arson_actions.append((act.actor_telegram_id, target_id))
                elif act.action_type == ActionType.MINE.value and role == Role.MINER:
                    mine_actions.append((act, target_id))
                elif act.action_type == ActionType.MINE_PROTECT.value and role == Role.MINER:
                    miner_protectors.add(act.actor_telegram_id)

            death_causes: dict[int, str] = {}
            mafia_dead: set[int] = set()
            death_visitors: dict[int, str] = {}
            transformed: list[str] = []
            night_event_lines: list[str] = []
            protected_notices: list[tuple[int, str]] = []
            last_words_prompts: list[tuple[int, str]] = []
            miner_result_notices: list[tuple[int, str]] = []
            miner_group_lines: list[str] = []
            hojiaka_notices: list[tuple[int, str]] = []
            hojiaka_target_notices: list[tuple[int, str]] = []
            hojiaka_group_lines: list[str] = []
            mashka_notices: list[tuple[int, str]] = []
            mashka_target_notices: list[tuple[int, str]] = []
            mashka_group_lines: list[str] = []
            arsonist_inferno_triggered = False
            doctor_saved_targets: set[int] = set()
            doctor_save_notices: list[tuple[int, int, int, str]] = []

            # SNITCH resolution
            snitch_actions = [
                act for act in actions
                if act.action_type == ActionType.CHECK.value
                and act.actor_telegram_id in player_map
                and Role(player_map[act.actor_telegram_id].role) == Role.SNITCH
                and act.actor_telegram_id not in blocked
            ]
            snitch_group_lines: list[str] = []
            snitch_notices: list[tuple[int, str]] = []
            for act in snitch_actions:
                target = player_map.get(act.target_telegram_id)
                if target is None:
                    continue
                target_role = Role(target.role)
                if target_role in {Role.DON, Role.MAFIA, Role.KILLER}:
                    snitch_group_lines.append(f"{_ce('🤓', SNITCH_EMOJI_ID)} Sotqinning izlanishlari samara berdi!")
                    snitch_group_lines.append(
                        f"{_ce('🤓', SNITCH_EMOJI_ID)} Sotqin odamlarga {self._tg_mention(target.telegram_id, target.display_name)}ning {role_label(target_role)} ekanini sotib berdi."
                    )
                    snitch_notices.append((
                        act.actor_telegram_id,
                        f"🤓 Siz {self._tg_mention(target.telegram_id, target.display_name)}ni tekshirdingiz. U {role_label(target_role)} ekan! Odamlarga bu haqida xabar berildi.",
                    ))
                else:
                    snitch_group_lines.append(f"{_ce('🤓', SNITCH_EMOJI_ID)} Sotqinning izlanishlari zoya ketdi!")
                    snitch_notices.append((
                        act.actor_telegram_id,
                        f"🤓 Siz {self._tg_mention(target.telegram_id, target.display_name)}ni tekshirdingiz. U oddiy o'yinchi ekan.",
                    ))

            if mine_actions or miner_protectors:
                miner_users = {
                    user.telegram_id: user
                    for user in (
                        await session.execute(
                            select(User).where(
                                User.telegram_id.in_(
                                    [act.actor_telegram_id for act, _ in mine_actions] + list(miner_protectors)
                                )
                            )
                        )
                    ).scalars().all()
                }
                for actor_id in miner_protectors:
                    miner_result_notices.append((actor_id, "⚜️ Siz bu tunda himoyalandingiz va konga bormadingiz."))
                for mine_action, mine_number in mine_actions:
                    actor_id = mine_action.actor_telegram_id
                    miner = player_map.get(actor_id)
                    if miner is None or not miner.alive:
                        continue
                    layout = ["death"] * 3 + ["diamond"] * 2 + ["dollar"] * 5
                    rng = random.Random(f"{game_id}:{night}:{actor_id}")
                    rng.shuffle(layout)
                    result = layout[mine_number - 1]
                    user = miner_users.get(actor_id)
                    if result == "diamond":
                        amount = 1
                        mine_action.details = json.dumps({
                            "result": "diamond",
                            "amount": amount,
                            "mine_number": mine_number,
                        })
                        miner_result_notices.append((actor_id, f"👷🏻‍♂️ {mine_number:02d}-kondan <tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {amount} olmos topdingiz."))
                        miner_group_lines.append(
                            f"👷🏻‍♂️ Konchi konda {amount} <tg-emoji emoji-id=\"5427168083074628968963\">💎</tg-emoji> olmos topdi!"
                        )
                    elif result == "dollar":
                        amount = 50
                        mine_action.details = json.dumps({
                            "result": "dollar",
                            "amount": amount,
                            "mine_number": mine_number,
                        })
                        miner_result_notices.append((actor_id, f"👷🏻‍♂️ {mine_number:02d}-kondan <tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> {amount} dollar topdingiz."))
                        miner_group_lines.append(
                            f"👷🏻‍♂️ Konchi konda {amount} <tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> topdi!"
                        )
                    elif user and user.use_miner_protection is not False and (user.miner_protection or 0) > 0:
                        user.miner_protection -= 1
                        mine_action.details = json.dumps({
                            "result": "protected",
                            "mine_number": mine_number,
                        })
                        miner_result_notices.append(
                            (actor_id, f"👷🏻‍♂️ {mine_number:02d}-o'lim koniga tushdingiz, lekin Konchi himoyasi sizni qutqardi.")
                        )
                        miner_group_lines.append("👷🏻‍♂️ Konchi o'lim konida sirpanib ketdi, lekin himoyasi uni qutqardi!")
                    else:
                        mine_action.details = json.dumps({
                            "result": "death",
                            "mine_number": mine_number,
                        })
                        dead.add(actor_id)
                        death_causes[actor_id] = "miner"
                        death_visitors[actor_id] = role_label(Role.MINER)
                        miner_result_notices.append((actor_id, f"👷🏻‍♂️ {mine_number:02d}-o'lim koniga tushdingiz."))
                        miner_group_lines.append("👷🏻‍♂️ Konchi konda sirpanib ketib halok bo'ldi!")

            if hojiaka_grants:
                dollar_choices = [50, 70, 90, 100, 130, 150, 170, 200, 250]
                item_choices: list[tuple[str, str]] = [
                    ("protection", "🛡 Himoya"),
                    ("killer_protection", "🧿 Qotildan himoya"),
                    ("drug_protection", "💊 Doridan himoya"),
                    ("vote_protection", "⚖️ Ovozdan himoya"),
                    ("miner_protection", "📦 Sirpanishdan himoya"),
                    ("mask", "🎭 Maska"),
                ]
                for actor_id, target_id in hojiaka_grants:
                    actor_player = player_map.get(actor_id)
                    target_player = player_map.get(target_id)
                    if actor_player is None or target_player is None:
                        continue
                    actor_user = users_by_tg.get(actor_id)
                    target_user = users_by_tg.get(target_id)
                    if actor_user is None or target_user is None:
                        continue
                    rng = random.Random(f"hojiaka:{game.id}:{game.night_number}:{actor_id}:{target_id}")
                    reward_type = rng.choices(["item", "dollar", "diamond"], weights=[75, 20, 5], k=1)[0]
                    if reward_type == "diamond":
                        amount = rng.choice([1, 1, 1, 2, 2, 3])
                        target_user.diamonds = int(target_user.diamonds or 0) + amount
                        self._record_diamond_transaction(
                            session,
                            target_user,
                            amount,
                            "hojiaka_grant",
                            note=f"O'yin #{game.id}: Hojiaka ehsoni",
                            counterparty=actor_user,
                            chat_id=game.chat_id,
                        )
                        gift_label = f"<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> {amount} olmos"
                    elif reward_type == "dollar":
                        low_dollar_choices = [v for v in dollar_choices if v <= 150]
                        high_dollar_choices = [v for v in dollar_choices if v > 150]
                        # Dollar berilganda 150+ faqat 20% holatda chiqadi.
                        if high_dollar_choices and rng.random() < 0.2:
                            amount = rng.choice(high_dollar_choices)
                        else:
                            amount = rng.choice(low_dollar_choices or dollar_choices)
                        target_user.dollar = int(target_user.dollar or 0) + amount
                        self._record_dollar_transaction(
                            session,
                            target_user,
                            amount,
                            "hojiaka_grant",
                            note=f"O'yin #{game.id}: Hojiaka ehsoni",
                            counterparty=actor_user,
                            chat_id=game.chat_id,
                        )
                        gift_label = f"<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> {amount} dollar"
                    else:
                        field, title = rng.choice(item_choices)
                        current = int(getattr(target_user, field) or 0)
                        setattr(target_user, field, current + 1)
                        gift_label = title

                    hojiaka_notices.append(
                        (actor_id, f"🕌 Siz {self._tg_mention(target_player.telegram_id, target_player.display_name)}ga {gift_label} ehson qildingiz.")
                    )
                    hojiaka_target_notices.append(
                        (target_id, f"🕌 Hojiaka sizga {gift_label} ehson ulashdi!")
                    )
                    hojiaka_group_lines.append(
                        f"🕌 Hojiaka {self._tg_mention(target_player.telegram_id, target_player.display_name)}ga "
                        f"{gift_label} ehson ulashdi."
                    )

            if mashka_steals:
                steal_dollar_choices = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
                for actor_id, target_id in mashka_steals:
                    actor_player = player_map.get(actor_id)
                    target_player = player_map.get(target_id)
                    if actor_player is None or target_player is None:
                        continue
                    actor_user = users_by_tg.get(actor_id)
                    target_user = users_by_tg.get(target_id)
                    if actor_user is None or target_user is None:
                        continue
                    rng = random.Random(f"mashka:{game.id}:{game.night_number}:{actor_id}:{target_id}")
                    steal_diamond = rng.random() < 0.1 and int(target_user.diamonds or 0) >= 1
                    if steal_diamond:
                        target_user.diamonds -= 1
                        actor_user.diamonds = int(actor_user.diamonds or 0) + 1
                        self._record_diamond_transaction(
                            session,
                            target_user,
                            -1,
                            "mashka_steal_out",
                            note=f"O'yin #{game.id}: Mashka o'g'irligi",
                            counterparty=actor_user,
                            chat_id=game.chat_id,
                        )
                        self._record_diamond_transaction(
                            session,
                            actor_user,
                            1,
                            "mashka_steal_in",
                            note=f"O'yin #{game.id}: Mashka o'g'irligi",
                            counterparty=target_user,
                            chat_id=game.chat_id,
                        )
                        stolen_label = "<tg-emoji emoji-id=\"5427168083074628963\">💎</tg-emoji> 1 olmos"
                    else:
                        possible = [v for v in steal_dollar_choices if v <= int(target_user.dollar or 0)]
                        if not possible:
                            current_hp = int(target_player.hero_hp or HERO_DEFAULT_HP)
                            target_max_hp = int(target_player.hero_max_hp or HERO_DEFAULT_HP)
                            # 50% damage must always be based on max HP (not current HP),
                            # so the second low-balance visit removes the player from the game.
                            hp_loss = max(1, target_max_hp // 2)
                            target_player.hero_hp = max(0, current_hp - hp_loss)
                            if target_player.hero_hp <= 0 and target_player.telegram_id not in dead:
                                dead.add(target_player.telegram_id)
                                death_causes[target_player.telegram_id] = "mashka"
                                death_visitors[target_player.telegram_id] = role_label(Role.MASHKA)
                            mashka_notices.append(
                                (
                                    actor_id,
                                    f"🧤 Balans yo'qligi sabab {self._tg_mention(target_player.telegram_id, target_player.display_name)}dan "
                                    f"♥️ {hp_loss} jon oldingiz. Qolgan jon: ♥️ {int(target_player.hero_hp or 0)}/{target_max_hp}",
                                )
                            )
                            mashka_target_notices.append(
                                (
                                    target_id,
                                    f"🧤 Mashka sizning 50% joningizni oldi: -♥️ {hp_loss}. "
                                    f"Qolgan jon: ♥️ {int(target_player.hero_hp or 0)}/{target_max_hp}",
                                )
                            )
                            mashka_group_lines.append(
                                f"🧤 Mashka {self._tg_mention(target_player.telegram_id, target_player.display_name)}ning 50% jonini oldi."
                            )
                            continue
                        amount = rng.choice(possible)
                        target_user.dollar -= amount
                        actor_user.dollar = int(actor_user.dollar or 0) + amount
                        self._record_dollar_transaction(
                            session,
                            target_user,
                            -amount,
                            "mashka_steal_out",
                            note=f"O'yin #{game.id}: Mashka o'g'irligi",
                            counterparty=actor_user,
                            chat_id=game.chat_id,
                        )
                        self._record_dollar_transaction(
                            session,
                            actor_user,
                            amount,
                            "mashka_steal_in",
                            note=f"O'yin #{game.id}: Mashka o'g'irligi",
                            counterparty=target_user,
                            chat_id=game.chat_id,
                        )
                        stolen_label = f"<tg-emoji emoji-id=\"5409048419211682843\">💵</tg-emoji> {amount} dollar"

                    mashka_notices.append(
                        (actor_id, f"🧤 Siz {self._tg_mention(target_player.telegram_id, target_player.display_name)}dan {stolen_label} o'g'irladingiz.")
                    )
                    mashka_target_notices.append(
                        (target_id, f"🧤 Mashka sizdan {stolen_label} o'g'irladi.")
                    )
                    mashka_group_lines.append(
                        f"🧤 Mashka kimdandir {stolen_label} o'g'irlab ketdi."
                    )

            joker_group_lines: list[str] = []
            for act in joker_actions:
                if not act.target_telegram_id:
                    continue
                actor_player = player_map.get(act.actor_telegram_id)
                target_player = player_map.get(act.target_telegram_id)
                if actor_player is None or target_player is None or not target_player.alive:
                    continue
                try:
                    details = json.loads(act.details or "{}")
                except (TypeError, ValueError):
                    details = {}
                if details.get("announced"):
                    continue
                result = details.get("result")
                if result is None:
                    details["target_card"] = "timeout"
                    details["result"] = "dead"
                    details["announced"] = True
                    act.details = json.dumps(details)
                    result = "dead"
                if result == "dead":
                    dead.add(target_player.telegram_id)
                    death_causes[target_player.telegram_id] = "joker"
                    death_visitors[target_player.telegram_id] = role_label(Role.JOKER)
                    joker_group_lines.append("🃏 Joker bugun hursand chunki karta o'yinida golib boldi.")
                elif result == "safe":
                    joker_group_lines.append("🃏 Joker bugun hafa chunki karta o'yinida golib bolmadi.")

            fairy_revive_lines: list[str] = []
            fairy_revive_notices: list[tuple[int, str]] = []
            fairy_revive_used = False
            for act in actions:
                if fairy_revive_used or act.action_type != ActionType.REVIVE.value or act.target_telegram_id is None:
                    continue
                actor = player_map.get(act.actor_telegram_id)
                target = player_map.get(act.target_telegram_id)
                if actor is None or target is None or target.alive or act.target_telegram_id not in dead:
                    continue
                fairy_revive_used = True
                dead.discard(act.target_telegram_id)
                death_causes.pop(act.target_telegram_id, None)
                death_visitors.pop(act.target_telegram_id, None)
                target.alive = True
                target.death_day = None
                fairy_revive_lines.append(
                    f"👼 Farishta {self._tg_mention(target.telegram_id, target.display_name)}ni qayta tiriltirdi."
                )
                fairy_revive_notices.append(
                    (act.actor_telegram_id, f"👼 Siz {self._tg_mention(target.telegram_id, target.display_name)}ni qayta tiriltirdingiz.")
                )
                fairy_revive_notices.append(
                    (target.telegram_id, "👼 Siz o'limdan qaytdingiz! Bu tunda yana o'yinda ishtirok etasiz.")
                )

            arson_group_lines: list[str] = []
            for actor_id, target_id in arson_actions:
                actor_player = player_map.get(actor_id)
                if actor_player is None or not actor_player.alive:
                    continue
                if target_id != actor_id:
                    arson_group_lines.append(f"{_ce('🧟', ZOMBIE_EMOJI_ID)} G'azabkor bu tunda yana bir nishonni belgiladi...")
                    continue

                marked_ids = {
                    marked_id
                    for marked_id in (
                        await session.execute(
                            select(NightAction.target_telegram_id).where(
                                NightAction.game_id == game_id,
                                NightAction.actor_telegram_id == actor_id,
                                NightAction.details == "arson",
                                NightAction.target_telegram_id.is_not(None),
                                NightAction.target_telegram_id != actor_id,
                                NightAction.night_number <= night,
                            )
                        )
                    ).scalars().all()
                    if marked_id in player_map
                }
                if len(marked_ids) < 3:
                    continue

                dead.add(actor_id)
                death_causes[actor_id] = "arsonist"
                death_visitors[actor_id] = role_label(Role.ARSONIST)
                actor_player.won = True
                arsonist_inferno_triggered = True
                arson_group_lines.append(
                    f"{_ce('🧟', ZOMBIE_EMOJI_ID)} G'azabkor {self._tg_mention(actor_player.telegram_id, actor_player.display_name)} alangani yoqdi!"
                )
                for marked_id in marked_ids:
                    marked_player = player_map.get(marked_id)
                    if marked_player is None or not marked_player.alive:
                        continue
                    dead.add(marked_id)
                    death_causes[marked_id] = "arsonist"
                    death_visitors[marked_id] = role_label(Role.ARSONIST)
                    marked_player.won = False
                    arson_group_lines.append(
                        f"🔥 {self._tg_mention(marked_player.telegram_id, marked_player.display_name)} G'azabkor alangasida yonib ketdi."
                    )

            mafia_fallback_as_don = False
            alive_don_ids = {
                p.telegram_id
                for p in alive_players
                if p.alive and Role(p.role) == Role.DON
            }
            don_blocked = bool(alive_don_ids & blocked)
            if don_blocked:
                # Kezuvchi Donni to'xtatgan bo'lsa, bu tunda mafiyaning boshqa ovozlari ham ishlamaydi.
                active_mafia_roles = {Role.DON}
                active_mafia_kills = []
            elif don_kills:
                active_mafia_roles = {Role.DON}
                active_mafia_kills = don_kills
            else:
                active_mafia_roles = {Role.MAFIA, Role.SPY, Role.HIRED_KILLER}
                active_mafia_kills = mafia_fallback_kills
                mafia_fallback_as_don = bool(mafia_fallback_kills)
            mafia_target = Counter(active_mafia_kills).most_common(1)
            if mafia_fallback_as_don and mafia_target:
                don_activity = self._night_activity_line(Role.DON, "kill")
                if don_activity:
                    night_activity_lines.append(don_activity)
            if mafia_target:
                target = mafia_target[0][0]
                target_player = player_map.get(target)
                if target_player:
                    if Role(target_player.role) == Role.WOLF:
                        target_player.role = Role.MAFIA.value
                        target_player.team = Team.MAFIA.value
                        transformed.append(f"{_ce('🐺', WOLF_EMOJI_ID)} Bo'ri mafiyaga aylandi")
                    elif target in healed and target_player.alive and target not in dead:
                        doctor_saved_targets.add(target)
                        healer_id = next(
                            (
                                actor_id
                                for actor_id, heal_target_id in doctor_heal_targets.items()
                                if heal_target_id == target
                            ),
                            None,
                        )
                        if healer_id is not None:
                            attacker_label = role_label(Role.DON) if mafia_fallback_as_don else role_label(Role.MAFIA)
                            doctor_save_notices.append((healer_id, target, target_player.telegram_id, attacker_label))
                    elif target not in guarded:
                        dead.add(target)
                        death_causes[target] = "mafia"
                        killer_actor = next(
                            (
                                player_map.get(action.actor_telegram_id)
                                for action in actions
                                if action.action_type == ActionType.KILL.value
                                and action.target_telegram_id == target
                                and action.actor_telegram_id in player_map
                                and Role(player_map[action.actor_telegram_id].role) in active_mafia_roles
                            ),
                            None,
                        )
                        if mafia_fallback_as_don:
                            death_visitors[target] = role_label(Role.DON)
                        elif killer_actor:
                            death_visitors[target] = role_label(killer_actor.role)
                        mafia_dead.add(target)

            killer_target = Counter(killer_kills).most_common(1)
            if killer_target:
                target = killer_target[0][0]
                target_player = player_map.get(target)
                if target_player:
                    if Role(target_player.role) == Role.WOLF:
                        dead.add(target)
                        death_causes[target] = "killer"
                        death_visitors[target] = role_label(Role.KILLER)
                    elif target in healed and target_player.alive:
                        doctor_saved_targets.add(target)
                        healer_id = next(
                            (
                                actor_id
                                for actor_id, heal_target_id in doctor_heal_targets.items()
                                if heal_target_id == target
                            ),
                            None,
                        )
                        if healer_id is not None:
                            doctor_save_notices.append((healer_id, target, target_player.telegram_id, role_label(Role.KILLER)))
                    elif target not in guarded and target_player.alive:
                        if target_player.telegram_id in defended:
                            pass
                        else:
                            dead.add(target)
                            death_causes[target] = "killer"
                            death_visitors[target] = role_label(Role.KILLER.value)

            for target in commissar_shots:
                target_player = player_map.get(target)
                if target_player is None:
                    continue
                if Role(target_player.role) == Role.WOLF:
                        target_player.role = Role.SERGEANT.value
                        target_player.team = Team.CITY.value
                        transformed.append(f"{_ce('🐺', WOLF_EMOJI_ID)} Bo'ri serjantga aylandi")
                else:
                    dead.add(target)
                    death_causes[target] = "commissar"
                    death_visitors[target] = role_label(Role.COMMISSAR.value)

            if dead:
                protected_users = {
                    user.telegram_id: user
                    for user in (
                        await session.execute(select(User).where(User.telegram_id.in_(list(dead))))
                    ).scalars().all()
                }
                for victim_id in list(dead):
                    user = protected_users.get(victim_id)
                    cause = death_causes.get(victim_id)
                    if user is None or cause is None:
                        continue
                    if cause == "killer" and user.use_killer_protection is not False and (user.killer_protection or 0) > 0:
                        if not await self.check_weapon_enabled(game.chat_id, "killer_protection"):
                            continue
                        user.killer_protection -= 1
                        dead.discard(victim_id)
                        death_causes.pop(victim_id, None)
                        death_visitors.pop(victim_id, None)
                        protected_notices.append((victim_id, "🧿 Qotildan himoya sizni qutqarib qoldi."))
                        protected_group_lines.append(f"{_ce('🧿', EYE_EMOJI_ID)} Kimdir qotildan himoyasini ishlatdi.")
                        self._add_game_log(
                            session,
                            game,
                            "killer_protection_used",
                            target=player_map.get(victim_id),
                            remaining_killer_protection=user.killer_protection,
                        )
                    elif cause in {"mafia", "commissar"} and user.use_protection is not False and (user.protection or 0) > 0:
                        if not await self.check_weapon_enabled(game.chat_id, "protection"):
                            continue
                        user.protection -= 1
                        dead.discard(victim_id)
                        mafia_dead.discard(victim_id)
                        death_causes.pop(victim_id, None)
                        death_visitors.pop(victim_id, None)
                        protected_notices.append((victim_id, "🛡 Himoya sizni qutqarib qoldi."))
                        if cause == "mafia":
                            protected_group_lines.append("🛡 Kimdir himoyasini ishlatdi.")
                        else:
                            player = player_map.get(victim_id)
                            if player:
                                protected_group_lines.append("🛡 Kimdir o'z himoyasini ishlatdi.")
                        self._add_game_log(
                            session,
                            game,
                            "protection_used",
                            target=player_map.get(victim_id),
                            cause=cause,
                            remaining_protection=user.protection,
                        )

            # Daydi sees what happened at the house he visited.
            witness_lines: list[tuple[int, str]] = []
            killed_targets = dead.copy()
            for observer_id, visited_id in visited.items():
                observer = player_map.get(observer_id)
                if observer is None:
                    continue
                if visited_id in killed_targets:
                    victim = player_map.get(visited_id)
                    if victim:
                        visitor = self._death_visitor_label(
                            death_causes.get(visited_id),
                            death_visitors.get(visited_id),
                        )
                        witness_lines.append(
                            (
                                observer.telegram_id,
                                f"{_ce('🍾', BOTTLE_EMOJI_ID)} Siz kimningdir jonsiz jasadi ustida "
                                f"{self._tg_mention(victim.telegram_id, victim.display_name)} - {role_label(victim.role)} "
                                f"yonida {visitor} turganini ko'rdingiz.",
                            )
                        )
                else:
                    don_visitors = [
                        player_map[visitor_id]
                        for visitor_id in visitors_by_target.get(visited_id, [])
                        if visitor_id in player_map and Role(player_map[visitor_id].role) == Role.DON
                    ]
                    if don_visitors:
                        target_player = player_map.get(visited_id)
                        don_player = don_visitors[0]
                        witness_lines.append(
                            (
                                observer.telegram_id,
                                f"{_ce('🍾', BOTTLE_EMOJI_ID)} Siz {self._tg_mention(target_player.telegram_id, target_player.display_name)}ning uyiga ichimlik uchun bordingiz, "
                                f"lekin u yerda {self._tg_mention(don_player.telegram_id, don_player.display_name)} - Don turganini ko'rdingiz.",
                            )
                        )
                    else:
                        witness_lines.append(
                            (
                                observer.telegram_id,
                                f"{_ce('🍾', BOTTLE_EMOJI_ID)} Siz shishani oldingiz va uyingizga qaytdingiz! Shubhali narsani ko'rmadingiz!",
                            )
                        )

            watcher_lines: list[tuple[int, str]] = []
            for watcher_id, watched_id in watched.items():
                watcher = player_map.get(watcher_id)
                watched_player = player_map.get(watched_id)
                if watcher is None or watched_player is None:
                    continue
                visitor_ids = [visitor_id for visitor_id in visitors_by_target.get(watched_id, []) if visitor_id in player_map]
                if visitor_ids:
                    if Role(watcher.role) == Role.JOURNALIST:
                        visitor_names = []
                        for visitor_id in visitor_ids:
                            visitor = player_map[visitor_id]
                            visitor_text = self._tg_mention(visitor.telegram_id, visitor.display_name)
                            if Role(visitor.role) != Role.COMMISSAR:
                                visitor_text += f" - {role_label(visitor.role)}"
                            visitor_names.append(visitor_text)
                    else:
                        visitor_names = [
                            self._tg_mention(visitor_id, player_map[visitor_id].display_name)
                            for visitor_id in visitor_ids
                        ]
                    text = (
                        f"🔎 Siz {self._tg_mention(watched_player.telegram_id, watched_player.display_name)}ni kuzatdingiz.\n"
                        "Uning oldiga kelganlar: " + ", ".join(visitor_names)
                    )
                else:
                    text = (
                        f"🔎 Siz {self._tg_mention(watched_player.telegram_id, watched_player.display_name)}ni kuzatdingiz.\n"
                        "Bu tunda uning oldiga hech kim kelmadi."
                    )
                watcher_lines.append((watcher_id, text))

            def pick_sorcerer_revenge_attacker(victim_id: int) -> tuple[int | None, Role | None]:
                mafia_targets = set(don_kills) | set(mafia_fallback_kills)
                if victim_id in mafia_targets:
                    # Mafia tomondan Afsungarga hujum bo'lsa qasos birinchi navbatda Donga tushadi.
                    # Don yo'q bo'lsa, aynan shu Afsungarni nishonga olgan mafia tomoni hujumchisi olinadi.
                    alive_don = next(
                        (
                            p
                            for p in alive_players
                            if Role(p.role) == Role.DON
                            and p.telegram_id in alive_ids
                        ),
                        None,
                    )
                    if alive_don is not None:
                        return alive_don.telegram_id, Role.DON
                    mafia_actor = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.KILL.value
                            and a.target_telegram_id == victim_id
                            and a.actor_telegram_id in player_map
                            and Role(player_map[a.actor_telegram_id].role)
                            in {Role.DON, Role.MAFIA, Role.SPY, Role.HIRED_KILLER}
                        ),
                        None,
                    )
                    if mafia_actor is not None:
                        return mafia_actor, Role(player_map[mafia_actor].role)

                if victim_id in killer_kills:
                    killer_actor = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.KILL.value
                            and a.details == "killer"
                            and a.target_telegram_id == victim_id
                            and a.actor_telegram_id in player_map
                        ),
                        None,
                    )
                    if killer_actor is not None:
                        return killer_actor, Role.KILLER

                if victim_id in commissar_shots:
                    shooter = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.SHOOT.value
                            and a.target_telegram_id == victim_id
                            and a.actor_telegram_id in player_map
                        ),
                        None,
                    )
                    if shooter is not None:
                        return shooter, Role.COMMISSAR

                return None, None

            sorcerer_revenge_candidates: list[tuple[int, int, Role | None]] = []
            for victim_id in list(dead):
                victim = player_map.get(victim_id)
                if victim and Role(victim.role) == Role.SORCERER:
                    attacker, attacker_role = pick_sorcerer_revenge_attacker(victim_id)
                    if attacker:
                        sorcerer_revenge_candidates.append((victim_id, attacker, attacker_role))

            for victim_id, attacker, attacker_role in sorcerer_revenge_candidates:
                sorcerer_player = player_map.get(victim_id)
                if sorcerer_player is not None:
                    sorcerer_player.sorcerer_revenge_used = True
                    sorcerer_player.won = attacker_role in {
                        Role.DON,
                        Role.MAFIA,
                        Role.SPY,
                        Role.HIRED_KILLER,
                        Role.KILLER,
                    }
                    attacker_player = player_map.get(attacker)
                    if attacker_player is not None:
                        role_text = role_label(attacker_player.role)
                        try:
                            await bot.send_message(
                                sorcerer_player.telegram_id,
                                f"🧙‍♂️ Sizni {role_text} oldirishga harakat qildi.",
                                reply_markup=await self.group_return_keyboard(bot, game.chat_id),
                            )
                        except TelegramForbiddenError:
                            pass
                if attacker in alive_ids and attacker not in dead:
                    dead.add(attacker)
                    death_causes[attacker] = "sorcerer"
                    death_visitors[attacker] = role_label(Role.SORCERER.value)
                    attacker_player = player_map.get(attacker)
                    if attacker_player is not None:
                        night_event_lines.append(
                            f"{_ce('💣', SKULL_EMOJI_ID)} Afsungar uni o'ldirgan "
                            f"{self._tg_mention(attacker_player.telegram_id, attacker_player.display_name)}ni "
                            "avtomatik jahannamga olib ketdi."
                        )

            sorcerer_judgement_prompts: list[tuple[int, int, int, str]] = []
            for victim_id in list(dead):
                victim = player_map.get(victim_id)
                if victim is None or Role(victim.role) != Role.MAQ:
                    continue
                attacker_id: Optional[int] = None
                attacker_role: Optional[Role] = None

                if victim_id in set(don_kills) | set(mafia_fallback_kills):
                    attacker_id = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.KILL.value
                            and a.target_telegram_id == victim_id
                            and a.actor_telegram_id in player_map
                            and Role(player_map[a.actor_telegram_id].role) == Role.DON
                        ),
                        None,
                    )
                    if attacker_id is not None:
                        attacker_role = Role.DON
                if attacker_id is None and victim_id in killer_kills:
                    attacker_id = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.KILL.value
                            and a.details == "killer"
                            and a.target_telegram_id == victim_id
                        ),
                        None,
                    )
                    if attacker_id is not None:
                        attacker_role = Role.KILLER
                if attacker_id is None and victim_id in commissar_shots:
                    attacker_id = next(
                        (
                            a.actor_telegram_id
                            for a in actions
                            if a.action_type == ActionType.SHOOT.value and a.target_telegram_id == victim_id
                        ),
                        None,
                    )
                    if attacker_id is not None:
                        attacker_role = Role.COMMISSAR

                if attacker_id is None or attacker_role is None:
                    continue

                dead.discard(victim_id)
                death_causes.pop(victim_id, None)
                death_visitors.pop(victim_id, None)
                sorcerer_judgement_prompts.append((game.id, victim_id, attacker_id, role_label(attacker_role)))

            scored_night_actor_ids: set[int] = set()
            for act in actions:
                if act.action_type == ActionType.SKIP.value or act.actor_telegram_id in scored_night_actor_ids:
                    continue
                actor = player_map.get(act.actor_telegram_id)
                if actor is None or not actor.alive:
                    continue
                if self._night_prompt_for_player(game_id, night, actor, alive_players) is None:
                    continue
                scored_night_actor_ids.add(act.actor_telegram_id)
                self._add_activity_points(session, game, actor, 10, "night_action")

            night_actor_ids = {
                act.actor_telegram_id
                for act in actions
                if act.actor_telegram_id in alive_ids
            }
            mine_rows = (
                await session.execute(
                    select(NightAction.actor_telegram_id, NightAction.target_telegram_id).where(
                        NightAction.game_id == game_id,
                        NightAction.action_type == ActionType.MINE.value,
                        NightAction.target_telegram_id.is_not(None),
                    )
                )
            ).all()
            miner_visits: dict[int, set[int]] = defaultdict(set)
            for actor_id, mine_number in mine_rows:
                if mine_number is not None:
                    miner_visits[actor_id].add(mine_number)
            arson_rows = (
                await session.execute(
                    select(NightAction.actor_telegram_id, NightAction.target_telegram_id).where(
                        NightAction.game_id == game_id,
                        NightAction.details == "arson",
                        NightAction.target_telegram_id.is_not(None),
                    )
                )
            ).all()
            arson_marks: dict[int, set[int]] = defaultdict(set)
            for actor_id, target_id in arson_rows:
                if target_id is not None and actor_id != target_id:
                    arson_marks[actor_id].add(target_id)

            dead_players = [
                player_map[player_id]
                for player_id in sorted({p_id for p_id in player_map if p_id not in alive_ids})
                if player_id in player_map
            ]
            fairy_revive_used_ids = {
                row.actor_telegram_id
                for row in (
                    await session.execute(
                        select(NightAction.actor_telegram_id).where(
                            NightAction.game_id == game_id,
                            NightAction.action_type == ActionType.REVIVE.value,
                        )
                    )
                ).all()
            }
            for player in alive_players:
                player_id = player.telegram_id
                role = Role(player.role)
                prompt = self._night_prompt_for_player(
                    game_id,
                    night,
                    player,
                    alive_players,
                    miner_visits,
                    arson_marks,
                    dead_players,
                    fairy_revive_used=player_id in fairy_revive_used_ids,
                )
                if (
                    player_id in dead
                    or player_id in blocked
                    or prompt is None
                    or role in self._night_inactivity_exempt_roles
                    or player_id in night_actor_ids
                ):
                    player.inactive_rounds = 0
                    continue

                player.inactive_rounds = (player.inactive_rounds or 0) + 1
                if player.inactive_rounds >= self._inactive_elimination_rounds:
                    dead.add(player_id)
                    death_causes[player_id] = "inactive"
                    player.left_game = True
                    player.awaiting_last_words = False
                    player.last_words = None
                    self._add_game_log(
                        session,
                        game,
                        "player_removed_for_night_inactivity",
                        actor=player,
                        inactive_nights=player.inactive_rounds,
                    )

            couple_death_lines = await self._expand_tournament_couple_deaths(
                session,
                game,
                alive_players,
                dead,
                death_causes=death_causes,
                death_visitors=death_visitors,
            )
            night_event_lines.extend(couple_death_lines)

            for dead_id in dead:
                pl = player_map.get(dead_id)
                if pl:
                    pl.alive = False
                    pl.death_day = game.day_number + 1
                    if dead_id in mafia_dead:
                        if pl.last_words:
                            night_event_lines.append(self._last_words_line(pl, pl.last_words))
                        else:
                            pl.awaiting_last_words = True
                            last_words_prompts.append((pl.telegram_id, pl.display_name))

            succession_events = self._apply_role_successions(alive_players, dead)
            night_event_lines.extend(line for line, _, _ in succession_events)
            night_event_lines.extend(fairy_revive_lines)

            game.phase = GamePhase.DAY_DISCUSSION.value
            game.day_number += 1
            self._add_game_log(
                session,
                game,
                "night_resolved",
                dead_ids=sorted(dead),
                transformed=transformed,
                blocked_ids=sorted(blocked),
                healed_ids=sorted(healed),
                guarded_ids=sorted(guarded),
                actions_count=len(actions),
            )
            await session.commit()

            chat_id = game.chat_id
            lang = await self.get_group_language(chat_id)
            alive_after_night = [player for player in alive_players if player.alive]
            dead_players = [player_map[player_id] for player_id in dead if player_id in player_map]
            day_caption = self._build_day_intro_text(game.day_number)
            is_tournament = await self._is_tournament_game_in_session(session, game_id)
            is_teamgame = await self._is_team_game_in_session(session, game_id)
            alive_status = self._build_alive_status_text(alive_after_night, game, tournament=(is_tournament or is_teamgame))
            story_messages = self._build_night_story_messages(
                dead_players=dead_players,
                transformed=transformed,
                night_activity_lines=night_activity_lines,
                night_event_lines=night_event_lines,
                death_causes=death_causes,
                death_visitors=death_visitors,
            )
            doctor_idle_actor_ids = sorted(
                {
                    actor_id
                    for actor_id, target_id in doctor_heal_targets.items()
                    if target_id not in doctor_saved_targets or target_id in dead
                }
            )
            mistress_visit_ids = [
                player_id
                for player_id in mistress_visit_targets
                if player_id in player_map and player_id not in dead
            ]
            succession_notices = list(succession_events)
            doctor_save_notices = list(doctor_save_notices)
            sorcerer_judgement_prompts = list(dict.fromkeys(sorcerer_judgement_prompts))

        await self._clear_night_prompt_buttons(bot, game_id, night)
        try:
            await self._send_phase_media(
                bot,
                chat_id,
                is_night=False,
                lang=lang,
                game_id=game_id,
                caption_override=day_caption,
            )
        except Exception:
            logger.exception("Failed to send day phase media game_id=%s", game_id)
        await self._safe_send_message(bot, chat_id, alive_status)
        for story_message in story_messages:
            await self._safe_send_message(bot, chat_id, story_message)
            await asyncio.sleep(0.15)

        for doctor_id, saved_id, saved_telegram_id, attacker_label in doctor_save_notices:
            saved_player = player_map.get(saved_id)
            saved_name = self._tg_mention(
                saved_telegram_id,
                saved_player.display_name if saved_player else str(saved_telegram_id),
            )
            try:
                await bot.send_message(
                    doctor_id,
                    f"🩺 Siz {saved_name}ni {attacker_label}dan qutqardingiz.",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
            except Exception:
                logger.exception("Failed to deliver doctor save notification to doctor")

            try:
                await bot.send_message(
                    saved_telegram_id,
                    f"🩺 Shifokor sizni {attacker_label}dan qutqarib qoldi.",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
            except Exception:
                logger.exception("Failed to deliver doctor save notification to saved target")

        for telegram_id in doctor_idle_actor_ids:
            if telegram_id in dead:
                continue
            try:
                await bot.send_message(
                    telegram_id,
                    "🌙 Bugun tinch tun o'tdi. Sizning yordamingiz kerak bo'lmadi.",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass
            except Exception:
                logger.exception("Failed to deliver doctor idle notification")

        for telegram_id in mistress_visit_ids:
            try:
                await bot.send_message(
                    telegram_id,
                    '"Ana 💊dori tasir qila boshladi endi sen bir kun uxlaysan...", - dedi 💃 Kezuvchi',
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in protected_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in prank_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in miner_result_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in snitch_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in hojiaka_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in hojiaka_target_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in mashka_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in mashka_target_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, text in fairy_revive_notices:
            try:
                await bot.send_message(
                    telegram_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        now_mono = self._monotonic()
        for game_id_prompt, sorcerer_id, attacker_id, attacker_role_name in sorcerer_judgement_prompts:
            self._pending_sorcerer_judgements[(game_id_prompt, sorcerer_id, attacker_id)] = (
                now_mono + 3600.0,
                attacker_role_name,
            )
            try:
                await bot.send_message(
                    sorcerer_id,
                    f"🧙‍♂️ {attacker_role_name} sizni oldirishga harakat qildi.\nQaroringizni tanlang:",
                    reply_markup=sorcerer_judgement_keyboard(
                        game_id=game_id_prompt,
                        sorcerer_id=sorcerer_id,
                        attacker_id=attacker_id,
                    ),
                )
            except TelegramForbiddenError:
                pass

        for line in miner_group_lines:
            await self._safe_send_message(bot, chat_id, line)

        for line in dict.fromkeys(protected_group_lines):
            await self._safe_send_message(bot, chat_id, line)

        for line in snitch_group_lines:
            await self._safe_send_message(bot, chat_id, line)

        for line in dict.fromkeys(hojiaka_group_lines):
            await self._safe_send_message(bot, chat_id, line)

        for line in dict.fromkeys(mashka_group_lines):
            await self._safe_send_message(bot, chat_id, line)

        for line in dict.fromkeys(joker_group_lines):
            await self._safe_send_message(bot, chat_id, line)

        for line in dict.fromkeys(arson_group_lines):
            await self._safe_send_message(bot, chat_id, line)

        for _, telegram_id, new_role in succession_notices:
            try:
                await self._safe_send_message(
                    bot,
                    telegram_id,
                    self._private_role_text(new_role),
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for telegram_id, _ in last_words_prompts:
            try:
                await bot.send_message(
                    telegram_id,
                    "Sizni shavqatsizlarcha o'ldirishdi :(\nSo'nggi so'zingni aytishing mumkin:",
                )
            except TelegramForbiddenError:
                pass

        for commissar_id, target_id in checks:
            async with self.session_factory() as s2:
                target = (
                    await s2.execute(
                        select(GamePlayer).where(GamePlayer.game_id == game_id, GamePlayer.telegram_id == target_id)
                    )
                ).scalar_one_or_none()
                target_user = (
                    await s2.execute(select(User).where(User.telegram_id == target_id))
                ).scalar_one_or_none()
                hidden_by_item = False
                if target_user is not None and target_user.use_mask is not False and (target_user.mask or 0) > 0:
                    target_user.mask -= 1
                    hidden_by_item = True
                    await s2.commit()
                elif target_user is not None and target_user.use_fake_document is not False and (target_user.fake_document or 0) > 0:
                    target_user.fake_document -= 1
                    hidden_by_item = True
                    await s2.commit()
                sergeant_ids = (
                    await s2.execute(
                        select(GamePlayer.telegram_id).where(
                            GamePlayer.game_id == game_id,
                            GamePlayer.alive.is_(True),
                            GamePlayer.role == Role.SERGEANT.value,
                            GamePlayer.telegram_id != commissar_id,
                        )
                    )
                ).scalars().all()
            if target is None:
                continue
            seen_role = Role(target.role)
            if Role(target.role) == Role.SPY:
                seen_role = Role.CITIZEN
            if target_id in defended and target.team == Team.MAFIA.value:
                seen_role = Role.CITIZEN
            if hidden_by_item:
                seen_role = Role.CITIZEN
                try:
                    await bot.send_message(
                        target_id,
                        "🎭 Maska yoki 📁 soxta hujjat komissar tekshiruvini yashirdi.",
                        reply_markup=await self.group_return_keyboard(bot, chat_id),
                    )
                except TelegramForbiddenError:
                    pass
            try:
                check_text = self._commissar_check_result_text(target, seen_role)
                await bot.send_message(commissar_id, check_text)
            except TelegramForbiddenError:
                pass
            for sergeant_id in sergeant_ids:
                try:
                    await bot.send_message(
                        sergeant_id,
                        check_text,
                        reply_markup=await self.group_return_keyboard(bot, chat_id),
                    )
                except TelegramForbiddenError:
                    pass
            try:
                await bot.send_message(
                    target_id,
                    "🕵🏼 Kimdir rolingizga judayam qiziqdi.",
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for observer_id, text in witness_lines:
            try:
                await bot.send_message(
                    observer_id,
                    text,
                    reply_markup=await self.group_return_keyboard(bot, chat_id),
                )
            except TelegramForbiddenError:
                pass

        for watcher_id, text in watcher_lines:
            try:
                await bot.send_message(watcher_id, text)
            except TelegramForbiddenError:
                pass

        if arsonist_inferno_triggered:
            await self.finish_game(bot, game_id, Team.KILLER)
            return

        winner = await self.check_winner(game_id)
        if winner:
            await self.finish_game(bot, game_id, winner)
            return

        try:
            await self.send_hero_phase_prompts(bot, game_id)
        except Exception:
            logger.exception("Failed to send hero phase prompts game_id=%s", game_id)

        discussion_timeout = await self.group_timeout(chat_id, "day_discussion_timeout")
        scheduler.add_job(
            self.start_voting,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=discussion_timeout),
            args=[bot, game_id],
            id=f"discussion_end_{game_id}",
            replace_existing=True,
            misfire_grace_time=120,
        )


