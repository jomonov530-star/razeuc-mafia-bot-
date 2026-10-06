"""GameEngine facade composing modular engine mixins."""
from __future__ import annotations

import logging
import asyncio

from app.engine.core import CoreMixin
from app.engine.registration import RegistrationMixin
from app.engine.phase_night import NightPhaseMixin
from app.engine.phase_day import DayPhaseMixin
from app.engine.victory import VictoryMixin
from app.engine.hero_ops import HeroOpsMixin
from app.engine.economy_ops import EconomyOpsMixin
from app.engine.admin_ops import AdminOpsMixin
from app.engine.social_ops import SocialOpsMixin

# Re-export key constants for backward-compatibility with handlers
from app.engine.admin_ops import (
    ADMIN_GROUP_ID_KEY,
    CHANNEL_GIFTS_ENABLED_PREFIX,
    DIAMOND_LOG_LAST_SENT_ID_KEY,
    DIAMOND_LOG_MIN_AMOUNT,
    PREMIUM_RESET_INTERVAL_MINUTES_KEY,
)
from app.engine.economy_ops import (
    GAMBLE_ENABLED_KEY,
    GAMBLE_GROUP_ID_KEY,
    GAMBLE_GROUP_LINK_KEY,
    GAMBLE_GROUP_PAY_DAYS,
    GAMBLE_GROUP_WEEK_PRICE_DIAMONDS,
    GAMBLE_LOSS_VOICE_FILE_ID_KEY,
    GAMBLE_PAID_GROUP_PREFIX,
    GAMBLE_WIN_VOICE_FILE_ID_KEY,
)
from app.engine.hero_ops import HERO_INFO_HIDDEN_PREFIX
from app.engine.registration import TEAM_GAME_PREFIX, TOURNAMENT_GAME_PREFIX
from app.engine.social_ops import (
    BANK_EMOJI_ID,
    BOTTLE_EMOJI_ID,
    CROSS_EMOJI_ID,
    DANCER_EMOJI_ID,
    DIAMOND_EMOJI_ID,
    DOLLAR_EMOJI_ID,
    DRUG_EMOJI_ID,
    EYE_EMOJI_ID,
    GIFT_EMOJI_ID,
    GUN_EMOJI_ID,
    INVISIBLE_NAME_CHARS,
    MASK_EMOJI_ID,
    NOTE_EMOJI_ID,
    POLICE_EMOJI_ID,
    SEARCH_EMOJI_ID,
    SKULL_EMOJI_ID,
    SLEEP_EMOJI_ID,
    SNITCH_EMOJI_ID,
    STAR_EMOJI_ID,
    SWORD_EMOJI_ID,
    SYRINGE_EMOJI_ID,
    TARGET_EMOJI_ID,
    WELCOME_DEFAULT_TEXT,
    WELCOME_ENABLED_KEY,
    WELCOME_MEDIA_FILE_ID_KEY,
    WELCOME_MEDIA_TYPE_KEY,
    WELCOME_TEXT_KEY,
    WOLF_EMOJI_ID,
    ZOMBIE_EMOJI_ID,
    _ce,
)

logger = logging.getLogger(__name__)


class GameEngine(
    CoreMixin,
    RegistrationMixin,
    NightPhaseMixin,
    DayPhaseMixin,
    VictoryMixin,
    HeroOpsMixin,
    EconomyOpsMixin,
    AdminOpsMixin,
    SocialOpsMixin,
):
    """Unified Mafia GameEngine composed from modular mixin classes.

    Provides 100% backward compatibility for all existing handlers and main.py.
    """

    pass
