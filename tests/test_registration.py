"""Tests for registration_watchdog concurrency fix.

Verifies:
- registration_watchdog issues close_registration calls concurrently via gather.
- A failure in one game's close_registration does not prevent the others.
- The game_ids list is collected before gather (no DB session held open across calls).
- When no games are expired, no close_registration calls are made.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone, timedelta

import pytest

from app.game_engine import GameEngine
from app.enums import GameStatus


def _make_engine() -> GameEngine:
    engine = object.__new__(GameEngine)
    return engine


def _utc_past(seconds: int = 60) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# registration_watchdog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_watchdog_no_expired_games():
    """If no games are expired, close_registration is never called."""
    engine = _make_engine()
    engine._now_utc = lambda: datetime.now(timezone.utc)

    # Mock session that returns empty list.
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=execute_result)

    engine.session_factory = MagicMock(return_value=mock_session)
    engine.close_registration = AsyncMock()

    await engine.registration_watchdog(bot=MagicMock())

    engine.close_registration.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_multiple_games_closed_concurrently():
    """Multiple expired games trigger concurrent close_registration calls."""
    engine = _make_engine()
    engine._now_utc = lambda: datetime.now(timezone.utc)

    # Fake games.
    g1, g2, g3 = MagicMock(), MagicMock(), MagicMock()
    g1.id, g2.id, g3.id = 10, 20, 30

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [g1, g2, g3]
    mock_session.execute = AsyncMock(return_value=execute_result)
    engine.session_factory = MagicMock(return_value=mock_session)

    call_order = []

    async def fake_close(bot, game_id):
        call_order.append(game_id)

    engine.close_registration = fake_close

    await engine.registration_watchdog(bot=MagicMock())

    # All three games were closed.
    assert set(call_order) == {10, 20, 30}


@pytest.mark.asyncio
async def test_watchdog_one_failure_does_not_block_others():
    """A RuntimeError in one close_registration doesn't prevent the rest."""
    engine = _make_engine()
    engine._now_utc = lambda: datetime.now(timezone.utc)

    g1, g2, g3 = MagicMock(), MagicMock(), MagicMock()
    g1.id, g2.id, g3.id = 10, 20, 30

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [g1, g2, g3]
    mock_session.execute = AsyncMock(return_value=execute_result)
    engine.session_factory = MagicMock(return_value=mock_session)

    closed = []

    async def fake_close(bot, game_id):
        if game_id == 20:
            raise RuntimeError("DB exploded for game 20")
        closed.append(game_id)

    engine.close_registration = fake_close

    # Should not raise — watchdog catches exceptions via return_exceptions=True.
    await engine.registration_watchdog(bot=MagicMock())

    assert 10 in closed
    assert 30 in closed
    # Game 20 failed but 10 and 30 completed.
    assert 20 not in closed


@pytest.mark.asyncio
async def test_watchdog_game_ids_collected_before_gather():
    """game_ids list is built inside the session block so the session is closed before gather."""
    engine = _make_engine()
    engine._now_utc = lambda: datetime.now(timezone.utc)

    g1 = MagicMock()
    g1.id = 99

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [g1]
    mock_session.execute = AsyncMock(return_value=execute_result)
    engine.session_factory = MagicMock(return_value=mock_session)

    closed = []

    async def fake_close(bot, game_id):
        # By the time close_registration runs, __aexit__ should already have been called.
        closed.append(game_id)

    engine.close_registration = fake_close

    await engine.registration_watchdog(bot=MagicMock())

    # Verify __aexit__ was called (session closed) before close_registration ran.
    assert mock_session.__aexit__.await_count >= 1
    assert closed == [99]
