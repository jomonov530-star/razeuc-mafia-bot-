from typing import Any, Dict
from ._cache import TTLCache

_cache = TTLCache(maxsize=8, ttl=2.0)


def _safe_import_psutil():
    try:
        import psutil

        return psutil
    except Exception:
        return None


def get_system_info() -> Dict[str, Any]:
    cached = _cache.get("system_info")
    if cached is not None:
        return cached
    psutil = _safe_import_psutil()
    out: Dict[str, Any] = {}
    if not psutil:
        out.update({"os": "N/A", "uptime": "N/A"})
        _cache.set("system_info", out)
        return out
    try:
        import platform, time

        out["os"] = platform.platform()
        out["python_version"] = platform.python_version()
        out["uptime"] = int(time.time() - psutil.boot_time())
    except Exception:
        out.update({"os": "N/A", "uptime": "N/A"})
    _cache.set("system_info", out)
    return out


def get_cpu_info() -> Dict[str, Any]:
    cached = _cache.get("cpu_info")
    if cached is not None:
        return cached
    psutil = _safe_import_psutil()
    if not psutil:
        res = {"cpu_percent": "N/A", "cores": "N/A", "load_avg": "N/A"}
        _cache.set("cpu_info", res)
        return res
    try:
        res = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cores": psutil.cpu_count(logical=True),
        }
        try:
            res["load_avg"] = psutil.getloadavg()
        except Exception:
            res["load_avg"] = "N/A"
    except Exception:
        res = {"cpu_percent": "N/A", "cores": "N/A", "load_avg": "N/A"}
    _cache.set("cpu_info", res)
    return res


def get_ram_info() -> Dict[str, Any]:
    cached = _cache.get("ram_info")
    if cached is not None:
        return cached
    psutil = _safe_import_psutil()
    if not psutil:
        res = {"total": "N/A", "used": "N/A", "percent": "N/A"}
        _cache.set("ram_info", res)
        return res
    try:
        vm = psutil.virtual_memory()
        res = {"total": vm.total, "used": vm.used, "percent": vm.percent}
    except Exception:
        res = {"total": "N/A", "used": "N/A", "percent": "N/A"}
    _cache.set("ram_info", res)
    return res


def get_disk_info(path: str = "/") -> Dict[str, Any]:
    key = f"disk:{path}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    psutil = _safe_import_psutil()
    if not psutil:
        res = {"total": "N/A", "used": "N/A", "free": "N/A", "percent": "N/A"}
        _cache.set(key, res)
        return res
    try:
        du = psutil.disk_usage(path)
        res = {"total": du.total, "used": du.used, "free": du.free, "percent": du.percent}
    except Exception:
        res = {"total": "N/A", "used": "N/A", "free": "N/A", "percent": "N/A"}
    _cache.set(key, res)
    return res
