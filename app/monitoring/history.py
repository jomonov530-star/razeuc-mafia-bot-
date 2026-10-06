from typing import Any, Dict, List

# Bounded in-memory history updated on-demand only
class BoundedHistory:
    def __init__(self, maxlen: int = 60):
        self.maxlen = maxlen
        self._data: List[Any] = []

    def append(self, value: Any) -> None:
        self._data.append(value)
        if len(self._data) > self.maxlen:
            del self._data[0 : len(self._data) - self.maxlen]

    def get(self) -> List[Any]:
        return list(self._data)


# Simple registry
_HISTORIES: Dict[str, BoundedHistory] = {}


def get_history(name: str, maxlen: int = 60) -> BoundedHistory:
    if name not in _HISTORIES:
        _HISTORIES[name] = BoundedHistory(maxlen=maxlen)
    return _HISTORIES[name]
