"""Unified configuration loader for the BaoStock data download project.

This module provides functions to load configuration from config.yaml
and provides convenient accessors for different config sections.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("baostock")

# Default config path
DEFAULT_CONFIG_PATH: Path = Path(__file__).parent.parent / "config.yaml"

# Module-level config cache to avoid repeated file I/O
_config_cache: dict[str, Any] | None = None


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from config.yaml file.

    Args:
        config_path: Optional custom path to config file.

    Returns:
        Configuration dictionary. Returns empty dict if file doesn't exist.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.warning(f"Config file not found at {path}, using defaults")
        return {}

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
            _config_cache = config if config else {}
            return _config_cache
    except Exception as e:
        logger.error(f"Failed to load config from {path}: {e}")
        return {}


def get_nested_value(
    config: dict[str, Any], keys: list[str], default: Any = None
) -> Any:
    """Safely get a nested value from config dictionary.

    Args:
        config: Configuration dictionary.
        keys: List of keys to traverse (e.g., ["download", "kline", "daily"]).
        default: Default value if key path doesn't exist.

    Returns:
        The value at the key path, or default if not found.
    """
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


# ============================================================================
# Convenience functions for common config access
# ============================================================================


def get_api_config() -> dict[str, Any]:
    """Get API configuration."""
    config = load_config()
    return config.get("api", {})


def get_download_config() -> dict[str, Any]:
    """Get download configuration."""
    config = load_config()
    return config.get("download", {})


def get_stocks_config() -> dict[str, Any]:
    """Get stocks configuration."""
    config = load_config()
    return config.get("stocks", {})


def get_batch_size() -> int:
    """Get batch size for downloads."""
    return get_stocks_config().get("batch_size", 200)


def get_batch_sleep() -> float:
    """Get sleep time between batches."""
    return get_stocks_config().get("batch_sleep", 2)


def get_socket_timeout() -> int:
    """Get socket timeout for API calls."""
    return get_api_config().get("socket_timeout", 30)


def get_daily_request_limit() -> int:
    """Get daily API request limit."""
    return get_api_config().get("daily_request_limit", 95000)


def is_download_enabled(category: str, subcategory: str | None = None) -> bool:
    """Check if a download category is enabled.

    Args:
        category: Main category (e.g., "macro", "financial", "kline").
        subcategory: Optional subcategory (e.g., "daily", "weekly").

    Returns:
        True if enabled, False otherwise.
    """
    if subcategory:
        return get_nested_value(
            get_download_config(), [category, subcategory, "enabled"], True
        )
    return get_nested_value(get_download_config(), [category, "enabled"], True)


def get_kline_start_date(freq: str) -> str:
    """Get start date for K-line downloads.

    Args:
        freq: Frequency ("daily", "weekly", "monthly", "minute").

    Returns:
        Start date string in YYYY-MM-DD format.
    """
    defaults = {
        "daily": "1990-12-19",
        "weekly": "1990-12-19",
        "monthly": "1990-12-19",
        "minute": "2019-01-02",
    }
    return get_nested_value(
        get_download_config(), ["kline", freq, "start_date"], defaults.get(freq)
    )


def get_financial_start_year() -> int:
    """Get start year for financial data downloads."""
    return get_nested_value(get_download_config(), ["financial", "start_year"], 2007)


def get_reports_start_date() -> str:
    """Get start date for report downloads."""
    return get_nested_value(
        get_download_config(), ["reports", "start_date"], "2003-01-01"
    )


def get_index_kline_start_date() -> str:
    """Get start date for index K-line downloads."""
    return get_nested_value(
        get_download_config(), ["index_kline", "start_date"], "2006-01-01"
    )


def get_minute_frequencies() -> list[str]:
    """Get minute K-line frequencies."""
    return get_nested_value(
        get_download_config(),
        ["kline", "minute", "frequencies"],
        ["5", "15", "30", "60"],
    )
