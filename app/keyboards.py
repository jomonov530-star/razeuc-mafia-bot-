from __future__ import annotations

import html
import re
from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.enums import Role
from app.roles import ACTIVE_ROLE_POOL, SHOP_ROLE_CATALOG, role_label
from app.texts import t

DIAMOND_BUTTON_EMOJI = "💎"
DOLLAR_BUTTON_EMOJI = "💵"
DIAMOND_BUTTON_EMOJI_ID = "5427168083074628963"
DOLLAR_BUTTON_EMOJI_ID = "5409048419211682843"

# Premium emoji IDs provided by user (order matches profile emoji list)
PREMIUM_PROFILE_EMOJI_IDS = [
    "5415897487594509180",  # 🛡
    "5416094446204768079",  # 🧿
    "5400250414929041085",  # ⚖️
    "5415593996615439212",  # 💊
    "5463172695132745432",  # 📦
    "5370695074222985162",  # 🎭
    "5345987742276797245",  # 📁
    "5371063968964037721",  # 🛒
    "5427168083074628963",  # 💎 (diamond)
    "5409048419211682843",  # 💵 (dollar)
    "5445221832074483553",  # 🥷
    "5203996991054432397",  # 🎁
    "5415772375197174070",  # 🎲
    "5413672733189886746",  # ⭐
]

# Map profile fields / buttons to premium emoji ids
PROFILE_EMOJI_BY_FIELD = {
    "use_protection": PREMIUM_PROFILE_EMOJI_IDS[0],
    "use_killer_protection": PREMIUM_PROFILE_EMOJI_IDS[1],
    "use_vote_protection": PREMIUM_PROFILE_EMOJI_IDS[2],
    "use_drug_protection": PREMIUM_PROFILE_EMOJI_IDS[3],
    "use_miner_protection": PREMIUM_PROFILE_EMOJI_IDS[4],
    "use_mask": PREMIUM_PROFILE_EMOJI_IDS[5],
    "use_fake_document": PREMIUM_PROFILE_EMOJI_IDS[6],
    "shop": PREMIUM_PROFILE_EMOJI_IDS[7],
    "diamond": PREMIUM_PROFILE_EMOJI_IDS[8],
    "dollar": PREMIUM_PROFILE_EMOJI_IDS[9],
    "hero": PREMIUM_PROFILE_EMOJI_IDS[10],
    "gifts": PREMIUM_PROFILE_EMOJI_IDS[11],
    "premium_groups": PREMIUM_PROFILE_EMOJI_IDS[12],
    "vip": PREMIUM_PROFILE_EMOJI_IDS[13],
}


def diamond_icon_button(text: str, **kwargs: object) -> InlineKeyboardButton:
    button_text = text if text.startswith("💎") else f"💎 {text}"
    return InlineKeyboardButton(text=button_text, icon_custom_emoji_id=DIAMOND_BUTTON_EMOJI_ID, **kwargs)


def dollar_icon_button(text: str, **kwargs: object) -> InlineKeyboardButton:
    button_text = text if text.startswith("💵") else f"💵 {text}"
    return InlineKeyboardButton(text=button_text, icon_custom_emoji_id=DOLLAR_BUTTON_EMOJI_ID, **kwargs)


def currency_icon_button(text: str, currency: str, **kwargs: object) -> InlineKeyboardButton:
    if currency == "diamonds":
        return diamond_icon_button(text, **kwargs)
    return dollar_icon_button(text, **kwargs)


def safe_text(text: str, limit: int) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"

JOKER_CARD_LABELS = {
    1: "♠️",
    2: "♥️",
    3: "♦️",
    4: "♣️",
}

LANGS = [
    ("az", "🇦🇿 Azərbaycanca"),
    ("tr", "🇹🇷 Türkçe"),
    ("en", "🇺🇸 English"),
    ("ru", "🇷🇺 Русский"),
    ("ua", "🇺🇦 Український"),
    ("kz", "🇰🇿 Қазақ"),
    ("uz", "🇺🇿 O'zbek tili"),
    ("id", "🇮🇩 Indonesia"),
]


def _clean_bot_username(username: str) -> str:
    return username.strip().lstrip("@")


def language_keyboard(scope: str = "user", chat_id: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = []
    for code, label in LANGS:
        suffix = f"{scope}:{code}:{chat_id or 0}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"lang:{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_menu_keyboard(
    lang: str,
    settings: Settings,
    is_admin: bool = False,
    news_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    add_url = f"https://t.me/{_clean_bot_username(settings.bot_username)}?startgroup=true"
    rows = [
        [InlineKeyboardButton(text=t(lang, "add_to_group"), url=add_url)],
        [InlineKeyboardButton(text=t(lang, "premium_groups"), callback_data="premium:info")],
        [
            InlineKeyboardButton(text=t(lang, "lang"), callback_data="lang:menu:user:0", style="success"),
            InlineKeyboardButton(text=t(lang, "rules_btn"), callback_data="rules:show", style="success"),
        ],
    ]
    if news_url:
        rows.insert(3, [InlineKeyboardButton(text=t(lang, "news"), url=news_url, style="success")])
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛡 Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _toggle_button(icon: str, field: str, user: object | None) -> InlineKeyboardButton:

    """Create a toggle button with standard emoji fallback text for non-Premium users,
    plus custom emoji ID for Telegram Premium custom emoji rendering.
    """
    enabled = getattr(user, field, True) is not False
    kwargs = {"style": "primary" if enabled else "danger"}
    emoji_id = PROFILE_EMOJI_BY_FIELD.get(field)
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(text=icon, callback_data=f"invtoggle:{field}", **kwargs)


def profile_dashboard_keyboard(
    settings: Settings,
    user: object | None = None,
    is_admin: bool = False,
    news_url: Optional[str] = None,
    has_hero: bool = False,
    show_create_clan: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            _toggle_button("🛡", "use_protection", user),
            _toggle_button("🧿", "use_killer_protection", user),
            _toggle_button("⚖️", "use_vote_protection", user),
            _toggle_button("💊", "use_drug_protection", user),
            _toggle_button("📦", "use_miner_protection", user),
            _toggle_button("🎭", "use_mask", user),
            _toggle_button("📁", "use_fake_document", user),
        ],
        [InlineKeyboardButton(text="🛒 Do'kon", icon_custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get("shop"), callback_data="shop:open", style="primary")],
        [
            diamond_icon_button("Xarid qilish", callback_data="diamond:shop", style="primary"),
            dollar_icon_button("Xarid qilish", callback_data="dollar:shop", style="primary"),
        ],
        *([[InlineKeyboardButton(text="🥷 Mening geroyim", icon_custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get("hero"), callback_data="hero:panel")]] if has_hero else []),
        [InlineKeyboardButton(text="🎁 Mening giftlarim", icon_custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get("gifts"), callback_data="shop:gifts", style="primary")],
        [InlineKeyboardButton(text="🎲 Premium guruhlar", icon_custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get("premium_groups"), callback_data="premium:info", style="primary")],
        [InlineKeyboardButton(text="👑 VIP user", icon_custom_emoji_id=PROFILE_EMOJI_BY_FIELD.get("vip"), callback_data="vip:open", style="primary")],
    ]
    if news_url:
        rows.append([InlineKeyboardButton(text="Yangiliklar ↗", url=news_url, style="success")])
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛡 Admin panel", callback_data="owner:panel", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def rules_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="start:back")],
        ]
    )


def couple_request_keyboard(chat_id: int, requester_id: int, target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💞 Rozi bo'lish",
                    callback_data=f"para:accept:{chat_id}:{requester_id}:{target_id}",
                ),
                InlineKeyboardButton(
                    text="💔 Rad etish",
                    callback_data=f"para:reject:{chat_id}:{requester_id}:{target_id}",
                ),
            ],
        ]
    )


def credit_menu_keyboard(has_active_loan: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_active_loan:
        rows.append([InlineKeyboardButton(text="💵 Kreditni so'ndirish", callback_data="credit:repay")])
    else:
        rows.extend(
            [
                [
                    InlineKeyboardButton(text="💵 1000", callback_data="credit:amount:1000"),
                    InlineKeyboardButton(text="💵 2500", callback_data="credit:amount:2500"),
                ],
                [
                    InlineKeyboardButton(text="💵 5000", callback_data="credit:amount:5000"),
                    InlineKeyboardButton(text="💵 7500", callback_data="credit:amount:7500"),
                ],
                [InlineKeyboardButton(text="💵 10000", callback_data="credit:amount:10000")],
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Dollar bo'limi", callback_data="dollar:shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_days_keyboard(amount: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    days = list(range(1, 8))
    for idx in range(0, len(days), 2):
        rows.append(
            [
                InlineKeyboardButton(text=f"{day} kun", callback_data=f"credit:days:{amount}:{day}")
                for day in days[idx:idx + 2]
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Kredit", callback_data="credit:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credit_confirm_keyboard(amount: int, days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Kredit olish", callback_data=f"credit:take:{amount}:{days}")],
            [InlineKeyboardButton(text="◀️ Muddatni tanlash", callback_data=f"credit:amount:{amount}")],
        ]
    )


ROLE_INFO_ORDER: tuple[Role, ...] = (
    Role.BOSS_ZOMBIE,
    Role.ZOMBIE,
    Role.ZOMBIE_RESCUER,
    Role.VIROLOGIST,
    Role.QUARANTINE_OFFICER,
    Role.VACCINATOR,
    Role.IMMUNE,
    Role.MUTANT_ZOMBIE,
    Role.INFECTOR,
    Role.HUMAN,
    Role.SORCERER,
    Role.SPY,
    Role.WOLF,
    Role.BUM,
    Role.DOCTOR,
    Role.DON,
    Role.MAYOR,
    Role.JESTER,
    Role.WATCHER,
    Role.JOURNALIST,
    Role.MISTRESS,
    Role.COMMISSAR,
    Role.MAFIA,
    Role.MINER,
    Role.PRANKSTER,
    Role.JOKER,
    Role.JUDGE,
    Role.KILLER,
    Role.LUCKY,
    Role.SERGEANT,
    Role.SNITCH,
    Role.ARSONIST,
    Role.CITIZEN,
    Role.LAWYER,
    Role.MAQ,
    Role.HIRED_KILLER,
    Role.CROOK,
    Role.GUARD,
    Role.HOJIAKA,
    Role.MASHKA,
    Role.FAIRY,
)


def roles_menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    buttons = [
        InlineKeyboardButton(text=role_label(role), callback_data=f"roles:info:{role.value}")
        for role in ROLE_INFO_ORDER
    ]
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index:index + 2])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="start:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Ortga", callback_data="roles:list")],
            [InlineKeyboardButton(text="🏠 User panel", callback_data="start:back")],
        ]
    )


def commands_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Profil", callback_data="profile:open"),
                InlineKeyboardButton(text="🃏 Qoidalar", callback_data="rules:show"),
            ],
            [
                dollar_icon_button("Dollar", callback_data="dollar:shop"),
                diamond_icon_button("Almaz", callback_data="diamond:shop"),
            ],
            [InlineKeyboardButton(text="◀️ User panel", callback_data="profile:open")],
        ]
    )


def lobby_keyboard(
    lang: str,
    game_id: int,
    bot_username: str,
    chat_id: int,
    active: bool = True,
    tournament: bool = False,
    teamgame: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    if not active:
        return None
    bot_username = _clean_bot_username(bot_username)
    if teamgame:
        blue_link = f"https://t.me/{bot_username}?start=jointeam_{game_id}_{chat_id}_blue"
        red_link = f"https://t.me/{bot_username}?start=jointeam_{game_id}_{chat_id}_red"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔵 Qo'shilish", url=blue_link),
                    InlineKeyboardButton(text="🔴 Qo'shilish", url=red_link),
                ]
            ]
        )
    deep_link = f"https://t.me/{bot_username}?start=join_{game_id}_{chat_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "join_btn"), url=deep_link)]]
    )


def go_private_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Bot-ga o'tish ↗", url=f"https://t.me/{_clean_bot_username(settings.bot_username)}")],
        ]
    )


def go_role_private_keyboard(settings: Settings, game_id: int, text: str = "Rol haqida") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    url=f"https://t.me/{_clean_bot_username(settings.bot_username)}",
                )
            ],
        ]
    )


def parse_player_button(raw_name: str) -> tuple[str, Optional[str]]:
    """Clean player display name and extract custom emoji ID for inline keyboard buttons.

    Telegram InlineKeyboardButton `text` does not support HTML tags (<tg-emoji>, <b>, etc.).
    To render a custom emoji on a button, `icon_custom_emoji_id` must be used.
    This helper:
    1. Extracts any custom emoji ID from `<tg-emoji emoji-id="...">` or numeric badge.
    2. Strips all HTML tags and unescapes entities.
    3. Returns (clean_name, custom_emoji_id).
    """
    if not raw_name:
        return ("O'yinchi", None)

    emoji_id: Optional[str] = None

    # 1. Extract from <tg-emoji emoji-id="(\d+)">...</tg-emoji>
    tg_emoji_match = re.search(r'<tg-emoji[^>]*emoji-id=["\']?(\d+)["\']?[^>]*>(.*?)</tg-emoji>', raw_name, re.DOTALL)
    if tg_emoji_match:
        emoji_id = tg_emoji_match.group(1)
        raw_name = raw_name[:tg_emoji_match.start()] + raw_name[tg_emoji_match.end():]
    else:
        tag_match = re.search(r'emoji-id=["\']?(\d+)["\']?', raw_name)
        if tag_match:
            emoji_id = tag_match.group(1)
            raw_name = re.sub(r'</?tg-emoji[^>]*>', '', raw_name)

    # 2. Strip any other HTML tags (<b>, </i>, etc.)
    clean = re.sub(r'<[^>]+>', '', raw_name)
    clean = html.unescape(clean)

    # 3. Check for standalone long digit sequence (17-21 digits Telegram emoji ID) that leaked into text
    id_match = re.search(r'\b(\d{17,21})\b', clean)
    if id_match:
        if not emoji_id:
            emoji_id = id_match.group(1)
        clean = clean.replace(id_match.group(1), '')

    clean = " ".join(clean.split()).strip()
    if not clean:
        clean = "O'yinchi"

    return clean, emoji_id


def go_vote_private_keyboard(settings: Settings, game_id: int) -> InlineKeyboardMarkup:
    bot_username = _clean_bot_username(settings.bot_username)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🗳 Ovoz berish (@{bot_username})",
                    url=f"https://t.me/{bot_username}",
                )
            ],
        ]
    )


def group_url_from_chat_id(chat_id: int) -> str:
    internal_id = str(chat_id)
    if internal_id.startswith("-100"):
        internal_id = internal_id[4:]
    elif internal_id.startswith("-"):
        internal_id = internal_id[1:]
    return f"https://t.me/c/{internal_id}"


def go_group_keyboard(chat_id: int, group_url: Optional[str] = None) -> InlineKeyboardMarkup:
    url = group_url or group_url_from_chat_id(chat_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Guruhga o'tish", url=url)],
        ]
    )


def target_keyboard(prefix: str, game_id: int, actor_id: int, choices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for target_id, name in choices:
        clean_name, emoji_id = parse_player_button(name)
        kwargs = {}
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        rows.append([
            InlineKeyboardButton(
                text=clean_name,
                callback_data=f"act:{prefix}:{game_id}:{actor_id}:{target_id}",
                **kwargs,
            )
        ])
    rows.append([InlineKeyboardButton(text="O'tkazib yuborish", callback_data=f"skip:night:{game_id}:{actor_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def joker_death_card_keyboard(game_id: int, actor_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🃏 {JOKER_CARD_LABELS[idx]}", callback_data=f"act:joker_card:{game_id}:{actor_id}:{idx}")]
        for idx in (1, 2, 3, 4)
    ]
    rows.append([InlineKeyboardButton(text="O'tkazib yuborish", callback_data=f"skip:night:{game_id}:{actor_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def joker_target_keyboard(game_id: int, actor_id: int, choices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for target_id, name in choices:
        clean_name, emoji_id = parse_player_button(name)
        kwargs = {}
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        rows.append([
            InlineKeyboardButton(
                text=clean_name,
                callback_data=f"act:joker_target:{game_id}:{actor_id}:{target_id}",
                **kwargs,
            )
        ])
    rows.append([InlineKeyboardButton(text="O'tkazib yuborish", callback_data=f"skip:night:{game_id}:{actor_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def joker_victim_card_keyboard(game_id: int, target_id: int, actor_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🃏 {JOKER_CARD_LABELS[idx]}", callback_data=f"jokerpick:{game_id}:{target_id}:{actor_id}:{idx}")]
        for idx in (1, 2, 3, 4)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sorcerer_hang_revenge_keyboard(
    game_id: int,
    sorcerer_id: int,
    choices: list[tuple[int, str]],
) -> InlineKeyboardMarkup:
    rows = []
    for target_id, name in choices:
        clean_name, emoji_id = parse_player_button(name)
        kwargs = {}
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        rows.append([
            InlineKeyboardButton(
                text=clean_name,
                callback_data=f"sorhang:{game_id}:{sorcerer_id}:{target_id}",
                **kwargs,
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sorcerer_judgement_keyboard(
    game_id: int,
    sorcerer_id: int,
    attacker_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kechirish",
                    callback_data=f"sorjudge:{game_id}:{sorcerer_id}:{attacker_id}:forgive",
                ),
                InlineKeyboardButton(
                    text="💀 Oldirish",
                    callback_data=f"sorjudge:{game_id}:{sorcerer_id}:{attacker_id}:kill",
                ),
            ]
        ]
    )


def miner_keyboard(game_id: int, actor_id: int, visited_mines: set[int] | None = None) -> InlineKeyboardMarkup:
    visited_mines = visited_mines or set()
    rows = []
    for start in (1, 6):
        row = []
        for mine in range(start, start + 5):
            if mine in visited_mines:
                continue
            row.append(
                InlineKeyboardButton(
                    text=f"{mine:02d}",
                    callback_data=f"act:mine:{game_id}:{actor_id}:{mine}",
                )
            )
        if row:
            rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="⚜️ Himoyalanish",
                callback_data=f"act:mine_protect:{game_id}:{actor_id}:0",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="O'tkazib yuborish", callback_data=f"skip:night:{game_id}:{actor_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commissar_action_keyboard(game_id: int, actor_id: int, can_shoot: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Tekshirish",
                callback_data=f"commissar:check:{game_id}:{actor_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Otish",
                callback_data=f"commissar:shoot:{game_id}:{actor_id}",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commissar_target_keyboard(
    action_key: str,
    game_id: int,
    actor_id: int,
    choices: list[tuple[int, str]],
) -> InlineKeyboardMarkup:
    kb = target_keyboard(action_key, game_id, actor_id, choices)
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"commissar:menu:{game_id}:{actor_id}")])
    return kb


def vote_keyboard(game_id: int, choices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for target_id, name in choices:
        clean_name, emoji_id = parse_player_button(name)
        kwargs = {}
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        rows.append([
            InlineKeyboardButton(
                text=clean_name,
                callback_data=f"vote:{game_id}:{target_id}",
                **kwargs,
            )
        ])
    rows.append([InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data=f"skip:vote:{game_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_hang_keyboard(game_id: int, target_id: int, yes_count: int = 0, no_count: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"👍 {yes_count}", callback_data=f"hang:yes:{game_id}:{target_id}"),
                InlineKeyboardButton(text=f"👎 {no_count}", callback_data=f"hang:no:{game_id}:{target_id}"),
            ],
        ]
    )


def judge_cancel_keyboard(game_id: int, target_id: int, judge_id: int, confirm_message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧑‍⚖️ Osishni bekor qilish",
                    callback_data=f"judgecancel:{game_id}:{target_id}:{judge_id}:{confirm_message_id}",
                )
            ],
            [InlineKeyboardButton(text="O'tkazib yuborish", callback_data=f"skip:judge:{game_id}:{judge_id}")],
        ]
    )


def settings_keyboard(lang: str, game_id: Optional[int] = None) -> InlineKeyboardMarkup:
    def callback(action: str) -> str:
        return f"settings:{game_id}:{action}" if game_id is not None else f"settings:{action}"

    items = [
        (callback("lang"), "🌍 Til sozlamasi"),
        (callback("timeout"), "⏳ Registration timeout"),
        (callback("minplayers"), "👥 Minimum players"),
        (callback("roles"), "🎮 O'yin turlari"),
        (callback("welcome"), "👋 Salomlashuv"),
        (callback("premium"), "🎲 Premium status"),
        (callback("logs"), "🧾 Game logs"),
        (callback("media"), "🖼 Day/Night media"),
        (callback("stop"), "🛑 Stop game"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=cb)] for cb, label in items]
    )


def group_welcome_keyboard(chat_id: int, enabled: bool, has_media: bool) -> InlineKeyboardMarkup:
    def callback(action: str) -> str:
        return f"settings:{chat_id}:{action}"

    rows = [
        [
            InlineKeyboardButton(
                text="🔴 O'chirish" if enabled else "🟢 Yoqish",
                callback_data=callback("welcome_toggle"),
            )
        ],
        [InlineKeyboardButton(text="✏️ Matnni o'zgartirish", callback_data=callback("welcome_text"))],
        [InlineKeyboardButton(text="🖼 Media qo'shish / o'zgartirish", callback_data=callback("welcome_media"))],
    ]
    if has_media:
        rows.append([InlineKeyboardButton(text="🗑 Mediani o'chirish", callback_data=callback("welcome_media_clear"))])
    rows.append([InlineKeyboardButton(text="◀️ Settings", callback_data=callback("back"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_preset_keyboard(current_preset: str = "black23", chat_id: Optional[int] = None) -> InlineKeyboardMarkup:
    if current_preset in {"black23", "extended35"}:
        current_preset = "classic"

    def label(preset: str, text: str) -> str:
        return f"✅ {text}" if current_preset == preset else text

    def callback(action: str) -> str:
        return f"settings:{chat_id}:{action}" if chat_id is not None else f"settings:{action}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label("classic", "🎭 Classic"), callback_data=callback("rolepreset:classic"))],
            [InlineKeyboardButton(text=label("super", "⚡ Super"), callback_data=callback("rolepreset:super"))],
            [InlineKeyboardButton(text=label("mega", "🔥 Mega"), callback_data=callback("rolepreset:mega"))],
            [InlineKeyboardButton(text=label("zombie", "🧟 Zombie"), callback_data=callback("rolepreset:zombie"))],
            [InlineKeyboardButton(text="◀️ Settings", callback_data=callback("back"))],
        ]
    )


def roles_overview_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=role_label(r), callback_data="noop") ] for r in Role]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_keyboard(has_hero: bool = False, is_vip: bool = False) -> InlineKeyboardMarkup:
    disc_tag = " (VIP -20%)" if is_vip else ""
    p_cost = 80 if is_vip else 100
    m_cost = 240 if is_vip else 300
    hero_button = (
        InlineKeyboardButton(text="🥷 Geroyim", callback_data="hero:panel")
        if has_hero
        else diamond_icon_button("🥷 Geroy sotib olish - 100", callback_data="hero:shop:buy")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [hero_button],
            [dollar_icon_button(f"🛡 Himoya - {p_cost}{disc_tag}", callback_data="shop:buy:protection")],
            [diamond_icon_button("⚖️ Ovozdan himoya - 1", callback_data="shop:buy:vote_protection")],
            [dollar_icon_button(f"💊 Doridan himoya - {p_cost}{disc_tag}", callback_data="shop:buy:drug_protection")],
            [dollar_icon_button(f"🎭 Maska - {p_cost}{disc_tag}", callback_data="shop:buy:mask")],
            [diamond_icon_button("🧿 Qotildan himoya - 2", callback_data="shop:buy:killer_protection")],
            [dollar_icon_button(f"📦 Sirpanishdan himoya - {m_cost}{disc_tag}", callback_data="shop:buy:miner_protection")],
            [InlineKeyboardButton(text="🃏 Keyingi rol tanlash", callback_data="shop:roles")],
            [InlineKeyboardButton(text="👑 VIP User", callback_data="vip:open")],
            [InlineKeyboardButton(text="🎁 Telegram sovg'asiga almashtirish", callback_data="shop:gifts")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="profile:open")],
        ]
    )


VIP_BADGE_EMOJI_IDS: list[str] = [
    "5044126248029128166", "5229011542011299168", "5433758796289685818", "5156877291397055163",
    "5422577965626060349", "5422621288961172772", "5422532756800301136", "5422506192427573372",
    "5422700402258765336", "5422753591133757491", "5422839473299809887", "5422336446730101022",
    "5422821460206971027", "5420405575462716697", "5422500776473814754", "5300886406665619524",
    "5300919177266088980", "5305376992542082453", "4972275512501077411", "4972377307520960338",
    "4972433872240249208", "4972016199555614538", "4972118660295427879", "4972394676368705639",
    "4972077527393633760", "4971982737465411019", "4971994449841227419", "4972139306203219960",
    "4974253473789904579", "4974334872010098434", "4974333592109843751"
]


def vip_keyboard(is_vip: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if is_vip:
        rows.append([InlineKeyboardButton(text="👑 VIP Panel (Sozlamalar)", callback_data="vip:panel")])
        rows.append([diamond_icon_button("30 almaz bilan uzaytirish (30 kun)", callback_data="vip:buy:diamonds")])
        rows.append([InlineKeyboardButton(text="⭐ 190 stars bilan uzaytirish (30 kun)", callback_data="vip:buy:stars")])
    else:
        rows.append([diamond_icon_button("30 almaz bilan faollashtirish", callback_data="vip:buy:diamonds")])
        rows.append([InlineKeyboardButton(text="⭐ 190 stars bilan faollashtirish", callback_data="vip:buy:stars")])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vip_panel_keyboard(user: object | None = None) -> InlineKeyboardMarkup:
    pos_text = "Oldida" if getattr(user, "vip_badge_pos", "before") == "before" else "Ketida"
    badge_val = getattr(user, "vip_badge", None)
    badge_status = "✅ Tanlangan" if badge_val else "Tanlanmagan"
    nick_val = getattr(user, "vip_nickname", None)
    nick_status = f" ({safe_text(nick_val, 12)})" if nick_val else " (Standart)"
    style_val = getattr(user, "vip_style", "bold")
    style_labels = {
        "bold": "👑 Bold",
        "italic": "✂️ Italic",
        "code": "💻 Code",
        "underline": "📝 Underline",
        "strikethrough": "⚡ Strikethrough",
        "none": "📄 Oddiy"
    }
    style_txt = style_labels.get(style_val, "👑 Bold")

    rows = [
        [InlineKeyboardButton(text=f"✏️ Nickname{nick_status}", callback_data="vip:set_nickname")],
        [InlineKeyboardButton(text=f"🎭 Premium Badge — {badge_status}", callback_data="vip:badges:1")],
        [InlineKeyboardButton(text="➕ O'z custom badge qo'yish", callback_data="vip:set_custom_start")],
        [InlineKeyboardButton(text=f"📍 Badge o'rni: {pos_text}", callback_data="vip:toggle_badge_pos")],
        [InlineKeyboardButton(text=f"🎨 Nickname stili: {style_txt}", callback_data="vip:styles:menu")],
    ]
    if nick_val:
        rows.append([InlineKeyboardButton(text="🔄 Nicknameni tozalash", callback_data="vip:reset_nickname")])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="vip:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vip_badge_picker_keyboard(selected_badge: str | None = None, page: int = 1) -> InlineKeyboardMarkup:
    per_page = 8
    total_pages = max(1, (len(VIP_BADGE_EMOJI_IDS) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_badges = VIP_BADGE_EMOJI_IDS[start_idx:end_idx]

    rows = []
    row = []
    for idx, emoji_id in enumerate(page_badges, start=start_idx + 1):
        mark = "✅ " if selected_badge == emoji_id else ""
        btn = InlineKeyboardButton(
            text=f"{mark}Badge #{idx}",
            icon_custom_emoji_id=emoji_id,
            callback_data=f"vip:badge:select:{emoji_id}"
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"vip:badges:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Oldinga ➡️", callback_data=f"vip:badges:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    if selected_badge:
        rows.append([InlineKeyboardButton(text="🗑 Badgeni olib tashlash", callback_data="vip:badge:remove")])
    rows.append([InlineKeyboardButton(text="🔙 VIP Panel", callback_data="vip:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vip_style_picker_keyboard(current_style: str = "bold") -> InlineKeyboardMarkup:
    styles = [
        ("bold", "👑 Qalin (Bold)"),
        ("italic", "✂️ Egiluvchan (Italic)"),
        ("code", "💻 Monospace (Code)"),
        ("underline", "📝 Tagiga chizilgan (Underline)"),
        ("strikethrough", "⚡ Ustiga chizilgan (Strikethrough)"),
        ("none", "📄 Oddiy matn"),
    ]
    rows = []
    for key, label in styles:
        mark = "✅ " if current_style == key else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"vip:style:set:{key}")])
    rows.append([InlineKeyboardButton(text="🔙 VIP Panel", callback_data="vip:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def box_info_keyboard(
    box_type: str,
    can_paid_open: bool = False,
    paid_open_cost: int = 5000,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🎁 Ochish", callback_data=f"box:open:{box_type}")]]
    if can_paid_open:
        rows.append([dollar_icon_button(f"{paid_open_cost} evaziga ochish", callback_data=f"box:open_paid:{box_type}")])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="vip:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def box_pick_keyboard(box_type: str, session_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    idx = 1
    for _ in range(4):
        row: list[InlineKeyboardButton] = []
        for _ in range(4):
            row.append(
                InlineKeyboardButton(
                    text=f"🎁 {idx}",
                    callback_data=f"box:pick:{box_type}:{session_id}:{idx}",
                )
            )
            idx += 1
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"box:info:{box_type}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_GIFT_TIER_EMOJI = [
    (15, "💝"),
    (25, "🌹"),
    (50, "🎂"),
    (100, "🧸"),
    (250, "🍾"),
    (500, DIAMOND_BUTTON_EMOJI),
    (1000, "👑"),
    (2500, "🏆"),
    (5000, "💍"),
    (10000, "💖"),
]


def _pick_gift_emoji(sticker_emoji: str | None, stars: int) -> str:
    # Prefer a real plain-emoji from sticker if present and not a generic gift-box.
    if sticker_emoji and sticker_emoji not in {"🎁", "📦"}:
        return sticker_emoji
    fallback = "🎁"
    for threshold, em in _GIFT_TIER_EMOJI:
        if stars <= threshold:
            return em
        fallback = em
    return fallback


_GIFT_FIXED_PRICES: dict[int, int] = {
    15: 8,
    25: 11,
    50: 15,
    100: 28,
}


def gift_shop_keyboard(gifts: list[object], stars_per_diamond: int) -> InlineKeyboardMarkup:
    import math
    rows: list[list[InlineKeyboardButton]] = []
    for gift in gifts:
        gift_id = getattr(gift, "id", None)
        stars = int(getattr(gift, "star_count", 0) or 0)
        if not gift_id or stars <= 0:
            continue
        diamonds = _GIFT_FIXED_PRICES.get(stars) or max(1, math.ceil(stars / stars_per_diamond))
        remaining = getattr(gift, "remaining_count", None)
        total = getattr(gift, "total_count", None)
        suffix = ""
        if remaining is not None and total is not None:
            suffix = f"  ({remaining}/{total})"
        sticker = getattr(gift, "sticker", None)
        emoji = _pick_gift_emoji(getattr(sticker, "emoji", None), stars)
        rows.append([
            diamond_icon_button(
                f"{emoji} {stars}⭐ — {diamonds}{suffix}",
                callback_data=f"gift:buy:{gift_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="👑 Telegram Premium", callback_data="gift:premium")])
    rows.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="shop:gifts")])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_shop_keyboard(plans: list[tuple[int, int, int]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for months, stars, diamonds in plans:
        rows.append([
            diamond_icon_button(
                f"👑 {months} oy — {diamonds}",
                callback_data=f"gift:premium:buy:{months}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:gifts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_confirm_keyboard(months: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"gift:premium:confirm:{months}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="gift:premium")],
        ]
    )


def gift_confirm_keyboard(gift_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"gift:confirm:{gift_id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="shop:gifts")],
        ]
    )


def hero_panel_keyboard(is_for_sale: bool = False) -> InlineKeyboardMarkup:
    sale_rows = (
        [
            [InlineKeyboardButton(text="❌ Sotuvdan qaytarish", callback_data="hero:sale:cancel")],
            [InlineKeyboardButton(text="✏️ Narxni o'zgartirish", callback_data="hero:sale:price")],
        ]
        if is_for_sale
        else [[InlineKeyboardButton(text="🏷 Geroyni sotish", callback_data="hero:sell")]]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥷 Mening geroylarim", callback_data="hero:list")],
            [InlineKeyboardButton(text="➕ 1000 Ball qo'shish", callback_data="hero:add_points")],
            [InlineKeyboardButton(text="🛡 Himoyani yangilash", callback_data="hero:upgrade_def")],
            [InlineKeyboardButton(text="🩸 Qurolni zaryadlash", callback_data="hero:recharge")],
            [InlineKeyboardButton(text="🖋 Nomini o'zgartirish", callback_data="hero:rename")],
            *sale_rows,
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="shop:open")],
        ]
    )


def hero_list_keyboard(heroes: list[object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for hero in heroes:
        marker = "✅ " if getattr(hero, "is_active", False) else ""
        name = safe_text(str(getattr(hero, "name", "Geroy") or "Geroy"), 24)
        level = int(getattr(hero, "level", 1) or 1)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}🥷 {name} | ⭐ {level}",
                    callback_data=f"hero:select:{int(getattr(hero, 'id'))}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔙 Geroy paneli", callback_data="hero:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hero_game_keyboard(can_attack: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if can_attack:
        rows.append([InlineKeyboardButton(text="⚔️ Zarba berish", callback_data="hero:game:attack")])
    rows.extend(
        [
            [InlineKeyboardButton(text="🛡 Himoyalanish", callback_data="hero:game:defend")],
            [InlineKeyboardButton(text="📊 Jonlar holati", callback_data="hero:game:hp")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="hero:game:cancel")],
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def hero_target_keyboard(players: list[object]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=getattr(player, "display_name", "User"), callback_data=f"hero:game:target:{player.id}")]
        for player in players
    ]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="hero:game:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hero_defense_keyboard(max_amount: int) -> InlineKeyboardMarkup:
    choices = [amount for amount in (10, 20, 30) if amount <= max_amount]
    rows = [[InlineKeyboardButton(text=str(amount), callback_data=f"hero:game:defamount:{amount}")] for amount in choices]
    rows.append([InlineKeyboardButton(text="Maksimal", callback_data="hero:game:defamount:max")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="hero:game:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hero_damage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Maksimal zarba", callback_data="hero:game:damage:max")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="hero:game:attack")],
        ]
    )


def hero_market_buy_keyboard(hero_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Sotib olish", callback_data=f"hero:market:buy:{hero_id}")],
        ]
    )


def owner_hero_market_keyboard(has_channel: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Qo'shish / o'zgartirish", callback_data="owner:hero_market_set")]]
    if has_channel:
        rows.append([InlineKeyboardButton(text="🗑 O'chirish", callback_data="owner:hero_market_clear")])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_shop_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for item in SHOP_ROLE_CATALOG:
        rows.append([
            currency_icon_button(
                f"{role_label(item.role)} - {item.price}",
                item.currency,
                callback_data=f"shop:role:{item.role.value}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🎒 Mening rollarim", callback_data="shop:my_roles")])
    rows.append([dollar_icon_button("🚫 Faol rolni o'chirish - 100", callback_data="shop:disable_roles")])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_roles_keyboard(roles: list[str], selected_role: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    counts: dict[str, int] = {}
    for rv in roles:
        counts[rv] = counts.get(rv, 0) + 1
    for role_value, count in counts.items():
        mark = "✅ " if selected_role == role_value else ""
        count_tag = f" ×{count}" if count > 1 else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{mark}{role_label(role_value)}{count_tag}",
                callback_data=f"shop:my_role:{role_value}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def disable_role_shop_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [dollar_icon_button(f"🚫 {role_label(role)} - 100", callback_data=f"shop:disable_role:{role.value}")]
        for role in ACTIVE_ROLE_POOL
        if role not in {Role.CITIZEN, Role.DON}
    ]
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="shop:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dollar_exchange_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Kredit", callback_data="credit:open")],
            [
                diamond_icon_button(f"1 → {DOLLAR_BUTTON_EMOJI} 500", callback_data="dollar:exchange:1"),
                diamond_icon_button(f"5 → {DOLLAR_BUTTON_EMOJI} 2500", callback_data="dollar:exchange:5"),
            ],
            [
                diamond_icon_button(f"10 → {DOLLAR_BUTTON_EMOJI} 5000", callback_data="dollar:exchange:10"),
                diamond_icon_button(f"50 → {DOLLAR_BUTTON_EMOJI} 25000", callback_data="dollar:exchange:50"),
            ],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="profile:open")],
        ]
    )


def diamond_shop_keyboard(admin_username: str) -> InlineKeyboardMarkup:
    admin_url = f"https://t.me/{_clean_bot_username(admin_username)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                diamond_icon_button("1 - ⭐ 7", callback_data="diamond:buy:1"),
                diamond_icon_button("10 - ⭐ 70", callback_data="diamond:buy:10"),
            ],
            [
                diamond_icon_button("30 - ⭐ 200", callback_data="diamond:buy:30"),
                diamond_icon_button("70 - ⭐ 450", callback_data="diamond:buy:70"),
            ],
            [
                diamond_icon_button("250 - ⭐ 1300", callback_data="diamond:buy:250"),
                diamond_icon_button("1000 - ⭐ 5000", callback_data="diamond:buy:1000"),
            ],
            [
                InlineKeyboardButton(text="👤 Admin orqali", url=admin_url),
                InlineKeyboardButton(text="◀️ Orqaga", callback_data="profile:open"),
            ],
        ]
    )


def owner_panel_keyboard(role: str = "super_admin") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if role == "super_admin":
        rows.extend([
            [InlineKeyboardButton(text="🛡 Sub-Adminlar (Moderatorlar)", callback_data="owner:sub_admins")],
            [InlineKeyboardButton(text="🎟 Promokodlar & Vaucherlar", callback_data="owner:promo_codes")],
            [InlineKeyboardButton(text="📈 Analitika & DAU/MAU", callback_data="owner:analytics")],
            [InlineKeyboardButton(text="🔥 2X Event Mode (Happy Hours)", callback_data="owner:toggle_2x_event")],
            [InlineKeyboardButton(text="🖥 Monitoring", callback_data="owner:monitor:menu")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="owner:stats")],
            [InlineKeyboardButton(text="🎰 Qimor sozlamalari", callback_data="owner:gamble")],
            [InlineKeyboardButton(text="👑 VIP aktiv userlar", callback_data="owner:vip")],
            [diamond_icon_button("TOP 30 almaz", callback_data="owner:diamond_top")],
            [dollar_icon_button("TOP 30 dollar", callback_data="owner:dollar_top")],
            [diamond_icon_button("Almaz loglari", callback_data="owner:diamond_audit")],
            [InlineKeyboardButton(text="🏠 Admin guruh", callback_data="owner:admin_group")],
            [InlineKeyboardButton(text="🎲 Premium guruhlar", callback_data="owner:premium_groups")],
            [InlineKeyboardButton(text="🏰 Clanlar boshqaruvi", callback_data="owner:clans")],
            [InlineKeyboardButton(text="🚷 Blacklist", callback_data="owner:premium_blocked_list")],
            [InlineKeyboardButton(text="👤 Xarid admini", callback_data="owner:purchase_admin")],
            [InlineKeyboardButton(text="📰 Yangiliklar kanali", callback_data="owner:news_channel")],
            [InlineKeyboardButton(text="📺 Kanal sovg'a balansi", callback_data="owner:channel_gifts")],
            [InlineKeyboardButton(text="🥷 Geroy savdo kanali", callback_data="owner:hero_market_channel")],
            [InlineKeyboardButton(text="📢 Reklama yuborish (Advanced)", callback_data="owner:broadcast_menu")],
            [dollar_icon_button("Dollar berish", callback_data="owner:grant_dollars")],
            [diamond_icon_button("Olmos berish", callback_data="owner:grant_diamonds")],
            [InlineKeyboardButton(text="🧾 Almaz invoice", callback_data="owner:invoice")],
            [InlineKeyboardButton(text="📋 Barcha buyruqlar", callback_data="owner:commands")],
            [InlineKeyboardButton(text="🧾 Yordam", callback_data="owner:help")],
        ])
    elif role == "finance_admin":
        rows.extend([
            [dollar_icon_button("Dollar berish", callback_data="owner:grant_dollars")],
            [diamond_icon_button("Olmos berish", callback_data="owner:grant_diamonds")],
            [InlineKeyboardButton(text="🧾 Almaz invoice", callback_data="owner:invoice")],
            [diamond_icon_button("Almaz loglari", callback_data="owner:diamond_audit")],
            [diamond_icon_button("TOP 30 almaz", callback_data="owner:diamond_top")],
            [dollar_icon_button("TOP 30 dollar", callback_data="owner:dollar_top")],
        ])
    elif role == "moderator":
        rows.extend([
            [InlineKeyboardButton(text="🚷 Blacklist", callback_data="owner:premium_blocked_list")],
            [InlineKeyboardButton(text="👑 VIP aktiv userlar", callback_data="owner:vip")],
            [InlineKeyboardButton(text="🏰 Clanlar boshqaruvi", callback_data="owner:clans")],
        ])
    elif role == "media_manager":
        rows.extend([
            [InlineKeyboardButton(text="📢 Reklama yuborish (Advanced)", callback_data="owner:broadcast_menu")],
            [InlineKeyboardButton(text="📰 Yangiliklar kanali", callback_data="owner:news_channel")],
            [InlineKeyboardButton(text="🔥 2X Event Mode (Happy Hours)", callback_data="owner:toggle_2x_event")],
        ])
    else:
        rows.append([InlineKeyboardButton(text="📊 Statistika", callback_data="owner:stats")])

    rows.append([InlineKeyboardButton(text="◀️ User panel", callback_data="start:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_admin_menu_keyboard(sub_admins: list[object] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Yangi sub-admin qo'shish", callback_data="owner:sub_admin:add")],
    ]
    for sub in (sub_admins or [])[:20]:
        user_id = getattr(sub, "user_telegram_id", 0)
        username = getattr(sub, "username", None)
        role = getattr(sub, "role", "moderator")
        role_label_str = {"super_admin": "Super", "finance_admin": "Finance", "moderator": "Mod", "media_manager": "Media"}.get(role, role)
        name_str = f"@{username}" if username else str(user_id)
        rows.append([InlineKeyboardButton(
            text=f"❌ [{role_label_str}] {name_str}",
            callback_data=f"owner:sub_admin:remove:{user_id}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_admin_role_select_keyboard(user_id: int, username: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛡 Super Admin", callback_data=f"owner:sub_admin:set:{user_id}:super_admin:{username}")],
            [InlineKeyboardButton(text="💳 Finance Admin", callback_data=f"owner:sub_admin:set:{user_id}:finance_admin:{username}")],
            [InlineKeyboardButton(text="👮 Moderator", callback_data=f"owner:sub_admin:set:{user_id}:moderator:{username}")],
            [InlineKeyboardButton(text="📢 Media Manager", callback_data=f"owner:sub_admin:set:{user_id}:media_manager:{username}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="owner:sub_admins")],
        ]
    )


def promo_code_menu_keyboard(promo_codes: list[object] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Yangi promokod yaratish", callback_data="owner:promo:create")],
    ]
    for promo in (promo_codes or [])[:15]:
        code = getattr(promo, "code", "")
        dollar = getattr(promo, "reward_dollar", 0)
        diamond = getattr(promo, "reward_diamond", 0)
        uses = getattr(promo, "current_uses", 0)
        max_u = getattr(promo, "max_uses", 0)
        rows.append([InlineKeyboardButton(
            text=f"🎟 {code} | 💵{dollar} 💎{diamond} ({uses}/{max_u})",
            callback_data=f"owner:promo:info:{getattr(promo, 'id', 0)}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Userlarga darhol yuborish", callback_data="owner:broadcast_users")],
            [InlineKeyboardButton(text="🏘 Guruhlarga darhol yuborish", callback_data="owner:broadcast_groups")],
            [InlineKeyboardButton(text="📅 Userlarga rejalashtirilgan reklama", callback_data="owner:sched_broadcast:users")],
            [InlineKeyboardButton(text="📅 Guruhlarga rejalashtirilgan reklama", callback_data="owner:sched_broadcast:groups")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def broadcast_pin_option_keyboard(target: str, sched: bool = False) -> InlineKeyboardMarkup:
    prefix = "owner:sched_bc" if sched else "owner:bc"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Xabarni qadash (Pin)", callback_data=f"{prefix}:{target}:pin")],
            [InlineKeyboardButton(text="➡️ Qadamay yuborish", callback_data=f"{prefix}:{target}:nopin")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="owner:broadcast_menu")],
        ]
    )


def analytics_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="owner:analytics")],
            [InlineKeyboardButton(text="🔥 2X Event Toggle", callback_data="owner:toggle_2x_event")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )



def owner_gamble_keyboard(
    enabled: bool,
    has_loss_voice: bool = False,
    has_win_voice: bool = False,
    has_group: bool = False,
) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Qimorni o'chirish" if enabled else "🟢 Qimorni yoqish"
    group_btn_text = "🏠 Qimor guruhini o'zgartirish" if has_group else "➕ Qimor guruh belgilash"
    group_rows = [[InlineKeyboardButton(text=group_btn_text, callback_data="owner:gamble:group")]]
    if has_group:
        group_rows.append([InlineKeyboardButton(text="🗑 Qimor guruhini o'chirish", callback_data="owner:gamble:group:clear")])
    voice_rows = [
        [InlineKeyboardButton(text="💣 Kuyganda voice qo'shish", callback_data="owner:gamble:voice:loss")],
    ]
    if has_loss_voice:
        voice_rows.append([InlineKeyboardButton(text="🗑 Kuygan voices o'chirish", callback_data="owner:gamble:voice:clear:loss")])
    voice_rows.append([InlineKeyboardButton(text="🏆 Yutuqda voice qo'shish", callback_data="owner:gamble:voice:win")])
    if has_win_voice:
        voice_rows.append([InlineKeyboardButton(text="🗑 Yutuq voices o'chirish", callback_data="owner:gamble:voice:clear:win")])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="owner:gamble:toggle")],
            *group_rows,
            *voice_rows,
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_vip_users_keyboard(users: list[object] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="owner:vip")]
    ]
    for user in (users or [])[:30]:
        telegram_id = int(getattr(user, "telegram_id", 0) or 0)
        name = str(getattr(user, "display_name", "") or getattr(user, "username", "") or telegram_id)
        short_name = name[:24] + ("…" if len(name) > 24 else "")
        rows.append([InlineKeyboardButton(text=f"❌ {short_name}", callback_data=f"owner:vip:disable:{telegram_id}")])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_channel_gifts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Almaz tarqatishni boshlash", callback_data="owner:channel_gifts:start")],
            [InlineKeyboardButton(text="📊 Kanal balansini ko'rish", callback_data="owner:channel_gifts:view")],
            [InlineKeyboardButton(text="➕ Kanal balansini to'ldirish", callback_data="owner:channel_gifts:grant")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_channel_gift_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Tez tarqatish", callback_data="owner:channel_gifts:mode:send")],
            [InlineKeyboardButton(text="🎲 Ro'yxatdan o'tish", callback_data="owner:channel_gifts:mode:change")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="owner:cancel")],
        ]
    )


def owner_diamond_audit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="owner:diamond_audit")],
            [InlineKeyboardButton(text="📥 CSV yuklab olish", callback_data="owner:diamond_audit:download")],
            [InlineKeyboardButton(text="🏠 Log guruhini ulash", callback_data="owner:admin_group")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_diamond_top_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="owner:diamond_top")],
            [dollar_icon_button("TOP 30 dollar", callback_data="owner:dollar_top")],
            [diamond_icon_button("Almaz loglari", callback_data="owner:diamond_audit")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_dollar_top_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="owner:dollar_top")],
            [diamond_icon_button("TOP 30 almaz", callback_data="owner:diamond_top")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_admin_group_keyboard(has_group: bool, can_use_current_chat: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if can_use_current_chat:
        rows.append([InlineKeyboardButton(text="✅ Shu guruhni ulash", callback_data="owner:admin_group:current")])
    rows.append([InlineKeyboardButton(text="✏️ ID bilan ulash", callback_data="owner:admin_group:set")])
    if has_group:
        rows.append([InlineKeyboardButton(text="🗑 O'chirish", callback_data="owner:admin_group:clear")])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_invoice_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangi invoice yaratish", callback_data="owner:invoice:new")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_invoice_delivery_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Sharable link yaratish", callback_data="owner:invoice:make_link")],
            [InlineKeyboardButton(text="📤 Aniq userga yuborish", callback_data="owner:invoice:make_send")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="owner:invoice")],
        ]
    )


def owner_invoice_after_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana invoice yaratish", callback_data="owner:invoice:new")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )


def owner_wait_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="owner:cancel")],
        ]
    )


def mandatory_sub_keyboard(news_url: str) -> InlineKeyboardMarkup:
    target_url = news_url if news_url else "https://t.me/WorldMafiaNews"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga a'zo bo'lish ↗", url=target_url)],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subscription")],
        ]
    )


def owner_news_channel_keyboard(has_link: bool, sub_required: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Qo'shish / o'zgartirish", callback_data="owner:news_set")]]
    if has_link:
        sub_btn_text = "🔴 Majburiy obunani o'chirish" if sub_required else "🟢 Majburiy obunani yoqish"
        rows.append([InlineKeyboardButton(text=sub_btn_text, callback_data="owner:news_sub_toggle")])
        rows.append([InlineKeyboardButton(text="🗑 O'chirish", callback_data="owner:news_clear")])
    rows.append([InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_premium_groups_keyboard(groups: list[object] | None = None) -> InlineKeyboardMarkup:
    rows = []
    for group in groups or []:
        total = getattr(group, "total_diamonds", 0) or 0
        if total <= 0:
            continue
        rows.append(
            [
                diamond_icon_button(
                    f"{group.title} - {total}",
                    callback_data=f"owner:premium_bankrupt:{group.id}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="📋 Premium guruhlar ro'yxati", callback_data="owner:premium_list")],
            [InlineKeyboardButton(text="⏱ Premium timer", callback_data="owner:premium_timer")],
            [
                InlineKeyboardButton(text="🚫 Userni bloklash", callback_data="owner:premium_block_user"),
                InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data="owner:premium_unblock_user"),
            ],
            [InlineKeyboardButton(text="🚷 Bloklanganlar", callback_data="owner:premium_blocked_list")],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="owner:panel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_groups_keyboard(groups: list[object]) -> InlineKeyboardMarkup:
    rows = []
    for group in groups:
        total = getattr(group, "total_diamonds", None) or getattr(group, "diamond_price", 0)
        rows.append(
            [
                diamond_icon_button(
                    f"{group.title} - {total}",
                    url=group.invite_link,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="start:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _back_btn(back_to: str) -> InlineKeyboardButton:
    return _btn("⬅️ Orqaga", f"settings:back:{back_to}")


def _exit_btn() -> InlineKeyboardButton:
    return _btn("❌ Chiqish", "settings:exit")


def _back_exit_row(back_to: str) -> list[InlineKeyboardButton]:
    return [_back_btn(back_to), _exit_btn()]


# --- CLAN KEYBOARDS ---

def clanless_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Clan yaratish — 30 💎", callback_data="clan:create_start")],
            [
                InlineKeyboardButton(text="🔎 Clanlarni ko'rish", callback_data="clan:list:1"),
                InlineKeyboardButton(text="📨 Mening arizalarim", callback_data="clan:my_apps"),
            ],
            [InlineKeyboardButton(text="🏆 Clan TOP", callback_data="clan:top:1")],
            [InlineKeyboardButton(text="❌ Yopish", callback_data="clan:close")],
        ]
    )


def clan_create_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [diamond_icon_button("✅ Yaratish — 30 💎", callback_data="clan:create_confirm")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="clan:main")],
        ]
    )


def clan_member_dashboard_keyboard(clan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 A'zolar", callback_data=f"clan:members:{clan_id}:1"),
                InlineKeyboardButton(text="📊 Batafsil statistika", callback_data=f"clan:stats:{clan_id}"),
            ],
            [InlineKeyboardButton(text="🏆 Clan TOP", callback_data="clan:top:1")],
            [InlineKeyboardButton(text="🚪 Clan'dan chiqish", callback_data=f"clan:leave_ask:{clan_id}")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="start:back")],
        ]
    )


def clan_owner_dashboard_keyboard(clan_id: int, pending_apps_count: int = 0) -> InlineKeyboardMarkup:
    badge = f" ({pending_apps_count})" if pending_apps_count > 0 else " (0)"
    apps_text = f"📨 Qo'shilish arizalari{badge}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=apps_text, callback_data=f"clan:apps:{clan_id}")],
            [
                InlineKeyboardButton(text="👥 A'zolar", callback_data=f"clan:members:{clan_id}:1"),
                InlineKeyboardButton(text="📊 Clan statistikasi", callback_data=f"clan:stats:{clan_id}"),
            ],
            [InlineKeyboardButton(text="🛡 Admin tayinlash", callback_data=f"clan:admin_start:{clan_id}")],
            [diamond_icon_button("✏️ Clan nomini o'zgartirish — 5 💎", callback_data=f"clan:rename_start:{clan_id}")],
            [dollar_icon_button("📝 Clan bio'sini o'zgartirish — $10,000", callback_data=f"clan:rebio_start:{clan_id}")],
            [InlineKeyboardButton(text="👑 Owner'ni almashtirish", callback_data=f"clan:transfer_start:{clan_id}")],
            [
                InlineKeyboardButton(text="🚪 Clan'dan chiqish", callback_data=f"clan:leave_ask:{clan_id}"),
                InlineKeyboardButton(text="🗑 Clan'ni o'chirish", callback_data=f"clan:delete_ask:{clan_id}"),
            ],
            [InlineKeyboardButton(text="🏆 Clan TOP", callback_data="clan:top:1")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="start:back")],
        ]
    )


def clan_applications_keyboard(applications: list, clan_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for app_rec, usr in applications:
        app_id = app_rec.id
        display_name = usr.display_name if usr else "User"
        short_name = safe_text(display_name, 16)
        rows.append(
            [
                InlineKeyboardButton(text=f"👤 {short_name}", callback_data=f"clan:user_profile:{usr.telegram_id}"),
                InlineKeyboardButton(text="✅ Qabul", callback_data=f"clan:app_action:accept:{app_id}"),
                InlineKeyboardButton(text="❌ Rad", callback_data=f"clan:app_action:reject:{app_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="🔙 Clan panel", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_app_confirm_keyboard(action: str, app_id: int) -> InlineKeyboardMarkup:
    yes_text = "✅ Ha, qo'shish" if action == "accept" else "❌ Ha, rad etish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes_text, callback_data=f"clan:app_confirm:{action}:{app_id}")],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="clan:main")],
        ]
    )


def clan_info_keyboard(clan_id: int, can_apply: bool, has_applied: bool, is_full: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_applied:
        rows.append([InlineKeyboardButton(text="⏳ Ariza ko'rib chiqilmoqda", callback_data="noop")])
    elif is_full:
        rows.append([InlineKeyboardButton(text="🔒 Clan to'lgan", callback_data="noop")])
    elif can_apply:
        rows.append([InlineKeyboardButton(text="📨 Qo'shilish uchun ariza", callback_data=f"clan:apply:{clan_id}")])
    rows.append([InlineKeyboardButton(text="🔙 Clanlar ro'yxati", callback_data="clan:list:1")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_top_keyboard(clans: list, page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, clan in enumerate(clans, start=(page - 1) * 10 + 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        name = safe_text(clan.name, 20)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{medal} {name} | ⭐ Lvl {clan.level} | 🔥 {clan.rating}",
                    callback_data=f"clan:info:{clan.id}",
                )
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"clan:top:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Oldinga ➡️", callback_data=f"clan:top:{page + 1}"))

    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_list_keyboard(clans: list, page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for clan in clans:
        name = safe_text(clan.name, 22)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏰 {name} ({clan.level}-lvl)",
                    callback_data=f"clan:info:{clan.id}",
                )
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"clan:list:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Oldinga ➡️", callback_data=f"clan:list:{page + 1}"))

    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔎 Qidiruv", callback_data="clan:search_start")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_list_apply_keyboard(clans: list, page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    """Similar to clan_list_keyboard but pressing a clan sends an application (clan:apply:ID)."""
    rows: list[list[InlineKeyboardButton]] = []
    for clan in clans:
        name = safe_text(clan.name, 22)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏰 {name} ({clan.level}-lvl)",
                    callback_data=f"clan:apply:{clan.id}",
                )
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"clan:list:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Oldinga ➡️", callback_data=f"clan:list:{page + 1}"))

    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔎 Qidiruv", callback_data="clan:search_start")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_members_keyboard(
    members: list, clan_id: int, is_owner: bool = False, page: int = 1, total_pages: int = 1
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for mem, usr in members:
        role_icon = "👑" if mem.role == "owner" else "🛡" if mem.role == "admin" else "👤"
        display_name = usr.display_name if usr else "User"
        name = safe_text(display_name, 18)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{role_icon} {name} | ⚡ {mem.contribution_xp} XP",
                    callback_data=f"clan:user_profile:{usr.telegram_id}",
                )
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"clan:members:{clan_id}:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Oldinga ➡️", callback_data=f"clan:members:{clan_id}:{page + 1}"))

    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔙 Clan panel", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_transfer_keyboard(members: list, clan_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for mem, usr in members:
        if mem.role == "owner":
            continue
        display_name = usr.display_name if usr else "User"
        name = safe_text(display_name, 24)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👑 Topshirish: {name}",
                    callback_data=f"clan:transfer_confirm_ask:{usr.telegram_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="clan:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_confirm_action_keyboard(action: str, payload: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"clan:confirm:{action}:{payload}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="clan:main")],
        ]
    )



def settings_main_keyboard() -> InlineKeyboardMarkup:
    items = [
        ("🎮 O'yin turlari", "settings:game_types"),
        ("🎁 Giveawaylar", "settings:giveaway"),
        ("⏰ Vaqtlar", "settings:times"),
        ("🎭 Rollar", "settings:roles"),
        ("🔫 Qurollar", "settings:weapons"),
        ("🚪 Leave qilish", "settings:leave"),
        ("🔐 Buyruqlarga ruxsatlar", "settings:permissions"),
        ("✍️ Yozishni cheklash", "settings:chat"),
        ("⚙️ Boshqa sozlamalar", "settings:extra"),
        ("📊 Boshqaruv paneli", "settings:panel"),
    ]
    rows = [[_btn(label, cb)] for label, cb in items]
    rows.append([_exit_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_giveaway_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [diamond_icon_button("Olmoslar", callback_data="settings:giveaway:diamond")],
        [_btn("🛡 Himoyalar", "settings:giveaway:protection")],
        _back_exit_row("main"),
    ])


def settings_giveaway_amount_keyboard(gtype: str, current: int = 0) -> InlineKeyboardMarkup:
    amounts = [0, 10, 20, 30, 40, 50]
    rows = []
    for a in amounts:
        mark = "✅ " if a == current else ""
        rows.append([_btn(f"{mark}{a}", f"settings:giveaway:{gtype}:{a}")])
    rows.append(_back_exit_row("giveaway"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_roles_keyboard(states: dict[str, bool] | None = None) -> InlineKeyboardMarkup:
    roles = [
        ("🤵🏻 Don", "don"),
        ("🤵🏼 Mafia", "mafia"),
        ("🕵🏼 Komissar Katani", "commissar_katani"),
        ("👨🏼‍⚕️ Doktor", "doctor"),
        ("👮🏼 Serjant", "sergeant"),
        ("🎖 Janob", "gentleman"),
        ("👨🏼 Tinch aholi", "citizen"),
        ("🧙‍♂️ Daydi", "wanderer"),
        ("💃 Kezuvchi", "traveler"),
        ("👨🏼‍💼 Advokat", "lawyer"),
        ("🤦 Suidsid", "suicide"),
        ("🤞 Omadli", "lucky"),
        ("🐺 Bo'ri", "wolf"),
        ("🔪 Qotil", "killer"),
        ("🥷 Yollanma qotil", "mercenary_killer"),
        ("💣 Afsungar", "sorcerer"),
        ("🃏 Aferist", "swindler"),
        ("🧙 Sehrgar", "magician"),
        ("🧟 G'azabkor", "angry"),
        ("📰 Jurnalist", "journalist"),
        ("😎 Sotqin", "traitor"),
        ("🧪 Kimyogar", "chemist"),
        ("🛡 Qo'riqchi", "guard"),
        ("😂 Hazilkash", "prankster"),
        ("🃏 Joker", "joker"),
    ]
    rows = []
    for label, key in roles:
        allowed = (states or {}).get(key, True)
        mark = "✅" if allowed else "🚫"
        rows.append([_btn(f"{mark} {label}", f"settings:role:{key}")])
    rows.append(_back_exit_row("main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_role_toggle_keyboard(role_key: str, is_allowed: bool = True) -> InlineKeyboardMarkup:
    ban_mark = "✅ " if not is_allowed else ""
    allow_mark = "✅ " if is_allowed else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{ban_mark}🚫 Taqiqlash", f"settings:role:{role_key}:ban")],
        [_btn(f"{allow_mark}✅ Ruxsat berish", f"settings:role:{role_key}:allow")],
        _back_exit_row("roles"),
    ])


def settings_weapons_keyboard(states: dict[str, bool] | None = None) -> InlineKeyboardMarkup:
    weapons = [
        ("🛡 Himoya", "protection"),
        ("📁 Hujjat", "document"),
        ("🚨 Qotildan himoya", "killer_protection"),
        ("⚖️ Ovozdan himoya", "vote_protection"),
        ("🔫 Miltiq", "gun"),
        ("💊 Doridan himoya", "medicine_protection"),
        ("📦 Sirpanishdan himoya", "slip_protection"),
        ("🎭 Maska", "mask"),
        ("🥷 Geroy", "hero"),
        ("🃏 Faol rol", "active_role"),
    ]
    rows = []
    for label, key in weapons:
        enabled = (states or {}).get(key, True)
        mark = "✅" if enabled else "🚫"
        rows.append([_btn(f"{mark} {label}", f"settings:weapon:{key}")])
    rows.append(_back_exit_row("main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_weapon_toggle_keyboard(weapon_key: str, is_enabled: bool = True) -> InlineKeyboardMarkup:
    on_mark = "✅ " if is_enabled else ""
    off_mark = "✅ " if not is_enabled else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{on_mark}✅ Yoqish", f"settings:weapon:{weapon_key}:on")],
        [_btn(f"{off_mark}🚫 O'chirish", f"settings:weapon:{weapon_key}:off")],
        _back_exit_row("weapons"),
    ])


def settings_leave_keyboard(current: bool = True, lock_minutes: int = 30) -> InlineKeyboardMarkup:
    on_mark = "✅ " if current else ""
    off_mark = "✅ " if not current else ""
    lock_label = "o'chirilgan" if lock_minutes <= 0 else f"{lock_minutes} daqiqa"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{on_mark}✅ /leave yoqilsin", "settings:leave:on")],
        [_btn(f"{off_mark}🚫 /leave o'chirilsin", "settings:leave:off")],
        [_btn(f"⏱ Qayta qo'shilish bloki: {lock_label}", "settings:leave:lock")],
        _back_exit_row("main"),
    ])


def settings_leave_lock_keyboard(current_minutes: int = 30) -> InlineKeyboardMarkup:
    options = [0, 5, 10, 15, 30, 45, 60, 120, 180, 360, 720, 1440]
    rows = []
    for value in options:
        mark = "✅ " if value == current_minutes else ""
        label = "O'chirish (0)" if value == 0 else f"{value} daqiqa"
        rows.append([_btn(f"{mark}{label}", f"settings:leave:lock:{value}")])
    rows.append(_back_exit_row("leave"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


PERMISSION_ICONS = {"owner": "👑", "admin": "🛡", "user": "👥"}


def settings_permissions_keyboard(states: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    commands = [
        ("start", "start"),
        ("stop", "stop"),
        ("game", "game"),
        ("Top 1", "top_1"),
        ("Top 7", "top_7"),
        ("Top 30", "top_30"),
        ("Taqdirlash Top 1", "reward_top_1"),
        ("Taqdirlash Top 7", "reward_top_7"),
        ("Taqdirlash Top 30", "reward_top_30"),
    ]
    rows = []
    for label, key in commands:
        level = (states or {}).get(key, "user")
        icon = PERMISSION_ICONS.get(level, "👥")
        rows.append([_btn(f"{icon} {label}", f"settings:permission:{key}")])
    rows.append(_back_exit_row("main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_permission_level_keyboard(cmd_key: str, current: str = "user") -> InlineKeyboardMarkup:
    levels = [("👑 Ega", "owner"), ("🛡 Admin", "admin"), ("👥 Obunachilar", "user")]
    rows = []
    for label, val in levels:
        mark = "✅ " if val == current else ""
        rows.append([_btn(f"{mark}{label}", f"settings:permission:{cmd_key}:{val}")])
    rows.append(_back_exit_row("permissions"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_chat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🌙 Tun", "settings:chat:night")],
        [_btn("☀️ Kun", "settings:chat:day")],
        _back_exit_row("main"),
    ])


def settings_chat_phase_keyboard(phase: str, current: str = "") -> InlineKeyboardMarkup:
    options = [
        ("👑 Faqat Ega", "owner"),
        ("🛡 Faqat Adminlar", "admin"),
        ("💚 Faqat tirik ishtirokchilar", "alive_players"),
        ("🎮 Faqat ishtirokchilar", "players"),
        ("👥 Hamma", "all"),
    ]
    rows = []
    for label, val in options:
        mark = "✅ " if val == current else ""
        rows.append([_btn(f"{mark}{label}", f"settings:chat:{phase}:{val}")])
    rows.append(_back_exit_row("chat"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_times_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🌙 Tun vaqti", "settings:time:night_time")],
        [_btn("☀️ Kun vaqti", "settings:time:day_time")],
        [_btn("🗳 Ovoz berish", "settings:time:vote_time")],
        [_btn("⏳ Ro'yxatdan o'tish", "settings:time:registration_time")],
        [_btn("🛡 Admin tasdiqi", "settings:time:admin_start_confirm")],
        _back_exit_row("main"),
    ])


def settings_time_value_keyboard(time_key: str, current: int = 0) -> InlineKeyboardMarkup:
    values = [30, 45, 60, 90, 120, 180, 300]
    rows = []
    for v in values:
        mark = "✅ " if v == current else ""
        rows.append([_btn(f"{mark}{v} soniya", f"settings:time:{time_key}:{v}")])
    rows.append(_back_exit_row("times"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_admin_confirm_keyboard(enabled: bool = False) -> InlineKeyboardMarkup:
    on_mark = "✅ " if enabled else ""
    off_mark = "✅ " if not enabled else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{on_mark}✅ Yoqish", "settings:time:admin_start_confirm:on")],
        [_btn(f"{off_mark}🚫 O'chirish", "settings:time:admin_start_confirm:off")],
        _back_exit_row("times"),
    ])


def settings_game_type_keyboard(current: str = "classic") -> InlineKeyboardMarkup:
    if current in {"black23", "extended35"}:
        current = "classic"
    game_types = [
        ("🎭 Classic", "classic"),
        ("⚡ Super", "super"),
        ("🔥 Mega", "mega"),
        ("🧟 Zombie", "zombie"),
    ]
    rows = []
    for label, val in game_types:
        mark = "✅ " if val == current else ""
        rows.append([_btn(f"{mark}{label}", f"settings:game_type:{val}")])
    rows.append(_back_exit_row("main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_extra_keyboard(states: dict[str, bool] | None = None) -> InlineKeyboardMarkup:
    extras = [
        ("🔔 Bildirishnoma", "notifications"),
        ("🗑 Avto tozalash", "auto_clean"),
        ("📌 Pin xabar", "pin_message"),
        ("📢 Natija e'loni", "result_announce"),
    ]
    rows = []
    for label, key in extras:
        enabled = (states or {}).get(key, True)
        mark = "✅" if enabled else "🚫"
        rows.append([_btn(f"{mark} {label}", f"settings:extra:{key}")])
    rows.append(_back_exit_row("main"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_extra_toggle_keyboard(extra_key: str, is_enabled: bool = True) -> InlineKeyboardMarkup:
    on_mark = "✅ " if is_enabled else ""
    off_mark = "✅ " if not is_enabled else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"{on_mark}✅ Yoqish", f"settings:extra:{extra_key}:on")],
        [_btn(f"{off_mark}🚫 O'chirish", f"settings:extra:{extra_key}:off")],
        _back_exit_row("extra"),
    ])


def settings_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back_exit_row("main")])
