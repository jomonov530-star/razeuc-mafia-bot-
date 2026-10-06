from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.game_engine import GameEngine
from app.models import ScheduledBroadcast, User, Group, Game


@pytest.mark.asyncio
async def test_2x_event_mode_and_analytics():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    # Initially 2X event is inactive
    assert await engine.is_2x_event_active() is False

    # Toggle 2X event
    is_on, text = await engine.toggle_2x_event(admin_id=99999)
    assert is_on is True
    assert await engine.is_2x_event_active() is True
    assert "YOQILDI" in text

    # Toggle off
    is_on_2, _ = await engine.toggle_2x_event(admin_id=99999)
    assert is_on_2 is False
    assert await engine.is_2x_event_active() is False


@pytest.mark.asyncio
async def test_dau_mau_analytics_stats():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    async with session_factory() as session:
        u1 = User(telegram_id=111, display_name="A1")
        u2 = User(telegram_id=222, display_name="A2")
        g1 = Group(chat_id=-1001)
        session.add_all([u1, u2, g1])
        await session.commit()

    stats = await engine.get_dau_mau_stats()
    assert stats["total_users"] == 2
    assert stats["total_groups"] == 1
    assert stats["dau"] == 2
    assert stats["mau"] == 2

    text = await engine.analytics_dashboard_text()
    assert "Bot Analitikasi" in text
    assert "DAU" in text


@pytest.mark.asyncio
async def test_scheduled_broadcast_processor():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    due_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    ok, msg = await engine.schedule_broadcast(
        target="users",
        from_chat_id=100,
        message_id=500,
        scheduled_at=due_time,
        created_by=99999,
    )
    assert ok is True
    assert "rejalashtirildi" in msg

    async with session_factory() as session:
        sb = (await session.execute(select(ScheduledBroadcast))).scalar_one_or_none()
        assert sb is not None
        assert sb.status == "pending"
