import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, maxsize: int = 16, ttl: float = 2.0):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if not entry:
            return None
        ts, val = entry
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self.maxsize and key not in self._data:
            # evict oldest
            oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
            self._data.pop(oldest, None)
        self._data[key] = (time.time(), value)

    def clear(self) -> None:
        self._data.clear()

