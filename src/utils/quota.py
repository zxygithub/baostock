"""Best-effort metering for bare bs.* calls outside BaseDownloader."""

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

from src.config import DB_PATH

logger = logging.getLogger("baostock")


def record_requests(n: int = 1, db_path: Path | str | None = None) -> None:
    """Best-effort metering for bare bs.* calls outside BaseDownloader.

    UPSERTs `count = count + n` for today's row in the request_count table
    (same schema as src/db_manager.py), committing immediately via its own
    sqlite connection (busy_timeout=30000). Default db_path must be resolved
    the same way src/config.py / src/db_manager.py resolve DB_PATH - do not
    hardcode. Must NEVER raise: on sqlite failure log a warning and return.
    """
    try:
        path = Path(db_path) if db_path is not None else Path(DB_PATH)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            today = date.today().isoformat()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO request_count (date, count, update_time) VALUES (?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET count = count + excluded.count, "
                "update_time = excluded.update_time",
                (today, n, now),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning(f"request_count metering failed (best-effort, ignored): {e}")
