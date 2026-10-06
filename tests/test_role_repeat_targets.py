"""Test that Kezuvchi, Daydi, Doctor, and Commissar can target the same player on multiple nights."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.database import Base
from app.enums import GamePhase, GameStatus, Role
from app.models import Game, GamePlayer
from app.game_engine import GameEngine


@pytest.mark.asyncio
async def test_repeat_target_allowed_for_kezuvchi_daydi_doctor_commissar():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings()
    engine = GameEngine(session_factory=session_factory, settings=settings)
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_bot.get_chat = AsyncMock()

    # Setup game in night phase
    async with session_factory() as session:
        game = Game(
            chat_id=-1001,
            creator_telegram_id=999,
            status=GameStatus.ACTIVE.value,
            phase=GamePhase.NIGHT.value,
            night_number=1,
        )
        session.add(game)
        await session.flush()

        p_doctor = GamePlayer(game_id=game.id, telegram_id=101, display_name="Doc", role=Role.DOCTOR.value, alive=True)
        p_mistress = GamePlayer(game_id=game.id, telegram_id=102, display_name="Mistress", role=Role.MISTRESS.value, alive=True)
        p_bum = GamePlayer(game_id=game.id, telegram_id=103, display_name="Bum", role=Role.BUM.value, alive=True)
        p_commissar = GamePlayer(game_id=game.id, telegram_id=104, display_name="Commissar", role=Role.COMMISSAR.value, alive=True)
        p_target = GamePlayer(game_id=game.id, telegram_id=105, display_name="Target", role=Role.CITIZEN.value, alive=True)
        session.add_all([p_doctor, p_mistress, p_bum, p_commissar, p_target])
        await session.commit()
        game_id = game.id

    # Night 1: All 4 roles target player 105
    ok, msg = await engine.record_action(mock_bot, game_id, 101, "heal", 105)
    assert ok is True, f"Night 1 Doctor failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 102, "block", 105)
    assert ok is True, f"Night 1 Mistress failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 103, "visit", 105)
    assert ok is True, f"Night 1 Bum failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 104, "check", 105)
    assert ok is True, f"Night 1 Commissar failed: {msg}"

    # Advance to Night 2
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        game.night_number = 2
        await session.commit()

    # Night 2: All 4 roles target player 105 AGAIN (repeat target allowed)
    ok, msg = await engine.record_action(mock_bot, game_id, 101, "heal", 105)
    assert ok is True, f"Night 2 Doctor repeat heal failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 102, "block", 105)
    assert ok is True, f"Night 2 Mistress repeat block failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 103, "visit", 105)
    assert ok is True, f"Night 2 Bum repeat visit failed: {msg}"

    ok, msg = await engine.record_action(mock_bot, game_id, 104, "check", 105)
    assert ok is True, f"Night 2 Commissar repeat check failed: {msg}"
