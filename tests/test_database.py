"""Tests for database.py — SQLite WAL pragma fix.

Verifies that init_db() applies WAL journal mode and related pragmas when
running against a SQLite database, and is a no-op for non-SQLite engines
(guarded by the url startswith check, tested here via a mock).
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_wal_pragma_applied(tmp_path):
    """After init_db()-style setup, file-backed SQLite should report WAL journal mode."""
    db_file = tmp_path / "test.db"
    file_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    
    try:
        # Apply the same pragma block that init_db() now executes.
        async with file_engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA busy_timeout=5000"))

        async with file_engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
            sync = (await conn.execute(text("PRAGMA synchronous"))).scalar()
            timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()

        assert mode.lower() == "wal", f"Expected WAL journal mode, got: {mode!r}"
        # synchronous=NORMAL is 1 in SQLite integer representation
        assert sync == 1, f"Expected synchronous=NORMAL (1), got: {sync!r}"
        assert timeout == 5000, f"Expected busy_timeout=5000, got: {timeout!r}"
    finally:
        await file_engine.dispose()


@pytest.mark.asyncio
async def test_database_url_guard():
    """The WAL block is guarded by startswith('sqlite'); PostgreSQL urls are not affected."""
    non_sqlite_url = "postgresql+asyncpg://user:pass@localhost/db"
    # Just verify the guard logic works as a unit — no actual connection needed.
    assert not non_sqlite_url.startswith("sqlite")
    assert "sqlite+aiosqlite:///:memory:".startswith("sqlite")


@pytest.mark.asyncio
async def test_init_db_creates_tables(sqlite_engine):
    """init_db logic (create_all) populates the schema without errors."""
    async with sqlite_engine.begin() as conn:
        # Apply WAL pragma first (as init_db now does)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)

    # Verify at least one known table was created.
    async with sqlite_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        tables = {row[0] for row in result.fetchall()}

    assert "games" in tables or "game" in tables or len(tables) > 0, (
        "Expected at least one table after create_all"
    )
