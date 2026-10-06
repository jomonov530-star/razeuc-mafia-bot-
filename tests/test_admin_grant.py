"""Tests for admin balance granting by target (username or user_id)."""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.database import Base
from app.models import User
from app.game_engine import GameEngine


@pytest.mark.asyncio
async def test_grant_balance_by_target_username_and_id():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    # Pre-create test users in database
    async with session_factory() as session:
        user1 = User(telegram_id=11111, username="test_user1", display_name="User One", dollar=100, diamonds=5)
        user2 = User(telegram_id=22222, username="Test_User2", display_name="User Two", dollar=50, diamonds=10)
        session.add_all([user1, user2])
        await session.commit()

    # 1. Grant dollars using @username
    ok, text = await engine.grant_balance_by_target("@test_user1", dollar=500, diamonds=0)
    assert ok is True
    assert "User One" in text
    assert "500" in text

    # Verify user1 dollars updated to 600
    async with session_factory() as session:
        u1 = (await session.get(User, user1.id))
        assert u1.dollar == 600
        assert u1.diamonds == 5

    # 2. Grant diamonds using username without @ (case insensitive)
    ok, text = await engine.grant_balance_by_target("TEST_USER2", dollar=0, diamonds=25)
    assert ok is True
    assert "User Two" in text
    assert "25" in text

    # Verify user2 diamonds updated to 35
    async with session_factory() as session:
        u2 = (await session.get(User, user2.id))
        assert u2.dollar == 50
        assert u2.diamonds == 35

    # 3. Grant both using telegram_id
    ok, text = await engine.grant_balance_by_target(11111, dollar=200, diamonds=10)
    assert ok is True

    async with session_factory() as session:
        u1 = (await session.get(User, user1.id))
        assert u1.dollar == 800
        assert u1.diamonds == 15

    # 4. Non-existent user
    ok, text = await engine.grant_balance_by_target("@non_existent_user", dollar=100)
    assert ok is False
    assert "Foydalanuvchi topilmadi" in text

    # 5. Backward compatible grant_balance
    ok, text = await engine.grant_balance(22222, dollar=100, diamonds=5)
    assert ok is True
    async with session_factory() as session:
        u2 = (await session.get(User, user2.id))
        assert u2.dollar == 150
        assert u2.diamonds == 40
