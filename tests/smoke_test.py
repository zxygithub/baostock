#!/usr/bin/env python3
"""冒烟测试：验证各数据下载模块的正确性。

测试策略：
1. 使用少量股票（浦发银行 sh.600000 + 平安银行 sz.000001）
2. 限制日期范围，减少数据量
3. 验证各表的字段对齐和数据写入
"""

import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.db_manager import DBManager
from src.utils.helpers import setup_logging
from src.downloaders.meta_downloader import MetaDownloader
from src.downloaders.macro_downloader import MacroDownloader
from src.downloaders.component_downloader import ComponentDownloader
from src.downloaders.index_downloader import IndexDownloader
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.report_downloader import ReportDownloader
from src.downloaders.dividend_downloader import DividendDownloader

logger = setup_logging("smoke_test")

# 冒烟测试用少量股票
TEST_CODES = ["sh.600000", "sz.000001"]
TEST_START_DATE = "2024-01-01"
TEST_END_DATE = "2024-12-31"
TEST_FINANCIAL_YEAR = 2024


def check_table_schema(table_name: str, expected_cols: list[str]):
    """验证表结构字段是否正确。"""
    conn = sqlite3.connect(str(DB_PATH))
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    conn.close()
    missing = set(expected_cols) - cols
    if missing:
        raise AssertionError(
            f"表 {table_name} 缺少字段: {missing}\n"
            f"期望: {sorted(expected_cols)}\n"
            f"实际: {sorted(cols)}"
        )
    logger.info(f"  ✅ {table_name} 字段验证通过 ({len(expected_cols)} 个字段)")


def check_table_count(table_name: str, min_rows: int = 0):
    """验证表数据行数是否满足最低要求。"""
    conn = sqlite3.connect(str(DB_PATH))
    # 强制读取 WAL 以确保可见性
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    cnt = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    conn.close()
    if cnt < min_rows:
        raise AssertionError(
            f"表 {table_name} 行数不足: 期望>={min_rows}, 实际={cnt}"
        )
    logger.info(f"  ✅ {table_name}: {cnt} 行")
    return cnt


def test_phase_1_db_init():
    """测试 1：数据库初始化"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 1: 数据库初始化")
    logger.info("═══════════════════════════════════════════")

    with DBManager(str(DB_PATH)) as db:
        db.init_all_tables()
        db.migrate_schema()

    # 验证 31 个表（不含 shibor）
    conn = sqlite3.connect(str(DB_PATH))
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
        "request_count",
    }

    if "shibor" in tables:
        raise AssertionError("shibor 表应当已被删除，但仍存在")

    missing = expected_tables - tables
    extra = tables - expected_tables
    if missing:
        raise AssertionError(f"缺少表: {missing}")
    if extra:
        logger.warning(f"  额外表 (非预期): {extra}")

    logger.info(f"  ✅ 共 {len(expected_tables)} 个表，全部创建成功")


def test_phase_2_metadata():
    """测试 2：元数据下载"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 2: 元数据下载")
    logger.info("═══════════════════════════════════════════")

    # 验证字段
    check_table_schema("trade_dates", ["calendar_date", "is_trading_day"])
    check_table_schema("stock_basic", ["code", "code_name", "ipo_date", "out_date", "type", "status"])
    check_table_schema("stock_industry", ["code", "code_name", "industry", "industry_classification", "update_date"])

    with MetaDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_metadata()

    check_table_count("trade_dates", min_rows=1)
    check_table_count("stock_basic", min_rows=1)
    check_table_count("stock_industry", min_rows=1)
    logger.info(f"  元数据下载结果: {results}")


def test_phase_3_macro():
    """测试 3：宏观经济数据"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 3: 宏观经济数据")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("deposit_rate", [
        "pub_date", "demand_deposit_rate", "fixed_deposit_rate_3_month",
        "fixed_deposit_rate_6_month", "fixed_deposit_rate_1_year",
        "fixed_deposit_rate_2_year", "fixed_deposit_rate_3_year",
        "fixed_deposit_rate_5_year", "installment_fixed_rate_1_year",
        "installment_fixed_rate_3_year", "installment_fixed_rate_5_year",
    ])
    check_table_schema("loan_rate", [
        "pub_date", "loan_rate_6_month", "loan_rate_6m_to_1y",
        "loan_rate_1y_to_3y", "loan_rate_3y_to_5y", "loan_rate_above_5y",
        "mortgage_rate_below_5y", "mortgage_rate_above_5y",
    ])
    check_table_schema("reserve_ratio", [
        "pub_date", "effective_date", "big_institutions_ratio_pre",
        "big_institutions_ratio_after", "medium_institutions_ratio_pre",
        "medium_institutions_ratio_after",
    ])
    check_table_schema("money_supply_month", [
        "stat_year", "stat_month", "m0_month", "m0_yoy", "m0_chain",
        "m1_month", "m1_yoy", "m1_chain", "m2_month", "m2_yoy", "m2_chain",
    ])
    check_table_schema("money_supply_year", [
        "stat_year", "m0_year", "m0_year_yoy", "m1_year",
        "m1_year_yoy", "m2_year", "m2_year_yoy",
    ])

    with MacroDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_macro()

    check_table_count("deposit_rate", min_rows=1)
    check_table_count("loan_rate", min_rows=1)
    check_table_count("reserve_ratio", min_rows=1)
    check_table_count("money_supply_month", min_rows=1)
    check_table_count("money_supply_year", min_rows=1)
    logger.info(f"  宏观数据下载结果: {results}")


def test_phase_4_components():
    """测试 4：指数成分股"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 4: 指数成分股")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("sz50_stocks", ["code", "code_name", "update_date"])
    check_table_schema("hs300_stocks", ["code", "code_name", "update_date"])
    check_table_schema("zz500_stocks", ["code", "code_name", "update_date"])

    with ComponentDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_components()

    check_table_count("sz50_stocks", min_rows=1)
    check_table_count("hs300_stocks", min_rows=1)
    check_table_count("zz500_stocks", min_rows=1)
    logger.info(f"  成分股下载结果: {results}")


def test_phase_5_index_kline():
    """测试 5：指数K线"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 5: 指数K线")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("index_daily", [
        "code", "date", "open", "high", "low", "close",
        "preclose", "volume", "amount", "pct_chg",
    ])
    check_table_schema("index_weekly", [
        "code", "date", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pct_chg",
    ])
    check_table_schema("index_monthly", [
        "code", "date", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pct_chg",
    ])

    with IndexDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_index(start_date=TEST_START_DATE)

    check_table_count("index_daily", min_rows=1)
    check_table_count("index_weekly", min_rows=1)
    check_table_count("index_monthly", min_rows=1)
    logger.info(f"  指数K线下载结果: {results}")


def test_phase_6_stock_kline():
    """测试 6：A股K线（日线/周线/月线，仅不复权）"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 6: A股K线 (日线/周线/月线, 不复权)")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("all_stock_daily", [
        "code", "date", "open", "high", "low", "close", "preclose",
        "volume", "amount", "adjustflag", "turn", "tradestatus",
        "pct_chg", "pe_ttm", "pb_mrq", "ps_ttm", "pcf_ncf_ttm", "is_st",
    ])
    check_table_schema("all_stock_weekly", [
        "code", "date", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pct_chg",
    ])
    check_table_schema("all_stock_monthly", [
        "code", "date", "open", "high", "low", "close",
        "volume", "amount", "adjustflag", "turn", "pct_chg",
    ])

    with KlineDownloader(str(DB_PATH), logger) as dl:
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

    check_table_count("all_stock_daily", min_rows=1)
    check_table_count("all_stock_weekly", min_rows=1)
    check_table_count("all_stock_monthly", min_rows=1)
    logger.info(f"  K线下载: 日线={count_daily}, 周线={count_weekly}, 月线={count_monthly}")


def test_phase_7_financial():
    """测试 7：季频财务数据"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 7: 季频财务数据")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("profit_data", [
        "code", "pub_date", "stat_date", "roe_avg", "np_margin", "gp_margin",
        "net_profit", "eps_ttm", "mb_revenue", "total_share", "liqa_share",
        "year", "quarter",
    ])
    check_table_schema("operation_data", [
        "code", "pub_date", "stat_date", "nr_turn_ratio", "nr_turn_days",
        "inv_turn_ratio", "inv_turn_days", "ca_turn_ratio", "asset_turn_ratio",
        "year", "quarter",
    ])
    check_table_schema("growth_data", [
        "code", "pub_date", "stat_date", "yoy_equity", "yoy_asset", "yoy_ni",
        "yoy_eps_basic", "yoy_pni", "year", "quarter",
    ])
    check_table_schema("balance_data", [
        "code", "pub_date", "stat_date", "current_ratio", "quick_ratio",
        "cash_ratio", "yoy_liability", "liability_to_asset", "asset_to_equity",
        "year", "quarter",
    ])
    check_table_schema("cash_flow_data", [
        "code", "pub_date", "stat_date", "ca_to_asset", "nca_to_asset",
        "tangible_asset_to_asset", "ebit_to_interest", "cfo_to_or",
        "cfo_to_np", "cfo_to_gr", "year", "quarter",
    ])
    check_table_schema("dupont_data", [
        "code", "pub_date", "stat_date", "dupont_roe", "dupont_asset_to_equity",
        "dupont_asset_turn", "dupont_pni_to_ni", "dupont_ni_to_gr",
        "dupont_tax_burden", "dupont_int_burden", "dupont_ebit_to_gr",
        "year", "quarter",
    ])

    with FinancialDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_financial(
            TEST_CODES, start_year=TEST_FINANCIAL_YEAR, end_year=TEST_FINANCIAL_YEAR,
        )

    # 财务数据可能为空（季度未披露），仅做 schema 验证
    for tbl in ["profit_data", "operation_data", "growth_data",
                "balance_data", "cash_flow_data", "dupont_data"]:
        check_table_count(tbl, min_rows=0)
    logger.info(f"  财务数据下载结果: {results}")


def test_phase_8_reports():
    """测试 8：公司报告"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 8: 公司报告")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("performance_express", [
        "code", "performance_exp_pub_date", "performance_exp_stat_date",
        "performance_exp_update_date", "total_asset", "net_asset",
        "eps_chg_pct", "roe_wa", "eps_diluted", "gr_yoy", "op_yoy",
    ])
    check_table_schema("forecast_report", [
        "code", "profit_forecast_exp_pub_date", "profit_forecast_exp_stat_date",
        "profit_forecast_type", "profit_forecast_abstract",
        "profit_forecast_chg_pct_up", "profit_forecast_chg_pct_down",
    ])

    with ReportDownloader(str(DB_PATH), logger) as dl:
        results = dl.download_all_reports(
            TEST_CODES, start_date="2007-01-01", end_date=TEST_END_DATE,
        )

    check_table_count("performance_express", min_rows=1)
    check_table_count("forecast_report", min_rows=1)
    logger.info(f"  公司报告下载结果: {results}")


def test_phase_9_dividend():
    """测试 9：分红和复权因子"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 9: 分红和复权因子")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("dividend", [
        "code", "divid_pre_notice_date", "divid_agm_pum_date",
        "divid_plan_announce_date", "divid_plan_date", "divid_regist_date",
        "divid_operate_date", "divid_pay_date", "divid_stock_market_date",
        "divid_cash_ps_before_tax", "divid_cash_ps_after_tax",
        "divid_stocks_ps", "divid_cash_stock", "divid_reserve_to_stock_ps",
        "year", "year_type",
    ])
    check_table_schema("adjust_factor", [
        "code", "divid_operate_date", "fore_adjust_factor",
        "back_adjust_factor", "adjust_factor",
    ])

    with DividendDownloader(str(DB_PATH), logger) as dl:
        div_results = dl.download_all_dividend(
            TEST_CODES, start_year=TEST_FINANCIAL_YEAR, end_year=TEST_FINANCIAL_YEAR,
        )
        fac_results = dl.download_adjust_factor(
            TEST_CODES, start_date=TEST_START_DATE, end_date=TEST_END_DATE,
        )

    check_table_count("dividend", min_rows=0)
    check_table_count("adjust_factor", min_rows=0)
    logger.info(f"  分红下载结果: {div_results}")
    logger.info(f"  复权因子下载结果: {fac_results}")


def test_phase_10_all_stock():
    """测试 10：query_all_stock 全股票列表"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 10: 全股票列表 (query_all_stock)")
    logger.info("═══════════════════════════════════════════")

    check_table_schema("all_stock", ["code", "trade_status", "code_name", "day"])

    import baostock as bs
    import pandas as pd
    from src.utils.helpers import fetch_all_rows

    bs.login()
    rs = bs.query_all_stock("2024-12-31")
    rows = fetch_all_rows(rs)
    bs.logout()

    if rows:
        df = pd.DataFrame(rows, columns=rs.fields)
        df.rename(columns={"tradeStatus": "trade_status"}, inplace=True)
        df["day"] = "2024-12-31"
        conn = sqlite3.connect(str(DB_PATH))
        df.to_sql("all_stock", conn, if_exists="replace", index=False)
        conn.commit()
        conn.close()

    check_table_count("all_stock", min_rows=1)


def test_phase_11_minute_kline():
    """测试 11：分钟线（5/15/30/60min，不复权）"""
    logger.info("\n═══════════════════════════════════════════")
    logger.info("  阶段 11: 分钟线 (5/15/30/60min, 不复权)")
    logger.info("═══════════════════════════════════════════")

    for freq in ["5", "15", "30", "60"]:
        table_name = f"all_stock_{freq}min"
        check_table_schema(table_name, [
            "code", "date", "time", "open", "high", "low",
            "close", "volume", "amount", "adjustflag",
        ])

    from src.downloaders.kline_downloader import KlineDownloader

    with KlineDownloader(str(DB_PATH), logger) as dl:
        for freq in ["5", "15", "30", "60"]:
            count = dl._download_kline_batch(
                ["sh.600000"], "2024-12-01", "2024-12-31",
                freq, "date,time,code,open,high,low,close,volume,amount,adjustflag",
                f"all_stock_{freq}min", adjustflag=3,
            )
            check_table_count(f"all_stock_{freq}min", min_rows=1)
            logger.info(f"  {freq}min K线: {count} 行")


def main():
    logger.info("🚀 开始冒烟测试: 验证各数据下载模块")

    tests = [
        ("数据库初始化", test_phase_1_db_init),
        ("元数据下载", test_phase_2_metadata),
        ("宏观经济数据", test_phase_3_macro),
        ("指数成分股", test_phase_4_components),
        ("指数K线", test_phase_5_index_kline),
        ("A股K线", test_phase_6_stock_kline),
        ("季频财务数据", test_phase_7_financial),
        ("公司报告", test_phase_8_reports),
        ("分红和复权因子", test_phase_9_dividend),
        ("全股票列表", test_phase_10_all_stock),
        ("分钟线", test_phase_11_minute_kline),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            logger.error(f"  ❌ {name} 失败: {e}")

    logger.info("\n" + "=" * 50)
    logger.info(f"冒烟测试完成: {passed} 通过, {failed} 失败")
    if errors:
        logger.info("\n失败详情:")
        for name, err in errors:
            logger.info(f"  - {name}: {err}")
    logger.info("=" * 50)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
