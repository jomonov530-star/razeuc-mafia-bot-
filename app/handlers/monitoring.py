from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from app.config import Settings
from app import monitoring
from app.handlers.admin import _is_owner
from app.game_engine import GameEngine
from app.monitoring.history import get_history
from app.monitoring.session_state import get_session, update_session, clear_session

router = Router()


def monitor_nav_kb(page: str = "server", page_params: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"owner:monitor:{page}:refresh")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="owner:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _safe_edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    if callback.message is None:
        return
    try:
        return callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        raise


@router.callback_query(F.data == "owner:monitor:server")
async def owner_monitor_server(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    # Collect metrics on demand
    sys = monitoring.get_system_info()
    cpu = monitoring.get_cpu_info()
    ram = monitoring.get_ram_info()
    db = monitoring.get_db_status()
    proc = monitoring.get_process_counts()
    tasks = monitoring.get_asyncio_tasks_summary()
    health = monitoring.get_combined_health()
    # update short-term histories (bounded, on-demand)
    get_history("cpu").append(cpu.get("cpu_percent"))
    get_history("ram").append(ram.get("percent"))
    get_history("threads").append(proc.get("threads"))
    get_history("processes").append(proc.get("bot_processes"))
    get_history("asyncio_tasks").append(tasks.get("total"))
    text_lines = ["🖥 <b>Server status</b>\n"]
    text_lines.append(f"OS: {sys.get('os')}")
    text_lines.append(f"Python: {sys.get('python_version', 'N/A')}")
    text_lines.append(f"Uptime(s): {sys.get('uptime')}")
    text_lines.append("")
    text_lines.append(f"CPU: {cpu.get('cpu_percent')}% (cores {cpu.get('cores')})")
    text_lines.append(f"RAM: {ram.get('used')}/{ram.get('total')} ({ram.get('percent')}%)")
    text_lines.append("")
    text_lines.append(f"DB: {db.get('engine')} {db.get('url')}")
    text_lines.append("")
    text_lines.append(f"Processes: python={proc.get('python_processes')} bot={proc.get('bot_processes')} pid={proc.get('current_pid')}")
    text_lines.append(f"Threads: {proc.get('threads')}")
    text_lines.append("")
    text_lines.append(f"Asyncio tasks total: {tasks.get('total')}")
    text_lines.append(f"Health score: {health.get('score')}")
    out = "\n".join(text_lines)
    await _safe_edit(callback, out, reply_markup=monitor_nav_kb("server"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:logs")
async def owner_monitor_logs(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    # show logs menu with pagination controls
    from pathlib import Path

    root = Path.cwd()
    candidates = [root / "bot.err", root / "bot.log"]
    log_path = None
    for p in candidates:
        if p.exists():
            log_path = p
            break
    if log_path is None:
        for p in root.glob("*.err"):
            log_path = p
            break
    if log_path is None:
        await _safe_edit(callback, "No log file found.", reply_markup=monitor_nav_kb("logs"))
        await callback.answer()
        return
    # default page 0 with 20 lines
    page_lines, total_est = monitoring.tail_log_page(str(log_path), page=0, page_size=20)
    text = "<b>Logs</b> (newest first)\n\n" + "\n".join(page_lines)
    # initialize session
    session = get_session(callback.from_user.id)
    session["file"] = str(log_path)
    session["page"] = 1
    session["page_size"] = 20
    session["level"] = None
    session["search"] = None
    session["awaiting_search_keyword"] = False

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Prev", callback_data=f"owner:monitor:logs:nav:prev"), InlineKeyboardButton(text=f"📄 Page 1/{max(1, (total_est + 19)//20)}", callback_data="owner:monitor:logs:nav:info"), InlineKeyboardButton(text="Next ▶️", callback_data=f"owner:monitor:logs:nav:next")],
        [InlineKeyboardButton(text="20", callback_data="owner:monitor:logs:size:20"), InlineKeyboardButton(text="50", callback_data="owner:monitor:logs:size:50"), InlineKeyboardButton(text="100", callback_data="owner:monitor:logs:size:100")],
        [InlineKeyboardButton(text="🔍 Search", callback_data="owner:monitor:logs:search"), InlineKeyboardButton(text="❌ Clear Search", callback_data="owner:monitor:logs:clearsearch")],
        [InlineKeyboardButton(text="Filter: INFO", callback_data="owner:monitor:logs:filter:INFO"), InlineKeyboardButton(text="Filter: ERROR", callback_data="owner:monitor:logs:filter:ERROR")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="owner:panel")],
    ])
    await _safe_edit(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:menu")
async def owner_monitor_menu(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 Server Status", callback_data="owner:monitor:server")],
        [InlineKeyboardButton(text="📊 Resources", callback_data="owner:monitor:resources")],
        [InlineKeyboardButton(text="❤️ Health", callback_data="owner:monitor:health")],
        [InlineKeyboardButton(text="📜 Logs", callback_data="owner:monitor:logs")],
        [InlineKeyboardButton(text="🔴 Errors", callback_data="owner:monitor:errors")],
        [InlineKeyboardButton(text="🚨 Resource Monitor", callback_data="owner:monitor:resource")],
        [InlineKeyboardButton(text="🗄 Database", callback_data="owner:monitor:database")],
        [InlineKeyboardButton(text="🤖 Telegram", callback_data="owner:monitor:telegram")],
        [InlineKeyboardButton(text="⏰ Scheduler", callback_data="owner:monitor:scheduler")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="owner:panel")],
    ])
    await _safe_edit(callback, "<b>Monitoring Menu</b>", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:resources")
async def owner_monitor_resources(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    cpu = monitoring.get_cpu_info()
    ram = monitoring.get_ram_info()
    proc = monitoring.get_process_counts()
    tasks = monitoring.get_asyncio_tasks_summary()
    # histories
    cpu_hist = get_history("cpu").get()
    ram_hist = get_history("ram").get()
    threads_hist = get_history("threads").get()
    tasks_hist = get_history("asyncio_tasks").get()
    text_lines = ["📊 <b>Resources</b>\n"]
    text_lines.append(f"CPU: {cpu.get('cpu_percent')}% cores={cpu.get('cores')}")
    text_lines.append(f"CPU history: {cpu_hist[-10:]}")
    text_lines.append(f"RAM: {ram.get('used')}/{ram.get('total')} ({ram.get('percent')}%)")
    text_lines.append(f"RAM history: {ram_hist[-10:]}")
    text_lines.append(f"Processes: bot={proc.get('bot_processes')} python={proc.get('python_processes')}")
    text_lines.append(f"Threads history: {threads_hist[-10:]}")
    text_lines.append(f"Asyncio tasks: {tasks.get('total')}")
    text_lines.append(f"Asyncio tasks history: {tasks_hist[-10:]}")
    await _safe_edit(callback, "\n".join(text_lines), reply_markup=monitor_nav_kb("resources"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:health")
async def owner_monitor_health(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    health = monitoring.get_combined_health()
    score = health.get("score")
    if isinstance(score, (int, float)):
        if score >= 70:
            status = "🟢 HEALTHY"
        elif score >= 40:
            status = "🟡 WARNING"
        else:
            status = "🔴 CRITICAL"
    else:
        status = "N/A"
    text = f"❤️ <b>Health</b>\n\nStatus: {status}\nScore: {score}\n"
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("health"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:errors")
async def owner_monitor_errors(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    # search logs for ERROR/CRITICAL lines
    from pathlib import Path

    root = Path.cwd()
    log_path = None
    for p in [root / "bot.err", root / "bot.log"]:
        if p.exists():
            log_path = p
            break
    if log_path is None:
        await _safe_edit(callback, "No log file.", reply_markup=monitor_nav_kb("errors"))
        await callback.answer()
        return
    results = monitoring.search_log_with_filters(str(log_path), "ERROR", level="ERROR", max_results=100)
    text = "<b>Recent Errors</b>\n\n" + "\n".join(results[:50])
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("errors"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:resource")
async def owner_monitor_resource(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    proc = monitoring.get_process_counts()
    fds = monitoring.get_open_fds(proc.get("current_pid"))
    limits = monitoring.get_resource_limits()
    text = (
        "🚨 <b>Resource Monitor</b>\n\n"
        f"Python processes: {proc.get('python_processes')}\n"
        f"Bot processes: {proc.get('bot_processes')}\n"
        f"Current PID: {proc.get('current_pid')}\n"
        f"Threads: {proc.get('threads')}\n"
        f"Open FDs: {fds}\n"
        f"Limits: {limits}\n"
    )
    # search log for fork errors
    from pathlib import Path

    root = Path.cwd()
    log_path = None
    for p in [root / "bot.err", root / "bot.log"]:
        if p.exists():
            log_path = p
            break
    fork_lines = []
    rtu_lines = []
    if log_path:
        fork_lines = monitoring.search_log_with_filters(str(log_path), "fork", max_results=20)
        rtu_lines = monitoring.search_log_with_filters(str(log_path), "Resource temporarily unavailable", max_results=20)
    if fork_lines:
        text += "\nRecent 'fork' occurrences:\n" + "\n".join(fork_lines[:10])
    if rtu_lines:
        text += "\nRecent 'Resource temporarily unavailable' occurrences:\n" + "\n".join(rtu_lines[:10])
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("resource"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:database")
async def owner_monitor_database(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    db = monitoring.get_db_status()
    text = f"🗄 <b>Database</b>\n\nType: {db.get('engine')}\nURL: {db.get('url')}\nDB size: {db.get('db_file_size', 'N/A')}\n"
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("database"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:telegram")
async def owner_monitor_telegram(callback: CallbackQuery, engine: GameEngine, settings: Settings, bot=None) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    status = await monitoring.get_telegram_status(bot)
    text = f"🤖 <b>Telegram</b>\n\nUsername: {status.get('bot_username')}\nID: {status.get('bot_id')}\nOK: {status.get('ok')}\n"
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("telegram"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:scheduler")
async def owner_monitor_scheduler(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    sched = monitoring.get_scheduler_status()
    lines = ["⏰ <b>Scheduler</b>\n\n"]
    lines.append(f"Running: {sched.get('running')}")
    lines.append(f"Num jobs: {sched.get('num_jobs')}")
    for j in sched.get("jobs", [])[:20]:
        lines.append(f"{j.get('id')} next_run: {j.get('next_run_time')}")
    await _safe_edit(callback, "\n".join(lines), reply_markup=monitor_nav_kb("scheduler"))
    await callback.answer()


@router.callback_query(F.data.startswith("owner:monitor:logs:size:"))
async def owner_monitor_logs_size(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    # change page size
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await callback.answer()
        return
    try:
        size = int(parts[4])
    except Exception:
        size = 20
    from pathlib import Path

    root = Path.cwd()
    log_path = None
    for p in [root / "bot.err", root / "bot.log"]:
        if p.exists():
            log_path = p
            break
    session = get_session(callback.from_user.id)
    if log_path is None:
        await callback.answer("No log file.")
        return
    # apply change: reset to page 1 when page size changes
    update_session(callback.from_user.id, page_size=size, page=1)
    page_lines, total_est = monitoring.tail_log_page(str(log_path), page=0, page_size=size)
    text = "<b>Logs</b> (newest first)\n\n" + "\n".join(page_lines)
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("logs"))
    await callback.answer()


@router.callback_query(F.data.startswith("owner:monitor:logs:nav:"))
async def owner_monitor_logs_nav(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 5:
        await callback.answer()
        return
    action = parts[4]
    session = get_session(callback.from_user.id)
    if not session.get("file"):
        await callback.answer("No active log session. Open logs first.")
        return
    page = int(session.get("page", 1))
    size = int(session.get("page_size", 20))
    # compute total_est using tail of size*(page window)
    _, total_est = monitoring.tail_log_page(session["file"], page=0, page_size=size)
    last_page = max(1, (total_est + size - 1) // size)
    if action == "next":
        page = min(last_page, page + 1)
    elif action == "prev":
        page = max(1, page - 1)
    elif action == "info":
        # no-op just re-render
        pass
    else:
        await callback.answer()
        return
    update_session(callback.from_user.id, page=page)
    page_lines, total_est = monitoring.tail_log_page(session["file"], page=page - 1, page_size=size)
    # prepare keyboard with updated page label
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Prev" if page>1 else "", callback_data=f"owner:monitor:logs:nav:prev"), InlineKeyboardButton(text=f"📄 Page {page}/{last_page}", callback_data="owner:monitor:logs:nav:info"), InlineKeyboardButton(text="Next ▶️" if page<last_page else "", callback_data=f"owner:monitor:logs:nav:next")],
        [InlineKeyboardButton(text=str(size), callback_data=f"owner:monitor:logs:size:{size}" )],
        [InlineKeyboardButton(text="🔍 Search", callback_data="owner:monitor:logs:search"), InlineKeyboardButton(text="❌ Clear Search", callback_data="owner:monitor:logs:clearsearch")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="owner:panel")],
    ])
    text = "<b>Logs</b> (newest first)\n\n" + "\n".join(page_lines)
    await _safe_edit(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("owner:monitor:logs:filter:"))
async def owner_monitor_logs_filter(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await callback.answer()
        return
    level = parts[4]
    from pathlib import Path

    root = Path.cwd()
    log_path = None
    for p in [root / "bot.err", root / "bot.log"]:
        if p.exists():
            log_path = p
            break
    if log_path is None:
        await callback.answer("No log file.")
        return
    # set session filter and reset to page 1
    update_session(callback.from_user.id, level=level, page=1)
    # perform bounded search for level
    results = monitoring.search_log_with_filters(str(log_path), level, level=level, max_results=100)
    text = f"<b>Logs filtered by {level}</b>\n\n" + "\n".join(results[:100])
    if len(text) > 3500:
        text = text[-3500:]
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("logs"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:logs:search")
async def owner_monitor_logs_start_search(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    session = get_session(callback.from_user.id)
    session["awaiting_search_keyword"] = True
    await _safe_edit(callback, "🔍 Enter keyword to search logs (max 200 chars):", reply_markup=monitor_nav_kb("logs"))
    await callback.answer()


@router.callback_query(F.data == "owner:monitor:logs:clearsearch")
async def owner_monitor_logs_clear_search(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    update_session(callback.from_user.id, search=None, page=1)
    await _safe_edit(callback, "Search cleared.", reply_markup=monitor_nav_kb("logs"))
    await callback.answer()


@router.callback_query(F.data.startswith("owner:monitor:logs:page:"))
async def owner_monitor_logs_page(callback: CallbackQuery, engine: GameEngine, settings: Settings) -> None:
    if callback.from_user is None or not await _is_owner(callback.from_user.id, engine, "super_admin"):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    # expected like owner:monitor:logs:page:<n>
    if len(parts) < 5:
        await callback.answer()
        return
    try:
        page = int(parts[4])
    except Exception:
        page = 0
    from pathlib import Path

    root = Path.cwd()
    log_path = None
    for p in [root / "bot.err", root / "bot.log"]:
        if p.exists():
            log_path = p
            break
    if log_path is None:
        await callback.answer("No log file.")
        return
    page_lines, total_est = monitoring.tail_log_page(str(log_path), page=page, page_size=20)
    text = "<b>Logs</b> (newest first)\n\n" + "\n".join(page_lines)
    await _safe_edit(callback, text, reply_markup=monitor_nav_kb("logs"))
    await callback.answer()


@router.message()
async def owner_monitor_logs_search_message(message, engine: GameEngine, settings: Settings) -> None:
    # This handler processes owner search keyword replies when awaiting input
    if message.from_user is None:
        return
    if not await _is_owner(message.from_user.id, engine, "super_admin"):
        return
    session = get_session(message.from_user.id)
    if not session.get("awaiting_search_keyword"):
        return
    text = (message.text or "").strip()
    if not text:
        try:
            await message.answer("Empty keyword. Search cancelled.")
        except Exception:
            pass
        update_session(message.from_user.id, awaiting_search_keyword=False)
        return
    # cap keyword
    if len(text) > 200:
        text = text[:200]
    # set search and reset page
    update_session(message.from_user.id, search=text, page=1, awaiting_search_keyword=False)
    # perform search and render first page
    session = get_session(message.from_user.id)
    path = session.get("file")
    if not path:
        try:
            await message.answer("No active log file. Open Logs from Monitoring menu first.")
        except Exception:
            pass
        return
    # bounded search (case-insensitive)
    results = monitoring.search_log_with_filters(path, text, level=session.get("level"), max_results=200)
    page_size = int(session.get("page_size", 20))
    page = int(session.get("page", 1))
    total = len(results)
    last_page = max(1, (total + page_size - 1) // page_size)
    page = min(page, last_page)
    start = (page - 1) * page_size
    page_lines = results[start : start + page_size]
    out = f"🔍 Search: {text} (results {total})\n\n" + "\n".join(page_lines)
    if len(out) > 3500:
        out = out[:3500]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Prev", callback_data=f"owner:monitor:logs:nav:prev"), InlineKeyboardButton(text=f"📄 Page {page}/{last_page}", callback_data="owner:monitor:logs:nav:info"), InlineKeyboardButton(text="Next ▶️", callback_data=f"owner:monitor:logs:nav:next")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="owner:monitor:logs:nav:info"), InlineKeyboardButton(text="❌ Clear Search", callback_data="owner:monitor:logs:clearsearch")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="owner:panel")],
    ])
    try:
        await message.answer(out, reply_markup=kb)
    except Exception:
        pass


