import time
from typing import Dict, Any

# Bounded per-owner session state with TTL and max sessions
_SESSIONS: Dict[int, Dict[str, Any]] = {}
_LAST_ACTIVE: Dict[int, float] = {}
_MAX_SESSIONS = 16
_SESSION_TTL = 300.0  # seconds


def _expire_old() -> None:
    now = time.time()
    to_delete = [uid for uid, ts in _LAST_ACTIVE.items() if now - ts > _SESSION_TTL]
    for uid in to_delete:
        _SESSIONS.pop(uid, None)
        _LAST_ACTIVE.pop(uid, None)


def get_session(user_id: int) -> Dict[str, Any]:
    _expire_old()
    if user_id not in _SESSIONS:
        # enforce max sessions by evicting oldest
        if len(_SESSIONS) >= _MAX_SESSIONS:
            oldest = min(_LAST_ACTIVE.items(), key=lambda kv: kv[1])[0]
            _SESSIONS.pop(oldest, None)
            _LAST_ACTIVE.pop(oldest, None)
        _SESSIONS[user_id] = {
            "file": None,
            "page": 1,
            "page_size": 20,
            "level": None,
            "search": None,
            "awaiting_search_keyword": False,
        }
    _LAST_ACTIVE[user_id] = time.time()
    return _SESSIONS[user_id]


def update_session(user_id: int, **kwargs) -> None:
    s = get_session(user_id)
    for k, v in kwargs.items():
        if k in s:
            s[k] = v
    _LAST_ACTIVE[user_id] = time.time()


def clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)
    _LAST_ACTIVE.pop(user_id, None)
