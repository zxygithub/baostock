import baostock as bs
import pandas as pd
import sqlite3
import time
import signal
import logging
import json
from datetime import datetime
from pathlib import Path

from src.config_loader import get_socket_timeout, get_daily_request_limit

# API request log marker - used for statistical analysis
API_LOG_MARKER = "[API_REQ]"


class _ApiResultWrapper:
    """Wraps a BaoStock result set to log row count when fully consumed."""

    def __init__(self, rs, func_name: str, params: str, logger: logging.Logger):
        self._rs = rs
        self._func_name = func_name
        self._params = params
        self._logger = logger
        self._row_count = 0
        self._consumed = False
        self._has_error = False

    def mark_error(self):
        """Mark this result as having an error (suppresses row count logging)."""
        self._has_error = True

    def __getattr__(self, name):
        return getattr(self._rs, name)

    def next(self):
        result = self._rs.next()
        if result:
            self._row_count += 1
        else:
            self._consumed = True
            if not self._has_error:
                self._logger.info(
                    f"{API_LOG_MARKER} {self._func_name} | params={self._params} | rows={self._row_count}"
                )
        return result

    def get_row_data(self):
        return self._rs.get_row_data()

    @property
    def error_code(self):
        return self._rs.error_code

    @property
    def error_msg(self):
        return self._rs.error_msg


def _build_params_str(func, *args, **kwargs) -> str:
    """Build a concise parameter string for logging."""
    parts = []
    for arg in args:
        parts.append(str(arg))
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return " ".join(parts)


# Load configuration when module is imported
_SOCKET_TIMEOUT = get_socket_timeout()
_DAILY_REQUEST_LIMIT = get_daily_request_limit()


class BaseDownloader:
    SOCKET_TIMEOUT: int = _SOCKET_TIMEOUT  # seconds for socket recv/connect
    DAILY_REQUEST_LIMIT: int = _DAILY_REQUEST_LIMIT

    def __init__(self, db_path: str | Path, logger: logging.Logger | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger("baostock")
        self._conn: sqlite3.Connection | None = None
        self._login_time: float = 0
        self._interrupted: bool = False
        self._limit_exceeded: bool = False
        self._check_daily_limit()
        self.login()

    def _apply_socket_timeout(self):
        import baostock.common.context as context

        if hasattr(context, "default_socket") and context.default_socket is not None:
            context.default_socket.settimeout(self.SOCKET_TIMEOUT)
            self.logger.debug(f"Socket timeout set to {self.SOCKET_TIMEOUT}s")

    def _check_daily_limit(self):
        """Check if today's API request count has reached the limit."""
        from src.db_manager import DBManager

        db = DBManager(str(self.db_path))
        db.migrate_schema()
        count = db.get_today_request_count()
        if count >= self.DAILY_REQUEST_LIMIT:
            self._limit_exceeded = True
            self.logger.error(
                f"今日 API 请求已达上限 ({count}/{self.DAILY_REQUEST_LIMIT})，"
                f"为避免进入黑名单，程序已退出。请明日再试。"
            )
            db.close()
            raise SystemExit(1)
        self.logger.info(f"今日 API 请求计数: {count}/{self.DAILY_REQUEST_LIMIT}")
        db.close()

    def _increment_request_count(self):
        """Increment today's API request count by 1, using direct SQL (方案C).

        Avoids DBManager/migrate_schema() overhead by executing raw SQL directly.
        Uses INSERT ... ON CONFLICT DO UPDATE to atomically insert or increment.
        """
        from datetime import date, datetime

        today = date.today().isoformat()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO request_count (date, count, update_time) VALUES (?, 1, ?) "
            "ON CONFLICT(date) DO UPDATE SET count = count + 1, update_time = excluded.update_time",
            (today, now),
        )
        conn.commit()
        cursor = conn.execute("SELECT count FROM request_count WHERE date = ?", (today,))
        row = cursor.fetchone()
        new_count = row[0] if row else 0
        conn.close()

        if new_count >= self.DAILY_REQUEST_LIMIT:
            self._limit_exceeded = True
            self.logger.error(
                f"今日 API 请求已达上限 ({new_count}/{self.DAILY_REQUEST_LIMIT})，"
                f"为避免进入黑名单，程序已退出。请明日再试。"
            )
            raise SystemExit(1)

    def _api_call(self, func, *args, **kwargs):
        """Wrapper for direct baostock API calls that increments request count."""
        func_name = getattr(func, "__name__", str(func))
        params = _build_params_str(func, *args, **kwargs)
        rs = func(*args, **kwargs)
        self._increment_request_count()
        return _ApiResultWrapper(rs, func_name, params, self.logger)

    def login(self):
        lg = bs.login()
        if lg.error_code == "10001011":
            self.logger.error(
                "BaoStock IP is blacklisted. Please seek help in the QQ group."
            )
            raise SystemExit("IP blacklisted.")
        if lg.error_code != "0":
            raise ConnectionError(f"BaoStock login failed: {lg.error_msg}")
        self._apply_socket_timeout()
        self._login_time = time.time()
        self.logger.info("BaoStock login successful")

    def logout(self):
        bs.logout()
        self.logger.info("BaoStock logout successful")

    def ensure_login(self):
        from src.config import LOGIN_REFRESH_INTERVAL

        if time.time() - self._login_time > LOGIN_REFRESH_INTERVAL:
            self.logger.info("Session expired, re-logging in...")
            self.logout()
            self.login()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None
        if not self._limit_exceeded:
            self.logout()

    def setup_signal_handler(self, checkpoint_path: Path | None = None):
        if checkpoint_path is None:
            checkpoint_path = self.db_path.parent / ".download_checkpoint.json"

        def handler(signum, frame):
            sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
            self.logger.warning(f"\nReceived {sig_name}, saving checkpoint...")
            self._interrupted = True
            if checkpoint_path:
                self._save_checkpoint(checkpoint_path)
            self.logger.info("Checkpoint saved. Exiting gracefully.")
            import sys

            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        self._checkpoint_path = checkpoint_path

    def _save_checkpoint(self, path: Path):
        if hasattr(self, "_checkpoint_data") and self._checkpoint_data:
            path.write_text(json.dumps(self._checkpoint_data))
            self.logger.info(f"Checkpoint saved: {self._checkpoint_data}")

    def _load_checkpoint(self, path: Path) -> dict:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self.logger.info(f"Loaded checkpoint: {data}")
                return data
            except (json.JSONDecodeError, OSError):
                self.logger.warning(f"Corrupted checkpoint file, ignoring")
        return {}

    def clear_checkpoint(self, path: Path | None = None):
        if path is None:
            path = getattr(self, "_checkpoint_path", None)
        if path and path.exists():
            path.unlink()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def fetch_all_rows(self, rs) -> list[list]:
        data_list = []
        while rs.error_code == "0" and rs.next():
            data_list.append(rs.get_row_data())
        return data_list

    def query_with_retry(
        self, query_func, max_retries: int = 3, sleep_base: int = 2, **kwargs
    ):
        for attempt in range(max_retries):
            try:
                self.ensure_login()
                rs = query_func(**kwargs)
                # 无论成功失败都计数，因为服务器端已计数
                self._increment_request_count()
                func_name = getattr(query_func, "__name__", str(query_func))
                params = _build_params_str(query_func, **kwargs)
                wrapped = _ApiResultWrapper(rs, func_name, params, self.logger)
                if rs.error_code == "0":
                    return wrapped
                wrapped.mark_error()
                if "session" in rs.error_msg.lower() or "网络" in rs.error_msg:
                    self.logger.warning(
                        f"Session/network error, re-logging in: {rs.error_msg}"
                    )
                    try:
                        self.logout()
                    except Exception:
                        pass
                    self.login()
                    continue
                self.logger.warning(
                    f"Query failed (attempt {attempt + 1}): {rs.error_msg}"
                )
            except Exception as e:
                self.logger.warning(f"Query exception (attempt {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                sleep_time = sleep_base ** (attempt + 1)
                self.logger.info(f"Retrying in {sleep_time}s...")
                time.sleep(sleep_time)

        raise RuntimeError(f"Query failed after {max_retries} attempts: {kwargs}")

    def save_df(self, df: pd.DataFrame, table: str, if_exists: str = "append"):
        if df.empty:
            return
        if "update_time" not in df.columns:
            df = df.copy()
            df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if if_exists == "upsert":
            tmp = f"{table}_tmp"
            df.to_sql(tmp, self.conn, if_exists="replace", index=False)
            cols = ", ".join(str(c) for c in df.columns)
            self.conn.execute(f"""
                INSERT OR REPLACE INTO {table} ({cols})
                SELECT {cols} FROM {tmp}
            """)
            self.conn.execute(f"DROP TABLE IF EXISTS {tmp}")
            self.conn.commit()
        else:
            df.to_sql(table, self.conn, if_exists=if_exists, index=False)
            self.conn.commit()

    def get_max_date(self, table: str, date_column: str = "date") -> str | None:
        try:
            cursor = self.conn.execute(f"SELECT MAX({date_column}) FROM {table}")
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]
        except sqlite3.OperationalError:
            pass
        return None

    def get_last_downloaded(
        self, table: str, code: str, date_column: str = "date", adjustflag: int | None = None
    ) -> str | None:
        try:
            if adjustflag is not None:
                row = self.conn.execute(
                    f"SELECT MAX({date_column}) FROM {table} WHERE code = ? AND adjustflag = ?",
                    (code, adjustflag),
                ).fetchone()
            else:
                row = self.conn.execute(
                    f"SELECT MAX({date_column}) FROM {table} WHERE code = ?", (code,)
                ).fetchone()
            return row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            return None

    def get_downloaded_codes(self, table: str, code_column: str = "code") -> set[str]:
        try:
            cursor = self.conn.execute(f"SELECT DISTINCT {code_column} FROM {table}")
            return {row[0] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            return set()
