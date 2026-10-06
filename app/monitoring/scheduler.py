from typing import Any, Dict


def get_scheduler_status() -> Dict[str, Any]:
    try:
        from app import scheduler as app_scheduler
    except Exception:
        return {"running": "N/A"}
    try:
        sched = getattr(app_scheduler, "scheduler", None)
        if sched is None:
            return {"running": False}
        jobs = []
        for j in sched.get_jobs():
            try:
                jobs.append({"id": j.id, "next_run_time": str(j.next_run_time)})
            except Exception:
                continue
        return {"running": True, "num_jobs": len(jobs), "jobs": jobs}
    except Exception:
        return {"running": "N/A"}
