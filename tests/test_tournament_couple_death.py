"""Tests for tournament couple elimination and voting button premium emoji formatting."""
from unittest.mock import AsyncMock, MagicMock
import pytest
import pytest_asyncio
from aiogram.types import InlineKeyboardButton, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.enums import GamePhase, GameStatus, Role, Team
from app.game_engine import GameEngine
from app.keyboards import parse_player_button, vote_keyboard
from app.models import BotSetting, CoupleRelationship, Game, GamePlayer, User


@pytest_asyncio.fixture
async def tournament_db():
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
    bot.get_chat_member = AsyncMock()
    return bot


def test_parse_player_button_clean_and_emoji_extraction():
    """Verify that parse_player_button extracts custom emoji IDs and cleans HTML."""
    # 1. HTML with tg-emoji and bold tags
    raw1 = '<tg-emoji emoji-id="5422577965626060349">⭐</tg-emoji> <b>Sanjarbek</b>'
    clean1, emoji1 = parse_player_button(raw1)
    assert clean1 == "Sanjarbek"
    assert emoji1 == "5422577965626060349"

    # 2. tg-emoji after nickname
    raw2 = '<b>Laylo</b> <tg-emoji emoji-id="5415897487594509180">🛡</tg-emoji>'
    clean2, emoji2 = parse_player_button(raw2)
    assert clean2 == "Laylo"
    assert emoji2 == "5415897487594509180"

    # 3. Plain nickname without badge
    raw3 = "Oddiy O'yinchi"
    clean3, emoji3 = parse_player_button(raw3)
    assert clean3 == "Oddiy O'yinchi"
    assert emoji3 is None

    # 4. Leaked standalone digit ID
    raw4 = "5422577965626060349 Botir"
    clean4, emoji4 = parse_player_button(raw4)
    assert clean4 == "Botir"
    assert emoji4 == "5422577965626060349"


def test_vote_keyboard_uses_icon_custom_emoji_id():
    """Verify that vote_keyboard applies icon_custom_emoji_id to InlineKeyboardButton."""
    choices = [
        (101, '<tg-emoji emoji-id="5422577965626060349">⭐</tg-emoji> <b>VIP_User</b>'),
        (102, "Oddiy_User"),
    ]
    kb = vote_keyboard(game_id=42, choices=choices)
    
    # First button: VIP user with custom emoji
    btn_vip = kb.inline_keyboard[0][0]
    assert btn_vip.text == "VIP_User"
    assert btn_vip.icon_custom_emoji_id == "5422577965626060349"
    assert btn_vip.callback_data == "vote:42:101"

    # Second button: Regular user without custom emoji
    btn_regular = kb.inline_keyboard[1][0]
    assert btn_regular.text == "Oddiy_User"
    assert getattr(btn_regular, "icon_custom_emoji_id", None) is None
    assert btn_regular.callback_data == "vote:42:102"

    # Last button: skip vote
    btn_skip = kb.inline_keyboard[2][0]
    assert "O'tkazib yuborish" in btn_skip.text
    assert btn_skip.callback_data == "skip:vote:42:0"


@pytest.mark.asyncio
async def test_tournament_couple_death_at_night(tournament_db, mock_bot):
    """When a partner dies at night in /turnir, their partner must also die."""
    engine = GameEngine(Settings(), tournament_db)
    chat_id = -1005555

    async with tournament_db() as session:
        game = Game(chat_id=chat_id, creator_telegram_id=1, status=GameStatus.ACTIVE.value, phase=GamePhase.NIGHT.value, day_number=1)
        session.add(game)
        await session.flush()

        # Mark game as tournament
        session.add(BotSetting(key=engine._tournament_game_key(game.id), value="1"))

        # Create active couple
        couple = CoupleRelationship(
            chat_id=chat_id,
            user_one_telegram_id=10,
            user_one_name="Majnun",
            user_two_telegram_id=20,
            user_two_name="Layli",
            active=True,
        )
        session.add(couple)

        # Add players
        p1 = GamePlayer(game_id=game.id, telegram_id=10, display_name="Majnun", role=Role.DOCTOR.value, team=Team.CITY.value, alive=True)
        p2 = GamePlayer(game_id=game.id, telegram_id=20, display_name="Layli", role=Role.CITIZEN.value, team=Team.CITY.value, alive=True)
        p3 = GamePlayer(game_id=game.id, telegram_id=30, display_name="Don", role=Role.DON.value, team=Team.MAFIA.value, alive=True)
        session.add_all([p1, p2, p3])
        await session.commit()

        # Simulate Majnun killed by Mafia at night
        dead_ids = {10}
        death_causes = {10: "mafia"}
        death_visitors = {10: "Don yoki Mafiya"}
        players = [p1, p2, p3]

        lines = await engine._expand_tournament_couple_deaths(
            session,
            game,
            players,
            dead_ids,
            death_causes=death_causes,
            death_visitors=death_visitors,
        )

        # Both should be in dead_ids now
        assert 10 in dead_ids
        assert 20 in dead_ids
        assert p2.alive is False
        assert death_causes[20] == "couple"
        assert len(lines) == 1
        assert "Turnir fojiasi" in lines[0]
        assert "Layli" in lines[0]
        assert "Majnun" in lines[0]


@pytest.mark.asyncio
async def test_regular_game_couple_not_affected_by_death(tournament_db):
    """In a non-tournament game, one partner dying does NOT kill the other partner."""
    engine = GameEngine(Settings(), tournament_db)
    chat_id = -1006666

    async with tournament_db() as session:
        game = Game(chat_id=chat_id, creator_telegram_id=1, status=GameStatus.ACTIVE.value, phase=GamePhase.NIGHT.value, day_number=1)
        session.add(game)
        await session.flush()

        # Regular game: NOT marked as tournament
        couple = CoupleRelationship(
            chat_id=chat_id,
            user_one_telegram_id=10,
            user_one_name="Yigit",
            user_two_telegram_id=20,
            user_two_name="Qiz",
            active=True,
        )
        session.add(couple)

        p1 = GamePlayer(game_id=game.id, telegram_id=10, display_name="Yigit", role=Role.DOCTOR.value, team=Team.CITY.value, alive=True)
        p2 = GamePlayer(game_id=game.id, telegram_id=20, display_name="Qiz", role=Role.CITIZEN.value, team=Team.CITY.value, alive=True)
        session.add_all([p1, p2])
        await session.commit()

        dead_ids = {10}
        lines = await engine._expand_tournament_couple_deaths(
            session,
            game,
            [p1, p2],
            dead_ids,
        )

        # In regular game, partner 20 remains alive!
        assert dead_ids == {10}
        assert p2.alive is True
        assert lines == []


@pytest.mark.asyncio
async def test_tournament_couple_leave_active_game(tournament_db, mock_bot):
    """When a player leaves an active tournament game, their partner also leaves."""
    engine = GameEngine(Settings(), tournament_db)
    chat_id = -1007777

    async with tournament_db() as session:
        game = Game(chat_id=chat_id, creator_telegram_id=1, status=GameStatus.ACTIVE.value, phase=GamePhase.DAY_DISCUSSION.value, day_number=1)
        session.add(game)
        await session.flush()

        session.add(BotSetting(key=engine._tournament_game_key(game.id), value="1"))

        couple = CoupleRelationship(
            chat_id=chat_id,
            user_one_telegram_id=100,
            user_one_name="Ali",
            user_two_telegram_id=200,
            user_two_name="Vali",
            active=True,
        )
        session.add(couple)

        p1 = GamePlayer(game_id=game.id, telegram_id=100, display_name="Ali", role=Role.CITIZEN.value, team=Team.CITY.value, alive=True)
        p2 = GamePlayer(game_id=game.id, telegram_id=200, display_name="Vali", role=Role.DOCTOR.value, team=Team.CITY.value, alive=True)
        session.add_all([p1, p2])
        await session.commit()

    # User 100 leaves
    success, msg = await engine.leave_game(mock_bot, game.id, 100)
    assert success is True

    async with tournament_db() as session:
        p1_db = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.telegram_id == 100))).scalar_one()
        p2_db = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.telegram_id == 200))).scalar_one()
        
        # Both should be marked dead/left
        assert p1_db.alive is False
        assert p1_db.left_game is True
        assert p2_db.alive is False
        assert p2_db.left_game is True

    # Check that broadcast announced couple departure
    sent_msgs = [call.args[1] for call in mock_bot.send_message.call_args_list if len(call.args) > 1]
    assert any("Turnir" in str(m) and "Ali" in str(m) and "Vali" in str(m) for m in sent_msgs)
