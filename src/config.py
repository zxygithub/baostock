"""Configuration constants for the BaoStock data download project.

This module contains technical constants, field definitions, and paths
that rarely change. User-configurable settings (enabled switches, date ranges,
batch parameters) are in config.yaml and accessed via src.config_loader.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(__file__).parent.parent / "data" / "baostock.db"

# ---------------------------------------------------------------------------
# Internal timing settings (not user-configurable)
# ---------------------------------------------------------------------------

FINANCIAL_SLEEP: float = 0.5  # seconds between financial API calls
LOGIN_REFRESH_INTERVAL: int = 1800  # seconds (30 min) before re-login
MAX_RETRIES: int = 3  # maximum number of retry attempts

# ---------------------------------------------------------------------------
# Index codes
# ---------------------------------------------------------------------------

INDEX_CODES: list[str] = [
    "sh.000001",  # 上证综指
    "sh.000002",  # 上证A股
    "sh.000003",  # 上证B股
    "sz.399001",  # 深证成指
    "sz.399006",  # 创业板指
    "sh.000300",  # 沪深300
    "sh.000905",  # 中证500
    "sz.399005",  # 中小板指
]

# ---------------------------------------------------------------------------
# K-line field definitions
# ---------------------------------------------------------------------------

DAILY_KLINE_FIELDS: str = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,"
    "pcfNcfTTM,isST"
)

WEEKLY_MONTHLY_KLINE_FIELDS: str = (
    "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
)

MINUTE_KLINE_FIELDS: str = "date,time,code,open,high,low,close,volume,amount,adjustflag"

INDEX_DAILY_FIELDS: str = "date,code,open,high,low,close,preclose,volume,amount,pctChg"

INDEX_WEEKLY_MONTHLY_FIELDS: str = (
    "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
)
