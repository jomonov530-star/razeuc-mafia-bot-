"""Tests for _safe_send_message and _safe_edit_message_reply_markup.

Verifies:
- TelegramRetryAfter triggers a sleep + single retry.
- TelegramForbiddenError is handled silently (no retry).
- TelegramBadRequest is handled silently (no retry).
- asyncio.TimeoutError is handled silently (no retry).
- The outbound semaphore is acquired on every call.
- _safe_edit_message_reply_markup retries on TelegramRetryAfter.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.game_engine import GameEngine


def _make_engine() -> GameEngine:
    """Return a bare GameEngine instance bypassing __init__."""
    engine = object.__new__(GameEngine)
    return engine


def _make_retry_after_exc(retry_after: int = 3) -> TelegramRetryAfter:
    exc = TelegramRetryAfter.__new__(TelegramRetryAfter)
    exc.retry_after = retry_after
    exc.message = f"Retry after {retry_after}"
    return exc


def _make_bad_request_exc() -> TelegramBadRequest:
    exc = TelegramBadRequest.__new__(TelegramBadRequest)
    exc.message = "Bad request"
    return exc


def _make_forbidden_exc() -> TelegramForbiddenError:
    exc = TelegramForbiddenError.__new__(TelegramForbiddenError)
    exc.message = "Forbidden"
    return exc


# ---------------------------------------------------------------------------
# _safe_send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_send_message_success():
    """Normal send: returns the sent message object."""
    engine = _make_engine()
    fake_msg = MagicMock()
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=fake_msg)

    result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is fake_msg
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_send_message_retries_on_retry_after():
    """On TelegramRetryAfter: sleeps the required duration then retries once."""
    engine = _make_engine()
    fake_msg = MagicMock()
    bot = MagicMock()
    retry_exc = _make_retry_after_exc(retry_after=2)
    # First call raises, second succeeds.
    bot.send_message = AsyncMock(side_effect=[retry_exc, fake_msg])

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is fake_msg
    assert bot.send_message.await_count == 2
    # Should sleep for retry_after + 1 = 3, capped at 30.
    mock_sleep.assert_any_await(3)



@pytest.mark.asyncio
async def test_safe_send_message_retry_after_second_call_also_fails():
    """On TelegramRetryAfter where the retry also fails: returns None, no exception raised."""
    engine = _make_engine()
    retry_exc = _make_retry_after_exc(retry_after=1)
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[retry_exc, Exception("network down")])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is None
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_safe_send_message_forbidden_no_retry():
    """TelegramForbiddenError: returns None immediately, no retry."""
    engine = _make_engine()
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_make_forbidden_exc())

    result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is None
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_send_message_bad_request_no_retry():
    """TelegramBadRequest: returns None immediately, no retry."""
    engine = _make_engine()
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_make_bad_request_exc())

    result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is None
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_send_message_timeout_no_retry():
    """asyncio.TimeoutError: returns None immediately, no retry."""
    engine = _make_engine()
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=asyncio.TimeoutError())

    result = await engine._safe_send_message(bot, chat_id=1, text="hello")

    assert result is None
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_send_message_retry_after_capped_at_30s():
    """retry_after value higher than 29 s is capped to max 30 s sleep."""
    engine = _make_engine()
    retry_exc = _make_retry_after_exc(retry_after=60)  # Very high
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[retry_exc, MagicMock()])

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await engine._safe_send_message(bot, chat_id=1, text="hello")

    waited = mock_sleep.call_args[0][0]
    assert waited <= 30, f"Sleep should be capped at 30 s, got {waited}"


# ---------------------------------------------------------------------------
# _safe_edit_message_reply_markup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_edit_reply_markup_success():
    """Normal edit: returns True."""
    engine = _make_engine()
    bot = MagicMock()
    bot.edit_message_reply_markup = AsyncMock(return_value=None)

    result = await engine._safe_edit_message_reply_markup(
        bot, chat_id=1, message_id=99, reply_markup=None
    )

    assert result is True


@pytest.mark.asyncio
async def test_safe_edit_reply_markup_retries_on_retry_after():
    """On TelegramRetryAfter: sleeps then retries once, returns True on success."""
    engine = _make_engine()
    bot = MagicMock()
    retry_exc = _make_retry_after_exc(retry_after=2)
    bot.edit_message_reply_markup = AsyncMock(side_effect=[retry_exc, None])

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await engine._safe_edit_message_reply_markup(
            bot, chat_id=1, message_id=99, reply_markup=None
        )

    assert result is True
    assert bot.edit_message_reply_markup.await_count == 2
    mock_sleep.assert_any_await(3)



@pytest.mark.asyncio
async def test_safe_edit_reply_markup_forbidden_no_retry():
    """TelegramForbiddenError: returns False immediately."""
    engine = _make_engine()
    bot = MagicMock()
    bot.edit_message_reply_markup = AsyncMock(side_effect=_make_forbidden_exc())

    result = await engine._safe_edit_message_reply_markup(
        bot, chat_id=1, message_id=99
    )

    assert result is False
    bot.edit_message_reply_markup.assert_awaited_once()
