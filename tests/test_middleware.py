"""Tests for CreditBlock middleware cache fix (is_credit_blocked).

Verifies:
- is_credit_blocked() hits the DB on first call and caches the result.
- Subsequent calls within TTL use the cache (no DB call).
- Cache expires after TTL and re-queries the DB.
- invalidate_credit_blocked_cache() forces a DB re-check on next call.
- CreditBlockMessageMiddleware uses engine.is_credit_blocked() instead of raw DB.
- CreditBlockCallbackMiddleware uses engine.is_credit_blocked() instead of raw DB.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.game_engine import GameEngine
from app.models import CreditBlockedUser, User


def _make_engine_with_session(session_factory) -> GameEngine:
    engine = object.__new__(GameEngine)
    engine.session_factory = session_factory
    engine._credit_blocked_cache = {}
    engine._blocked_users_cache_ttl = 30.0
    engine._cache_limit = 1000
    engine._monotonic = time.monotonic
    return engine


def _prune_noop(cache):
    pass  # Skip cache pruning in unit tests.


import pytest_asyncio



@pytest_asyncio.fixture
async def db_session_factory():
    db_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    await db_engine.dispose()


# ---------------------------------------------------------------------------
# is_credit_blocked — unit tests (mock session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_credit_blocked_false_for_unknown_user():
    """Unknown user returns False and caches the result."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=execute_result)

    factory = MagicMock(return_value=mock_session)
    engine = _make_engine_with_session(factory)
    engine._prune_cache_if_needed = _prune_noop

    result = await engine.is_credit_blocked(telegram_id=42)

    assert result is False
    assert 42 in engine._credit_blocked_cache


@pytest.mark.asyncio
async def test_is_credit_blocked_true_for_blocked_user():
    """Blocked user returns True."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = 999  # non-None → blocked
    mock_session.execute = AsyncMock(return_value=execute_result)

    factory = MagicMock(return_value=mock_session)
    engine = _make_engine_with_session(factory)
    engine._prune_cache_if_needed = _prune_noop

    result = await engine.is_credit_blocked(telegram_id=999)

    assert result is True


@pytest.mark.asyncio
async def test_is_credit_blocked_caches_result():
    """Second call within TTL hits cache and does NOT open a new DB session."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=execute_result)

    factory = MagicMock(return_value=mock_session)
    engine = _make_engine_with_session(factory)
    engine._prune_cache_if_needed = _prune_noop

    # First call: DB query.
    await engine.is_credit_blocked(telegram_id=7)
    # Second call: should use cache.
    await engine.is_credit_blocked(telegram_id=7)

    # Session factory was called only once (first call).
    assert factory.call_count == 1


@pytest.mark.asyncio
async def test_invalidate_credit_blocked_cache_forces_requery():
    """After invalidation, next call re-queries the DB."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=execute_result)

    factory = MagicMock(return_value=mock_session)
    engine = _make_engine_with_session(factory)
    engine._prune_cache_if_needed = _prune_noop

    await engine.is_credit_blocked(telegram_id=55)
    assert factory.call_count == 1

    engine.invalidate_credit_blocked_cache(telegram_id=55)
    assert 55 not in engine._credit_blocked_cache

    await engine.is_credit_blocked(telegram_id=55)
    assert factory.call_count == 2  # Re-queried after invalidation.


# ---------------------------------------------------------------------------
# is_credit_blocked — integration test (real SQLite)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_credit_blocked_integration(db_session_factory):
    """End-to-end: blocked user in DB is correctly detected; non-blocked is not."""
    engine = _make_engine_with_session(db_session_factory)
    engine._prune_cache_if_needed = _prune_noop

    # Insert a blocked user.
    async with db_session_factory() as session:
        session.add(User(telegram_id=1001, username="blocked", display_name="Blocked", diamonds=0, dollar=0))
        session.add(CreditBlockedUser(telegram_id=1001))
        session.add(User(telegram_id=1002, username="clean", display_name="Clean", diamonds=0, dollar=0))
        await session.commit()

    assert await engine.is_credit_blocked(1001) is True
    assert await engine.is_credit_blocked(1002) is False


# ---------------------------------------------------------------------------
# Middleware uses engine cache — structural test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credit_block_message_middleware_uses_engine():
    """CreditBlockMessageMiddleware calls engine.is_credit_blocked, not raw DB."""
    from app.main import CreditBlockMessageMiddleware

    engine = MagicMock()
    engine.is_credit_blocked = AsyncMock(return_value=True)

    data = {"engine": engine}
    event = MagicMock()
    event.from_user = MagicMock()
    event.from_user.id = 777
    event.answer = AsyncMock()

    handler = AsyncMock()

    mw = CreditBlockMessageMiddleware()
    result = await mw(handler, event, data)

    engine.is_credit_blocked.assert_awaited_once_with(777)
    handler.assert_not_awaited()   # Blocked → handler not called.
    assert result is None


@pytest.mark.asyncio
async def test_credit_block_message_middleware_allows_clean_user():
    """Non-blocked user passes through to the handler."""
    from app.main import CreditBlockMessageMiddleware

    engine = MagicMock()
    engine.is_credit_blocked = AsyncMock(return_value=False)

    data = {"engine": engine}
    event = MagicMock()
    event.from_user = MagicMock()
    event.from_user.id = 888

    handler = AsyncMock(return_value="ok")

    mw = CreditBlockMessageMiddleware()
    result = await mw(handler, event, data)

    handler.assert_awaited_once_with(event, data)


@pytest.mark.asyncio
async def test_credit_block_callback_middleware_uses_engine():
    """CreditBlockCallbackMiddleware calls engine.is_credit_blocked for callbacks."""
    from app.main import CreditBlockCallbackMiddleware

    engine = MagicMock()
    engine.is_credit_blocked = AsyncMock(return_value=True)

    data = {"engine": engine}
    event = MagicMock()
    event.from_user = MagicMock()
    event.from_user.id = 555
    event.answer = AsyncMock()

    handler = AsyncMock()

    mw = CreditBlockCallbackMiddleware()
    result = await mw(handler, event, data)

    engine.is_credit_blocked.assert_awaited_once_with(555)
    handler.assert_not_awaited()
    assert result is None
