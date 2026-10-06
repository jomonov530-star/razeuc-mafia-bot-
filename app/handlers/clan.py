from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.clan_service import (
    CLAN_BIO_DOLLAR_COST,
    CLAN_CREATE_DIAMOND_COST,
    CLAN_RENAME_DIAMOND_COST,
    ClanService,
    calc_member_limit,
    format_emoji,
    xp_for_level,
)
from app.database import SessionLocal
from app.game_engine import GameEngine
from app.keyboards import (
    clan_app_confirm_keyboard,
    clan_applications_keyboard,
    clan_confirm_action_keyboard,
    clan_create_confirm_keyboard,
    clan_info_keyboard,
    clan_list_keyboard,
    clan_member_dashboard_keyboard,
    clan_members_keyboard,
    clan_owner_dashboard_keyboard,
    clan_top_keyboard,
    clan_transfer_keyboard,
    clanless_menu_keyboard,
    safe_text,
)
from app.models import Clan, User

logger = logging.getLogger(__name__)
router = Router()
clan_service = ClanService(SessionLocal)

# Global switch to disable all clan UI/handlers — returns no visible reply
DISABLE_CLAN = True

if DISABLE_CLAN:
    @router.callback_query(F.data.startswith("clan:"))
    async def _ignore_clan_callbacks(callback: CallbackQuery) -> None:
        # answer silently to dismiss client spinner but do not perform any clan action
        try:
            await callback.answer()
        except Exception:
            pass


class CreateClanState(StatesGroup):
    waiting_name = State()


class RenameClanState(StatesGroup):
    waiting_name = State()


class RebioClanState(StatesGroup):
    waiting_bio = State()


class SearchClanState(StatesGroup):
    waiting_query = State()


def _format_tg_mention(tg_id: int, name: str) -> str:
    from html import escape
    safe_name = escape(name or "User")
    return f'<a href="tg://user?id={tg_id}">{safe_name}</a>'


async def _render_clan_dashboard(event: Message | CallbackQuery, telegram_id: int, user_tg) -> None:
    # High-visibility entry log to trace calls reliably during debugging
    try:
        logger.warning("ENTER_RENDER_CLAN_DASHBOARD event=%s user=%s", type(event).__name__, telegram_id)
    except Exception:
        logger.exception("Failed to log ENTER_RENDER_CLAN_DASHBOARD")

    try:
        status, clan, member_rec, pending_count = await clan_service.get_user_clan_info(telegram_id)

        try:
            logger.warning("AFTER_GET_USER_CLAN_INFO status=%s clan_id=%s pending=%s", status, getattr(clan, 'id', None), pending_count)
        except Exception:
            logger.exception("Failed to log AFTER_GET_USER_CLAN_INFO")

        logger.warning("ENTER_DB_FETCH user=%s clan_id=%s", telegram_id, getattr(clan, 'id', None))
        async with SessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == telegram_id)
            )
            owner_name = "Unknown"
            current_members = 0
            if clan:
                owner_user = await session.scalar(
                    select(User).where(User.telegram_id == clan.owner_id)
                )
                if owner_user:
                    owner_name = owner_user.display_name or owner_user.username or str(clan.owner_id)

                from app.models import ClanMember
                current_members = int(
                    await session.scalar(
                        select(func.count(ClanMember.id)).where(ClanMember.clan_id == clan.id)
                    )
                    or 0
                )

        logger.warning("AFTER_DB_FETCH current_members=%s", current_members)

        owner_mention = _format_tg_mention(clan.owner_id, owner_name) if clan else ""
        created_date = clan.created_at.strftime("%d.%m.%Y") if clan and clan.created_at else ""

        c_logo = format_emoji("clan", "🏰")
        c_owner = format_emoji("owner", "👑")
        c_members = format_emoji("members", "👥")
        c_level = format_emoji("level", "⭐")
        c_xp = format_emoji("xp", "⚡")
        c_wins = format_emoji("wins", "🏆")
        c_losses = format_emoji("losses", "💀")
        c_games = format_emoji("games", "🎮")
        c_stats = format_emoji("stats", "📊")
        c_power = format_emoji("power", "🔥")
        c_date = format_emoji("date", "📅")

        if status == "clanless":
            # Show available clans directly and allow one-click apply
            clans, total = await clan_service.get_top_clans(limit=10, page=1)
            total_pages = max(1, (total + 9) // 10)
            text = (
                f"{c_logo} <b>CLANLAR</b>\n\n"
                "Quyidagi Clanlardan birini tanlang va qo'shilish uchun ariza yuboring:\n"
            )
            from app.keyboards import clan_list_apply_keyboard
            kb = clan_list_apply_keyboard(clans, page=1, total_pages=total_pages)

        elif status == "member":
            win_rate = (clan.wins / clan.total_games * 100) if clan.total_games > 0 else 0.0
            limit = clan.member_limit or calc_member_limit(clan.level)
            next_xp = xp_for_level(clan.level)

            text = (
                f"{c_logo} <b>CLAN: {clan.name}</b>\n\n"
                f"{c_owner} <b>Owner:</b> {owner_mention}\n\n"
                f"{c_members} <b>A'zolar:</b> {current_members}/{limit}\n\n"
                f"{c_level} <b>Level:</b> {clan.level}\n"
                f"{c_xp} <b>XP:</b> {clan.xp:,} / {next_xp:,}\n\n"
                f"{c_wins} <b>G'alabalar:</b> {clan.wins}\n"
                f"{c_losses} <b>Mag'lubiyatlar:</b> {clan.losses}\n"
                f"{c_games} <b>Jami o'yinlar:</b> {clan.total_games}\n\n"
                f"{c_stats} <b>Win rate:</b> {win_rate:.1f}%\n"
                f"{c_power} <b>Clan Power:</b> {clan.rating:,}\n\n"
                f"{c_date} <b>Yaratilgan:</b> {created_date}"
            )
            kb = clan_member_dashboard_keyboard(clan.id)

        else:  # Owner
            win_rate = (clan.wins / clan.total_games * 100) if clan.total_games > 0 else 0.0
            limit = clan.member_limit or calc_member_limit(clan.level)
            next_xp = xp_for_level(clan.level)
            c_bio = format_emoji("bio", "📝")

            text = (
                f"{c_logo} <b>CLAN: {clan.name}</b>\n\n"
                f"{c_bio} <b>Bio:</b>\n"
                f"<i>{clan.bio}</i>\n\n"
                f"{c_owner} <b>Owner:</b> {owner_mention}\n\n"
                f"{c_members} <b>A'zolar:</b> {current_members}/{limit}\n\n"
                f"{c_level} <b>Level:</b> {clan.level}\n"
                f"{c_xp} <b>XP:</b> {clan.xp:,} / {next_xp:,}\n\n"
                f"{c_wins} <b>Wins:</b> {clan.wins}\n"
                f"{c_losses} <b>Losses:</b> {clan.losses}\n"
                f"{c_games} <b>Games:</b> {clan.total_games}\n\n"
                f"{c_stats} <b>Win Rate:</b> {win_rate:.1f}%\n"
                f"{c_power} <b>Clan Power:</b> {clan.rating:,}"
            )
            kb = clan_owner_dashboard_keyboard(clan.id, pending_count)
            try:
                logger.warning("OWNER_DASHBOARD_RENDERED clan_id=%s pending=%s kb=%s", getattr(clan, 'id', None), pending_count, type(kb).__name__)
            except Exception:
                logger.exception("Failed logging OWNER_DASHBOARD_RENDERED")

        # Log outgoing snippet for debugging visibility issues
        try:
            logger.warning("SENDING_CLAN_DASHBOARD to=%s snippet=%s", getattr(event, 'chat', getattr(event, 'from_user', None)), (text[:120] + '...') if len(text) > 120 else text)
        except Exception:
            logger.exception("Failed to log outgoing clan text")

        # Send or edit the message depending on event type
        if isinstance(event, Message):
            try:
                logger.warning("SENDING_CLAN_DASHBOARD_MESSAGE to chat=%s", event.chat.id if event.chat else None)
                await event.answer(text, reply_markup=kb)
                logger.warning("Sent clan dashboard via Message.answer to chat=%s", event.chat.id if event.chat else None)
            except Exception as msg_exc:
                logger.exception("Failed to answer clan dashboard message: %s", msg_exc)
                try:
                    await event.reply(text, reply_markup=kb)
                    logger.warning("Replied with clan dashboard to chat=%s", event.chat.id if event.chat else None)
                except Exception:
                    logger.exception("Failed to reply with fallback clan dashboard")
        else:
            # CallbackQuery: prefer editing the original message
            try:
                await event.message.edit_text(text, reply_markup=kb)
                logger.warning("Edited original message for clan dashboard in chat %s", event.message.chat.id)
            except Exception as edit_exc:
                logger.exception("Failed to edit original message for clan dashboard: %s", edit_exc)
                # fallback to sending a direct message to the user
                try:
                    await event.bot.send_message(event.from_user.id, text, reply_markup=kb)
                    logger.warning("Sent clan dashboard via send_message to %s", event.from_user.id)
                except Exception as send_exc:
                    logger.exception("Failed to send clan dashboard via send_message: %s", send_exc)
                    # last-resort: answer the callback with an alert so the user sees something
                    try:
                        await event.answer("Iltimos kuting... clan ma'lumotini yuklashda muammo bo'ldi.", show_alert=True)
                    except Exception:
                        logger.exception("Failed to send callback alert fallback for clan dashboard")
    except Exception as exc:
        logger.exception("Unhandled error in _render_clan_dashboard: %s", exc)
        try:
            if isinstance(event, CallbackQuery):
                await event.answer("Xatolik yuz berdi — iltimos qayta urinib ko'ring.", show_alert=True)
            else:
                await event.answer("Xatolik yuz berdi — iltimos qayta urinib ko'ring.")
        except Exception:
            logger.exception("Failed to send fallback error message for clan dashboard")


@router.message(Command("clan"))
async def cmd_clan(message: Message, state: FSMContext, engine: GameEngine) -> None:
    if message.from_user is None:
        return
    if DISABLE_CLAN:
        # per user request: do nothing when /clan is used
        return
    logger.info("cmd_clan triggered by %s (%s)", getattr(message.from_user, 'id', None), getattr(message.from_user, 'username', None))
    await state.clear()
    await engine.ensure_user(message.from_user)

    # In group chats only send a short info text without interactive buttons
    chat_type = getattr(message.chat, 'type', None)
    if chat_type in ("group", "supergroup"):
        status, clan, member_rec, pending_count = await clan_service.get_user_clan_info(message.from_user.id)

        c_logo = format_emoji("clan", "🏰")
        c_owner = format_emoji("owner", "👑")
        c_members = format_emoji("members", "👥")
        c_level = format_emoji("level", "⭐")

        if status == "clanless":
            text = f"{c_logo} <b>CLAN</b>\n\nSiz hozircha hech qaysi Clan'ga a'zo emassiz. Shaxsiy chatda bot bilan bog'laning."
        else:
            owner_mention = ""
            try:
                owner_mention = _format_tg_mention(clan.owner_id, "Owner") if clan else ""
            except Exception:
                owner_mention = str(getattr(clan, 'owner_id', ''))

            limit = clan.member_limit or calc_member_limit(clan.level) if clan else 0
            members_count = 0
            try:
                from app.models import ClanMember
                async with SessionLocal() as session:
                    members_count = int(
                        await session.scalar(
                            select(func.count(ClanMember.id)).where(ClanMember.clan_id == clan.id)
                        )
                        or 0
                    )
            except Exception:
                members_count = 0

            if status == "member":
                text = f"{c_logo} <b>{clan.name}</b> — {c_owner} {owner_mention} | {c_members} {members_count}/{limit} | {c_level} Lvl {clan.level}"
            else:  # owner
                text = f"{c_logo} <b>{clan.name}</b> — Owner: {owner_mention} | Pending: {pending_count} | Members: {members_count}/{limit}"

        await message.answer(text)
        return

    # Default: show full interactive dashboard
    await _render_clan_dashboard(message, message.from_user.id, message.from_user)


@router.callback_query(F.data == "clan:main")
async def callback_clan_main(callback: CallbackQuery, state: FSMContext, engine: GameEngine) -> None:
    if callback.from_user is None or callback.message is None:
        return
    logger.info("callback_clan_main triggered by %s", callback.from_user.id)
    await state.clear()
    await engine.ensure_user(callback.from_user)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "clan:close")
async def callback_clan_close(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            await callback.message.delete()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    await callback.answer()


@router.callback_query(F.data == "clan:create_start")
async def callback_clan_create_start(callback: CallbackQuery) -> None:
    c_logo = format_emoji("clan", "🏰")
    c_diamond = format_emoji("diamond", "💎")
    c_owner = format_emoji("owner", "👑")

    text = (
        f"{c_logo} <b>Yangi Clan yaratmoqchimisiz?</b>\n\n"
        f"Narxi: <b>{CLAN_CREATE_DIAMOND_COST}</b> {c_diamond}\n\n"
        f"Clan yaratilgandan keyin siz uning {c_owner} Owner'i bo'lasiz."
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=clan_create_confirm_keyboard())
    await callback.answer()




@router.callback_query(F.data == "clan:create_confirm")
async def callback_clan_create_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await state.set_state(CreateClanState.waiting_name)
    c_create = format_emoji("create", "➕")
    await callback.message.edit_text(
        f"{c_create} <b>Yangi Clan nomini kiriting:</b>\n\n"
        "<i>(3 ta dan 32 ta belgigacha)</i>"
    )
    await callback.answer()


@router.message(CreateClanState.waiting_name)
async def process_create_clan_name(message: Message, state: FSMContext, engine: GameEngine) -> None:
    if DISABLE_CLAN:
        return
    if message.from_user is None or not message.text:
        return
    clan_name = message.text.strip()
    await state.clear()

    await engine.ensure_user(message.from_user)
    ok, text, clan = await clan_service.create_clan(message.from_user, clan_name)
    if not ok:
        await message.answer(text)
        return

    await message.answer(text)
    await _render_clan_dashboard(message, message.from_user.id, message.from_user)


@router.callback_query(F.data.startswith("clan:apply:"))
async def callback_clan_apply(callback: CallbackQuery, engine: GameEngine) -> None:
    if callback.from_user is None or callback.message is None:
        return
    logger.info("callback_clan_apply: %s -> %s", callback.from_user.id, callback.data)
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    await engine.ensure_user(callback.from_user)
    ok, text = await clan_service.apply_to_clan(callback.from_user, clan_id)
    await callback.answer(text, show_alert=True)

    if ok:
        # Notify owner if possible
        async with SessionLocal() as session:
            clan = await session.get(Clan, clan_id)
            if clan and clan.owner_id:
                try:
                    c_apps = format_emoji("apps", "📨")
                    try:
                        await callback.bot.send_message(
                            clan.owner_id,
                            f"{c_apps} <b>Yangi Clan arizasi!</b>\n\n"
                            f"👤 {callback.from_user.full_name}\n"
                            f"Arizani ko'rib chiqish uchun bot paneliga murojaat qiling."
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
        await callback.message.edit_text(text, reply_markup=clan_info_keyboard(clan_id, False, True, False))


@router.callback_query(F.data.startswith("clan:apps:"))
async def callback_clan_apps(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    # Check permission: allow owner or admins
    status, clan, member_rec, _ = await clan_service.get_user_clan_info(callback.from_user.id)
    is_admin = False
    if member_rec:
        try:
            is_admin = getattr(member_rec, 'role', None) == 'admin'
        except Exception:
            is_admin = False
    if clan is None or clan.id != clan_id or not (status == "owner" or is_admin):
        await callback.answer("🚫 Siz ushbu Clan owner'i yoki admini emassiz.", show_alert=True)
        return

    apps = await clan_service.get_pending_applications(clan_id)
    c_apps = format_emoji("apps", "📨")

    if not apps:
        await callback.message.edit_text(
            f"{c_apps} <b>CLAN JOIN REQUESTS</b>\n\nHozircha ko'rib chiqilmagan arizalar yo'q.",
            reply_markup=clan_applications_keyboard([], clan_id)
        )
        await callback.answer()
        return

    text_lines = [f"{c_apps} <b>CLAN JOIN REQUESTS ({len(apps)})</b>\n"]
    for idx, (app_rec, usr) in enumerate(apps, start=1):
        disp = usr.display_name if usr else "User"
        win_rate = (usr.wins / usr.total_games * 100) if usr and usr.total_games > 0 else 0.0
        text_lines.append(f"{idx}. 👤 <b>{disp}</b>\n   🏆 Wins: {usr.wins if usr else 0} | 📊 Win rate: {win_rate:.0f}%\n")

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=clan_applications_keyboard(apps, clan_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:app_action:"))
async def callback_clan_app_action(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        return
    action = parts[2]
    app_id = int(parts[3])

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=clan_app_confirm_keyboard(action, app_id))
    await callback.answer()


@router.callback_query(F.data.startswith("clan:app_confirm:"))
async def callback_clan_app_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    logger.info("callback_clan_app_confirm: %s -> %s", callback.from_user.id, callback.data)
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        return
    action = parts[2]
    app_id = int(parts[3])

    ok, text = await clan_service.process_application(callback.bot, callback.from_user.id, app_id, action)
    await callback.answer(text, show_alert=True)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)


@router.callback_query(F.data.startswith("clan:rename_start:"))
async def callback_clan_rename_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    status, clan, member_rec, _ = await clan_service.get_user_clan_info(callback.from_user.id)
    is_admin = member_rec and getattr(member_rec, 'role', None) == 'admin'
    if not ((status == "owner") or is_admin) or clan is None or clan.id != clan_id:
        await callback.answer("🚫 Siz ushbu Clan owner'i yoki admini emassiz.", show_alert=True)
        return

    await state.set_state(RenameClanState.waiting_name)
    c_edit = format_emoji("edit", "✏️")
    c_diamond = format_emoji("diamond", "💎")

    await callback.message.edit_text(
        f"{c_edit} <b>Clan nomini o'zgartirish</b>\n\n"
        f"Narxi: <b>{CLAN_RENAME_DIAMOND_COST}</b> {c_diamond}\n\n"
        "Yangi nomni kiriting:"
    )
    await callback.answer()


@router.message(RenameClanState.waiting_name)
async def process_rename_clan_name(message: Message, state: FSMContext, engine: GameEngine) -> None:
    if DISABLE_CLAN:
        return
    if message.from_user is None or not message.text:
        return
    new_name = message.text.strip()
    await state.clear()

    await engine.ensure_user(message.from_user)
    ok, text = await clan_service.change_clan_name(message.from_user.id, new_name)
    await message.answer(text)
    await _render_clan_dashboard(message, message.from_user.id, message.from_user)


@router.callback_query(F.data.startswith("clan:rebio_start:"))
async def callback_clan_rebio_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    status, clan, member_rec, _ = await clan_service.get_user_clan_info(callback.from_user.id)
    is_admin = member_rec and getattr(member_rec, 'role', None) == 'admin'
    if not ((status == "owner") or is_admin) or clan is None or clan.id != clan_id:
        await callback.answer("🚫 Siz ushbu Clan owner'i yoki admini emassiz.", show_alert=True)
        return

    await state.set_state(RebioClanState.waiting_bio)
    c_bio = format_emoji("bio", "📝")
    c_dollar = format_emoji("dollar", "💵")

    await callback.message.edit_text(
        f"{c_bio} <b>Clan bio'sini o'zgartirish</b>\n\n"
        f"Narxi: <b>${CLAN_BIO_DOLLAR_COST:,}</b> {c_dollar}\n\n"
        "Yangi bio/tavsifni kiriting:"
    )
    await callback.answer()


@router.message(RebioClanState.waiting_bio)
async def process_rebio_clan_bio(message: Message, state: FSMContext, engine: GameEngine) -> None:
    if DISABLE_CLAN:
        return
    if message.from_user is None or not message.text:
        return
    new_bio = message.text.strip()
    await state.clear()

    await engine.ensure_user(message.from_user)
    ok, text = await clan_service.change_clan_bio(message.from_user.id, new_bio)
    await message.answer(text)
    await _render_clan_dashboard(message, message.from_user.id, message.from_user)


@router.callback_query(F.data.startswith("clan:transfer_start:"))
async def callback_clan_transfer_start(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    status, clan, _, _ = await clan_service.get_user_clan_info(callback.from_user.id)
    if status != "owner" or clan is None or clan.id != clan_id:
        await callback.answer("🚫 Siz ushbu Clan owner'i emassiz.", show_alert=True)
        return

    members, _ = await clan_service.get_clan_members(clan_id, page=1, limit=50)
    c_owner = format_emoji("owner", "👑")

    await callback.message.edit_text(
        f"{c_owner} <b>OWNER TRANSFER</b>\n\n"
        "Yangi Clan egasini tanlang:",
        reply_markup=clan_transfer_keyboard(members, clan_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:admin_start:"))
async def callback_clan_admin_start(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    # Only owner may assign admins
    status, clan, member_rec, _ = await clan_service.get_user_clan_info(callback.from_user.id)
    if status != "owner" or clan is None or clan.id != clan_id:
        await callback.answer("🚫 Faqat Clan owner'i admin tayinlashi mumkin.", show_alert=True)
        return

    members, total = await clan_service.get_clan_members(clan_id, page=1, limit=50)
    # Build keyboard: each member row has Promote button
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows: list[list[InlineKeyboardButton]] = []
    for mem, usr in members:
        if mem.role == 'owner':
            continue
        if usr is None:
            continue
        display_name = usr.display_name or usr.username or str(usr.telegram_id)
        role_badge = "🛡 " if mem.role == 'admin' else ""
        btn_text = "✅ Admin" if mem.role == 'admin' else "🛡 Tayinlash"
        rows.append([
            InlineKeyboardButton(
                text=f"{role_badge}👤 {safe_text(display_name, 18)}",
                callback_data=f"clan:user_profile:{usr.telegram_id}"
            ),
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"clan:make_admin:{usr.telegram_id}"
            ),
        ])
    if not rows:
        await callback.message.edit_text(
            "👥 Hozircha tayinlash uchun a'zo yo'q.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Clan panel", callback_data="clan:main")]
            ])
        )
        await callback.answer()
        return

    rows.append([InlineKeyboardButton(text="🔙 Clan panel", callback_data="clan:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await callback.message.edit_text("👑 Admin tayinlash — a'zoni tanlang:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("clan:make_admin:"))
async def callback_clan_make_admin(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    target_tg = int(parts[2])

    # Ask confirmation
    await callback.message.edit_text(
        "🛡 A'zoni admin etmoqchimisiz?",
        reply_markup=clan_confirm_action_keyboard("make_admin", str(target_tg)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:transfer_confirm_ask:"))
async def callback_clan_transfer_confirm_ask(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    target_tg_id = int(parts[2])

    c_owner = format_emoji("owner", "👑")
    await callback.message.edit_text(
        f"{c_owner} <b>OWNER TRANSFER</b>\n\n"
        f"Clan egasini berilgan a'zoga o'tkazmoqchimisiz?\n\n"
        "⚠️ <i>Tasdiqlangandan keyin siz oddiy Member bo'lib qolasiz.</i>",
        reply_markup=clan_confirm_action_keyboard("transfer", str(target_tg_id))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:confirm:transfer:"))
async def callback_clan_confirm_transfer(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        return
    target_tg_id = int(parts[3])

    ok, text = await clan_service.transfer_owner(callback.from_user.id, target_tg_id)
    await callback.answer(text, show_alert=True)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)


@router.callback_query(F.data.startswith("clan:confirm:make_admin:"))
async def callback_clan_confirm_make_admin(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[3].isdigit():
        return
    target_tg = int(parts[3])

    ok, text = await clan_service.make_admin(callback.from_user.id, target_tg)
    await callback.answer(text, show_alert=True)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)


@router.callback_query(F.data.startswith("clan:leave_ask:"))
async def callback_clan_leave_ask(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    c_leave = format_emoji("leave", "🚪")
    await callback.message.edit_text(
        f"{c_leave} <b>Clan'dan chiqmoqchimisiz?</b>",
        reply_markup=clan_confirm_action_keyboard("leave", "")
    )
    await callback.answer()


@router.callback_query(F.data == "clan:confirm:leave:")
async def callback_clan_confirm_leave(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    ok, text = await clan_service.leave_clan(callback.from_user.id)
    await callback.answer(text, show_alert=True)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)


@router.callback_query(F.data.startswith("clan:delete_ask:"))
async def callback_clan_delete_ask(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    c_delete = format_emoji("delete", "🗑")
    await callback.message.edit_text(
        f"{c_delete} <b>Clan'ni o'chirishga ishonchingiz komilmi?</b>\n\n"
        "⚠️ <i>Bu amalni qaytarib bo'lmaydi!</i>",
        reply_markup=clan_confirm_action_keyboard("delete", "")
    )
    await callback.answer()


@router.callback_query(F.data == "clan:confirm:delete:")
async def callback_clan_confirm_delete(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    ok, text = await clan_service.delete_clan(callback.from_user.id)
    await callback.answer(text, show_alert=True)
    await _render_clan_dashboard(callback, callback.from_user.id, callback.from_user)


@router.callback_query(F.data.startswith("clan:members:"))
async def callback_clan_members(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
        return
    clan_id = int(parts[2])
    page = max(1, int(parts[3]))

    members, total = await clan_service.get_clan_members(clan_id, page=page, limit=10)
    total_pages = max(1, (total + 9) // 10)

    c_members = format_emoji("members", "👥")
    text = f"{c_members} <b>CLAN A'ZOLARI ({total})</b>\n\nA'zolar va ularning qo'shgan hissasi (XP):"

    await callback.message.edit_text(
        text,
        reply_markup=clan_members_keyboard(members, clan_id, is_owner=False, page=page, total_pages=total_pages)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:stats:"))
async def callback_clan_stats(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    async with SessionLocal() as session:
        clan = await session.get(Clan, clan_id)
        if clan is None or clan.status != "active":
            await callback.answer("❌ Clan topilmadi.", show_alert=True)
            return

        from sqlalchemy import select, func
        from app.models import ClanMember, User
        members_count = int(
            await session.scalar(select(func.count(ClanMember.id)).where(ClanMember.clan_id == clan.id)) or 0
        )
        top_members = (
            await session.execute(
                select(ClanMember, User)
                .join(User, ClanMember.user_telegram_id == User.telegram_id)
                .where(ClanMember.clan_id == clan.id)
                .order_by(ClanMember.contribution_xp.desc())
                .limit(5)
            )
        ).all()

    c_stats = format_emoji("stats", "📊")
    c_wins = format_emoji("wins", "🏆")
    c_losses = format_emoji("losses", "💀")
    c_games = format_emoji("games", "🎮")
    c_power = format_emoji("power", "🔥")

    win_rate = (clan.wins / clan.total_games * 100) if clan.total_games > 0 else 0.0

    lines = [
        f"{c_stats} <b>STATISTIKA: {clan.name}</b>\n",
        f"{c_games} Jami o'yinlar: <b>{clan.total_games}</b>",
        f"{c_wins} G'alabalar: <b>{clan.wins}</b>",
        f"{c_losses} Mag'lubiyatlar: <b>{clan.losses}</b>",
        f"📊 Win Rate: <b>{win_rate:.1f}%</b>",
        f"{c_power} Clan Power: <b>{clan.rating:,}</b>\n",
        "<b> Eng faol a'zolar:</b>",
    ]

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for idx, (mem, usr) in enumerate(top_members):
        disp = usr.display_name if usr else "User"
        lines.append(f"{medals[idx]} {disp} — {mem.contribution_xp} XP")

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")]])

    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("clan:top:"))
async def callback_clan_top(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    page = max(1, int(parts[2])) if len(parts) == 3 and parts[2].isdigit() else 1

    clans, total = await clan_service.get_top_clans(limit=10, page=page)
    total_pages = max(1, (total + 9) // 10)

    c_top = format_emoji("wins", "🏆")
    text = f"{c_top} <b>CLAN REYTINGI (TOP)</b>\n\nBarcha aktiv Clanlar:"

    await callback.message.edit_text(
        text,
        reply_markup=clan_top_keyboard(clans, page=page, total_pages=total_pages)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:list:"))
async def callback_clan_list(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    page = max(1, int(parts[2])) if len(parts) == 3 and parts[2].isdigit() else 1

    clans, total = await clan_service.get_top_clans(limit=10, page=page)
    total_pages = max(1, (total + 9) // 10)

    c_logo = format_emoji("clan", "🏰")
    text = f"{c_logo} <b>CLANLAR RO'YXATI</b>\n\nMa'lumot olish uchun tanlang:"

    await callback.message.edit_text(
        text,
        reply_markup=clan_list_keyboard(clans, page=page, total_pages=total_pages)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clan:info:"))
async def callback_clan_info(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    clan_id = int(parts[2])

    async with SessionLocal() as session:
        clan = await session.get(Clan, clan_id)
        if clan is None or clan.status != "active":
            await callback.answer("❌ Clan topilmadi.", show_alert=True)
            return

        owner_user = await session.scalar(select(User).where(User.telegram_id == clan.owner_id))
        owner_name = owner_user.display_name if owner_user else str(clan.owner_id)

        from sqlalchemy import func, select
        from app.models import ClanMember, ClanApplication
        members_count = int(
            await session.scalar(select(func.count(ClanMember.id)).where(ClanMember.clan_id == clan.id)) or 0
        )
        has_applied = bool(
            await session.scalar(
                select(ClanApplication.id).where(
                    ClanApplication.clan_id == clan.id,
                    ClanApplication.user_telegram_id == callback.from_user.id,
                    ClanApplication.status == "pending",
                )
            )
        )
        in_any_clan = bool(
            await session.scalar(
                select(ClanMember.id)
                .join(Clan, ClanMember.clan_id == Clan.id)
                .where(ClanMember.user_telegram_id == callback.from_user.id, Clan.status == "active")
            )
        )

    limit = clan.member_limit or calc_member_limit(clan.level)
    is_full = members_count >= limit
    can_apply = not in_any_clan and not has_applied and not is_full

    c_logo = format_emoji("clan", "🏰")
    c_owner = format_emoji("owner", "👑")
    c_members = format_emoji("members", "👥")
    c_level = format_emoji("level", "⭐")
    c_xp = format_emoji("xp", "⚡")
    c_wins = format_emoji("wins", "🏆")
    c_power = format_emoji("power", "🔥")

    owner_mention = _format_tg_mention(clan.owner_id, owner_name)
    win_rate = (clan.wins / clan.total_games * 100) if clan.total_games > 0 else 0.0

    text = (
        f"{c_logo} <b>{clan.name}</b>\n\n"
        f"📝 <b>Bio:</b>\n<i>{clan.bio}</i>\n\n"
        f"{c_owner} <b>Owner:</b> {owner_mention}\n"
        f"{c_members} <b>Members:</b> {members_count}/{limit}\n\n"
        f"{c_level} <b>Level:</b> {clan.level}\n"
        f"{c_xp} <b>XP:</b> {clan.xp:,}\n\n"
        f"{c_wins} <b>Wins:</b> {clan.wins} | 🎮 <b>Games:</b> {clan.total_games}\n"
        f"📊 <b>Win Rate:</b> {win_rate:.1f}%\n"
        f"{c_power} <b>Power:</b> {clan.rating:,}\n\n"
        f"📅 <b>Created:</b> {clan.created_at.strftime('%d.%m.%Y') if clan.created_at else ''}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=clan_info_keyboard(clan.id, can_apply=can_apply, has_applied=has_applied, is_full=is_full)
    )
    await callback.answer()


@router.callback_query(F.data == "clan:my_apps")
async def callback_clan_my_apps(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    apps = await clan_service.get_my_applications(callback.from_user.id)
    c_apps = format_emoji("apps", "📨")
    c_pending = format_emoji("pending", "⏳")

    if not apps:
        await callback.message.edit_text(
            f"{c_apps} <b>MENING ARIZALARIM</b>\n\nHozircha faol arizalaringiz yo'q.",
            reply_markup=clan_top_keyboard([], 1, 1)
        )
        await callback.answer()
        return

    lines = [f"{c_apps} <b>MENING ARIZALARIM ({len(apps)})</b>\n"]
    for app_rec, clan in apps:
        lines.append(f"🏰 <b>{clan.name}</b> — {c_pending} Ko'rib chiqilmoqda...")

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")]])

    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "clan:search_start")
async def callback_clan_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await state.set_state(SearchClanState.waiting_query)
        c_search = format_emoji("search", "🔎")
        await callback.message.edit_text(
            f"{c_search} <b>Clan qidirish</b>\n\n"
            "Qidirmoqchi bo'lgan Clan nomini yozing:"
        )
    await callback.answer()


@router.message(SearchClanState.waiting_query)
async def process_clan_search_query(message: Message, state: FSMContext) -> None:
    if DISABLE_CLAN:
        return
    if not message.text:
        return
    query = message.text.strip()
    await state.clear()

    clans, total = await clan_service.search_clans(query, page=1, limit=10)
    c_search = format_emoji("search", "🔎")
    if not clans:
        await message.answer(f"{c_search} <b>'{query}'</b> bo'yicha hech qanday Clan topilmadi.")
        return

    await message.answer(
        f"{c_search} <b>Qidiruv natijalari ('{query}'):</b>",
        reply_markup=clan_list_keyboard(clans, page=1, total_pages=max(1, (total + 9) // 10))
    )


@router.callback_query(F.data.startswith("clan:user_profile:"))
async def callback_clan_user_profile(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    tg_id = int(parts[2])

    async with SessionLocal() as session:
        usr = await session.scalar(select(User).where(User.telegram_id == tg_id))
        if usr is None:
            await callback.answer("❌ Profil topilmadi.", show_alert=True)
            return

        member = await session.scalar(
            select(ClanMember).where(ClanMember.user_telegram_id == tg_id)
        )
        clan_name = "Yo'q"
        role_label = "A'zo emas"
        contribution = 0
        if member:
            clan = await session.get(Clan, member.clan_id)
            if clan:
                clan_name = clan.name
                role_label = "Owner 👑" if member.role == "owner" else "Admin 🛡" if member.role == "admin" else "Member 👤"
                contribution = member.contribution_xp

    c_user = format_emoji("member", "👤")
    c_logo = format_emoji("clan", "🏰")
    c_stats = format_emoji("stats", "📊")
    c_xp = format_emoji("xp", "⚡")

    win_rate = (usr.wins / usr.total_games * 100) if usr.total_games > 0 else 0.0

    text = (
        f"{c_user} <b>PLAYER PROFILE</b>\n\n"
        f"<b>{usr.display_name}</b> (@{usr.username or 'username'})\n\n"
        f"{c_logo} <b>Clan:</b> {clan_name}\n"
        f"🛡 <b>Role:</b> {role_label}\n\n"
        f"🎮 <b>Games:</b> {usr.total_games}\n"
        f"🏆 <b>Wins:</b> {usr.wins}\n"
        f"{c_stats} <b>Win rate:</b> {win_rate:.0f}%\n\n"
        f"{c_xp} <b>Clan contribution:</b> {contribution} XP"
    )

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="clan:main")]])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
