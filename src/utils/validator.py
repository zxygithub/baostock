import sqlite3
from pathlib import Path


class DataValidator:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(str(db_path))

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def check_all(self) -> list[str]:
        issues = []
        issues.extend(self._check_trade_dates())
        issues.extend(self._check_stock_basic())
        issues.extend(self._check_kline_gaps())
        issues.extend(self._check_financial_coverage())
        issues.extend(self._check_table_counts())
        return issues

    def _check_trade_dates(self) -> list[str]:
        issues = []
        row = self.conn.execute(
            "SELECT COUNT(*) FROM trade_dates WHERE is_trading_day = 1"
        ).fetchone()
        if not row or row[0] < 8000:
            issues.append(
                f"Trade dates: only {row[0] if row else 0} trading days (expected 8000+)"
            )
        return issues

    def _check_stock_basic(self) -> list[str]:
        issues = []
        row = self.conn.execute(
            "SELECT COUNT(*) FROM stock_basic WHERE type=1"
        ).fetchone()
        if not row or row[0] < 1000:
            issues.append(
                f"Stock basic: only {row[0] if row else 0} stocks (expected 1000+)"
            )
        return issues

    def _check_kline_gaps(self) -> list[str]:
        issues = []
        cursor = self.conn.execute("""
            SELECT code, COUNT(*) as days
            FROM all_stock_daily
            WHERE adjustflag = 3
            GROUP BY code
            HAVING days < 100
        """)
        for code, days in cursor:
            issues.append(f"{code}: only {days} days of daily K-line data")
        return issues

    def _check_financial_coverage(self) -> list[str]:
        issues = []
        tables = [
            "profit_data",
            "operation_data",
            "growth_data",
            "balance_data",
            "cash_flow_data",
            "dupont_data",
        ]
        for table in tables:
            try:
                row = self.conn.execute(
                    f"SELECT COUNT(DISTINCT code) FROM {table}"
                ).fetchone()
                if row and row[0] < 10:
                    issues.append(f"{table}: only {row[0]} stocks covered")
            except sqlite3.OperationalError:
                issues.append(f"{table}: table empty or missing")
        return issues

    def _check_table_counts(self) -> list[str]:
        issues = []
        expected_min = {
            "trade_dates": 10000,
            "stock_basic": 5000,
            "stock_industry": 3000,
            "deposit_rate": 10,
            "loan_rate": 10,
            "reserve_ratio": 20,
            "money_supply_month": 100,
        }
        for table, min_rows in expected_min.items():
            try:
                row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                if row and row[0] < min_rows:
                    issues.append(f"{table}: {row[0]} rows (expected {min_rows}+)")
            except sqlite3.OperationalError:
                issues.append(f"{table}: missing")
        return issues

    def summary(self) -> dict[str, int]:
        result = {}
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        for (table,) in cursor:
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            result[table] = count
        return result
