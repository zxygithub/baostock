#!/usr/bin/env python3
"""BaoStock 数据完整性校验脚本

校验数据库中已下载数据的完整性，找出所有缺失数据，生成可操作的缺失报告。

输出两份报告：
- data/integrity_report.json — 结构化数据，供后续补齐脚本读取
- data/integrity_report.txt — 可读性强的完整校验报告

用法：
    .venv/bin/python scripts/check_data_integrity.py                  # 全部检查
    .venv/bin/python scripts/check_data_integrity.py --date 2026-07-20  # 指定校验基准日
    .venv/bin/python scripts/check_data_integrity.py --level 3        # 仅检查特定层级
    .venv/bin/python scripts/check_data_integrity.py --code sh.600000 # 只检查指定股票
"""

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH, INDEX_CODES


class DataIntegrityChecker:
    """数据完整性校验器"""

    def __init__(self, db_path: Path, check_date: str | None = None, codes: set[str] | None = None):
        """
        初始化校验器
        
        Args:
            db_path: 数据库路径
            check_date: 校验基准日 (YYYY-MM-DD)，默认为今天
            codes: 只检查指定的股票代码集合，None 表示检查所有
        """
        self.db_path = db_path
        self.check_date = check_date or date.today().isoformat()
        self.codes = codes
        
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        
        self.trading_days: list[str] = []
        self.latest_trading_day: str | None = None
        self.stocks: dict[str, dict] = {}
        self.expected_cutoff: str | None = None
        
        self._load_trade_dates()
        self._load_stock_basic()
        self._compute_expected_cutoff()

    def _load_trade_dates(self):
        """加载交易日历到内存"""
        rows = self.conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE is_trading_day = 1 "
            "ORDER BY calendar_date"
        ).fetchall()
        self.trading_days = [row[0] for row in rows]
        self.latest_trading_day = self.trading_days[-1] if self.trading_days else None

    def _load_stock_basic(self):
        """加载股票基础信息到内存"""
        if self.codes:
            placeholders = ",".join("?" for _ in self.codes)
            rows = self.conn.execute(
                f"SELECT code, code_name, ipo_date, out_date, type, status "
                f"FROM stock_basic WHERE type = 1 AND code IN ({placeholders})",
                tuple(self.codes)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT code, code_name, ipo_date, out_date, type, status "
                "FROM stock_basic WHERE type = 1"
            ).fetchall()
        for row in rows:
            self.stocks[row[0]] = {
                "code": row[0],
                "code_name": row[1],
                "ipo_date": row[2],
                "out_date": row[3],
                "type": int(row[4]) if row[4] is not None else None,
                "status": int(row[5]) if row[5] is not None else None,
            }

    def _compute_expected_cutoff(self):
        """
        计算预期截止日：check_date 之前的最近一个交易日（含 check_date 当天如果是交易日）
        
        例如：
        - check_date = "2026-07-26" (周日) -> expected_cutoff = "2026-07-25" (周五)
        - check_date = "2026-07-25" (周五，交易日) -> expected_cutoff = "2026-07-25"
        """
        candidates = [d for d in self.trading_days if d <= self.check_date]
        self.expected_cutoff = max(candidates) if candidates else None

    def _effective_end(self, stock: dict) -> str:
        if stock["status"] == 1:
            return self.expected_cutoff or ""
        else:
            out_date = stock.get("out_date") or "9999-12-31"
            cutoff = self.expected_cutoff or "9999-12-31"
            return min(out_date, cutoff)

    def _expected_trading_days(self, code: str) -> int:
        """基于 stock_basic.ipo_date/out_date + trade_dates 计算预期交易日数"""
        stock = self.stocks.get(code)
        if not stock or not stock["ipo_date"]:
            return 0
        effective_end = self._effective_end(stock)
        return len([d for d in self.trading_days if stock["ipo_date"] <= d <= effective_end])

    def _get_stock_codes(self) -> list[str]:
        """获取要检查的股票代码列表"""
        if self.codes:
            return [code for code in self.codes if code in self.stocks]
        return list(self.stocks.keys())

    def check_L1_meta(self) -> dict:
        """L1: 基础表自身完整性"""
        result = {
            "status": "pass",
            "trade_dates_latest": self.latest_trading_day,
            "trade_dates_covers_cutoff": False,
            "trading_day_count": len(self.trading_days),
            "trading_day_range": f"{self.trading_days[0]} ~ {self.trading_days[-1]}" if self.trading_days else "",
            "stock_count": len(self.stocks),
            "active_stocks": sum(1 for s in self.stocks.values() if s["status"] == 1),
            "delisted_stocks": sum(1 for s in self.stocks.values() if s["status"] == 0),
            "ipo_date_missing": 0,
            "out_date_missing": 0,
            "industry_coverage": 0.0,
            "index_components": {},
            "issues": [],
        }

        if self.expected_cutoff and self.latest_trading_day:
            result["trade_dates_covers_cutoff"] = self.latest_trading_day >= self.expected_cutoff
            if not result["trade_dates_covers_cutoff"]:
                result["status"] = "fail"
                result["issues"].append(
                    f"交易日历未覆盖校验基准日: 最新交易日 {self.latest_trading_day} < 预期截止日 {self.expected_cutoff}"
                )

        if len(self.trading_days) < 8000:
            result["status"] = "warn"
            result["issues"].append(f"交易日数量不足: {len(self.trading_days)} < 8000")

        if len(self.stocks) < 4000:
            result["status"] = "warn"
            result["issues"].append(f"股票数量不足: {len(self.stocks)} < 4000")

        ipo_missing = sum(1 for s in self.stocks.values() if not s["ipo_date"])
        result["ipo_date_missing"] = ipo_missing
        if ipo_missing > len(self.stocks) * 0.05:
            result["status"] = "warn"
            result["issues"].append(f"IPO 日期缺失率过高: {ipo_missing}/{len(self.stocks)} ({ipo_missing/len(self.stocks)*100:.1f}%)")

        out_missing = sum(1 for s in self.stocks.values() if s["status"] == 0 and not s["out_date"])
        result["out_date_missing"] = out_missing
        if out_missing > 0:
            result["issues"].append(f"退市股票缺少退市日期: {out_missing} 只")

        try:
            industry_count = self.conn.execute("SELECT COUNT(DISTINCT code) FROM stock_industry").fetchone()[0]
            result["industry_coverage"] = industry_count / len(self.stocks) if self.stocks else 0
            if result["industry_coverage"] < 0.9:
                result["issues"].append(f"行业分类覆盖率不足: {result['industry_coverage']*100:.1f}%")
        except Exception:
            result["issues"].append("stock_industry 表不存在或为空")

        for index_name, table_name, expected_count in [
            ("上证50", "sz50_stocks", 50),
            ("沪深300", "hs300_stocks", 300),
            ("中证500", "zz500_stocks", 500),
        ]:
            try:
                count = self.conn.execute(f"SELECT COUNT(DISTINCT code) FROM {table_name}").fetchone()[0]
                result["index_components"][index_name] = {"count": count, "expected": expected_count}
                if count < expected_count:
                    result["issues"].append(f"{index_name}成分股数量不足: {count} < {expected_count}")
            except Exception:
                result["index_components"][index_name] = {"count": 0, "expected": expected_count}
                result["issues"].append(f"{table_name} 表不存在或为空")

        return result

    def check_L2_kline_coverage(self) -> dict:
        """L2: K线数据覆盖率"""
        result = {
            "daily": {"adjustflag_1": {}, "adjustflag_2": {}, "adjustflag_3": {}},
            "weekly": {},
            "monthly": {},
            "low_coverage_stocks": [],
        }

        codes = self._get_stock_codes()
        if not codes:
            return result

        for adjustflag in [1, 2, 3]:
            stats = {"fully_covered": 0, "above_95": 0, "between_80_95": 0, "below_80": 0, "zero_data": 0}
            
            for code in codes:
                stock = self.stocks[code]
                if not stock["ipo_date"]:
                    continue
                
                expected = self._expected_trading_days(code)
                if expected == 0:
                    continue

                row = self.conn.execute(
                    "SELECT COUNT(DISTINCT date) FROM all_stock_daily "
                    "WHERE code = ? AND adjustflag = ?",
                    (code, adjustflag)
                ).fetchone()
                actual = row[0] if row else 0

                if actual == 0:
                    stats["zero_data"] += 1
                    result["low_coverage_stocks"].append({
                        "code": code,
                        "code_name": stock["code_name"],
                        "ipo_date": stock["ipo_date"],
                        "out_date": stock["out_date"],
                        "status": stock["status"],
                        "adjustflag": adjustflag,
                        "expected_days": expected,
                        "actual_days": 0,
                        "coverage": 0.0,
                    })
                else:
                    coverage = actual / expected
                    if coverage >= 1.0:
                        stats["fully_covered"] += 1
                    elif coverage >= 0.95:
                        stats["above_95"] += 1
                    elif coverage >= 0.80:
                        stats["between_80_95"] += 1
                        result["low_coverage_stocks"].append({
                            "code": code,
                            "code_name": stock["code_name"],
                            "ipo_date": stock["ipo_date"],
                            "out_date": stock["out_date"],
                            "status": stock["status"],
                            "adjustflag": adjustflag,
                            "expected_days": expected,
                            "actual_days": actual,
                            "coverage": coverage,
                        })
                    else:
                        stats["below_80"] += 1
                        result["low_coverage_stocks"].append({
                            "code": code,
                            "code_name": stock["code_name"],
                            "ipo_date": stock["ipo_date"],
                            "out_date": stock["out_date"],
                            "status": stock["status"],
                            "adjustflag": adjustflag,
                            "expected_days": expected,
                            "actual_days": actual,
                            "coverage": coverage,
                        })

            result["daily"][f"adjustflag_{adjustflag}"] = stats

        for kline_type, table_name in [("weekly", "all_stock_weekly"), ("monthly", "all_stock_monthly")]:
            stats = {"fully_covered": 0, "above_95": 0, "between_80_95": 0, "below_80": 0, "zero_data": 0}
            result[kline_type] = stats

        return result

    def check_L3_kline_gaps(self) -> dict:
        """L3: K线日期连续性（空洞检测）"""
        result = {
            "daily": [],
            "weekly": [],
            "monthly": [],
            "stocks_with_gaps": 0,
            "total_missing_days": 0,
            "latest_cutoff_check": {"active_stocks_behind": 0, "delisted_stocks_behind": 0},
        }

        codes = self._get_stock_codes()
        if not codes or not self.expected_cutoff:
            return result

        for code in codes:
            stock = self.stocks[code]
            if not stock["ipo_date"]:
                continue

            effective_end = self._effective_end(stock)
            
            expected_dates = set(d for d in self.trading_days if stock["ipo_date"] <= d <= effective_end)
            
            rows = self.conn.execute(
                "SELECT DISTINCT date FROM all_stock_daily WHERE code = ? AND adjustflag = 3",
                (code,)
            ).fetchall()
            actual_dates = set(row[0] for row in rows)

            missing_dates = sorted(expected_dates - actual_dates)

            if missing_dates:
                result["stocks_with_gaps"] += 1
                result["total_missing_days"] += len(missing_dates)
                
                latest_row = self.conn.execute(
                    "SELECT MAX(date) FROM all_stock_daily WHERE code = ? AND adjustflag = 3",
                    (code,)
                ).fetchone()
                latest_date = latest_row[0] if latest_row and latest_row[0] else None

                result["daily"].append({
                    "code": code,
                    "code_name": stock["code_name"],
                    "ipo_date": stock["ipo_date"],
                    "out_date": stock["out_date"],
                    "status": stock["status"],
                    "adjustflag": 3,
                    "expected_days": len(expected_dates),
                    "actual_days": len(actual_dates),
                    "latest_data_date": latest_date,
                    "missing_recent_days": 0,
                    "missing_dates": missing_dates,
                })

        for code in codes:
            stock = self.stocks[code]
            if not stock["ipo_date"]:
                continue

            latest_row = self.conn.execute(
                "SELECT MAX(date) FROM all_stock_daily WHERE code = ? AND adjustflag = 3",
                (code,)
            ).fetchone()
            latest_date = latest_row[0] if latest_row and latest_row[0] else None

            if not latest_date:
                continue

            effective_end = self._effective_end(stock)
            
            missing_recent = len([d for d in self.trading_days if latest_date < d <= effective_end])
            
            for gap in result["daily"]:
                if gap["code"] == code:
                    gap["missing_recent_days"] = missing_recent
                    break

            if stock["status"] == 1 and latest_date < self.expected_cutoff:
                result["latest_cutoff_check"]["active_stocks_behind"] += 1
            elif stock["status"] == 0 and latest_date < effective_end:
                result["latest_cutoff_check"]["delisted_stocks_behind"] += 1

        return result

    def check_L4_financial(self) -> dict:
        """L4: 财务数据覆盖率"""
        result = {
            "tables": {},
            "cross_table_inconsistency": [],
        }

        codes = self._get_stock_codes()
        if not codes:
            return result

        current_year = datetime.now().year
        current_month = datetime.now().month
        current_quarter = (current_month - 1) // 3 + 1

        financial_tables = [
            "profit_data", "operation_data", "growth_data",
            "balance_data", "cash_flow_data", "dupont_data"
        ]

        for table_name in financial_tables:
            table_result = {"expected": 0, "actual": 0, "missing": []}
            
            for code in codes:
                stock = self.stocks[code]
                if not stock["ipo_date"]:
                    continue

                ipo_year = int(stock["ipo_date"][:4]) if stock["ipo_date"] else 2007
                start_year = max(2007, ipo_year)
                
                out_date = stock.get("out_date") or "9999-12-31"
                end_year = min(current_year, int(out_date[:4]) if out_date[:4].isdigit() else current_year)

                for year in range(start_year, end_year + 1):
                    for quarter in [1, 2, 3, 4]:
                        if year == current_year and quarter in (current_quarter, current_quarter - 1):
                            continue
                        
                        if table_name == "growth_data" and year == ipo_year:
                            continue

                        quarter_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[quarter]
                        period_end = f"{year}-{quarter_end}"
                        if stock.get("out_date") and stock["out_date"] < period_end:
                            continue

                        table_result["expected"] += 1

                        row = self.conn.execute(
                            f"SELECT COUNT(*) FROM {table_name} WHERE code = ? AND year = ? AND quarter = ?",
                            (code, year, quarter)
                        ).fetchone()
                        if row and row[0] > 0:
                            table_result["actual"] += 1
                        else:
                            table_result["missing"].append({
                                "code": code,
                                "code_name": stock["code_name"],
                                "year": year,
                                "quarter": quarter,
                            })

            result["tables"][table_name] = table_result

        return result

    def check_L5_dividend(self) -> dict:
        """L5: 分红与复权因子"""
        result = {
            "dividend_count": 0,
            "adjust_factor_count": 0,
            "missing_dividend": [],
            "missing_adjust_factor": [],
        }

        row = self.conn.execute("SELECT COUNT(*) FROM dividend").fetchone()
        result["dividend_count"] = row[0] if row else 0

        row = self.conn.execute("SELECT COUNT(*) FROM adjust_factor").fetchone()
        result["adjust_factor_count"] = row[0] if row else 0

        rows = self.conn.execute("""
            SELECT d.code, d.divid_operate_date, d.year, d.year_type
            FROM dividend d
            LEFT JOIN adjust_factor af ON af.code = d.code AND af.divid_operate_date = d.divid_operate_date
            WHERE d.divid_operate_date != '9999-01-01'
              AND af.code IS NULL
        """).fetchall()

        for row in rows:
            result["missing_adjust_factor"].append({
                "code": row[0],
                "divid_operate_date": row[1],
                "year": row[2],
                "year_type": row[3],
            })

        return result

    def check_L6_index(self) -> dict:
        """L6: 指数K线"""
        result = {
            "daily_gaps": [],
            "weekly_gaps": [],
            "monthly_gaps": [],
        }

        if not self.expected_cutoff:
            return result

        # 每个指数真实有数据的最早日期。晚于 2006-01-01 发布的指数若仍按
        # 2006 起算，会把发布前的交易日误报为空洞（如创业板指 2010-06-01 发布）。
        index_data_start = {code: "2006-01-01" for code in INDEX_CODES}
        index_data_start["sz.399006"] = "2010-06-01"  # 创业板指发布日

        for index_code in INDEX_CODES:
            start = index_data_start.get(index_code, "2006-01-01")
            expected_dates = set(d for d in self.trading_days if start <= d <= self.expected_cutoff)

            rows = self.conn.execute(
                "SELECT DISTINCT date FROM index_daily WHERE code = ?",
                (index_code,)
            ).fetchall()
            actual_dates = set(row[0] for row in rows)

            missing_dates = sorted(expected_dates - actual_dates)

            if missing_dates:
                latest_row = self.conn.execute(
                    "SELECT MAX(date) FROM index_daily WHERE code = ?",
                    (index_code,)
                ).fetchone()
                latest_date = latest_row[0] if latest_row and latest_row[0] else None

                missing_recent = len([d for d in self.trading_days if latest_date and latest_date < d <= self.expected_cutoff])

                result["daily_gaps"].append({
                    "code": index_code,
                    "latest_data_date": latest_date,
                    "expected_cutoff": self.expected_cutoff,
                    "missing_recent_days": missing_recent,
                    "missing_dates": missing_dates,
                })

        return result

    def check_L7_macro(self) -> dict:
        """L7: 宏观数据"""
        result = {"tables": {}, "issues": []}

        macro_tables = [
            ("deposit_rate", 20, "3 years"),
            ("loan_rate", 20, "3 years"),
            ("reserve_ratio", 30, None),
            ("money_supply_month", 200, "6 months"),
            ("money_supply_year", 20, None),
        ]

        for table_name, min_rows, recency in macro_tables:
            try:
                row = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                count = row[0] if row else 0
                
                table_result = {"count": count, "min_expected": min_rows, "status": "pass"}
                
                if count < min_rows:
                    table_result["status"] = "warn"
                    result["issues"].append(f"{table_name} 行数不足: {count} < {min_rows}")

                result["tables"][table_name] = table_result
            except Exception as e:
                result["tables"][table_name] = {"count": 0, "min_expected": min_rows, "status": "error"}
                result["issues"].append(f"{table_name} 表不存在或查询失败: {e}")

        return result

    def check_L8_quality(self) -> dict:
        """L8: 数据质量"""
        result = {
            "null_close": 0,
            "negative_price": 0,
            "high_low_inverted": 0,
            "negative_volume": 0,
            "abnormal_pct_chg": [],
        }

        where_clause = "WHERE"
        params: tuple = ()
        if self.codes:
            placeholders = ",".join("?" for _ in self.codes)
            where_clause = f"WHERE code IN ({placeholders}) AND"
            params = tuple(self.codes)

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM all_stock_daily {where_clause} close IS NULL", params
        ).fetchone()
        result["null_close"] = row[0] if row else 0

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM all_stock_daily {where_clause} close <= 0 AND adjustflag = 3", params
        ).fetchone()
        result["negative_price"] = row[0] if row else 0

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM all_stock_daily {where_clause} high < low", params
        ).fetchone()
        result["high_low_inverted"] = row[0] if row else 0

        row = self.conn.execute(
            f"SELECT COUNT(*) FROM all_stock_daily {where_clause} volume < 0", params
        ).fetchone()
        result["negative_volume"] = row[0] if row else 0

        rows = self.conn.execute(
            f"SELECT code, date, pct_chg FROM all_stock_daily {where_clause} ABS(pct_chg) > 22 LIMIT 100", params
        ).fetchall()
        for row in rows:
            result["abnormal_pct_chg"].append({
                "code": row[0],
                "date": row[1],
                "pct_chg": row[2],
            })

        return result

    def run_all(self, levels: list[int] | None = None) -> dict:
        """运行所有检查，返回完整 JSON 报告"""
        report = {
            "report_time": datetime.now().isoformat(timespec="seconds"),
            "check_date": self.check_date,
            "expected_cutoff": self.expected_cutoff,
            "expected_cutoff_note": "check_date 之前的最近交易日（含 check_date 当天如果是交易日）",
            "db_path": str(self.db_path),
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 2) if self.db_path.exists() else 0,
            "summary": {
                "total_stocks": len(self.stocks),
                "active_stocks": sum(1 for s in self.stocks.values() if s["status"] == 1),
                "delisted_stocks": sum(1 for s in self.stocks.values() if s["status"] == 0),
                "trading_days_covered": f"{self.trading_days[0]} ~ {self.trading_days[-1]}" if self.trading_days else "",
                "overall_completeness": 0.0,
            },
        }

        if not levels or 1 in levels:
            print("  [1/8] L1: 基础表完整性...", flush=True)
            report["L1_meta"] = self.check_L1_meta()
        if not levels or 2 in levels:
            print("  [2/8] L2: K线覆盖率...", flush=True)
            report["L2_kline_coverage"] = self.check_L2_kline_coverage()
        if not levels or 3 in levels:
            print("  [3/8] L3: K线日期连续性...", flush=True)
            report["L3_kline_gaps"] = self.check_L3_kline_gaps()
        if not levels or 4 in levels:
            print("  [4/8] L4: 财务数据覆盖率...", flush=True)
            report["L4_financial"] = self.check_L4_financial()
        if not levels or 5 in levels:
            print("  [5/8] L5: 分红与复权因子...", flush=True)
            report["L5_dividend"] = self.check_L5_dividend()
        if not levels or 6 in levels:
            print("  [6/8] L6: 指数K线空洞...", flush=True)
            report["L6_index"] = self.check_L6_index()
        if not levels or 7 in levels:
            print("  [7/8] L7: 宏观数据...", flush=True)
            report["L7_macro"] = self.check_L7_macro()
        if not levels or 8 in levels:
            print("  [8/8] L8: 数据质量...", flush=True)
            report["L8_quality"] = self.check_L8_quality()

        report["summary"]["overall_completeness"] = self._calculate_completeness(report)

        return report

    def _calculate_completeness(self, report: dict) -> float:
        if "L2_kline_coverage" in report:
            daily = report["L2_kline_coverage"]["daily"]
            adj3 = daily.get("adjustflag_3", {})
            total = adj3.get("fully_covered", 0) + adj3.get("above_95", 0) + adj3.get("between_80_95", 0) + adj3.get("below_80", 0) + adj3.get("zero_data", 0)
            if total > 0:
                covered = adj3.get("fully_covered", 0) + adj3.get("above_95", 0) * 0.95 + adj3.get("between_80_95", 0) * 0.85
                return round(covered / total, 3)
        return 0.0

    def save_json_report(self, report: dict, output_path: str):
        """保存 JSON 报告到文件"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def generate_text_report(self, json_report: dict) -> str:
        """生成文字报告"""
        lines = []
        
        lines.append("=" * 80)
        lines.append("                    BaoStock 数据完整性校验报告")
        lines.append("=" * 80)
        lines.append(f"校验时间:     {json_report['report_time']}")
        lines.append(f"校验基准日:   {json_report['check_date']}")
        lines.append(f"预期截止日:   {json_report['expected_cutoff']}")
        lines.append(f"数据库路径:   {json_report['db_path']}")
        lines.append(f"数据库大小:   {json_report['db_size_mb']} MB")
        lines.append("")

        lines.append("=" * 80)
        lines.append("一、汇总说明")
        lines.append("=" * 80)
        lines.append("")
        summary = json_report["summary"]
        lines.append(f"【整体完整度】{summary['overall_completeness']*100:.1f}%")
        lines.append("")
        lines.append("【数据概况】")
        lines.append(f"  • 股票总数:     {summary['total_stocks']:,} 只")
        lines.append(f"    - 上市中:     {summary['active_stocks']:,} 只")
        lines.append(f"    - 已退市:     {summary['delisted_stocks']:,} 只")
        lines.append(f"  • 交易日历:     {summary['trading_days_covered']}")
        lines.append("")

        lines.append("【各层校验结果】")
        lines.append("  " + "-" * 76)
        lines.append("  │ 层级 │ 检查项              │ 状态  │ 问题数                            │")
        lines.append("  " + "-" * 76)
        
        level_status = []
        if "L1_meta" in json_report:
            l1 = json_report["L1_meta"]
            status = "✅ 通过" if l1["status"] == "pass" else "⚠️ 警告" if l1["status"] == "warn" else "❌ 失败"
            level_status.append(("L1", "基础表完整性", status, f"{len(l1['issues'])} 个问题"))
        
        if "L3_kline_gaps" in json_report:
            l3 = json_report["L3_kline_gaps"]
            gap_count = l3["stocks_with_gaps"]
            status = "✅ 通过" if gap_count == 0 else "⚠️ 警告"
            level_status.append(("L3", "K线日期连续性", status, f"{gap_count} 只股票存在空洞"))

        for level, name, status, issue in level_status:
            lines.append(f"  │ {level:<4} │ {name:<18} │ {status:<6} │ {issue:<35} │")
        
        lines.append("  " + "-" * 76)
        lines.append("")

        if "L1_meta" in json_report:
            lines.extend(self._format_L1_text(json_report["L1_meta"]))
        if "L2_kline_coverage" in json_report:
            lines.extend(self._format_L2_text(json_report["L2_kline_coverage"]))
        if "L3_kline_gaps" in json_report:
            lines.extend(self._format_L3_text(json_report["L3_kline_gaps"]))
        if "L4_financial" in json_report:
            lines.extend(self._format_L4_text(json_report["L4_financial"]))
        if "L5_dividend" in json_report:
            lines.extend(self._format_L5_text(json_report["L5_dividend"]))
        if "L6_index" in json_report:
            lines.extend(self._format_L6_text(json_report["L6_index"]))
        if "L7_macro" in json_report:
            lines.extend(self._format_L7_text(json_report["L7_macro"]))
        if "L8_quality" in json_report:
            lines.extend(self._format_L8_text(json_report["L8_quality"]))

        lines.append("=" * 80)
        lines.append("总结")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"数据完整度: {summary['overall_completeness']*100:.1f}%")
        lines.append("")
        lines.append("=" * 80)
        lines.append("                              报告结束")
        lines.append("=" * 80)

        return "\n".join(lines)

    def _format_L1_text(self, l1: dict) -> list[str]:
        """格式化 L1 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("二、基础表完整性 (L1)")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"【交易日历】")
        lines.append(f"  • 覆盖范围:     {l1['trading_day_range']}")
        lines.append(f"  • 交易日总数:   {l1['trading_day_count']:,} 天")
        lines.append(f"  • 最新交易日:   {l1['trade_dates_latest']}")
        lines.append(f"  • 覆盖校验基准日: {'✅ 是' if l1['trade_dates_covers_cutoff'] else '❌ 否'}")
        lines.append("")
        lines.append(f"【股票基础信息】")
        lines.append(f"  • 股票总数:     {l1['stock_count']:,} 只")
        lines.append(f"    - 上市中:     {l1['active_stocks']:,} 只")
        lines.append(f"    - 已退市:     {l1['delisted_stocks']:,} 只")
        lines.append(f"  • IPO日期缺失:  {l1['ipo_date_missing']} 只")
        lines.append(f"  • 退市日期缺失: {l1['out_date_missing']} 只")
        lines.append("")
        if l1["issues"]:
            lines.append("【问题】")
            for issue in l1["issues"]:
                lines.append(f"  ⚠️ {issue}")
            lines.append("")
        return lines

    def _format_L2_text(self, l2: dict) -> list[str]:
        """格式化 L2 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("三、K线数据覆盖率 (L2)")
        lines.append("=" * 80)
        lines.append("")
        lines.append("【日K线覆盖率】")
        for adj in ["adjustflag_1", "adjustflag_2", "adjustflag_3"]:
            stats = l2["daily"].get(adj, {})
            lines.append(f"  {adj}: 完全覆盖 {stats.get('fully_covered', 0)}, >=95% {stats.get('above_95', 0)}, <80% {stats.get('below_80', 0)}")
        lines.append("")
        return lines

    def _format_L3_text(self, l3: dict) -> list[str]:
        """格式化 L3 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("四、K线日期连续性 (L3)")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"【空洞统计】")
        lines.append(f"  • 存在空洞的股票: {l3['stocks_with_gaps']} 只")
        lines.append(f"  • 总缺失交易日:   {l3['total_missing_days']:,} 天")
        lines.append("")
        if l3["daily"]:
            lines.append("【缺失最严重的股票 (前10)】")
            sorted_gaps = sorted(l3["daily"], key=lambda x: len(x["missing_dates"]), reverse=True)[:10]
            for gap in sorted_gaps:
                lines.append(f"  • {gap['code']} ({gap['code_name']}): 缺失 {len(gap['missing_dates'])} 天")
            lines.append("")
        return lines

    def _format_L4_text(self, l4: dict) -> list[str]:
        """格式化 L4 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("五、财务数据覆盖率 (L4)")
        lines.append("=" * 80)
        lines.append("")
        for table_name, data in l4.get("tables", {}).items():
            missing_count = len(data.get("missing", []))
            lines.append(f"  {table_name}: 预期 {data['expected']:,}, 实际 {data['actual']:,}, 缺失 {missing_count}")
        lines.append("")
        return lines

    def _format_L5_text(self, l5: dict) -> list[str]:
        """格式化 L5 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("六、分红与复权因子 (L5)")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"  • 分红数据: {l5['dividend_count']:,} 条")
        lines.append(f"  • 复权因子: {l5['adjust_factor_count']:,} 条")
        lines.append(f"  • 缺失复权因子: {len(l5['missing_adjust_factor'])} 条")
        lines.append("")
        return lines

    def _format_L6_text(self, l6: dict) -> list[str]:
        """格式化 L6 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("七、指数K线 (L6)")
        lines.append("=" * 80)
        lines.append("")
        if l6["daily_gaps"]:
            lines.append("【存在空洞的指数】")
            for gap in l6["daily_gaps"]:
                lines.append(f"  • {gap['code']}: 缺失 {len(gap['missing_dates'])} 天")
        else:
            lines.append("  ✅ 所有指数数据完整")
        lines.append("")
        return lines

    def _format_L7_text(self, l7: dict) -> list[str]:
        """格式化 L7 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("八、宏观数据 (L7)")
        lines.append("=" * 80)
        lines.append("")
        for table_name, data in l7.get("tables", {}).items():
            status = "✅" if data["status"] == "pass" else "⚠️"
            lines.append(f"  {status} {table_name}: {data['count']} 条")
        if l7["issues"]:
            lines.append("")
            lines.append("【问题】")
            for issue in l7["issues"]:
                lines.append(f"  ⚠️ {issue}")
        lines.append("")
        return lines

    def _format_L8_text(self, l8: dict) -> list[str]:
        """格式化 L8 文字报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("九、数据质量 (L8)")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"  • 价格为 NULL:      {l8['null_close']}")
        lines.append(f"  • 价格 <= 0:        {l8['negative_price']}")
        lines.append(f"  • 高低价倒挂:       {l8['high_low_inverted']}")
        lines.append(f"  • 成交量为负:       {l8['negative_volume']}")
        lines.append(f"  • 涨跌幅异常 (>22%): {len(l8['abnormal_pct_chg'])} 条")
        lines.append("")
        return lines

    def save_text_report(self, text_report: str, output_path: str):
        """保存文字报告到文件"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text_report)

    def save_reports(self, json_report: dict, base_path: str):
        """同时保存 JSON 和文字报告"""
        self.save_json_report(json_report, f"{base_path}.json")
        text_report = self.generate_text_report(json_report)
        self.save_text_report(text_report, f"{base_path}.txt")
        return text_report

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def main():
    parser = argparse.ArgumentParser(description="BaoStock 数据完整性校验")
    parser.add_argument("--date", type=str, help="校验基准日 (YYYY-MM-DD)，默认为今天")
    parser.add_argument("--level", type=int, action="append", help="仅检查特定层级 (1-8)，可多次指定")
    parser.add_argument("--code", type=str, help="只检查指定股票代码")
    parser.add_argument("--output", type=str, default="data/integrity_report", help="输出文件基础路径")
    parser.add_argument("--json-only", action="store_true", help="仅生成 JSON 报告")
    parser.add_argument("--text-only", action="store_true", help="仅生成文字报告")
    
    args = parser.parse_args()

    codes = {args.code} if args.code else None

    print(f"开始数据完整性校验...")
    print(f"  校验基准日: {args.date or date.today().isoformat()}")
    print(f"  数据库: {DB_PATH}")
    print()

    with DataIntegrityChecker(DB_PATH, check_date=args.date, codes=codes) as checker:
        report = checker.run_all(levels=args.level)

        if args.json_only:
            checker.save_json_report(report, f"{args.output}.json")
            print(f"✅ JSON 报告已保存: {args.output}.json")
        elif args.text_only:
            text_report = checker.generate_text_report(report)
            checker.save_text_report(text_report, f"{args.output}.txt")
            print(f"✅ 文字报告已保存: {args.output}.txt")
        else:
            checker.save_reports(report, args.output)
            print(f"✅ JSON 报告已保存: {args.output}.json")
            print(f"✅ 文字报告已保存: {args.output}.txt")

        print()
        print("=" * 60)
        print("校验摘要")
        print("=" * 60)
        print(f"整体完整度: {report['summary']['overall_completeness']*100:.1f}%")
        print(f"股票总数:   {report['summary']['total_stocks']:,}")
        
        if "L3_kline_gaps" in report:
            l3 = report["L3_kline_gaps"]
            print(f"K线空洞:    {l3['stocks_with_gaps']} 只股票, {l3['total_missing_days']:,} 天缺失")
        
        if "L1_meta" in report and report["L1_meta"]["issues"]:
            print()
            print("⚠️ 发现的问题:")
            for issue in report["L1_meta"]["issues"]:
                print(f"  • {issue}")


if __name__ == "__main__":
    main()
