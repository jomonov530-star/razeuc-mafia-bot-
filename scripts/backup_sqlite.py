#!/usr/bin/env python3
"""Safe Hot Backup script for SQLite database in WAL mode.

Uses the official sqlite3 online backup API (or .backup) to create
a consistent point-in-time snapshot of mafia.db even while games
are actively writing to the database.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sqlite_backup")


def perform_backup() -> str | None:
    settings = get_settings()
    db_url = settings.database_url

    # Parse database path from sqlite+aiosqlite:///./storage/mafia.db
    if "sqlite" not in db_url:
        logger.warning("Database URL is not SQLite. Skipping SQLite backup.")
        return None

    # Remove driver prefix to extract path
    raw_path = db_url.split(":///")[-1]
    db_path = Path(raw_path).resolve()

    if not db_path.exists():
        logger.error("Source database file does not exist at path: %s", db_path)
        return None

    # Backup destination directory
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"mafia_backup_{timestamp}.db"

    logger.info("Starting safe hot backup from %s to %s", db_path, backup_path)

    try:
        source_conn = sqlite3.connect(str(db_path))
        dest_conn = sqlite3.connect(str(backup_path))

        with dest_conn:
            source_conn.backup(dest_conn, pages=100, progress=None)

        dest_conn.close()
        source_conn.close()

        file_size_mb = backup_path.stat().st_size / (1024 * 1024)
        logger.info("Backup successfully completed! Backup size: %.2f MB", file_size_mb)
        return str(backup_path)

    except Exception:
        logger.exception("Backup failed with unexpected error")
        if backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                pass
        return None


if __name__ == "__main__":
    result = perform_backup()
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
