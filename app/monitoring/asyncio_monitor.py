from typing import Any, Dict, Optional
import asyncio


def get_asyncio_tasks_summary(loop: Optional[asyncio.AbstractEventLoop] = None) -> Dict[str, Any]:
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return {"total": "N/A", "pending": "N/A", "running": "N/A", "top_coroutines": []}
    try:
        tasks = asyncio.all_tasks(loop=loop)
    except Exception:
        tasks = set()
    total = len(tasks)
    running = 0
    pending = 0
    coro_count: dict[str, int] = {}
    for t in tasks:
        try:
            st = t._state  # type: ignore[attr-defined]
        except Exception:
            st = None
        if st == "RUNNING":
            running += 1
        else:
            pending += 1
        try:
            coro = t.get_coro()
            name = getattr(coro, "__qualname__", getattr(coro, "__name__", str(coro)))
        except Exception:
            name = "<unknown>"
        coro_count[name] = coro_count.get(name, 0) + 1
    top = sorted(coro_count.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {"total": total, "pending": pending, "running": running, "top_coroutines": top}
