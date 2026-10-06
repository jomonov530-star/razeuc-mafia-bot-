from __future__ import annotations

from weakref import WeakValueDictionary
import asyncio
from typing import Hashable

# WeakValueDictionary holds locks weakly so they don't accumulate indefinitely
_LOCKS: WeakValueDictionary = WeakValueDictionary()


def get_lock(key: Hashable) -> asyncio.Lock:
    """Return an asyncio.Lock for the given key. Locks are kept weakly so
    they can be garbage-collected when no longer referenced elsewhere.
    """
    k = int(key)
    lock = _LOCKS.get(k)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[k] = lock
    return lock
