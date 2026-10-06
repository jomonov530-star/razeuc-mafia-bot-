from typing import Any, Dict
import os
from urllib.parse import urlparse


def _mask_db_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.hostname or ""
        path = parsed.path or ""
        return f"{parsed.scheme}://{netloc}{path}"
    except Exception:
        return "N/A"


def get_db_status() -> Dict[str, Any]:
    # Import lazily to avoid startup side-effects
    try:
        from app import database
    except Exception:
        return {"engine": "N/A"}
    out: Dict[str, Any] = {"engine": "unknown"}
    try:
        engine = getattr(database, "engine", None)
        url = getattr(engine, "url", None)
        if url is None:
            # maybe engine has an URL attribute via dialect
            out["engine"] = str(engine)
            out["url"] = "N/A"
        else:
            out["engine"] = engine.name if hasattr(engine, "name") else str(engine)
            out["url"] = _mask_db_url(str(url))
        # sqlite file size
        if out.get("url", "").startswith("sqlite") or (hasattr(database, "DATABASE_URL") and "sqlite" in str(getattr(database, "DATABASE_URL"))):
            # try find file
            try:
                dbpath = None
                if hasattr(database, "DATABASE_URL"):
                    dbpath = getattr(database, "DATABASE_URL")
                if dbpath and isinstance(dbpath, str) and dbpath.startswith("sqlite"):
                    # file path after sqlite:///
                    p = dbpath.split("sqlite:///", 1)[-1]
                    if os.path.exists(p):
                        out["db_file_size"] = os.path.getsize(p)
            except Exception:
                pass
    except Exception:
        return {"engine": "N/A"}
    return out
