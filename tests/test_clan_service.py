import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clan_service import ClanService
from app.database import Base
from app.models import Clan, ClanApplication, ClanMember, User


class FakeUser:
    def __init__(self, telegram_id: int, username: str = "user", display_name: str = "User"):
        self.id = telegram_id
        self.username = username
        self.full_name = display_name
        self.display_name = display_name


@pytest_asyncio.fixture
async def clan_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_clan_creation_creates_owner_member(clan_session):
    service = ClanService(clan_session)

    async with clan_session() as session:
        session.add(User(telegram_id=101, username="owner", display_name="Owner", diamonds=100, dollar=100000))
        await session.commit()

    ok, message, clan = await service.create_clan(FakeUser(101), "Alpha")

    assert ok is True
    assert "Alpha" in message
    assert clan is not None

    async with clan_session() as session:
        saved = await session.get(Clan, clan.id)
        assert saved is not None
        owners = list((await session.execute(select(ClanMember).where(ClanMember.clan_id == clan.id))).scalars().all())
        assert len(owners) == 1
        assert owners[0].user_telegram_id == 101
        assert owners[0].role == "owner"


@pytest.mark.asyncio
async def test_apply_and_accept_membership_flow(clan_session):
    service = ClanService(clan_session)

    async with clan_session() as session:
        session.add_all(
            [
                User(telegram_id=101, username="owner", display_name="Owner", diamonds=100, dollar=100000),
                User(telegram_id=202, username="applicant", display_name="Applicant", diamonds=50, dollar=1000),
            ]
        )
        await session.commit()

    ok, _, clan = await service.create_clan(FakeUser(101), "Beta")
    assert ok is True

    ok, message = await service.apply_to_clan(FakeUser(202), clan.id)
    assert ok is True
    assert "ariza" in message.lower()

    async with clan_session() as session:
        app = (await session.execute(select(ClanApplication).where(ClanApplication.user_telegram_id == 202))).scalar_one()
        assert app.status == "pending"

    ok, result = await service.process_application(bot=None, owner_telegram_id=101, app_id=app.id, action="accept")
    assert ok is True
    assert "qabul" in result.lower()

    async with clan_session() as session:
        member = (await session.execute(select(ClanMember).where(ClanMember.user_telegram_id == 202))).scalar_one()
        assert member.clan_id == clan.id
        assert member.role == "member"

        app = await session.get(ClanApplication, app.id)
        assert app.status == "accepted"
