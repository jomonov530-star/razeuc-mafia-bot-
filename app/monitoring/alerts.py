from typing import Any, Dict, List
import time

# Very small in-memory alert evaluator with cooldown
_ALERT_HISTORY: List[Dict[str, Any]] = []


def evaluate_alerts(metrics: Dict[str, Any], cooldown: int = 300) -> List[Dict[str, Any]]:
    now = int(time.time())
    out: List[Dict[str, Any]] = []
    # simple rules
    cpu = metrics.get("cpu", {})
    try:
        cpu_percent = cpu.get("cpu_percent") if isinstance(cpu.get("cpu_percent"), (int, float)) else None
        if cpu_percent is not None and cpu_percent > 90:
            out.append({"level": "critical", "message": "CPU > 90%"})
    except Exception:
        pass
    # respect cooldown by checking last similar alert
    filtered = []
    for a in out:
        found = False
        for h in _ALERT_HISTORY:
            if h.get("message") == a.get("message") and now - h.get("ts", 0) < cooldown:
                found = True
                break
        if not found:
            filtered.append(a)
            _ALERT_HISTORY.append({"ts": now, **a})
    # keep history bounded
    if len(_ALERT_HISTORY) > 64:
        del _ALERT_HISTORY[: len(_ALERT_HISTORY) - 64]
    return filtered
