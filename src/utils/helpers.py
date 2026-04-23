"""Utility helper functions for BaoStock data processing."""

import logging
from collections.abc import Generator
from datetime import datetime
from pathlib import Path


__all__ = [
    "batch_iterable",
    "convert_stock_code",
    "convert_time_format",
    "convert_turn_field",
    "fetch_all_rows",
    "get_current_quarter",
    "safe_float",
    "safe_int",
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


def fetch_all_rows(result_set) -> list[list]:
    """Iterate through a BaoStock result set and collect all rows.

    Args:
        result_set: A BaoStock query result object with error_code, next(), and get_row_data().

    Returns:
        List of row data lists.
    """
    data_list: list[list] = []
    while result_set.error_code == "0" and result_set.next():
        data_list.append(result_set.get_row_data())
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
