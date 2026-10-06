from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.game_engine import GameEngine
from app.models import User, PromoCode, PromoCodeRedemption


@pytest.mark.asyncio
async def test_promo_code_creation_and_redemption():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)

    user_id = 123456789

    # Create test user
    async with session_factory() as session:
        user = User(telegram_id=user_id, display_name="Sanjarbek", dollar=100, diamonds=10)
        session.add(user)
        await session.commit()

    # 1. Create valid promo code
    ok, msg = await engine.create_promo_code(
        code="MAFIA2026",
        dollar=500,
        diamond=50,
        max_uses=2,
        created_by=99999,
    )
    assert ok is True
    assert "MAFIA2026" in msg

    # 2. Try duplicate promo code creation
    ok_dup, msg_dup = await engine.create_promo_code("mafia2026", dollar=100, diamond=10)
    assert ok_dup is False
    assert "allaqachon mavjud" in msg_dup

    # 3. Redeem promo code for user
    ok_red, msg_red = await engine.redeem_promo_code(user_id, "Sanjarbek", "mafia2026")
    assert ok_red is True
    assert "500 $" in msg_red
    assert "50 olmos" in msg_red

    # Check updated balance
    async with session_factory() as session:
        u = await session.get(User, 1)
        assert u.dollar == 600
        assert u.diamonds == 60

    # 4. Try double redemption by same user
    ok_twice, msg_twice = await engine.redeem_promo_code(user_id, "Sanjarbek", "MAFIA2026")
    assert ok_twice is False
    assert "allaqachon ishlatgansiz" in msg_twice

    # 5. Second user redeems code
    async with session_factory() as session:
        user2 = User(telegram_id=88888, display_name="User Two", dollar=0, diamonds=0)
        session.add(user2)
        await session.commit()

    ok_user2, _ = await engine.redeem_promo_code(88888, "User Two", "MAFIA2026")
    assert ok_user2 is True

    # 6. Third user tries to redeem (exceeds max_uses=2)
    async with session_factory() as session:
        user3 = User(telegram_id=77777, display_name="User Three", dollar=0, diamonds=0)
        session.add(user3)
        await session.commit()

    ok_user3, msg_user3 = await engine.redeem_promo_code(77777, "User Three", "MAFIA2026")
    assert ok_user3 is False
    assert "limiti tugagan" in msg_user3
