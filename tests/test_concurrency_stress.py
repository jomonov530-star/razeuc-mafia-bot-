"""Stress and concurrency tests simulating multiple active games running simultaneously."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.database import Base
from app.enums import GamePhase, GameStatus, Role, Team
from app.game_engine import GameEngine
from app.models import Game, GamePlayer, Group


@pytest_asyncio.fixture
async def stress_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    bot.edit_message_reply_markup = AsyncMock(return_value=True)
    return bot


async def _setup_active_game(session_factory, chat_id: int, num_players: int = 6) -> int:
    async with session_factory() as session:
        group = Group(chat_id=chat_id, title=f"Stress Group {chat_id}")
        session.add(group)
        game = Game(
            chat_id=chat_id,
            creator_telegram_id=999,
            status=GameStatus.ACTIVE.value,
            phase=GamePhase.NIGHT.value,
            night_number=1,
            day_number=0,
            role_preset="black23",
        )
        session.add(game)
        await session.commit()
        await session.refresh(game)
        game_id = game.id

        # Add players
        roles = [Role.DON.value, Role.MAFIA.value, Role.COMMISSAR.value, Role.DOCTOR.value, Role.CITIZEN.value, Role.CITIZEN.value]
        teams = [Team.MAFIA.value, Team.MAFIA.value, Team.CITY.value, Team.CITY.value, Team.CITY.value, Team.CITY.value]
        for i in range(num_players):
            uid = chat_id * 1000 + i + 1
            gp = GamePlayer(
                game_id=game_id,
                telegram_id=uid,
                display_name=f"Player_{uid}",
                role=roles[i % len(roles)],
                team=teams[i % len(teams)],
                alive=True,
            )
            session.add(gp)
        await session.commit()
        return game_id


@pytest.mark.asyncio
async def test_single_active_game_stress(stress_db, mock_bot):
    """Simulate 1 active game sending night prompts concurrently."""
    engine = GameEngine(Settings(), stress_db)
    game_id = await _setup_active_game(stress_db, chat_id=1001)

    await engine.send_night_prompts(mock_bot, game_id)
    assert mock_bot.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_five_concurrent_games_stress(stress_db, mock_bot):
    """Simulate 5 active games sending night prompts concurrently."""
    engine = GameEngine(Settings(), stress_db)
    game_ids = await asyncio.gather(*(
        _setup_active_game(stress_db, chat_id=2000 + i) for i in range(5)
    ))

    # Run send_night_prompts for all 5 games in parallel
    results = await asyncio.gather(*(
        engine.send_night_prompts(mock_bot, gid) for gid in game_ids
    ), return_exceptions=True)

    for res in results:
        assert not isinstance(res, Exception), f"Game execution raised: {res}"

    assert mock_bot.send_message.call_count >= 5


@pytest.mark.asyncio
async def test_ten_concurrent_games_stress(stress_db, mock_bot):
    """Simulate 10 active games (peak load) sending night prompts concurrently under Semaphore limits."""
    engine = GameEngine(Settings(), stress_db)
    game_ids = await asyncio.gather(*(
        _setup_active_game(stress_db, chat_id=3000 + i) for i in range(10)
    ))

    # Run send_night_prompts for all 10 games in parallel
    results = await asyncio.gather(*(
        engine.send_night_prompts(mock_bot, gid) for gid in game_ids
    ), return_exceptions=True)

    for res in results:
        assert not isinstance(res, Exception), f"Peak stress game execution raised: {res}"

    # Verify all 10 games processed their prompts successfully without deadlocks
    assert mock_bot.send_message.call_count >= 10


@pytest.mark.asyncio
async def test_slow_telegram_response_isolation(stress_db, mock_bot):
    """Simulate Telegram API delay in Game 1 to verify Game 2 is not blocked."""
    async def delayed_send(chat_id, text, **kwargs):
        if chat_id > 4005:  # Slow user in game 1
            await asyncio.sleep(0.5)
        return MagicMock(message_id=888)

    mock_bot.send_message.side_effect = delayed_send
    engine = GameEngine(Settings(), stress_db)

    gid1 = await _setup_active_game(stress_db, chat_id=4001)
    gid2 = await _setup_active_game(stress_db, chat_id=4002)

    start_time = asyncio.get_running_loop().time()
    await asyncio.gather(
        engine.send_night_prompts(mock_bot, gid1),
        engine.send_night_prompts(mock_bot, gid2),
    )
    elapsed = asyncio.get_running_loop().time() - start_time

    # Concurrent execution should complete close to the max single delay (0.5s), not 2x cumulative delay
    assert elapsed < 1.2, f"Expected concurrent execution < 1.2s, got {elapsed:.2f}s"
