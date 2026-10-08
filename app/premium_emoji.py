"""Premium (custom) emoji almashtirish tizimi.

Admin panelda "oddiy emoji -> premium emoji" juftligi saqlanadi (bazada, `bot_settings`
jadvalida). Keyin botdan chiqadigan HAR BIR xabar va tugma avtomatik tekshiriladi:

* xabar matnidagi/captiondagi oddiy emoji  -> <tg-emoji emoji-id="..."> ga almashtiriladi;
* mavjud <tg-emoji> bo'lsa va uning oddiy belgisi ro'yxatda bo'lsa -> yangi ID qo'yiladi;
* tugma matni emoji bilan boshlansa -> emoji matndan olinib, `icon_custom_emoji_id` qo'yiladi;
* tugmada `icon_custom_emoji_id` bor bo'lsa, matndagi oddiy emoji olib tashlanadi
  (ikkita emoji yonma-yon ko'rinib qolmasligi uchun).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from aiogram import Bot
from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import (
    EditMessageCaption,
    EditMessageReplyMarkup,
    EditMessageText,
    SendAnimation,
    SendAudio,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
    SendVoice,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.models import BotSetting

logger = logging.getLogger(__name__)

SETTING_KEY = "premium_emoji_map"

# Bitta emoji (bayroq, ZWJ ketma-ketlik, teri tusi va variation selector bilan)
_ONE = (
    r"(?:[\U0001F1E6-\U0001F1FF]{2}"
    r"|[\U0001F300-\U0001FAFF☀-➿⬅-⭕←-⇿⌀-⏿"
    r"⤴⤵〰〽㊗㊙©®‼⁉™ℹⓂ▪-◾])"
    r"[️⃣\U0001F3FB-\U0001F3FF]*"
)
EMOJI_RE = re.compile(rf"{_ONE}(?:‍{_ONE})*")
_LEADING_RE = re.compile(rf"^\s*({_ONE}(?:‍{_ONE})*)\s*")

_TOKEN_RE = re.compile(
    r"(<tg-emoji\b[^>]*>.*?</tg-emoji>|<(?:code|pre)\b[^>]*>.*?</(?:code|pre)>|<[^>]+>)",
    re.DOTALL | re.IGNORECASE,
)
_TG_EMOJI_RE = re.compile(
    r'^<tg-emoji\b([^>]*?)emoji-id="(\d+)"([^>]*)>(.*?)</tg-emoji>$', re.DOTALL | re.IGNORECASE
)

_MAP: dict[str, str] = {}
_PATTERN: Optional[re.Pattern[str]] = None


def norm(char: str) -> str:
    """Variation selector (U+FE0F) siz holatga keltiradi."""
    return (char or "").replace("️", "").strip()


def first_emoji(text: str) -> Optional[str]:
    match = EMOJI_RE.search(text or "")
    return match.group(0) if match else None


def _rebuild() -> None:
    global _PATTERN
    if not _MAP:
        _PATTERN = None
        return
    keys = sorted(_MAP, key=len, reverse=True)
    parts = ["".join(re.escape(ch) + "️?" for ch in key) for key in keys]
    _PATTERN = re.compile("(?:" + "|".join(parts) + ")")


def get_map() -> dict[str, str]:
    return dict(_MAP)


def set_map(data: dict[str, str]) -> None:
    _MAP.clear()
    for key, value in data.items():
        k = norm(key)
        if k and str(value).isdigit():
            _MAP[k] = str(value)
    _rebuild()


def resolve_id(char: str, default: Optional[str] = None) -> Optional[str]:
    """Oddiy emoji uchun premium ID (admin o'rnatgan bo'lsa), aks holda `default`."""
    return _MAP.get(norm(char)) or default


# --- bazaga saqlash -------------------------------------------------------------------


async def load(session_factory: Any) -> None:
    try:
        async with session_factory() as session:
            setting = (
                await session.execute(select(BotSetting).where(BotSetting.key == SETTING_KEY))
            ).scalar_one_or_none()
        data = json.loads(setting.value) if setting and setting.value else {}
        set_map(data if isinstance(data, dict) else {})
        logger.info("Premium emoji map yuklandi: %d ta", len(_MAP))
    except Exception:
        logger.exception("Premium emoji map yuklanmadi")


async def _save(session_factory: Any) -> None:
    payload = json.dumps(_MAP, ensure_ascii=False)
    async with session_factory() as session:
        setting = (
            await session.execute(select(BotSetting).where(BotSetting.key == SETTING_KEY))
        ).scalar_one_or_none()
        if setting is None:
            session.add(BotSetting(key=SETTING_KEY, value=payload))
        else:
            setting.value = payload
        await session.commit()


async def set_mapping(session_factory: Any, char: str, emoji_id: str) -> None:
    key = norm(char)
    if not key or not str(emoji_id).isdigit():
        raise ValueError("Noto'g'ri emoji yoki ID")
    _MAP[key] = str(emoji_id)
    _rebuild()
    await _save(session_factory)


async def remove_mapping(session_factory: Any, char: str) -> bool:
    removed = _MAP.pop(norm(char), None) is not None
    _rebuild()
    if removed:
        await _save(session_factory)
    return removed


async def clear_all(session_factory: Any) -> None:
    _MAP.clear()
    _rebuild()
    await _save(session_factory)


# --- matn va tugmalarni qayta yozish --------------------------------------------------


def apply_html(text: str) -> str:
    """HTML matndagi emoji'larni premium ga almashtiradi (teglar ichiga tegmaydi)."""
    if not text or _PATTERN is None:
        return text
    out: list[str] = []
    for token in _TOKEN_RE.split(text):
        if not token:
            continue
        if token.startswith("<"):
            m = _TG_EMOJI_RE.match(token)
            if m:
                new_id = _MAP.get(norm(m.group(4)))
                if new_id and new_id != m.group(2):
                    token = f'<tg-emoji{m.group(1)}emoji-id="{new_id}"{m.group(3)}>{m.group(4)}</tg-emoji>'
            out.append(token)
            continue
        out.append(
            _PATTERN.sub(
                lambda mm: f'<tg-emoji emoji-id="{_MAP[norm(mm.group(0))]}">{mm.group(0)}</tg-emoji>',
                token,
            )
        )
    return "".join(out)


def _process_button(button: InlineKeyboardButton) -> InlineKeyboardButton:
    text = button.text or ""
    match = _LEADING_RE.match(text)
    if match is None:
        return button
    rest = text[match.end():].strip()
    mapped = _MAP.get(norm(match.group(1)))
    icon = button.icon_custom_emoji_id
    update: dict[str, Any] = {}
    if icon:
        if mapped and mapped != icon:
            update["icon_custom_emoji_id"] = mapped
        if rest:
            update["text"] = rest
    elif mapped:
        update["icon_custom_emoji_id"] = mapped
        if rest:
            update["text"] = rest
    return button.model_copy(update=update) if update else button


def process_markup(markup: Any) -> Any:
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = [[_process_button(b) for b in row] for row in markup.inline_keyboard]
    return InlineKeyboardMarkup(inline_keyboard=rows)


_TEXT_METHODS = (SendMessage, EditMessageText)
_CAPTION_METHODS = (
    SendPhoto,
    SendVideo,
    SendAnimation,
    SendDocument,
    SendAudio,
    SendVoice,
    EditMessageCaption,
)


def _is_html(parse_mode: Any) -> bool:
    if isinstance(parse_mode, Default):
        return True  # Bot default = HTML (main.py da shunday o'rnatilgan)
    return isinstance(parse_mode, str) and parse_mode.upper() == "HTML"


class PremiumEmojiMiddleware(BaseRequestMiddleware):
    """Botdan chiqayotgan so'rovlarni (xabar/tugma) premium emoji bilan boyitadi."""

    async def __call__(self, make_request, bot: Bot, method):  # type: ignore[no-untyped-def]
        try:
            method = self._rewrite(method)
        except Exception:
            logger.exception("Premium emoji almashtirishda xato (asl xabar yuboriladi)")
        return await make_request(bot, method)

    @staticmethod
    def _rewrite(method):  # type: ignore[no-untyped-def]
        has_buttons = isinstance(method, (*_TEXT_METHODS, *_CAPTION_METHODS, EditMessageReplyMarkup))
        if not has_buttons:
            return method
        update: dict[str, Any] = {}

        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            update["reply_markup"] = process_markup(markup)

        if _MAP:
            if isinstance(method, _TEXT_METHODS):
                if not method.entities and _is_html(method.parse_mode) and method.text:
                    update["text"] = apply_html(method.text)
            elif isinstance(method, _CAPTION_METHODS):
                if not method.caption_entities and _is_html(method.parse_mode) and method.caption:
                    update["caption"] = apply_html(method.caption)

        return method.model_copy(update=update) if update else method
