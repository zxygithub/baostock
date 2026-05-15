# BaoStock 数据下载方案

## 1. 方案概述

基于 BaoStock Python API，将中国 A 股市场数据下载并存储至 SQLite 数据库。设计原则：**一种数据一张表**，便于后续量化分析、回测和基本面研究。

### 1.1 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 数据源 | BaoStock (v0.9.1) | 免费开源，无需注册 |
| 数据库 | SQLite | 轻量级，单文件，零配置 |
| Python | 3.11+ | 通过 uv 管理 |
| ORM | 原生 sqlite3 + pandas | pandas 直接写入 SQLite |

### 1.2 数据覆盖范围

| 数据类型 | 时间范围 | 更新频率 |
|----------|----------|----------|
| 日/周/月 K 线 | 1990-12-19 至今 | 交易日 17:30 |
| 分钟 K 线 (5/15/30/60) | 近 5 年 | 次日 11:00 |
| 季频财务数据 | 2007 年至今 | 季报发布后 |
| 季频公司报告 | 2003/2006 年至今 | 季报发布后 |
| 宏观经济数据 | 视数据类型 | 不定期 |
| 行业/指数成分 | 2006-01-01 至今 | 每周一 |

---

## 2. 数据库设计

数据库文件：`baostock.db`

### 2.1 表清单（共 33 张表）

| 序号 | 表名 | 数据类型 | API 函数 | 主键 | 说明 |
|------|------|----------|----------|------|------|
| 1 | `trade_dates` | 交易日历 | `query_trade_dates()` | `calendar_date` | 交易日历信息 |
| 2 | `stock_basic` | 证券基本资料 | `query_stock_basic()` | `code` | 股票基本信息 |
| 3 | `stock_industry` | 行业分类 | `query_stock_industry()` | `code` | 行业分类信息 |
| 4 | `all_stock` | 证券代码查询 | `query_all_stock()` | `(code, day)` | 每日股票列表 |
| 5 | `all_stock_daily` | 全股票日 K 线 | `query_history_k_data_plus()` | `(code, date, adjustflag)` | 日K线数据 |
| 6 | `all_stock_weekly` | 全股票周 K 线 | `query_history_k_data_plus()` | `(code, date, adjustflag)` | 周K线数据 |
| 7 | `all_stock_monthly` | 全股票月 K 线 | `query_history_k_data_plus()` | `(code, date, adjustflag)` | 月K线数据 |
| 8 | `all_stock_5min` | 全股票 5 分钟 K 线 | `query_history_k_data_plus()` | `(code, date, time, adjustflag)` | 5分钟K线 |
| 9 | `all_stock_15min` | 全股票 15 分钟 K 线 | `query_history_k_data_plus()` | `(code, date, time, adjustflag)` | 15分钟K线 |
| 10 | `all_stock_30min` | 全股票 30 分钟 K 线 | `query_history_k_data_plus()` | `(code, date, time, adjustflag)` | 30分钟K线 |
| 11 | `all_stock_60min` | 全股票 60 分钟 K 线 | `query_history_k_data_plus()` | `(code, date, time, adjustflag)` | 60分钟K线 |
| 12 | `index_daily` | 指数日 K 线 | `query_history_k_data_plus()` | `(code, date)` | 指数日K线 |
| 13 | `index_weekly` | 指数周 K 线 | `query_history_k_data_plus()` | `(code, date, adjustflag)` | 指数周K线 |
| 14 | `index_monthly` | 指数月 K 线 | `query_history_k_data_plus()` | `(code, date, adjustflag)` | 指数月K线 |
| 15 | `dividend` | 除权除息 | `query_dividend_data()` | `(code, divid_operate_date, year_type)` | 分红数据 |
| 16 | `adjust_factor` | 复权因子 | `query_adjust_factor()` | `(code, divid_operate_date)` | 复权因子 |
| 17 | `profit_data` | 季频盈利能力 | `query_profit_data()` | `(code, year, quarter)` | 盈利能力指标 |
| 18 | `operation_data` | 季频营运能力 | `query_operation_data()` | `(code, year, quarter)` | 营运能力指标 |
| 19 | `growth_data` | 季频成长能力 | `query_growth_data()` | `(code, year, quarter)` | 成长能力指标 |
| 20 | `balance_data` | 季频偿债能力 | `query_balance_data()` | `(code, year, quarter)` | 偿债能力指标 |
| 21 | `cash_flow_data` | 季频现金流量 | `query_cash_flow_data()` | `(code, year, quarter)` | 现金流量指标 |
| 22 | `dupont_data` | 季频杜邦指数 | `query_dupont_data()` | `(code, year, quarter)` | 杜邦分析指标 |
| 23 | `performance_express` | 季频业绩快报 | `query_performance_express_report()` | `(code, performance_exp_pub_date)` | 业绩快报 |
| 24 | `forecast_report` | 季频业绩预告 | `query_forecast_report()` | `(code, profit_forecast_exp_pub_date)` | 业绩预告 |
| 25 | `sz50_stocks` | 上证 50 成分股 | `query_sz50_stocks()` | `(code, update_date)` | 上证50成分股 |
| 26 | `hs300_stocks` | 沪深 300 成分股 | `query_hs300_stocks()` | `(code, update_date)` | 沪深300成分股 |
| 27 | `zz500_stocks` | 中证 500 成分股 | `query_zz500_stocks()` | `(code, update_date)` | 中证500成分股 |
| 28 | `deposit_rate` | 存款利率 | `query_deposit_rate_data()` | `pub_date` | 存款利率 |
| 29 | `loan_rate` | 贷款利率 | `query_loan_rate_data()` | `pub_date` | 贷款利率 |
| 30 | `reserve_ratio` | 存款准备金率 | `query_required_reserve_ratio_data()` | `pub_date` | 存款准备金率 |
| 31 | `money_supply_month` | 货币供应量(月) | `query_money_supply_data_month()` | `(stat_year, stat_month)` | 月度货币供应量 |
| 32 | `money_supply_year` | 货币供应量(年) | `query_money_supply_data_year()` | `stat_year` | 年度货币供应量 |
| 33 | `request_count` | API 请求计数 | - | `date` | 每日API请求计数 |

**注意**：原计划中的 `shibor` 表因BaoStock API不提供该接口已移除。

> **设计决策说明**：
> - K 线数据按频率分表（日线/周线/月线/分钟线），而非按股票分表，便于跨股票分析
> - 股票 K 线与指数 K 线分表，因为字段不同（指数无 preclose/turn/tradestatus/peTTM 等）
> - 分钟线不含指数，故单独存放
> - 财务数据按能力维度分表（盈利/营运/成长/偿债/现金流/杜邦），与 API 一致

---

## 3. 各表详细 Schema

### 3.1 trade_dates — 交易日历

```sql
CREATE TABLE trade_dates (
    calendar_date   TEXT PRIMARY KEY,   -- 日期 YYYY-MM-DD
    is_trading_day  INTEGER NOT NULL    -- 0:非交易日; 1:交易日
);
```

### 3.2 stock_basic — 证券基本资料

```sql
CREATE TABLE stock_basic (
    code        TEXT PRIMARY KEY,   -- 证券代码 sh.600000
    code_name   TEXT,               -- 证券名称
    ipo_date    TEXT,               -- 上市日期 YYYY-MM-DD
    out_date    TEXT,               -- 退市日期
    type        INTEGER,            -- 1:股票 2:指数 3:其它 4:可转债 5:ETF
    status      INTEGER             -- 1:上市 0:退市
);
```

### 3.3 stock_industry — 行业分类

```sql
CREATE TABLE stock_industry (
    code            TEXT PRIMARY KEY,   -- 证券代码
    code_name       TEXT,               -- 证券名称
    industry        TEXT,               -- 所属行业
    industry_classification TEXT        -- 行业分类标准(申万一级)
);
```

### 3.4 all_stock_daily — 股票日 K 线

```sql
CREATE TABLE all_stock_daily (
    code        TEXT NOT NULL,          -- 证券代码
    date        TEXT NOT NULL,          -- 行情日期 YYYY-MM-DD
    open        REAL,                   -- 开盘价
    high        REAL,                   -- 最高价
    low         REAL,                   -- 最低价
    close       REAL,                   -- 收盘价
    preclose    REAL,                   -- 前收盘价
    volume      REAL,                   -- 成交量(股)
    amount      REAL,                   -- 成交额(元)
    adjustflag  INTEGER,                -- 复权状态 1:后复权 2:前复权 3:不复权
    turn        REAL,                   -- 换手率(%)
    tradestatus INTEGER,                -- 交易状态 1:正常 0:停牌
    pct_chg     REAL,                   -- 涨跌幅(%)
    pe_ttm      REAL,                   -- 滚动市盈率
    pb_mrq      REAL,                   -- 市净率
    ps_ttm      REAL,                   -- 滚动市销率
    pcf_ncf_ttm REAL,                   -- 滚动市现率
    is_st       INTEGER,                -- 是否ST 1:是 0:否
    PRIMARY KEY (code, date, adjustflag)
);

CREATE INDEX idx_daily_date ON all_stock_daily(date);
CREATE INDEX idx_daily_code ON all_stock_daily(code);
```

### 3.5 all_stock_weekly — 股票周 K 线

```sql
CREATE TABLE all_stock_weekly (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,          -- 周最后一个交易日
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  INTEGER,
    turn        REAL,
    pct_chg     REAL,
    PRIMARY KEY (code, date, adjustflag)
);
```

### 3.6 all_stock_monthly — 股票月 K 线

```sql
CREATE TABLE all_stock_monthly (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,          -- 月最后一个交易日
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  INTEGER,
    turn        REAL,
    pct_chg     REAL,
    PRIMARY KEY (code, date, adjustflag)
);
```

### 3.7~3.10 all_stock_*min — 分钟 K 线 (5/15/30/60)

```sql
-- 以 5 分钟线为例，15/30/60 分钟结构相同
CREATE TABLE all_stock_5min (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,          -- 行情日期 YYYY-MM-DD
    time        TEXT NOT NULL,          -- 行情时间 YYYYMMDDHHMMSSsss
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  INTEGER,
    PRIMARY KEY (code, date, time, adjustflag)
);

CREATE INDEX idx_5min_datetime ON all_stock_5min(date, time);
```

### 3.11 index_daily — 指数日 K 线

```sql
CREATE TABLE index_daily (
    code        TEXT NOT NULL,          -- 指数代码 sh.000001
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    preclose    REAL,
    volume      REAL,
    amount      REAL,
    pct_chg     REAL,
    PRIMARY KEY (code, date)
);

CREATE INDEX idx_index_date ON index_daily(date);
```

### 3.12~3.13 index_weekly / index_monthly

```sql
CREATE TABLE index_weekly (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  INTEGER,
    turn        REAL,
    pct_chg     REAL,
    PRIMARY KEY (code, date, adjustflag)
);

CREATE TABLE index_monthly (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    amount      REAL,
    adjustflag  INTEGER,
    turn        REAL,
    pct_chg     REAL,
    PRIMARY KEY (code, date, adjustflag)
);
```

### 3.14 dividend — 除权除息

```sql
CREATE TABLE dividend (
    code                    TEXT NOT NULL,
    divid_pre_notice_date   TEXT,       -- 预批露公告日
    divid_agm_pum_date      TEXT,       -- 股东大会公告日期
    divid_plan_announce_date TEXT,      -- 预案公告日
    divid_plan_date         TEXT,       -- 分红实施公告日
    divid_regist_date       TEXT,       -- 股权登记日
    divid_operate_date      TEXT,       -- 除权除息日
    divid_pay_date          TEXT,       -- 派息日
    divid_stock_market_date TEXT,       -- 红股上市日
    divid_cash_ps_before_tax REAL,      -- 每股股利(税前)
    divid_cash_ps_after_tax  REAL,      -- 每股股利(税后)
    divid_stocks_ps         REAL,       -- 每股红股
    divid_cash_stock        TEXT,       -- 分红送转描述
    divid_reserve_to_stock_ps REAL,     -- 每股转增资本
    year                    INTEGER,    -- 年份
    year_type               TEXT,       -- report/operate
    PRIMARY KEY (code, divid_operate_date)
);
```

### 3.15 adjust_factor — 复权因子

```sql
CREATE TABLE adjust_factor (
    code                TEXT NOT NULL,
    divid_operate_date  TEXT NOT NULL,  -- 除权除息日
    fore_adjust_factor  REAL,           -- 向前复权因子
    back_adjust_factor  REAL,           -- 向后复权因子
    adjust_factor       REAL,           -- 本次复权因子
    PRIMARY KEY (code, divid_operate_date)
);
```

### 3.16 profit_data — 季频盈利能力

```sql
CREATE TABLE profit_data (
    code        TEXT NOT NULL,
    pub_date    TEXT,                   -- 财报发布日期
    stat_date   TEXT,                   -- 统计季度最后一天
    roe_avg     REAL,                   -- 净资产收益率(平均)(%)
    np_margin   REAL,                   -- 销售净利率(%)
    gp_margin   REAL,                   -- 销售毛利率(%)
    net_profit  REAL,                   -- 净利润(元)
    eps_ttm     REAL,                   -- 每股收益
    mb_revenue  REAL,                   -- 主营营业收入(元)
    total_share REAL,                   -- 总股本
    liqa_share  REAL,                   -- 流通股本
    year        INTEGER,
    quarter     INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.17 operation_data — 季频营运能力

```sql
CREATE TABLE operation_data (
    code            TEXT NOT NULL,
    pub_date        TEXT,
    stat_date       TEXT,
    nr_turn_ratio   REAL,               -- 应收账款周转率(次)
    nr_turn_days    REAL,               -- 应收账款周转天数
    inv_turn_ratio  REAL,               -- 存货周转率(次)
    inv_turn_days   REAL,               -- 存货周转天数
    ca_turn_ratio   REAL,               -- 流动资产周转率(次)
    asset_turn_ratio REAL,              -- 总资产周转率
    year            INTEGER,
    quarter         INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.18 growth_data — 季频成长能力

```sql
CREATE TABLE growth_data (
    code            TEXT NOT NULL,
    pub_date        TEXT,
    stat_date       TEXT,
    yoy_equity      REAL,               -- 净资产同比增长率
    yoy_asset       REAL,               -- 总资产同比增长率
    yoy_ni          REAL,               -- 净利润同比增长率
    yoy_eps_basic   REAL,               -- 基本每股收益同比增长率
    yoy_pni         REAL,               -- 归属母公司股东净利润同比增长率
    year            INTEGER,
    quarter         INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.19 balance_data — 季频偿债能力

```sql
CREATE TABLE balance_data (
    code                TEXT NOT NULL,
    pub_date            TEXT,
    stat_date           TEXT,
    current_ratio       REAL,           -- 流动比率
    quick_ratio         REAL,           -- 速动比率
    cash_ratio          REAL,           -- 现金比率
    yoy_liability       REAL,           -- 总负债同比增长率
    liability_to_asset  REAL,           -- 资产负债率
    asset_to_equity     REAL,           -- 权益乘数
    year                INTEGER,
    quarter             INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.20 cash_flow_data — 季频现金流量

```sql
CREATE TABLE cash_flow_data (
    code                TEXT NOT NULL,
    pub_date            TEXT,
    stat_date           TEXT,
    ca_to_asset         REAL,           -- 流动资产/总资产
    nca_to_asset        REAL,           -- 非流动资产/总资产
    tangible_asset_to_asset REAL,       -- 有形资产/总资产
    ebit_to_interest    REAL,           -- 已获利息倍数
    cfo_to_or           REAL,           -- 经营现金流/营业收入
    cfo_to_np           REAL,           -- 经营现金流/净利润
    cfo_to_gr           REAL,           -- 经营现金流/营业总收入
    year                INTEGER,
    quarter             INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.21 dupont_data — 季频杜邦指数

```sql
CREATE TABLE dupont_data (
    code                    TEXT NOT NULL,
    pub_date                TEXT,
    stat_date               TEXT,
    dupont_roe              REAL,           -- 净资产收益率
    dupont_asset_to_equity  REAL,           -- 权益乘数
    dupont_asset_turn       REAL,           -- 总资产周转率
    dupont_pni_to_ni        REAL,           -- 归属母公司净利润/净利润
    dupont_ni_to_gr         REAL,           -- 净利润/营业总收入
    dupont_tax_burden       REAL,           -- 税负水平
    dupont_int_burden       REAL,           -- 利息负担
    dupont_ebit_to_gr       REAL,           -- 经营利润率
    year                    INTEGER,
    quarter                 INTEGER,
    PRIMARY KEY (code, year, quarter)
);
```

### 3.22 performance_express — 季频业绩快报

```sql
CREATE TABLE performance_express (
    code                        TEXT NOT NULL,
    performance_exp_pub_date    TEXT,       -- 业绩快报披露日
    performance_exp_stat_date   TEXT,       -- 统计日期
    performance_exp_update_date TEXT,       -- 最新披露日
    total_asset                 REAL,       -- 总资产
    net_asset                   REAL,       -- 净资产
    eps_chg_pct                 REAL,       -- 每股收益增长率
    roe_wa                      REAL,       -- ROE-加权
    eps_diluted                 REAL,       -- 每股收益-摊薄
    gr_yoy                      REAL,       -- 营业总收入同比
    op_yoy                      REAL,       -- 营业利润同比
    PRIMARY KEY (code, performance_exp_pub_date)
);
```

### 3.23 forecast_report — 季频业绩预告

```sql
CREATE TABLE forecast_report (
    code                        TEXT NOT NULL,
    profit_forecast_exp_pub_date TEXT,      -- 业绩预告发布日期
    profit_forecast_exp_stat_date TEXT,     -- 统计日期
    profit_forecast_type        TEXT,       -- 预告类型
    profit_forecast_abstract    TEXT,       -- 预告摘要
    profit_forecast_chg_pct_up  REAL,       -- 增长上限(%)
    profit_forecast_chg_pct_down REAL,      -- 增长下限(%)
    PRIMARY KEY (code, profit_forecast_exp_pub_date)
);
```

### 3.24~3.26 指数成分股表

```sql
CREATE TABLE sz50_stocks (
    code        TEXT NOT NULL,          -- 成分股代码
    code_name   TEXT,                   -- 成分股名称
    update_date TEXT,                   -- 更新日期
    PRIMARY KEY (code, update_date)
);

CREATE TABLE hs300_stocks (
    code        TEXT NOT NULL,
    code_name   TEXT,
    update_date TEXT,
    PRIMARY KEY (code, update_date)
);

CREATE TABLE zz500_stocks (
    code        TEXT NOT NULL,
    code_name   TEXT,
    update_date TEXT,
    PRIMARY KEY (code, update_date)
);
```

### 3.27 deposit_rate — 存款利率

```sql
CREATE TABLE deposit_rate (
    pub_date                        TEXT PRIMARY KEY,   -- 发布日期
    demand_deposit_rate             REAL,               -- 活期存款
    fixed_deposit_rate_3_month      REAL,               -- 定期3个月
    fixed_deposit_rate_6_month      REAL,               -- 定期6个月
    fixed_deposit_rate_1_year       REAL,               -- 定期1年
    fixed_deposit_rate_2_year       REAL,               -- 定期2年
    fixed_deposit_rate_3_year       REAL,               -- 定期3年
    fixed_deposit_rate_5_year       REAL,               -- 定期5年
    installment_fixed_rate_1_year   REAL,               -- 零存整取1年
    installment_fixed_rate_3_year   REAL,               -- 零存整取3年
    installment_fixed_rate_5_year   REAL                -- 零存整取5年
);
```

### 3.28 loan_rate — 贷款利率

```sql
CREATE TABLE loan_rate (
    pub_date                    TEXT PRIMARY KEY,
    loan_rate_6_month           REAL,       -- 6个月贷款利率
    loan_rate_6m_to_1y          REAL,       -- 6个月至1年
    loan_rate_1y_to_3y          REAL,       -- 1年至3年
    loan_rate_3y_to_5y          REAL,       -- 3年至5年
    loan_rate_above_5y          REAL,       -- 5年以上
    mortgage_rate_below_5y      REAL,       -- 5年以下公积金
    mortgage_rate_above_5y      REAL        -- 5年以上公积金
);
```

### 3.29 reserve_ratio — 存款准备金率

```sql
CREATE TABLE reserve_ratio (
    pub_date                    TEXT PRIMARY KEY,   -- 公告日期
    effective_date              TEXT,               -- 生效日期
    big_institutions_ratio_pre  REAL,               -- 大型金融机构-调整前
    big_institutions_ratio_after REAL,              -- 大型金融机构-调整后
    medium_institutions_ratio_pre REAL,             -- 中小型-调整前
    medium_institutions_ratio_after REAL            -- 中小型-调整后
);
```

### 3.30 money_supply_month — 货币供应量(月度)

```sql
CREATE TABLE money_supply_month (
    stat_year       INTEGER NOT NULL,
    stat_month      INTEGER NOT NULL,
    m0_month        REAL,               -- M0(当月)
    m0_yoy          REAL,               -- M0同比
    m0_chain        REAL,               -- M0环比
    m1_month        REAL,               -- M1(当月)
    m1_yoy          REAL,               -- M1同比
    m1_chain        REAL,               -- M1环比
    m2_month        REAL,               -- M2(当月)
    m2_yoy          REAL,               -- M2同比
    m2_chain        REAL,               -- M2环比
    PRIMARY KEY (stat_year, stat_month)
);
```

### 3.31 money_supply_year — 货币供应量(年底余额)

```sql
CREATE TABLE money_supply_year (
    stat_year   INTEGER PRIMARY KEY,
    m0_year     REAL,               -- M0(年底余额, 亿元)
    m0_year_yoy REAL,               -- M0同比
    m1_year     REAL,               -- M1(年底余额, 亿元)
    m1_year_yoy REAL,               -- M1同比
    m2_year     REAL,               -- M2(年底余额, 亿元)
    m2_year_yoy REAL,               -- M2同比
    update_time TEXT                -- 数据下载时间
);
```

> ~~### 3.32 shibor — 银行间同业拆放利率~~
>
> 已移除：BaoStock API 不提供 shibor 接口，该表已从计划中删除。

---

## 4. 下载策略

### 4.1 下载顺序

```
Phase 1: 基础元数据 (一次性)
  ├── trade_dates       (全量)
  ├── stock_basic       (全量)
  ├── stock_industry    (全量)
  ├── sz50_stocks       (全量)
  ├── hs300_stocks      (全量)
  └── zz500_stocks      (全量)

Phase 2: 宏观经济数据 (一次性)
  ├── deposit_rate
  ├── loan_rate
  ├── reserve_ratio
  ├── money_supply_month
  └── money_supply_year

Phase 3: K 线数据 (按批次, 每批后短暂休眠)
  ├── index_daily       (所有指数, 日/周/月)
  ├── all_stock_daily   (分批: 每批 200 只股票)
  ├── all_stock_weekly
  ├── all_stock_monthly
  └── all_stock_*min    (近5年数据, 分批)

Phase 4: 财务数据 (按年份, 每批后短暂休眠)
  ├── profit_data       (2007-至今, 逐年)
  ├── operation_data
  ├── growth_data
  ├── balance_data
  ├── cash_flow_data
  └── dupont_data

Phase 5: 公司报告 (按日期范围)
  ├── performance_express
  └── forecast_report

Phase 6: 分红与复权 (按股票)
  ├── dividend
  └── adjust_factor
```

### 4.2 防超时策略

| 策略 | 说明 |
|------|------|
| 批次大小 | K 线数据每批 200 只股票 |
| 批次间隔 | 每批之间 `time.sleep(2)` |
| 登录刷新 | 每 30 分钟重新 `bs.login()` |
| 重试机制 | 失败重试 3 次，指数退避 |
| 断点续传 | 记录已下载的股票+日期范围 |

### 4.3 增量更新策略

| 数据类型 | 更新方式 |
|----------|----------|
| 日 K 线 | 查询 `MAX(date)` 后的数据 |
| 周/月 K 线 | 查询 `MAX(date)` 后的数据 |
| 分钟 K 线 | 查询 `MAX(date)` 后近 5 天数据 |
| 财务数据 | 查询当前年/季度的数据 |
| 指数成分 | 每周一全量更新 |
| 宏观数据 | 全量查询（数据量小） |

---

## 5. 项目文件结构

```
baostock/
├── config.yaml                    # 用户配置文件
├── pyproject.toml                 # Python项目配置
├── start.sh                       # 主要入口脚本
├── clean_data.sh                  # 数据管理脚本
├── clean_memory.sh                # 内存清理脚本
├── data/
│   └── baostock.db                # SQLite 数据库文件
├── logs/                          # 日志文件
├── docs/                          # 项目文档
├── scripts/
│   ├── init_db.py                 # 初始化数据库 (建表)
│   ├── download_all.py            # 全量下载入口
│   ├── update_daily.py            # 每日增量更新
│   ├── daily_report.py            # 邮件日报
│   ├── check_blacklist.py         # 黑名单检测
│   ├── analyze_latest_dates.py    # 最新日期分析
│   └── estimate_data_volume.py    # 数据量估算
├── src/
│   ├── __init__.py
│   ├── config.py                  # 技术常量 (字段定义、路径、指数代码)
│   ├── config_loader.py           # 配置加载器 (从 config.yaml 读取)
│   ├── db_manager.py              # 数据库初始化、连接管理
│   ├── downloaders/
│   │   ├── __init__.py
│   │   ├── base.py                # 下载器基类 (登录/登出/重试/休眠)
│   │   ├── meta_downloader.py     # 元数据下载 (交易日历/股票列表/行业)
│   │   ├── kline_downloader.py    # K 线数据下载 (日/周/月/分钟)
│   │   ├── financial_downloader.py # 财务数据下载 (6 类)
│   │   ├── report_downloader.py   # 公司报告下载
│   │   ├── dividend_downloader.py # 分红与复权下载
│   │   ├── index_downloader.py    # 指数数据下载
│   │   ├── macro_downloader.py    # 宏观经济数据下载
│   │   └── component_downloader.py # 指数成分股下载
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py             # 工具函数 (类型转换、日期处理)
│       └── validator.py           # 数据验证
└── tests/
    ├── test_helpers.py            # helpers.py 单元测试
    ├── smoke_test.py              # 冒烟测试
    └── integration_test.py        # 集成测试
```

### 配置系统说明

项目采用**三层次配置**设计：

| 文件 | 职责 | 修改频率 | 使用者 |
|------|------|----------|--------|
| `config.yaml` | 用户配置（开关、日期、批处理参数） | 经常调整 | 用户 |
| `.env` | 敏感凭据（邮箱 SMTP 等） | 初始设置 | 用户 |
| `src/config.py` | 技术常量（字段定义、路径、指数代码） | 几乎不改 | 开发者 |
| `src/config_loader.py` | 配置加载器 | 几乎不改 | 代码 |

**配置加载流程**：
1. 所有下载器通过 `config_loader.py` 统一从 `config.yaml` 读取用户配置
2. 敏感凭据从 `.env` 文件读取
3. 技术常量（如字段定义）直接从 `config.py` 导入
4. 用户只需编辑 `config.yaml` 即可控制所有下载行为

---

## 6. 核心下载流程伪代码

```python
# 基础下载器模式
class BaseDownloader:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.login()

    def login(self):
        lg = bs.login()
        if lg.error_code != '0':
            raise ConnectionError(f"登录失败: {lg.error_msg}")

    def logout(self):
        bs.logout()

    def download_with_retry(self, func, max_retries=3, **kwargs):
        for attempt in range(max_retries):
            try:
                result = func(**kwargs)
                if result.error_code == '0':
                    return result
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
        raise Exception("下载失败")

    def save_to_sqlite(self, df: pd.DataFrame, table: str, if_exists='append'):
        df.to_sql(table, self.conn, if_exists=if_exists, index=False)

# 日 K 线下载示例
def download_daily_kline(stock_codes: list, start_date: str, end_date: str):
    fields = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"

    for i in range(0, len(stock_codes), BATCH_SIZE):
        batch = stock_codes[i:i+BATCH_SIZE]
        for code in batch:
            for adjustflag in [1, 2, 3]:  # 后复权/前复权/不复权
                rs = bs.query_history_k_data_plus(
                    code, fields,
                    start_date=start_date, end_date=end_date,
                    frequency="d", adjustflag=str(adjustflag)
                )
                data = fetch_all_rows(rs)
                df = pd.DataFrame(data, columns=rs.fields)
                df.to_sql('all_stock_daily', conn, if_exists='append', index=False)
        time.sleep(2)  # 批次间隔
```

---

## 7. 注意事项

### 7.1 BaoStock 限制

| 限制 | 说明 |
|------|------|
| 会话超时 | 登录后一段时间不操作会超时，需重新登录 |
| 分钟线范围 | 仅提供近 5 年数据 |
| 指数分钟线 | 不提供 |
| 财务数据 | 仅提供 2007 年至今 |
| 复权方式 | 使用"涨跌幅复权法"，与同花顺/通达信可能不一致 |
| 停牌数据 | 停牌时 OHLC 相同，volume/amount 为 0，turn 为空 |

### 7.2 SQLite 注意事项

| 事项 | 说明 |
|------|------|
| 并发写入 | SQLite 不支持高并发写入，下载时单线程 |
| 文件大小 | 全量数据预计 2-5GB，SQLite 可轻松处理 |
| 类型映射 | BaoStock 返回 string，入库时需转换 REAL/INTEGER |
| WAL 模式 | 建议开启 `PRAGMA journal_mode=WAL` 提升性能 |

### 7.3 数据质量

| 问题 | 处理 |
|------|------|
| 空值 | 财务数据部分字段可能为空，保持 NULL |
| 停牌 | tradestatus=0 的记录保留，用于完整时间序列 |
| 退市股票 | stock_basic 中 status=0，K 线数据保留 |
| 类型转换 | turn 字段空字符串需转为 0.0 |

---

## 8. 后续扩展

- [ ] 添加 CPI/PPI/PMI 等宏观经济指标表
- [ ] 添加概念分类表 (`query_stock_concept`)
- [ ] 添加地域分类表 (`query_stock_area`)
- [ ] 添加 ST/退市股票列表
- [ ] 添加沪港通/深港通标的表
- [ ] 支持 PostgreSQL/MySQL 切换
- [ ] 添加数据校验与完整性检查
- [ ] 添加下载进度可视化
