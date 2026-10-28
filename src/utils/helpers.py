"""Utility helper functions for BaoStock data processing."""

import logging
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from datetime import date, datetime
from pathlib import Path

from src.config_loader import (
    get_daily_request_limit,
    get_idle_pass_interval_minutes,
    get_productive_pass_interval_minutes,
)
from src.utils import blacklist
from src.downloaders.base import BlacklistedError


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


class RequestPacer:
    """Batch pacing for per-request loops: sleep once every N requests.

    Replaces per-request ``time.sleep(batch_sleep)`` (which cost hours of pure
    sleeping in the dividend/adjust/report phases) with the same pacing the
    K-line batches use: one ``sleep_seconds`` pause per ``requests_per_sleep``
    API requests.
    """

    def __init__(
        self,
        requests_per_sleep: int,
        sleep_seconds: float,
        sleep: Callable[[float], None] | None = None,
    ):
        self.every = max(int(requests_per_sleep), 1)  # 非正窗口视为 1,不得除零
        self.seconds = sleep_seconds
        self._sleep = sleep
        self._count = 0

    def tick(self) -> None:
        """Count one API request; sleep after every ``requests_per_sleep``."""
        self._count += 1
        if self._count % self.every == 0:
            # sleep=None 时调用期解析 time.sleep,保证测试可替换
            (self._sleep or time.sleep)(self.seconds)


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
        # 日报生成在 16GB 库上需 2~3 分钟（全表 COUNT 扫描），高并发时更久——
        # 2026-10-03 曾因 120 秒超时把子进程杀死导致当日日报未发出
        result = subprocess.run(cmd, timeout=600, check=False)
        if result.returncode != 0:
            log.warning("daily_report exited %s (fallback cron will retry)", result.returncode)
    except Exception as e:
        log.warning("daily_report send failed (fallback cron will retry): %s", e)


_SLEEP_SEGMENT_SECONDS = 300  # 心跳休眠每段上限,确保 monitor 15 分钟静默阈值内总有日志


def _sleep_idle_in_segments(
    total_minutes: int,
    log: logging.Logger,
    is_past_shutdown_time,
) -> bool:
    """Sleep ``total_minutes`` in ≤300 s segments, logging a heartbeat each.

    Returns True if the 23:55 shutdown time was reached mid-sleep (so the
    caller can terminate and send the daily report); False otherwise.
    """
    total_minutes = max(total_minutes, 1)  # 钳位非正间隔,避免无休眠热循环
    total_seconds = total_minutes * 60
    slept = 0
    while slept < total_seconds:
        segment = min(total_seconds - slept, _SLEEP_SEGMENT_SECONDS)
        time.sleep(segment)
        slept += segment
        log.info(
            "休眠心跳: 已休眠 %d 分钟 / 计划 %d 分钟,下趟继续",
            slept // 60,
            total_minutes,
        )
        if is_past_shutdown_time():
            return True
    return False


def compute_pass_interval_minutes(new_rows: int, idle_count: int) -> tuple[int, int]:
    """Return (sleep_minutes, next_idle_count) for the pass scheduler.

    A pass that added rows waits the base interval and resets the idle
    counter; an idle pass backs off exponentially (base * 2**(idle_count-1))
    capped at get_idle_pass_interval_minutes(). Non-positive results are
    clamped to a real 1-minute sleep by _sleep_idle_in_segments.
    """
    if new_rows > 0:
        return get_productive_pass_interval_minutes(), 0
    idle_count += 1
    base = get_productive_pass_interval_minutes()
    cap = get_idle_pass_interval_minutes()
    return min(base * 2 ** (idle_count - 1), cap), idle_count


def run_main_with_report(
    main_fn, logger: logging.Logger | None = None, *, loop: bool = False
) -> None:
    """Send the daily report only when the day's fetch is truly finished.

    ``loop=False`` (single pass, used by update_daily.py and ``--once``):
    Terminal = SystemExit(1) (daily request limit) or normal return past the
    23:55 shutdown. A mid-day normal return is just a pass boundary — the
    monitor restarts the fetch — so it must not send.

    ``loop=True`` (pass scheduler, used by download_all.py): keep running
    passes until SystemExit(1) or the 23:55 shutdown, sleeping between passes
    in ≤300 s segments with a heartbeat log per segment. Interval is adaptive:
    base interval after a pass that added rows, exponential backoff capped at
    ``idle_pass_interval_minutes`` on consecutive idle passes.
    """
    from src.downloaders.base import is_past_shutdown_time

    log = logger or logging.getLogger("baostock")

    # 启动闸(组件 2):封禁退避期内不发起任何网络请求,退出码 2
    blocked, remain = blacklist.in_backoff()
    if blocked:
        log.error(blacklist.blocked_message(remain))
        raise SystemExit(2)

    if not loop:
        reason = None
        try:
            main_fn()
        except SystemExit as e:
            if e.code != 1:
                raise
            reason = f"达到每日请求上限({get_daily_request_limit()})"
        else:
            if is_past_shutdown_time():
                reason = "达到每日停止时间(23:55)"
            else:
                log = logger or logging.getLogger("baostock")
                log.info("趟次结束但当日拉取未终结（monitor 将重启续拉），日报延至真正终结时发送")
        if reason is not None:
            send_daily_report(reason, logger)
        return

    log = logger or logging.getLogger("baostock")
    idle_count = 0
    while True:
        # 趟次顶部闸:中途被 monitor 等外部方标记封禁时同样止步(每趟一次)
        blocked, remain = blacklist.in_backoff()
        if blocked:
            log.error(blacklist.blocked_message(remain))
            raise SystemExit(2)
        reason = None
        try:
            new_rows = main_fn()
        except BlacklistedError:
            # 决策 2:被封立即终止进程;沿用既有裁定——不发日报。
            # spec §3.2:退出码须非 0(1=配额,2=启动闸,3=熔断终止),
            # 不得静默退出 0,否则 start.sh 会误标 DONE、外部调度误判成功。
            log.warning("命中黑名单熔断,终止趟次调度(退出码 3;不发日报;等待退避期过后重试)")
            raise SystemExit(3)
        except SystemExit as e:
            if e.code != 1:
                raise
            reason = f"达到每日请求上限({get_daily_request_limit()})"
        else:
            if new_rows is None:
                new_rows = 0
            if is_past_shutdown_time():
                reason = "达到每日停止时间(23:55)"
            else:
                minutes, idle_count = compute_pass_interval_minutes(
                    new_rows, idle_count
                )
                log.info(
                    "本趟新增 %d 行 → %d 分钟后下一趟(连续空趟 %d)",
                    new_rows,
                    minutes,
                    idle_count,
                )
                if _sleep_idle_in_segments(minutes, log, is_past_shutdown_time):
                    reason = "达到每日停止时间(23:55)"
        if reason is not None:
            send_daily_report(reason, logger)
            return
