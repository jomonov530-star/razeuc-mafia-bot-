from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.config import Settings
from app.database import Base
from app.game_engine import GameEngine
from app.models import AdminAuditLog, SubAdmin, User


@pytest.mark.asyncio
async def test_sub_admin_role_hierarchy_and_permissions():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings(ADMIN_IDS="99999")
    engine = GameEngine(session_factory=session_factory, settings=settings)

    owner_id = 99999
    mod_id = 10001
    finance_id = 10002
    regular_id = 10003

    # Super admin check
    assert await engine.get_sub_admin_role(owner_id) == "super_admin"
    assert await engine.has_admin_permission(owner_id, "super_admin") is True
    assert await engine.has_admin_permission(owner_id, "finance_admin") is True

    # Regular user check
    assert await engine.get_sub_admin_role(regular_id) is None
    assert await engine.has_admin_permission(regular_id, "any") is False

    # Set sub-admin: moderator
    ok, text = await engine.set_sub_admin(
        admin_id=owner_id,
        target_user_id=mod_id,
        username="mod_user",
        role="moderator",
    )
    assert ok is True
    assert "Moderator" in text

    # Set sub-admin: finance_admin
    ok, text = await engine.set_sub_admin(
        admin_id=owner_id,
        target_user_id=finance_id,
        username="finance_user",
        role="finance_admin",
    )
    assert ok is True
    assert "Moliya Admini" in text

    # Check moderator permissions
    assert await engine.get_sub_admin_role(mod_id) == "moderator"
    assert await engine.has_admin_permission(mod_id, "moderator") is True
    assert await engine.has_admin_permission(mod_id, "finance_admin") is False

    # Check finance permissions
    assert await engine.get_sub_admin_role(finance_id) == "finance_admin"
    assert await engine.has_admin_permission(finance_id, "finance_admin") is True
    assert await engine.has_admin_permission(finance_id, "moderator") is False

    # Non-super admin trying to assign sub-admin
    ok, text = await engine.set_sub_admin(
        admin_id=mod_id,
        target_user_id=regular_id,
        username="new_mod",
        role="moderator",
    )
    assert ok is False
    assert "Faqat Super Admin" in text

    # List sub-admins
    subs = await engine.list_sub_admins()
    assert len(subs) == 2

    # Remove sub-admin
    ok, text = await engine.remove_sub_admin(admin_id=owner_id, target_user_id=mod_id)
    assert ok is True
    assert await engine.get_sub_admin_role(mod_id) is None

    # Check AdminAuditLog table
    async with session_factory() as session:
        logs = (await session.execute(select(AdminAuditLog))).scalars().all()
        assert len(logs) >= 3
        actions = [log.action_type for log in logs]
        assert "set_sub_admin" in actions
        assert "remove_sub_admin" in actions


@pytest.mark.asyncio
async def test_sub_admin_ui_keyboard_visibility():
    from app.keyboards import owner_panel_keyboard, profile_dashboard_keyboard, start_menu_keyboard

    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings(ADMIN_IDS="99999")
    engine = GameEngine(session_factory=session_factory, settings=settings)

    owner_id = 99999
    mod_id = 10001
    regular_id = 10002

    await engine.set_sub_admin(
        admin_id=owner_id,
        target_user_id=mod_id,
        username="mod_user",
        role="moderator",
    )

    # Sub-admin role check for UI
    owner_is_admin = bool(await engine.get_sub_admin_role(owner_id))
    mod_is_admin = bool(await engine.get_sub_admin_role(mod_id))
    reg_is_admin = bool(await engine.get_sub_admin_role(regular_id))

    assert owner_is_admin is True
    assert mod_is_admin is True
    assert reg_is_admin is False

    # Check start menu keyboard buttons
    start_kb_mod = start_menu_keyboard("uz", settings, is_admin=mod_is_admin)
    start_kb_reg = start_menu_keyboard("uz", settings, is_admin=reg_is_admin)

    has_admin_btn_mod = any(
        btn.callback_data == "owner:panel" for row in start_kb_mod.inline_keyboard for btn in row
    )
    has_admin_btn_reg = any(
        btn.callback_data == "owner:panel" for row in start_kb_reg.inline_keyboard for btn in row
    )

    assert has_admin_btn_mod is True
    assert has_admin_btn_reg is False

    # Check profile dashboard keyboard buttons
    prof_kb_mod = profile_dashboard_keyboard(settings, is_admin=mod_is_admin)
    prof_kb_reg = profile_dashboard_keyboard(settings, is_admin=reg_is_admin)

    prof_admin_btn_mod = any(
        btn.callback_data == "owner:panel" for row in prof_kb_mod.inline_keyboard for btn in row
    )
    prof_admin_btn_reg = any(
        btn.callback_data == "owner:panel" for row in prof_kb_reg.inline_keyboard for btn in row
    )

    assert prof_admin_btn_mod is True
    assert prof_admin_btn_reg is False


def test_owner_panel_keyboard_role_filtering():
    from app.keyboards import owner_panel_keyboard

    # Super Admin keyboard contains all
    kb_super = owner_panel_keyboard("super_admin")
    cbs_super = [btn.callback_data for row in kb_super.inline_keyboard for btn in row]
    assert "owner:sub_admins" in cbs_super
    assert "owner:grant_dollars" in cbs_super
    assert "owner:vip" in cbs_super

    # Moderator keyboard contains restricted items
    kb_mod = owner_panel_keyboard("moderator")
    cbs_mod = [btn.callback_data for row in kb_mod.inline_keyboard for btn in row]
    assert "owner:vip" in cbs_mod
    assert "owner:premium_blocked_list" in cbs_mod
    assert "owner:grant_dollars" not in cbs_mod
    assert "owner:sub_admins" not in cbs_mod

    # Finance Admin keyboard contains financial items
    kb_fin = owner_panel_keyboard("finance_admin")
    cbs_fin = [btn.callback_data for row in kb_fin.inline_keyboard for btn in row]
    assert "owner:grant_dollars" in cbs_fin
    assert "owner:grant_diamonds" in cbs_fin
    assert "owner:invoice" in cbs_fin
    assert "owner:sub_admins" not in cbs_fin

    # Media Manager keyboard contains broadcast items
    kb_media = owner_panel_keyboard("media_manager")
    cbs_media = [btn.callback_data for row in kb_media.inline_keyboard for btn in row]
    assert "owner:broadcast_menu" in cbs_media
    assert "owner:toggle_2x_event" in cbs_media
    assert "owner:grant_dollars" not in cbs_media


@pytest.mark.asyncio
async def test_sub_admin_username_resolution():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, expire_on_commit=False)
    settings = Settings(ADMIN_IDS="99999")
    engine = GameEngine(session_factory=session_factory, settings=settings)

    owner_id = 99999
    username_target = "john_doe"
    user_id_target = 88888

    # 1. Add sub-admin by username when user_id is 0
    ok, text = await engine.set_sub_admin(
        admin_id=owner_id,
        target_user_id=0,
        username=username_target,
        role="finance_admin",
    )
    assert ok is True

    # User is not resolved yet for user_id_target if user does not exist in User table
    # Now simulate user starting the bot and registering in User table
    async with session_factory() as session:
        u = User(telegram_id=user_id_target, username="john_doe")
        session.add(u)
        await session.commit()

    # Query get_sub_admin_role for user_id_target
    role = await engine.get_sub_admin_role(user_id_target)
    assert role == "finance_admin"

    # Verify user_telegram_id was auto-updated in SubAdmin table
    async with session_factory() as session:
        sub = (await session.execute(select(SubAdmin).where(SubAdmin.username == "john_doe"))).scalar_one_or_none()
        assert sub is not None
        assert sub.user_telegram_id == user_id_target


