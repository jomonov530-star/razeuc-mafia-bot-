"""Tests for mandatory news channel subscription feature."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.database import Base
from app.game_engine import GameEngine


@pytest.mark.asyncio
async def test_extract_channel_identifier():
    assert GameEngine.extract_channel_identifier("@WorldMafiaNews") == "@WorldMafiaNews"
    assert GameEngine.extract_channel_identifier("https://t.me/WorldMafiaNews") == "@WorldMafiaNews"
    assert GameEngine.extract_channel_identifier("t.me/WorldMafiaNews") == "@WorldMafiaNews"
    assert GameEngine.extract_channel_identifier("-100123456789") == -100123456789
    assert GameEngine.extract_channel_identifier("https://t.me/+AbCdEfGh") is None


@pytest.mark.asyncio
async def test_toggle_and_check_news_sub():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    admin_id = next(iter(settings.admin_ids)) if settings.admin_ids else 123456789
    settings.admin_ids_raw = str(admin_id)

    mock_bot = MagicMock()
    mock_bot.get_chat_member = AsyncMock()

    # Initially sub is disabled -> returns True
    assert await engine.is_news_sub_required() is False
    assert await engine.check_user_news_subscription(mock_bot, 12345) is True

    # Enable mandatory sub
    is_req, msg = await engine.toggle_news_sub_required()
    assert is_req is True
    assert await engine.is_news_sub_required() is True

    # Set news channel url
    await engine.set_news_channel_url("https://t.me/WorldMafiaNews")

    # Admin bypasses mandatory sub
    assert await engine.check_user_news_subscription(mock_bot, admin_id) is True

    # Mock subscribed member
    mock_member_sub = MagicMock()
    mock_member_sub.status = "member"
    mock_bot.get_chat_member.return_value = mock_member_sub

    assert await engine.check_user_news_subscription(mock_bot, 11111, ignore_cache=True) is True

    # Mock unsubscribed member
    mock_member_unsub = MagicMock()
    mock_member_unsub.status = "left"
    mock_bot.get_chat_member.return_value = mock_member_unsub

    assert await engine.check_user_news_subscription(mock_bot, 22222, ignore_cache=True) is False

    # Toggle back to disabled
    is_req, msg = await engine.toggle_news_sub_required()
    assert is_req is False
    assert await engine.check_user_news_subscription(mock_bot, 22222, ignore_cache=True) is True
