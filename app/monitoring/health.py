from typing import Any, Dict
from .system import get_cpu_info, get_ram_info, get_disk_info


def get_combined_health() -> Dict[str, Any]:
    cpu = get_cpu_info()
    ram = get_ram_info()
    disk = get_disk_info()
    status = {
        "cpu": cpu,
        "ram": ram,
        "disk_root": disk,
        "score": "unknown",
    }
    try:
        # simple scoring heuristic
        cpu_ok = cpu.get("cpu_percent") if isinstance(cpu.get("cpu_percent"), (int, float)) else 0
        ram_ok = ram.get("percent") if isinstance(ram.get("percent"), (int, float)) else 0
        score = 100
        if isinstance(cpu_ok, (int, float)):
            score -= min(50, int(cpu_ok // 2))
        if isinstance(ram_ok, (int, float)):
            score -= min(50, int(ram_ok // 2))
        status["score"] = max(0, score)
    except Exception:
        status["score"] = "N/A"
    return status
