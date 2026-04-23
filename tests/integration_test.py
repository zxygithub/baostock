#!/usr/bin/env python3
"""集成测试脚本：验证所有数据下载模块的端到端功能。

测试策略：
1. 使用极少量股票（仅2只）
2. 限制日期范围，减少数据量
3. 每个模块下载少量数据（最多50条）
4. 验证表结构、数据写入和配置加载
5. 测试完成后清理测试数据

使用方式：
    .venv/bin/python tests/integration_test.py

测试覆盖：
- 数据库初始化和表结构创建
- 配置系统（config.yaml + config_loader）
- 元数据下载（交易日历、股票信息、行业分类）
- 宏观经济数据（利率、准备金率、货币供应量）
- 指数成分股（上证50、沪深300、中证500）
- 指数K线（日/周/月）
- 股票K线（日/周/月，仅不复权）
- 财务数据（6类季频指标）
- 公司报告（业绩快报、业绩预告）
- 分红和复权因子数据
"""

import sys
import sqlite3
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.config_loader import (
    load_config,
    get_batch_size,
    get_batch_sleep,
    get_kline_start_date,
    get_financial_start_year,
    get_reports_start_date,
    get_index_kline_start_date,
    is_download_enabled,
)
from src.db_manager import DBManager
from src.utils.helpers import setup_logging, fetch_all_rows
from src.downloaders.meta_downloader import MetaDownloader
from src.downloaders.macro_downloader import MacroDownloader
from src.downloaders.component_downloader import ComponentDownloader
from src.downloaders.index_downloader import IndexDownloader
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.report_downloader import ReportDownloader
from src.downloaders.dividend_downloader import DividendDownloader

logger = setup_logging("integration_test")

# ============================================================================
# 测试配置：限制数据量
# ============================================================================
TEST_CODES = ["sh.600000", "sz.000001"]  # 浦发银行 + 平安银行
TEST_START_DATE = "2024-01-01"
TEST_END_DATE = "2024-03-31"  # 仅3个月数据
TEST_FINANCIAL_YEAR = 2024
MAX_ROWS_PER_TABLE = 50  # 每个表最多保留50条数据

# 测试数据库路径（使用独立的测试数据库）
TEST_DB_PATH = DB_PATH.parent / "test_baostock.db"


class IntegrationTestRunner:
    """集成测试执行器。"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.warnings = []

    def run_all_tests(self):
        """执行所有集成测试。"""
        logger.info("=" * 60)
        logger.info("🚀 BaoStock 数据下载集成测试")
        logger.info("=" * 60)
        logger.info(f"测试数据库: {TEST_DB_PATH}")
        logger.info(f"测试股票: {', '.join(TEST_CODES)}")
        logger.info(f"日期范围: {TEST_START_DATE} ~ {TEST_END_DATE}")
        logger.info(f"每表最大行数: {MAX_ROWS_PER_TABLE}")
        logger.info("")

        # 验证配置系统
        self.test_00_config_loading()

        # 初始化测试数据库
        self.test_01_db_init()

        # 各数据下载测试
        self.test_02_metadata()
        self.test_03_macro_data()
        self.test_04_index_components()
        self.test_05_index_kline()
        self.test_06_stock_kline()
        self.test_07_financial_data()
        self.test_08_reports()
        self.test_09_dividend_data()

        # 验证数据完整性
        self.test_10_data_integrity()

        # 打印总结
        self.print_summary()

    # ========================================================================
    # 测试用例
    # ========================================================================

    def test_00_config_loading(self):
        """测试 00：配置系统加载"""
        test_name = "配置系统加载"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 00: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            # 测试配置加载
            config = load_config()
            assert config, "配置加载失败"
            assert "api" in config, "缺少 api 配置"
            assert "download" in config, "缺少 download 配置"
            assert "stocks" in config, "缺少 stocks 配置"

            # 测试配置读取函数
            batch_size = get_batch_size()
            batch_sleep = get_batch_sleep()
            assert isinstance(batch_size, int) and batch_size > 0
            assert isinstance(batch_sleep, (int, float)) and batch_sleep >= 0

            # 测试日期配置
            daily_start = get_kline_start_date("daily")
            fin_year = get_financial_start_year()
            assert daily_start, "日线起始日期为空"
            assert isinstance(fin_year, int) and fin_year > 2000

            # 测试下载开关
            assert is_download_enabled("macro") is True
            assert is_download_enabled("kline", "daily") is True

            logger.info(f"  ✅ batch_size: {batch_size}")
            logger.info(f"  ✅ batch_sleep: {batch_sleep}")
            logger.info(f"  ✅ daily_start: {daily_start}")
            logger.info(f"  ✅ financial_start_year: {fin_year}")
            logger.info(f"  ✅ macro enabled: {is_download_enabled('macro')}")
            logger.info(f"  ✅ kline daily enabled: {is_download_enabled('kline', 'daily')}")
            logger.info(f"  ✅ 配置系统测试通过")

            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_01_db_init(self):
        """测试 01：数据库初始化"""
        test_name = "数据库初始化"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 01: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            # 清理旧测试数据库
            if TEST_DB_PATH.exists():
                TEST_DB_PATH.unlink()
                logger.info(f"  已删除旧测试数据库: {TEST_DB_PATH}")

            # 初始化数据库
            with DBManager(str(TEST_DB_PATH)) as db:
                db.init_all_tables()
                db.migrate_schema()

            # 验证表数量
            conn = sqlite3.connect(str(TEST_DB_PATH))
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()

            expected_tables = {
                "trade_dates", "stock_basic", "stock_industry", "all_stock",
                "all_stock_daily", "all_stock_weekly", "all_stock_monthly",
                "all_stock_5min", "all_stock_15min", "all_stock_30min", "all_stock_60min",
                "index_daily", "index_weekly", "index_monthly",
                "dividend", "adjust_factor",
                "profit_data", "operation_data", "growth_data",
                "balance_data", "cash_flow_data", "dupont_data",
                "performance_express", "forecast_report",
                "sz50_stocks", "hs300_stocks", "zz500_stocks",
                "deposit_rate", "loan_rate", "reserve_ratio",
                "money_supply_month", "money_supply_year",
            }

            missing = expected_tables - tables
            if missing:
                raise AssertionError(f"缺少表: {missing}")

            logger.info(f"  ✅ 共 {len(expected_tables)} 个表，全部创建成功")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_02_metadata(self):
        """测试 02：元数据下载"""
        test_name = "元数据下载"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 02: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with MetaDownloader(str(TEST_DB_PATH), logger) as dl:
                results = dl.download_all_metadata()

            # 验证数据量
            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["trade_dates", "stock_basic", "stock_industry"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count > 0, f"{table} 数据为空"
                logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 元数据下载通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_03_macro_data(self):
        """测试 03：宏观经济数据"""
        test_name = "宏观经济数据"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 03: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with MacroDownloader(str(TEST_DB_PATH), logger) as dl:
                results = dl.download_all_macro()

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["deposit_rate", "loan_rate", "reserve_ratio",
                         "money_supply_month", "money_supply_year"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count > 0, f"{table} 数据为空"
                logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 宏观经济数据通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_04_index_components(self):
        """测试 04：指数成分股"""
        test_name = "指数成分股"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 04: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with ComponentDownloader(str(TEST_DB_PATH), logger) as dl:
                results = dl.download_all_components()

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["sz50_stocks", "hs300_stocks", "zz500_stocks"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count > 0, f"{table} 数据为空"
                logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 指数成分股通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_05_index_kline(self):
        """测试 05：指数K线"""
        test_name = "指数K线"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 05: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with IndexDownloader(str(TEST_DB_PATH), logger) as dl:
                # 仅下载测试日期范围的数据
                results = dl.download_all_index(start_date=TEST_START_DATE)

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["index_daily", "index_weekly", "index_monthly"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count > 0, f"{table} 数据为空"
                # 限制数据量
                if count > MAX_ROWS_PER_TABLE:
                    conn.execute(
                        f"DELETE FROM {table} WHERE rowid NOT IN "
                        f"(SELECT rowid FROM {table} ORDER BY date DESC LIMIT {MAX_ROWS_PER_TABLE})"
                    )
                    conn.commit()
                    logger.info(f"  ⚠️  {table}: 已截断至 {MAX_ROWS_PER_TABLE} 行")
                else:
                    logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 指数K线通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_06_stock_kline(self):
        """测试 06：股票K线（日/周/月，仅不复权）"""
        test_name = "股票K线"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 06: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with KlineDownloader(str(TEST_DB_PATH), logger) as dl:
                # 仅测试不复权数据
                count_daily = dl._download_kline_batch(
                    TEST_CODES, TEST_START_DATE, TEST_END_DATE,
                    "d", "date,code,open,high,low,close,preclose,volume,amount,"
                         "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,"
                         "pcfNcfTTM,isST",
                    "all_stock_daily", adjustflag=3,
                )
                count_weekly = dl._download_kline_batch(
                    TEST_CODES, TEST_START_DATE, None,
                    "w", "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg",
                    "all_stock_weekly", adjustflag=3,
                )
                count_monthly = dl._download_kline_batch(
                    TEST_CODES, TEST_START_DATE, None,
                    "m", "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg",
                    "all_stock_monthly", adjustflag=3,
                )

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table, count in [("all_stock_daily", count_daily),
                                 ("all_stock_weekly", count_weekly),
                                 ("all_stock_monthly", count_monthly)]:
                assert count > 0, f"{table} 数据为空"
                actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                # 限制数据量
                if actual > MAX_ROWS_PER_TABLE:
                    conn.execute(
                        f"DELETE FROM {table} WHERE rowid NOT IN "
                        f"(SELECT rowid FROM {table} ORDER BY date DESC LIMIT {MAX_ROWS_PER_TABLE})"
                    )
                    conn.commit()
                    logger.info(f"  ⚠️  {table}: 已截断至 {MAX_ROWS_PER_TABLE} 行")
                else:
                    logger.info(f"  ✅ {table}: {actual} 行 (下载: {count})")
            conn.close()

            logger.info(f"  ✅ 股票K线通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_07_financial_data(self):
        """测试 07：季频财务数据"""
        test_name = "季频财务数据"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 07: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with FinancialDownloader(str(TEST_DB_PATH), logger) as dl:
                results = dl.download_all_financial(
                    TEST_CODES, start_year=TEST_FINANCIAL_YEAR, end_year=TEST_FINANCIAL_YEAR,
                )

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["profit_data", "operation_data", "growth_data",
                         "balance_data", "cash_flow_data", "dupont_data"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 季频财务数据通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_08_reports(self):
        """测试 08：公司报告"""
        test_name = "公司报告"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 08: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with ReportDownloader(str(TEST_DB_PATH), logger) as dl:
                results = dl.download_all_reports(
                    TEST_CODES, start_date="2007-01-01", end_date=TEST_END_DATE,
                )

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["performance_express", "forecast_report"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                # 限制数据量
                if count > MAX_ROWS_PER_TABLE:
                    conn.execute(
                        f"DELETE FROM {table} WHERE rowid NOT IN "
                        f"(SELECT rowid FROM {table} ORDER BY rowid DESC LIMIT {MAX_ROWS_PER_TABLE})"
                    )
                    conn.commit()
                    logger.info(f"  ⚠️  {table}: 已截断至 {MAX_ROWS_PER_TABLE} 行")
                else:
                    logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 公司报告通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_09_dividend_data(self):
        """测试 09：分红和复权因子"""
        test_name = "分红和复权因子"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 09: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            with DividendDownloader(str(TEST_DB_PATH), logger) as dl:
                div_results = dl.download_all_dividend(
                    TEST_CODES, start_year=TEST_FINANCIAL_YEAR, end_year=TEST_FINANCIAL_YEAR,
                )
                fac_results = dl.download_adjust_factor(
                    TEST_CODES, start_date=TEST_START_DATE, end_date=TEST_END_DATE,
                )

            conn = sqlite3.connect(str(TEST_DB_PATH))
            for table in ["dividend", "adjust_factor"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                logger.info(f"  ✅ {table}: {count} 行")
            conn.close()

            logger.info(f"  ✅ 分红和复权因子通过")
            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    def test_10_data_integrity(self):
        """测试 10：数据完整性验证"""
        test_name = "数据完整性验证"
        logger.info(f"\n{'=' * 60}")
        logger.info(f"  测试 10: {test_name}")
        logger.info(f"{'=' * 60}")

        try:
            conn = sqlite3.connect(str(TEST_DB_PATH))

            # 验证所有表都存在
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            expected_tables = {
                "trade_dates", "stock_basic", "stock_industry",
                "all_stock_daily", "all_stock_weekly", "all_stock_monthly",
                "index_daily", "index_weekly", "index_monthly",
                "dividend", "adjust_factor",
                "profit_data", "operation_data", "growth_data",
                "balance_data", "cash_flow_data", "dupont_data",
                "performance_express", "forecast_report",
                "sz50_stocks", "hs300_stocks", "zz500_stocks",
                "deposit_rate", "loan_rate", "reserve_ratio",
                "money_supply_month", "money_supply_year",
            }

            missing = expected_tables - tables
            if missing:
                raise AssertionError(f"缺少表: {missing}")

            # 统计总数据量
            total_rows = 0
            table_stats = {}
            for table in sorted(expected_tables):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                table_stats[table] = count
                total_rows += count

            conn.close()

            logger.info(f"  ✅ 所有 {len(expected_tables)} 个表都存在")
            logger.info(f"  ✅ 总数据行数: {total_rows}")
            logger.info(f"  ✅ 数据完整性验证通过")

            self._mark_passed(test_name)
        except Exception as e:
            self._mark_failed(test_name, str(e))

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def _mark_passed(self, test_name: str):
        """标记测试通过。"""
        self.passed += 1

    def _mark_failed(self, test_name: str, error: str):
        """标记测试失败。"""
        self.failed += 1
        self.errors.append((test_name, error))
        logger.error(f"  ❌ {test_name} 失败: {error}")

    def print_summary(self):
        """打印测试总结。"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 集成测试总结")
        logger.info("=" * 60)
        logger.info(f"  通过: {self.passed}")
        logger.info(f"  失败: {self.failed}")
        logger.info(f"  总计: {self.passed + self.failed}")
        logger.info("")

        if self.errors:
            logger.info("失败详情:")
            for name, err in self.errors:
                logger.info(f"  - {name}: {err}")
            logger.info("")

        logger.info("=" * 60)

        if self.failed > 0:
            logger.info("❌ 集成测试失败！")
            sys.exit(1)
        else:
            logger.info("✅ 集成测试全部通过！")


def main():
    """主函数。"""
    runner = IntegrationTestRunner()
    runner.run_all_tests()


if __name__ == "__main__":
    main()
