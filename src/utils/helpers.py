"""Utility helper functions for BaoStock data processing."""

import logging
import subprocess
import sys
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path


__all__ = [
    "batch_iterable",
    "convert_stock_code",
    "convert_time_format",
    "convert_turn_field",
    "fetch_all_rows",
    "get_current_quarter",
    "run_main_with_report",
    "safe_float",
    "safe_int",
    "send_daily_report",
    "setup_logging",
]


def convert_time_format(time_str: str) -> str:
    """Convert BaoStock minute time format to standard datetime string.

    Converts "YYYYMMDDHHMMSSsss" to "YYYY-MM-DD HH:MM:SS".

    Args:
        time_str: Time string in BaoStock format, e.g. "20240101093000000".

    Returns:
        Formatted datetime string, e.g. "2024-01-01 09:30:00".
    """
    return f"{time_str[0:4]}-{time_str[4:6]}-{time_str[6:8]} {time_str[8:10]}:{time_str[10:12]}:{time_str[12:14]}"


def safe_float(value: str | None, default: float = 0.0) -> float:
    """Safely convert a string to float, returning default on failure.

    Handles empty strings, None, and non-numeric placeholders like "—" or "N/A".

    Args:
        value: The string value to convert.
        default: Fallback value if conversion fails.

    Returns:
        Converted float or the default value.
    """
    if value is None or value.strip() in ("", "—", "N/A"):
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: str | None, default: int = 0) -> int:
    """Safely convert a string to int, returning default on failure.

    Args:
        value: The string value to convert.
        default: Fallback value if conversion fails.

    Returns:
        Converted int or the default value.
    """
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def convert_turn_field(value: str) -> float:
    """Convert the BaoStock 'turn' (换手率) field to float.

    Args:
        value: The turn field value as a string.

    Returns:
        Float representation, or 0.0 for empty strings.
    """
    if not value or value.strip() == "":
        return 0.0
    return float(value)


def fetch_all_rows(result_set, max_rows: int = 100000) -> list[list]:
    """Iterate through a BaoStock result set and collect all rows.

    Args:
        result_set: A BaoStock query result object with error_code, next(), and get_row_data().
        max_rows: Maximum number of rows to fetch (safety limit to prevent infinite loops).

    Returns:
        List of row data lists.
    """
    data_list: list[list] = []
    count = 0
    while result_set.error_code == "0" and result_set.next():
        data_list.append(result_set.get_row_data())
        count += 1
        if count > max_rows:
            break
    return data_list


def convert_stock_code(code: str) -> str:
    """Convert a plain stock code to BaoStock format.

    Args:
        code: Stock code string, e.g. "600000" or "sh.600000".

    Returns:
        BaoStock-formatted code, e.g. "sh.600000" or "sz.000001".
    """
    if "." in code:
        return code
    if code.startswith("6"):
        return f"sh.{code}"
    return f"sz.{code}"


def get_current_quarter() -> tuple[int, int]:
    """Determine the current year and quarter based on today's date.

    Quarter mapping:
        Q1: January - March
        Q2: April - June
        Q3: July - September
        Q4: October - December

    Returns:
        Tuple of (year, quarter).
    """
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    return now.year, quarter


def setup_logging(
    name: str = "baostock", log_file: str | None = None
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def batch_iterable(items: list, batch_size: int) -> Generator[list, None, None]:
    """Yield successive batches from a list.

    Args:
        items: The input list to batch.
        batch_size: Maximum number of items per batch.

    Yields:
        Sublists of items, each with at most batch_size elements.
    """
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def send_daily_report(reason: str, logger: logging.Logger | None = None) -> None:
    """Trigger daily_report.py in a subprocess. Never raises."""
    log = logger or logging.getLogger("baostock")
    script = Path(__file__).resolve().parents[2] / "scripts" / "daily_report.py"
    cmd = [
        sys.executable, str(script),
        "--if-needed",
        "--date", date.today().isoformat(),
        "--reason", reason,
    ]
    try:
        result = subprocess.run(cmd, timeout=120, check=False)
        if result.returncode != 0:
            log.warning("daily_report exited %s (fallback cron will retry)", result.returncode)
    except Exception as e:
        log.warning("daily_report send failed (fallback cron will retry): %s", e)


def run_main_with_report(main_fn, logger: logging.Logger | None = None) -> None:
    """Send the daily report only when the day's fetch is truly finished.

    Terminal = SystemExit(1) (49000 limit) or normal return past the 23:55
    shutdown. A mid-day normal return is just a pass boundary — the monitor
    restarts the fetch — so it must not send.
    """
    from src.downloaders.base import is_past_shutdown_time

    reason = None
    try:
        main_fn()
    except SystemExit as e:
        if e.code != 1:
            raise
        reason = "达到每日请求上限(49000)"
    else:
        if is_past_shutdown_time():
            reason = "达到每日停止时间(23:55)"
        else:
            log = logger or logging.getLogger("baostock")
            log.info("趟次结束但当日拉取未终结（monitor 将重启续拉），日报延至真正终结时发送")
    if reason is not None:
        send_daily_report(reason, logger)
