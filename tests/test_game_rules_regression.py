"""Regression tests for end-to-end GameEngine lifecycle and game rules preservation."""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.types import User as TgUser
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.database import Base
from app.enums import GamePhase, GameStatus, Role, Team
from app.game_engine import GameEngine
from app.models import Game, GamePlayer, Group, User


@pytest_asyncio.fixture
async def regression_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
    bot.edit_message_text = AsyncMock(return_value=True)
    bot.edit_message_reply_markup = AsyncMock(return_value=True)
    bot.pin_chat_message = AsyncMock(return_value=True)
    return bot


@pytest.mark.asyncio
async def test_game_registration_lifecycle(regression_db, mock_bot):
    """Test full game creation, player joining, and registration status."""
    engine = GameEngine(Settings(), regression_db)
    chat_id = -1001234567

    # 1. Create registration
    success, msg = await engine.create_game_registration(
        mock_bot, chat_id, "Regression Group", creator_id=101
    )
    assert success is True

    # 2. Fetch created active game ID and join with users
    async with regression_db() as session:
        game = await engine.find_active_game(session, chat_id)
        assert game is not None
        game_id = game.id

    for uid in [101, 102, 103, 104]:
        tg_user = TgUser(id=uid, is_bot=False, first_name=f"User{uid}", username=f"user{uid}")
        j_success, j_msg = await engine.join_game(mock_bot, game_id, tg_user)
        assert j_success is True, f"Failed to join game for user {uid}: {j_msg}"

    # 3. Verify players in DB
    async with regression_db() as session:
        game = await engine.find_active_game(session, chat_id)
        assert game is not None
        assert game.status == GameStatus.REGISTRATION.value
        players = (await session.execute(
            text("SELECT count(*) FROM game_players WHERE game_id = :gid"), {"gid": game.id}
        )).scalar()
        assert players == 4


@pytest.mark.asyncio
async def test_winner_checking_logic(regression_db):
    """Test check_winner logic for City vs Mafia victory conditions."""
    engine = GameEngine(Settings(), regression_db)
    
    async with regression_db() as session:
        game = Game(chat_id=5001, creator_telegram_id=999, status=GameStatus.ACTIVE.value, phase=GamePhase.NIGHT.value)
        session.add(game)
        await session.commit()
        await session.refresh(game)

        # 1. City alive, Mafia dead -> City wins
        p1 = GamePlayer(game_id=game.id, telegram_id=1, display_name="City_1", role=Role.CITIZEN.value, team=Team.CITY.value, alive=True)
        p2 = GamePlayer(game_id=game.id, telegram_id=2, display_name="Don_2", role=Role.DON.value, team=Team.MAFIA.value, alive=False)
        session.add_all([p1, p2])
        await session.commit()

    winner = await engine.check_winner(game.id)
    assert winner == Team.CITY.value

    async with regression_db() as session:
        # 2. Equal Mafia and City -> Mafia wins
        p1.alive = True
        p2.alive = True
        session.add_all([p1, p2])
        await session.commit()

    winner = await engine.check_winner(game.id)
    assert winner == Team.MAFIA.value


@pytest.mark.asyncio
async def test_restored_methods_functionality(regression_db, mock_bot):
    """Verify restored methods user_in_running_game, active_game_for_chat, is_vip_user_active, _news_bonus_channel_id."""
    engine = GameEngine(Settings(), regression_db)
    chat_id = -100999888

    # 1. _news_bonus_channel_id returns string
    assert engine._news_bonus_channel_id() == "@WorldMafiaNews"

    # 2. active_game_for_chat returns None when no game
    active_g = await engine.active_game_for_chat(chat_id)
    assert active_g is None

    # 3. Create game and verify active_game_for_chat and user_in_running_game
    await engine.create_game_registration(mock_bot, chat_id, "Test Group", creator_id=777)
    active_g = await engine.active_game_for_chat(chat_id)
    assert active_g is not None
    assert active_g.chat_id == chat_id

    # 4. Join player and transition to active
    tg_u = TgUser(id=777, is_bot=False, first_name="Player777")
    await engine.join_game(mock_bot, active_g.id, tg_u)

    async with regression_db() as session:
        game = await session.get(Game, active_g.id)
        game.status = GameStatus.ACTIVE.value
        await session.commit()

    in_game = await engine.user_in_running_game(777)
    assert in_game is True

    # 5. is_vip_user_active for unknown user returns False
    is_vip = await engine.is_vip_user_active(777)
    assert is_vip is False


@pytest.mark.asyncio
async def test_cmd_profile_handler(regression_db):
    """Verify _send_profile formats and answers user dashboard without NameError."""
    from app.handlers.profile import _send_profile
    engine = GameEngine(Settings(), regression_db)
    msg = MagicMock()
    msg.from_user = TgUser(id=555111, is_bot=False, first_name="TestUser", username="testuser")
    msg.chat = MagicMock(type="private", id=555111)
    msg.answer = AsyncMock()

    await _send_profile(msg, engine, Settings())
    assert msg.answer.call_count == 1


