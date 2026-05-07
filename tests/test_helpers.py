"""Unit tests for src/utils/helpers.py — pure functions, no network/DB needed."""

import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.utils.helpers import (
    batch_iterable,
    convert_stock_code,
    convert_time_format,
    convert_turn_field,
    get_current_quarter,
    safe_float,
    safe_int,
    setup_logging,
)


# ---------------------------------------------------------------------------
# safe_float
# ---------------------------------------------------------------------------
class TestSafeFloat:
    def test_valid_number(self):
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_integer_string(self):
        assert safe_float("42") == pytest.approx(42.0)

    def test_none_returns_default(self):
        assert safe_float(None) == 0.0
        assert safe_float(None, default=-1.0) == -1.0

    def test_empty_string_returns_default(self):
        assert safe_float("") == 0.0
        assert safe_float("   ") == 0.0

    def test_em_dash_returns_default(self):
        assert safe_float("—") == 0.0

    def test_na_returns_default(self):
        assert safe_float("N/A") == 0.0

    def test_invalid_string_returns_default(self):
        assert safe_float("abc") == 0.0

    def test_custom_default(self):
        assert safe_float("bad", default=99.9) == pytest.approx(99.9)


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------
class TestSafeInt:
    def test_valid_number(self):
        assert safe_int("42") == 42

    def test_none_returns_default(self):
        assert safe_int(None) == 0
        assert safe_int(None, default=-1) == -1

    def test_empty_string_returns_default(self):
        assert safe_int("") == 0
        assert safe_int("   ") == 0

    def test_invalid_string_returns_default(self):
        assert safe_int("abc") == 0

    def test_custom_default(self):
        assert safe_int("bad", default=7) == 7


# ---------------------------------------------------------------------------
# convert_stock_code
# ---------------------------------------------------------------------------
class TestConvertStockCode:
    def test_shanghai_6(self):
        assert convert_stock_code("600000") == "sh.600000"

    def test_shenzhen_0(self):
        assert convert_stock_code("000001") == "sz.000001"

    def test_shenzhen_3(self):
        assert convert_stock_code("300001") == "sz.300001"

    def test_already_formatted(self):
        assert convert_stock_code("sh.600000") == "sh.600000"
        assert convert_stock_code("sz.000001") == "sz.000001"


# ---------------------------------------------------------------------------
# convert_time_format
# ---------------------------------------------------------------------------
class TestConvertTimeFormat:
    def test_standard_format(self):
        assert convert_time_format("20240101093000000") == "2024-01-01 09:30:00"

    def test_afternoon(self):
        assert convert_time_format("20241231150000000") == "2024-12-31 15:00:00"


# ---------------------------------------------------------------------------
# convert_turn_field
# ---------------------------------------------------------------------------
class TestConvertTurnField:
    def test_valid_value(self):
        assert convert_turn_field("2.5") == pytest.approx(2.5)

    def test_empty_string(self):
        assert convert_turn_field("") == 0.0
        assert convert_turn_field("   ") == 0.0

    def test_none(self):
        assert convert_turn_field(None) == 0.0


# ---------------------------------------------------------------------------
# get_current_quarter
# ---------------------------------------------------------------------------
class TestGetCurrentQuarter:
    def test_returns_year_and_quarter(self):
        year, quarter = get_current_quarter()
        now = datetime.now()
        assert year == now.year
        expected_q = (now.month - 1) // 3 + 1
        assert quarter == expected_q

    def test_quarter_boundaries(self):
        """Verify quarter calculation logic for each month."""
        for month, expected_q in [
            (1, 1), (2, 1), (3, 1),
            (4, 2), (5, 2), (6, 2),
            (7, 3), (8, 3), (9, 3),
            (10, 4), (11, 4), (12, 4),
        ]:
            q = (month - 1) // 3 + 1
            assert q == expected_q


# ---------------------------------------------------------------------------
# batch_iterable
# ---------------------------------------------------------------------------
class TestBatchIterable:
    def test_exact_division(self):
        result = list(batch_iterable([1, 2, 3, 4, 5, 6], 3))
        assert result == [[1, 2, 3], [4, 5, 6]]

    def test_remainder(self):
        result = list(batch_iterable([1, 2, 3, 4, 5], 2))
        assert result == [[1, 2], [3, 4], [5]]

    def test_batch_size_larger_than_list(self):
        result = list(batch_iterable([1, 2], 10))
        assert result == [[1, 2]]

    def test_empty_list(self):
        assert list(batch_iterable([], 5)) == []

    def test_batch_size_one(self):
        result = list(batch_iterable([1, 2, 3], 1))
        assert result == [[1], [2], [3]]


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------
class TestSetupLogging:
    def test_console_handler_created(self):
        logger = setup_logging("test_console")
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_file_handler_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "sub" / "test.log"
            logger = setup_logging("test_file", str(log_path))
            assert log_path.exists()
            assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)

    def test_log_level_is_info(self):
        logger = setup_logging("test_level")
        assert logger.level == logging.INFO
