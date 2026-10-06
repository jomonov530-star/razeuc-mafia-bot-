from typing import Any, Dict


async def get_telegram_status(bot) -> Dict[str, Any]:
    out = {"bot_username": "N/A", "bot_id": "N/A", "ok": False}
    try:
        me = await bot.get_me()
        out["bot_username"] = getattr(me, "username", "N/A")
        out["bot_id"] = getattr(me, "id", "N/A")
        out["ok"] = True
    except Exception:
        # graceful fallback
        pass
    return out
