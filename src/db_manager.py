"""Database initialization and management module for BaoStock data project."""

import sqlite3
from datetime import date, datetime
from pathlib import Path


class DBManager:
    """SQLite database connection and schema management for BaoStock data."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_all_tables(self) -> None:
        conn = self.get_connection()
        self._create_trade_dates(conn)
        self._create_stock_basic(conn)
        self._create_stock_industry(conn)
        self._create_all_stock(conn)
        self._create_all_stock_daily(conn)
        self._create_all_stock_weekly(conn)
        self._create_all_stock_monthly(conn)
        self._create_all_stock_5min(conn)
        self._create_all_stock_15min(conn)
        self._create_all_stock_30min(conn)
        self._create_all_stock_60min(conn)
        self._create_index_daily(conn)
        self._create_index_weekly(conn)
        self._create_index_monthly(conn)
        self._create_dividend(conn)
        self._create_adjust_factor(conn)
        self._create_profit_data(conn)
        self._create_operation_data(conn)
        self._create_growth_data(conn)
        self._create_balance_data(conn)
        self._create_cash_flow_data(conn)
        self._create_dupont_data(conn)
        self._create_performance_express(conn)
        self._create_forecast_report(conn)
        self._create_sz50_stocks(conn)
        self._create_hs300_stocks(conn)
        self._create_zz500_stocks(conn)
        self._create_deposit_rate(conn)
        self._create_loan_rate(conn)
        self._create_reserve_ratio(conn)
        self._create_money_supply_month(conn)
        self._create_money_supply_year(conn)
        self._create_request_count(conn)
        conn.commit()

    def _create_trade_dates(self, conn: sqlite3.Connection) -> None:
        """交易日查询:query_trade_dates()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_dates (
                calendar_date   TEXT PRIMARY KEY,   -- 日期 (格式:YYYY-MM-DD)
                is_trading_day  INTEGER NOT NULL,   -- 是否交易日 (0:非交易日; 1:交易日)
                update_time     TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_stock_basic(self, conn: sqlite3.Connection) -> None:
        """证券基本资料:query_stock_basic()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_basic (
                code        TEXT PRIMARY KEY,   -- 证券代码 (格式:sh.600000)
                code_name   TEXT,               -- 证券名称
                ipo_date    TEXT,               -- 上市日期
                out_date    TEXT,               -- 退市日期
                type        INTEGER,            -- 证券类型 (1:股票, 2:指数, 3:其它, 4:可转债, 5:ETF)
                status      INTEGER,            -- 上市状态 (1:上市, 0:退市)
                update_time TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_stock_industry(self, conn: sqlite3.Connection) -> None:
        """行业分类:query_stock_industry()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_industry (
                update_date             TEXT,   -- 更新日期
                code                    TEXT PRIMARY KEY,   -- 证券代码
                code_name               TEXT,               -- 证券名称
                industry                TEXT,               -- 所属行业
                industry_classification TEXT,               -- 所属行业类别
                update_time             TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_all_stock(self, conn: sqlite3.Connection) -> None:
        """证券代码查询:query_all_stock()

        TODO: No downloader currently populates this table.
        The only write path is in tests/smoke_test.py (test_phase_10).
        To implement: add query_all_stock() to MetaDownloader or a dedicated script.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock (
                code           TEXT NOT NULL,   -- 证券代码
                trade_status   INTEGER,         -- 交易状态 (1:正常交易, 0:停牌)
                code_name      TEXT,            -- 证券名称
                day            TEXT NOT NULL,   -- 查询日期
                update_time    TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, day)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_all_stock_day ON all_stock(day)"
        )

    def _create_all_stock_daily(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（日线）:query_history_k_data_plus(frequency="d")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_daily (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 今开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 今收盘价 (精度:小数点后4位;单位:人民币元)
                preclose    REAL,            -- 昨日收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                turn        REAL,            -- 换手率 [指定交易日成交量/指定交易日流通股总数]*100% (精度:小数点后6位;单位:%)
                tradestatus INTEGER,         -- 交易状态 (1:正常交易, 0:停牌)
                pct_chg     REAL,            -- 涨跌幅(百分比) (精度:小数点后6位)
                pe_ttm      REAL,            -- 滚动市盈率 (精度:小数点后6位)
                pb_mrq      REAL,            -- 市净率 (精度:小数点后6位)
                ps_ttm      REAL,            -- 滚动市销率 (精度:小数点后6位)
                pcf_ncf_ttm REAL,            -- 滚动市现率 (精度:小数点后6位)
                is_st       INTEGER,         -- 是否ST (1:是, 0:否)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, adjustflag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_date ON all_stock_daily(date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_code ON all_stock_daily(code)"
        )

    def _create_all_stock_weekly(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（周线）:query_history_k_data_plus(frequency="w")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_weekly (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                turn        REAL,            -- 换手率 (精度:小数点后6位;单位:%)
                pct_chg     REAL,            -- 涨跌幅(百分比) (精度:小数点后6位)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, adjustflag)
            )
        """)

    def _create_all_stock_monthly(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（月线）:query_history_k_data_plus(frequency="m")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_monthly (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                turn        REAL,            -- 换手率 (精度:小数点后6位;单位:%)
                pct_chg     REAL,            -- 涨跌幅(百分比) (精度:小数点后6位)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, adjustflag)
            )
        """)

    def _create_all_stock_5min(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（5分钟线）:query_history_k_data_plus(frequency="5")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_5min (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                time        TEXT NOT NULL,   -- 交易所行情时间 (格式:YYYYMMDDHHMMSSsss)
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股;时间范围内累计)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元;时间范围内累计)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, time, adjustflag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_5min_datetime ON all_stock_5min(date, time)"
        )

    def _create_all_stock_15min(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（15分钟线）:query_history_k_data_plus(frequency="15")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_15min (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                time        TEXT NOT NULL,   -- 交易所行情时间 (格式:YYYYMMDDHHMMSSsss)
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股;时间范围内累计)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元;时间范围内累计)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, time, adjustflag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_15min_datetime ON all_stock_15min(date, time)"
        )

    def _create_all_stock_30min(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（30分钟线）:query_history_k_data_plus(frequency="30")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_30min (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                time        TEXT NOT NULL,   -- 交易所行情时间 (格式:YYYYMMDDHHMMSSsss)
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股;时间范围内累计)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元;时间范围内累计)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, time, adjustflag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_30min_datetime ON all_stock_30min(date, time)"
        )

    def _create_all_stock_60min(self, conn: sqlite3.Connection) -> None:
        """历史A股K线数据（60分钟线）:query_history_k_data_plus(frequency="60")"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS all_stock_60min (
                code        TEXT NOT NULL,   -- 证券代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                time        TEXT NOT NULL,   -- 交易所行情时间 (格式:YYYYMMDDHHMMSSsss)
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股;时间范围内累计)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元;时间范围内累计)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, time, adjustflag)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_60min_datetime ON all_stock_60min(date, time)"
        )

    def _create_index_daily(self, conn: sqlite3.Connection) -> None:
        """指数K线数据（日线）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_daily (
                code        TEXT NOT NULL,   -- 指数代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 开盘价
                high        REAL,            -- 最高价
                low         REAL,            -- 最低价
                close       REAL,            -- 收盘价
                preclose    REAL,            -- 前收盘价
                volume      REAL,            -- 成交量 (单位:股)
                amount      REAL,            -- 成交额 (单位:人民币元)
                pct_chg     REAL,            -- 涨跌幅(百分比)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_index_date ON index_daily(date)")

    def _create_index_weekly(self, conn: sqlite3.Connection) -> None:
        """指数K线数据（周线）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_weekly (
                code        TEXT NOT NULL,   -- 指数代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                turn        REAL,            -- 换手率 (精度:小数点后6位;单位:%)
                pct_chg     REAL,            -- 涨跌幅(百分比) (精度:小数点后6位)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, adjustflag)
            )
        """)

    def _create_index_monthly(self, conn: sqlite3.Connection) -> None:
        """指数K线数据（月线）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_monthly (
                code        TEXT NOT NULL,   -- 指数代码
                date        TEXT NOT NULL,   -- 交易所行情日期
                open        REAL,            -- 开盘价格 (精度:小数点后4位;单位:人民币元)
                high        REAL,            -- 最高价 (精度:小数点后4位;单位:人民币元)
                low         REAL,            -- 最低价 (精度:小数点后4位;单位:人民币元)
                close       REAL,            -- 收盘价 (精度:小数点后4位;单位:人民币元)
                volume      REAL,            -- 成交数量 (单位:股)
                amount      REAL,            -- 成交金额 (精度:小数点后4位;单位:人民币元)
                adjustflag  INTEGER,         -- 复权状态 (1:后复权, 2:前复权, 3:不复权)
                turn        REAL,            -- 换手率 (精度:小数点后6位;单位:%)
                pct_chg     REAL,            -- 涨跌幅(百分比) (精度:小数点后6位)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, date, adjustflag)
            )
        """)

    def _create_dividend(self, conn: sqlite3.Connection) -> None:
        """除权除息信息:query_dividend_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dividend (
                code                     TEXT NOT NULL,   -- 证券代码
                divid_pre_notice_date    TEXT,            -- 预批露公告日
                divid_agm_pum_date       TEXT,            -- 股东大会公告日期
                divid_plan_announce_date TEXT,            -- 预案公告日
                divid_plan_date          TEXT,            -- 分红实施公告日
                divid_regist_date        TEXT,            -- 股权登记日
                divid_operate_date       TEXT,            -- 除权除息日期
                divid_pay_date           TEXT,            -- 派息日
                divid_stock_market_date  TEXT,            -- 红股上市交易日
                divid_cash_ps_before_tax REAL,            -- 每股股利税前 (派息比例分子(税前)/派息比例分母)
                divid_cash_ps_after_tax  REAL,            -- 每股股利税后 (派息比例分子(税后)/派息比例分母)
                divid_stocks_ps          REAL,            -- 每股红股
                divid_cash_stock         TEXT,            -- 分红送转 (每股派息数(税前)+每股送股数+每股转增股本数)
                divid_reserve_to_stock_ps REAL,           -- 每股转增资本
                year                     INTEGER,         -- 年份
                year_type                TEXT,            -- 年份类别 (report:预案公告年份, operate:除权除息年份)
                update_time              TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, divid_operate_date, year_type)
            )
        """)

    def _create_adjust_factor(self, conn: sqlite3.Connection) -> None:
        """复权因子:query_adjust_factor()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS adjust_factor (
                code                TEXT NOT NULL,   -- 证券代码
                divid_operate_date  TEXT NOT NULL,   -- 除权除息日期
                fore_adjust_factor  REAL,            -- 向前复权因子 (除权除息日前一个交易日收盘价/除权除息日最近交易日前收盘价)
                back_adjust_factor  REAL,            -- 向后复权因子 (除权除息日最近交易日前收盘价/除权除息日前一个交易日收盘价)
                adjust_factor       REAL,            -- 本次复权因子
                update_time         TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, divid_operate_date)
            )
        """)

    def _create_profit_data(self, conn: sqlite3.Connection) -> None:
        """季频盈利能力:query_profit_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profit_data (
                code        TEXT NOT NULL,   -- 证券代码
                pub_date    TEXT,            -- 公司发布财报的日期
                stat_date   TEXT,            -- 财报统计季度的最后一天 (如 2017-03-31)
                roe_avg     REAL,            -- 净资产收益率(平均)(%) = 归属母公司股东净利润/[(期初权益+期末权益)/2]*100%
                np_margin   REAL,            -- 销售净利率(%) = 净利润/营业收入*100%
                gp_margin   REAL,            -- 销售毛利率(%) = 毛利/营业收入*100%
                net_profit  REAL,            -- 净利润(元)
                eps_ttm     REAL,            -- 每股收益 = 归属母公司股东净利润TTM/最新总股本
                mb_revenue  REAL,            -- 主营营业收入(元)
                total_share REAL,            -- 总股本
                liqa_share  REAL,            -- 流通股本
                year        INTEGER,         -- 统计年份
                quarter     INTEGER,         -- 统计季度 (1-4)
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_operation_data(self, conn: sqlite3.Connection) -> None:
        """季频营运能力:query_operation_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS operation_data (
                code             TEXT NOT NULL,   -- 证券代码
                pub_date         TEXT,            -- 公司发布财报的日期
                stat_date        TEXT,            -- 财报统计季度的最后一天
                nr_turn_ratio    REAL,            -- 应收账款周转率(次) = 营业收入/[(期初应收票据及应收账款+期末)/2]
                nr_turn_days     REAL,            -- 应收账款周转天数(天) = 季报天数/应收账款周转率
                inv_turn_ratio   REAL,            -- 存货周转率(次) = 营业成本/[(期初存货净额+期末)/2]
                inv_turn_days    REAL,            -- 存货周转天数(天) = 季报天数/存货周转率
                ca_turn_ratio    REAL,            -- 流动资产周转率(次) = 营业总收入/[(期初流动资产+期末)/2]
                asset_turn_ratio REAL,            -- 总资产周转率 = 营业总收入/[(期初资产总额+期末)/2]
                year             INTEGER,         -- 统计年份
                quarter          INTEGER,         -- 统计季度 (1-4)
                update_time      TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_growth_data(self, conn: sqlite3.Connection) -> None:
        """季频成长能力:query_growth_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS growth_data (
                code           TEXT NOT NULL,   -- 证券代码
                pub_date       TEXT,            -- 公司发布财报的日期
                stat_date      TEXT,            -- 财报统计季度的最后一天
                yoy_equity     REAL,            -- 净资产同比增长率 (%)
                yoy_asset      REAL,            -- 总资产同比增长率 (%)
                yoy_ni         REAL,            -- 净利润同比增长率 (%)
                yoy_eps_basic  REAL,            -- 基本每股收益同比增长率 (%)
                yoy_pni        REAL,            -- 归属母公司股东净利润同比增长率 (%)
                year           INTEGER,         -- 统计年份
                quarter        INTEGER,         -- 统计季度 (1-4)
                update_time    TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_balance_data(self, conn: sqlite3.Connection) -> None:
        """季频偿债能力:query_balance_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_data (
                code               TEXT NOT NULL,   -- 证券代码
                pub_date           TEXT,            -- 公司发布财报的日期
                stat_date          TEXT,            -- 财报统计季度的最后一天
                current_ratio      REAL,            -- 流动比率 = 流动资产/流动负债
                quick_ratio        REAL,            -- 速动比率 = (流动资产-存货净额)/流动负债
                cash_ratio         REAL,            -- 现金比率 = (货币资金+交易性金融资产)/流动负债
                yoy_liability      REAL,            -- 总负债同比增长率 (%)
                liability_to_asset REAL,            -- 资产负债率 = 负债总额/资产总额
                asset_to_equity    REAL,            -- 权益乘数 = 资产总额/股东权益总额 = 1/(1-资产负债率)
                year               INTEGER,         -- 统计年份
                quarter            INTEGER,         -- 统计季度 (1-4)
                update_time        TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_cash_flow_data(self, conn: sqlite3.Connection) -> None:
        """季频现金流量:query_cash_flow_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cash_flow_data (
                code                  TEXT NOT NULL,   -- 证券代码
                pub_date              TEXT,            -- 公司发布财报的日期
                stat_date             TEXT,            -- 财报统计季度的最后一天
                ca_to_asset           REAL,            -- 流动资产除以总资产
                nca_to_asset          REAL,            -- 非流动资产除以总资产
                tangible_asset_to_asset REAL,          -- 有形资产除以总资产
                ebit_to_interest      REAL,            -- 已获利息倍数 = 息税前利润/利息费用
                cfo_to_or             REAL,            -- 经营活动现金净流量/营业收入
                cfo_to_np             REAL,            -- 经营性现金净流量/净利润
                cfo_to_gr             REAL,            -- 经营性现金净流量/营业总收入
                year                  INTEGER,         -- 统计年份
                quarter               INTEGER,         -- 统计季度 (1-4)
                update_time           TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_dupont_data(self, conn: sqlite3.Connection) -> None:
        """季频杜邦指数:query_dupont_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dupont_data (
                code                   TEXT NOT NULL,   -- 证券代码
                pub_date               TEXT,            -- 公司发布财报的日期
                stat_date              TEXT,            -- 财报统计季度的最后一天
                dupont_roe             REAL,            -- 净资产收益率 (%)
                dupont_asset_to_equity REAL,            -- 权益乘数 (反映财务杠杆效应强弱和财务风险)
                dupont_asset_turn      REAL,            -- 总资产周转率 (反映企业资产管理效率)
                dupont_pni_to_ni       REAL,            -- 归属母公司股东净利润/净利润 (反映母公司控股子公司百分比)
                dupont_ni_to_gr        REAL,            -- 净利润/营业总收入 (反映企业销售获利率)
                dupont_tax_burden      REAL,            -- 净利润/利润总额 (反映企业税负水平)
                dupont_int_burden      REAL,            -- 利润总额/息税前利润 (反映企业利息负担)
                dupont_ebit_to_gr      REAL,            -- 息税前利润/营业总收入 (反映企业经营利润率)
                year                   INTEGER,         -- 统计年份
                quarter                INTEGER,         -- 统计季度 (1-4)
                update_time            TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, year, quarter)
            )
        """)

    def _create_performance_express(self, conn: sqlite3.Connection) -> None:
        """季频公司业绩快报:query_performance_express_report()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_express (
                code                        TEXT NOT NULL,   -- 证券代码
                performance_exp_pub_date    TEXT,            -- 业绩快报披露日
                performance_exp_stat_date   TEXT,            -- 业绩快报统计日期
                performance_exp_update_date TEXT,            -- 业绩快报披露日(最新)
                total_asset                 REAL,            -- 业绩快报总资产
                net_asset                   REAL,            -- 业绩快报净资产
                eps_chg_pct                 REAL,            -- 业绩每股收益增长率
                roe_wa                      REAL,            -- 业绩快报净资产收益率ROE-加权
                eps_diluted                 REAL,            -- 业绩快报每股收益EPS-摊薄
                gr_yoy                      REAL,            -- 业绩快报营业总收入同比
                op_yoy                      REAL,            -- 业绩快报营业利润同比
                update_time                 TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, performance_exp_pub_date)
            )
        """)

    def _create_forecast_report(self, conn: sqlite3.Connection) -> None:
        """季频公司业绩预告:query_forecast_report()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_report (
                code                         TEXT NOT NULL,   -- 证券代码
                profit_forecast_exp_pub_date  TEXT,           -- 业绩预告发布日期
                profit_forecast_exp_stat_date TEXT,           -- 业绩预告统计日期
                profit_forecast_type          TEXT,           -- 业绩预告类型
                profit_forecast_abstract      TEXT,           -- 业绩预告摘要
                profit_forecast_chg_pct_up    REAL,           -- 预告归属于母公司净利润增长上限(%)
                profit_forecast_chg_pct_down  REAL,           -- 预告归属于母公司净利润增长下限(%)
                update_time                   TEXT,           -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, profit_forecast_exp_pub_date)
            )
        """)

    def _create_sz50_stocks(self, conn: sqlite3.Connection) -> None:
        """上证50成分股:query_sz50_stocks()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sz50_stocks (
                update_date TEXT,            -- 更新日期
                code        TEXT NOT NULL,   -- 证券代码
                code_name   TEXT,            -- 证券名称
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, update_date)
            )
        """)

    def _create_hs300_stocks(self, conn: sqlite3.Connection) -> None:
        """沪深300成分股:query_hs300_stocks()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hs300_stocks (
                update_date TEXT,            -- 更新日期
                code        TEXT NOT NULL,   -- 证券代码
                code_name   TEXT,            -- 证券名称
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, update_date)
            )
        """)

    def _create_zz500_stocks(self, conn: sqlite3.Connection) -> None:
        """中证500成分股:query_zz500_stocks()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zz500_stocks (
                update_date TEXT,            -- 更新日期
                code        TEXT NOT NULL,   -- 证券代码
                code_name   TEXT,            -- 证券名称
                update_time TEXT,            -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (code, update_date)
            )
        """)

    def _create_deposit_rate(self, conn: sqlite3.Connection) -> None:
        """存款利率:query_deposit_rate_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deposit_rate (
                pub_date                      TEXT PRIMARY KEY,   -- 发布日期
                demand_deposit_rate           REAL,               -- 活期存款(不定期)
                fixed_deposit_rate_3_month    REAL,               -- 定期存款(三个月)
                fixed_deposit_rate_6_month    REAL,               -- 定期存款(半年)
                fixed_deposit_rate_1_year     REAL,               -- 定期存款整存整取(一年)
                fixed_deposit_rate_2_year     REAL,               -- 定期存款整存整取(二年)
                fixed_deposit_rate_3_year     REAL,               -- 定期存款整存整取(三年)
                fixed_deposit_rate_5_year     REAL,               -- 定期存款整存整取(五年)
                installment_fixed_rate_1_year REAL,               -- 零存整取/整存零取/存本取息(一年)
                installment_fixed_rate_3_year REAL,               -- 零存整取/整存零取/存本取息(三年)
                installment_fixed_rate_5_year REAL,               -- 零存整取/整存零取/存本取息(五年)
                update_time                   TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_loan_rate(self, conn: sqlite3.Connection) -> None:
        """贷款利率:query_loan_rate_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loan_rate (
                pub_date               TEXT PRIMARY KEY,   -- 发布日期
                loan_rate_6_month      REAL,               -- 6个月贷款利率
                loan_rate_6m_to_1y     REAL,               -- 6个月至1年贷款利率
                loan_rate_1y_to_3y     REAL,               -- 1年至3年贷款利率
                loan_rate_3y_to_5y     REAL,               -- 3年至5年贷款利率
                loan_rate_above_5y     REAL,               -- 5年以上贷款利率
                mortgage_rate_below_5y REAL,               -- 5年以下住房公积金贷款利率
                mortgage_rate_above_5y REAL,               -- 5年以上住房公积金贷款利率
                update_time            TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_reserve_ratio(self, conn: sqlite3.Connection) -> None:
        """存款准备金率:query_required_reserve_ratio_data()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reserve_ratio (
                pub_date                    TEXT PRIMARY KEY,   -- 公告日期
                effective_date              TEXT,               -- 生效日期
                big_institutions_ratio_pre  REAL,               -- 大型存款类金融机构-调整前
                big_institutions_ratio_after REAL,              -- 大型存款类金融机构-调整后
                medium_institutions_ratio_pre REAL,             -- 中小型存款类金融机构-调整前
                medium_institutions_ratio_after REAL,           -- 中小型存款类金融机构-调整后
                update_time                 TEXT                -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_money_supply_month(self, conn: sqlite3.Connection) -> None:
        """货币供应量(月):query_money_supply_data_month()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS money_supply_month (
                stat_year  INTEGER NOT NULL,   -- 统计年度
                stat_month INTEGER NOT NULL,   -- 统计月份
                m0_month   REAL,               -- 货币供应量M0(月)
                m0_yoy     REAL,               -- 货币供应量M0(同比)
                m0_chain   REAL,               -- 货币供应量M0(环比)
                m1_month   REAL,               -- 货币供应量M1(月)
                m1_yoy     REAL,               -- 货币供应量M1(同比)
                m1_chain   REAL,               -- 货币供应量M1(环比)
                m2_month   REAL,               -- 货币供应量M2(月)
                m2_yoy     REAL,               -- 货币供应量M2(同比)
                m2_chain   REAL,               -- 货币供应量M2(环比)
                update_time TEXT,              -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
                PRIMARY KEY (stat_year, stat_month)
            )
        """)

    def _create_money_supply_year(self, conn: sqlite3.Connection) -> None:
        """货币供应量(年底余额):query_money_supply_data_year()"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS money_supply_year (
                stat_year   INTEGER PRIMARY KEY,   -- 统计年度
                m0_year     REAL,                  -- 货币供应量M0(年底余额, 亿元)
                m0_year_yoy REAL,                  -- 货币供应量M0(同比)
                m1_year     REAL,                  -- 货币供应量M1(年底余额, 亿元)
                m1_year_yoy REAL,                  -- 货币供应量M1(同比)
                m2_year     REAL,                  -- 货币供应量M2(年底余额, 亿元)
                m2_year_yoy REAL,                  -- 货币供应量M2(同比)
                update_time TEXT                   -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def _create_request_count(self, conn: sqlite3.Connection) -> None:
        """API 请求每日计数"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_count (
                date        TEXT PRIMARY KEY,           -- 日期 (YYYY-MM-DD，唯一)
                count       INTEGER NOT NULL DEFAULT 0, -- 当日请求次数
                update_time TEXT                        -- 数据下载时间 (格式:YYYY-MM-DD HH:MM:SS)
            )
        """)

    def get_max_date(self, table: str, date_column: str = "date") -> str | None:
        conn = self.get_connection()
        cursor = conn.execute(f"SELECT MAX({date_column}) FROM {table}")
        row = cursor.fetchone()
        if row and row[0] is not None:
            return row[0]
        return None

    def is_trading_day(self, date_str: str) -> bool:
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT is_trading_day FROM trade_dates WHERE calendar_date = ?",
            (date_str,)
        )
        row = cursor.fetchone()
        if row:
            return row[0] == 1
        return False

    def get_latest_trading_day_on_or_before(self, date_str: str) -> str | None:
        """Find the most recent trading day on or before the given date."""
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date DESC LIMIT 1",
            (date_str,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def migrate_schema(self) -> None:
        conn = self.get_connection()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        self._add_update_time_to_tables(conn, tables)

        if "dividend" in tables:
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(dividend)").fetchall()
            }
            if "year_type" in cols:
                pk_sql = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name='dividend'"
                ).fetchone()
                if pk_sql and "year_type" not in pk_sql[0].split("PRIMARY KEY")[1]:
                    self._migrate_dividend_pk(conn)

        if "money_supply_year" in tables:
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(money_supply_year)").fetchall()
            }
            if "m0_year" not in cols:
                self._migrate_money_supply_year(conn)

        if "stock_industry" in tables:
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(stock_industry)").fetchall()
            }
            if "code" not in cols or "update_date" not in cols:
                self._migrate_stock_industry(conn)

        if "all_stock" not in tables:
            self._create_all_stock(conn)

        if "request_count" not in tables:
            self._create_request_count(conn)

        conn.commit()

    def _add_update_time_to_tables(self, conn: sqlite3.Connection, tables: set[str]) -> None:
        all_tables = [
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
            "money_supply_month", "money_supply_year", "request_count",
        ]
        for table in all_tables:
            if table not in tables:
                continue
            cols = {
                r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "update_time" not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN update_time TEXT"
                )

    def _migrate_dividend_pk(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE dividend RENAME TO dividend_old")
        self._create_dividend(conn)
        conn.execute("""
            INSERT OR IGNORE INTO dividend
            SELECT * FROM dividend_old
        """)
        conn.execute("DROP TABLE dividend_old")

    def _migrate_money_supply_year(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE money_supply_year RENAME TO money_supply_year_old")
        self._create_money_supply_year(conn)
        conn.execute("""
            INSERT OR IGNORE INTO money_supply_year (stat_year)
            SELECT stat_year FROM money_supply_year_old
        """)
        conn.execute("DROP TABLE money_supply_year_old")

    def _migrate_stock_industry(self, conn: sqlite3.Connection) -> None:
        """Migrate stock_industry table from old schema to new schema.

        Old schema had positional column names (0, 1, 2, 3, 4).
        Since we cannot reliably map old columns to new ones, we recreate
        the table and let the next download repopulate it.
        """
        conn.execute("ALTER TABLE stock_industry RENAME TO stock_industry_old")
        self._create_stock_industry(conn)
        conn.execute("DROP TABLE stock_industry_old")

    def get_downloaded_stocks(self, table: str) -> set[str]:
        conn = self.get_connection()
        cursor = conn.execute(f"SELECT DISTINCT code FROM {table}")
        return {row[0] for row in cursor.fetchall()}

    def get_today_request_count(self) -> int:
        """获取今日 API 请求次数"""
        conn = self.get_connection()
        today = date.today().isoformat()
        cursor = conn.execute(
            "SELECT count FROM request_count WHERE date = ?", (today,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def increment_request_count(self, n: int = 1) -> int:
        """增加今日 API 请求计数，返回新的计数值"""
        conn = self.get_connection()
        today = date.today().isoformat()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO request_count (date, count, update_time) VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET count = count + excluded.count, update_time = excluded.update_time
            """,
            (today, n, now),
        )
        conn.commit()
        cursor = conn.execute(
            "SELECT count FROM request_count WHERE date = ?", (today,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DBManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()