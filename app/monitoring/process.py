from typing import Any, Dict, List, Optional, Union
import os


def _safe_import_psutil():
    try:
        import psutil

        return psutil
    except Exception:
        return None


def list_bot_processes(match_cmd: str = "mafia") -> List[Dict[str, Any]]:
    psutil = _safe_import_psutil()
    out: List[Dict[str, Any]] = []
    if not psutil:
        # minimal fallback: current process only
        return [{
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "cmdline": "N/A",
            "cpu_percent": "N/A",
            "memory_rss": "N/A",
            "threads": "N/A",
        }]
    try:
        for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "cpu_percent", "memory_info", "num_threads"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if match_cmd in cmd or match_cmd in (p.info.get("name") or ""):
                    out.append(
                        {
                            "pid": p.info.get("pid"),
                            "ppid": p.info.get("ppid"),
                            "cmdline": cmd,
                            "cpu_percent": p.info.get("cpu_percent"),
                            "memory_rss": getattr(p.info.get("memory_info"), "rss", "N/A"),
                            "threads": p.info.get("num_threads"),
                        }
                    )
            except Exception:
                continue
    except Exception:
        return [{"pid": os.getpid(), "ppid": os.getppid(), "cmdline": "N/A"}]
    if not out:
        out = [{"pid": os.getpid(), "ppid": os.getppid(), "cmdline": "N/A"}]
    return out


def get_process_counts() -> Dict[str, int]:
    psutil = _safe_import_psutil()
    if not psutil:
        return {"python_processes": "N/A", "bot_processes": "N/A", "current_pid": os.getpid(), "threads": "N/A"}
    try:
        python_count = 0
        bot_count = 0
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (p.info.get("name") or "").lower()
                cmd = " ".join(p.info.get("cmdline") or [])
                if "python" in name or "python" in cmd:
                    python_count += 1
                if "mafia" in cmd or "mafia" in name:
                    bot_count += 1
            except Exception:
                continue
        cur = psutil.Process(os.getpid())
        threads = cur.num_threads()
        return {"python_processes": python_count, "bot_processes": bot_count, "current_pid": os.getpid(), "threads": threads}
    except Exception:
        return {"python_processes": "N/A", "bot_processes": "N/A", "current_pid": os.getpid(), "threads": "N/A"}


def get_open_fds(pid: Optional[int] = None) -> Union[int, str]:
    psutil = _safe_import_psutil()
    if not psutil:
        return "N/A"
    try:
        p = psutil.Process(pid or os.getpid())
        # num_fds on UNIX, num_handles on Windows
        if hasattr(p, "num_fds"):
            return p.num_fds()
        if hasattr(p, "num_handles"):
            return p.num_handles()
    except Exception:
        return "N/A"


def get_resource_limits() -> dict:
    # try resource module (POSIX)
    try:
        import resource

        limits = {}
        for name in ("RLIMIT_NOFILE", "RLIMIT_NPROC"):
            if hasattr(resource, name):
                try:
                    val = getattr(resource, name)
                    limits[name] = resource.getrlimit(val)
                except Exception:
                    limits[name] = "N/A"
        return limits
    except Exception:
        return {}
