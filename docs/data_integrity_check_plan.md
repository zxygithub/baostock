# 数据完整性校验方案

> 创建日期: 2026-07-26
> 状态: 待评审

## 1. 概述

### 1.1 目标

校验 BaoStock 数据库中已下载数据的完整性，找出所有缺失数据，生成可操作的缺失报告，后续根据报告补齐数据。

### 1.2 核心依赖

整个校验体系建立在两张基础表之上：

| 基础表 | 关键字段 | 用途 |
|--------|----------|------|
| `trade_dates` | `calendar_date`, `is_trading_day` | 确定"应该有多少个交易日" |
| `stock_basic` | `code`, `ipo_date`, `out_date`, `type`, `status` | 确定每只股票"从哪天有数据"到"哪天结束" |

### 1.3 校验基准日与预期截止日

校验时需要定义两个关键时间点：

| 概念 | 定义 | 说明 |
|------|------|------|
| **校验基准日** (`check_date`) | 运行校验的日期（默认为今天） | 用户可通过 `--date` 参数指定 |
| **预期截止日** (`expected_cutoff`) | `check_date` 之前的最近一个交易日（含 `check_date` 当天如果是交易日） | 完整数据至少应覆盖到此日期 |

**预期截止日计算逻辑**：

```python
def get_expected_cutoff(check_date: str, trading_days: list[str]) -> str:
    """
    获取预期截止日：check_date 之前的最近一个交易日（含 check_date 当天）
    
    例如：
    - check_date = "2026-07-26" (周日) -> expected_cutoff = "2026-07-25" (周五)
    - check_date = "2026-07-25" (周五，交易日) -> expected_cutoff = "2026-07-25"
    - check_date = "2026-07-21" (周一，交易日) -> expected_cutoff = "2026-07-21"
    """
    # 找到 <= check_date 的最大交易日
    candidates = [d for d in trading_days if d <= check_date]
    return max(candidates) if candidates else None
```

**核心公式**：

```
股票 s 的预期数据终点 = 
    - 退市股票: min(s.out_date, expected_cutoff)
    - 上市股票: expected_cutoff

股票 s 的预期数据范围 = trade_dates 中 [s.ipo_date, 预期数据终点] 的记录
预期数据量 = 上述范围内的交易日数（或周/月/季度数）
实际数据量 = 对应数据表中的实际记录数
完整度 = 实际 / 预期
```

**示例**：

```
假设 check_date = 2026-07-26 (周日)
     expected_cutoff = 2026-07-25 (周五，最近交易日)

股票 sh.600000 (浦发银行, status=1, ipo_date=1999-11-10, out_date=NULL):
    预期数据范围 = [1999-11-10, 2026-07-25] 内的所有交易日
    预期天数 = 6,543 天
    
股票 sh.600842 (中兴商业, status=0, ipo_date=1996-05-16, out_date=2023-08-15):
    预期数据终点 = min(2023-08-15, 2026-07-25) = 2023-08-15
    预期数据范围 = [1996-05-16, 2023-08-15] 内的所有交易日
```

### 1.4 校验范围

- **所有股票**：包括上市中 (`status=1`) 和已退市 (`status=0`)，退市股票同样严格校验
- **不做粗筛**：每只股票都做完整的空洞检测
- **所有数据类别**：K 线、财务、分红、指数、宏观
- **时间范围**：所有数据至少应覆盖到 `expected_cutoff`（校验基准日之前的最近交易日）

### 1.5 输出

- 结果写入文件 `data/integrity_report.json`，结构化 JSON 格式，方便后续程序读取并补齐数据
- 同时在终端输出可读的摘要报告

---

## 2. 校验层级

共 8 层，从基础到细节逐层递进。

| 层级 | 名称 | 说明 |
|------|------|------|
| L1 | 基础表自身完整性 | 确保 trade_dates 和 stock_basic 本身可靠 |
| L2 | K 线覆盖率 | 日/周/月线，每只股票每种复权的覆盖情况 |
| L3 | K 线日期连续性 | 找出每只股票缺失的具体交易日 |
| L4 | 财务数据覆盖率 | 6 类财务数据的季度覆盖 + 六表一致性 |
| L5 | 分红与复权因子 | 分红年度覆盖 + 复权因子与分红事件匹配 |
| L6 | 指数 K 线 | 8 个指数的日/周/月线覆盖 |
| L7 | 宏观数据 | 利率、准备金率、货币供应量 |
| L8 | 数据质量 | 数值合理性检查 |

---

## 3. 各层详细设计

### 3.1 L1 — 基础表自身完整性

在校验其他表之前，先确认这两张基础表本身是可靠的。

| 检查项 | 校验逻辑 | 异常判定 |
|--------|----------|----------|
| 交易日历覆盖起点 | `MIN(calendar_date)` | 应 <= 1990-12-19 |
| 交易日历覆盖终点 | `MAX(calendar_date)` | 应 >= `expected_cutoff`（见 1.3 节） |
| **交易日历覆盖校验基准日** | `MAX(calendar_date) WHERE is_trading_day=1` | **必须 >= `expected_cutoff`**，否则无法判断数据是否完整 |
| 交易日总数 | `COUNT(*) WHERE is_trading_day=1` | 应 > 8000 |
| 最近交易日 | `MAX(calendar_date) WHERE is_trading_day=1` | 与 `expected_cutoff` 的差距不应超过 7 天（排除长假） |
| 股票总数 | `COUNT(*) WHERE type=1` | 应 > 4000 |
| IPO 日期缺失 | `COUNT(*) WHERE type=1 AND (ipo_date IS NULL OR ipo_date='')` | 占比应 < 5% |
| 退市股标记 | `COUNT(*) WHERE type=1 AND status=0 AND (out_date IS NULL OR out_date='')` | 退市股票必须有 out_date |
| 行业分类覆盖 | `COUNT(DISTINCT code) FROM stock_industry` / 股票总数 | 应 > 90% |
| 指数成分股 | sz50=50, hs300=300, zz500=500 | 各指数最新一批应有正确数量 |

**关键检查**：如果 `trade_dates` 的最新交易日 < `expected_cutoff`，说明交易日历未更新到最新，后续所有校验都不可靠，应**中止校验**并提示用户先更新交易日历。

---

### 3.2 L2 — K 线数据覆盖率

#### 3.2.1 日 K 线 (`all_stock_daily`)

**预期行数计算**：

对每只股票 `s`（`type=1`，包括上市中和已退市）：

```
# 上市中股票：数据应至少到 expected_cutoff
# 退市股票：数据应到 min(out_date, expected_cutoff)

if s.status == 1:  # 上市中
    effective_end = expected_cutoff
elif s.status == 0:  # 已退市
    effective_end = min(s.out_date, expected_cutoff)

expected_days = trade_dates 中 [s.ipo_date, effective_end] 范围内 is_trading_day=1 的数量
```

**SQL 实现**：

```sql
SELECT 
    s.code,
    s.code_name,
    s.ipo_date,
    s.out_date,
    s.status,
    -- 预期终点：上市股票 = expected_cutoff，退市股票 = min(out_date, expected_cutoff)
    CASE 
        WHEN s.status = 1 THEN :expected_cutoff
        ELSE MIN(COALESCE(s.out_date, :expected_cutoff), :expected_cutoff)
    END AS effective_end,
    -- 预期天数：该股票存续期内（到 effective_end）的交易日数
    (SELECT COUNT(*) FROM trade_dates td 
     WHERE td.is_trading_day = 1 
     AND td.calendar_date >= s.ipo_date 
     AND td.calendar_date <= CASE 
         WHEN s.status = 1 THEN :expected_cutoff
         ELSE MIN(COALESCE(s.out_date, :expected_cutoff), :expected_cutoff)
     END
    ) AS expected_days,
    -- 实际天数：每种 adjustflag 的实际数据天数
    (SELECT COUNT(DISTINCT date) FROM all_stock_daily d WHERE d.code = s.code AND d.adjustflag = 1) AS actual_adj1,
    (SELECT COUNT(DISTINCT date) FROM all_stock_daily d WHERE d.code = s.code AND d.adjustflag = 2) AS actual_adj2,
    (SELECT COUNT(DISTINCT date) FROM all_stock_daily d WHERE d.code = s.code AND d.adjustflag = 3) AS actual_adj3
FROM stock_basic s
WHERE s.type = 1
ORDER BY expected_days DESC;
```

**实际行数统计**：

```sql
SELECT code, adjustflag, COUNT(DISTINCT date) AS actual_days
FROM all_stock_daily
GROUP BY code, adjustflag
```

**覆盖率计算**：

```
coverage = actual_days / expected_days
```

**三种 adjustflag 分别统计**，因为下载逻辑是 `for adjustflag in [1, 2, 3]` 循环下载的，任何一种缺失都意味着下载中断。

**输出报告**：

```
日 K 线覆盖率统计 (adjustflag=3 不复权)
─────────────────────────────────────────────
完全覆盖 (100%)     : 4,812 只
>= 95% 覆盖         :   312 只
80% ~ 95% 覆盖      :    58 只   <-- 需关注
< 80% 覆盖          :    12 只   <-- 异常
零数据              :     0 只

低覆盖股票明细 (< 100%):
  code         name     ipo_date    out_date    预期天数  实际天数  覆盖率  adjustflag
  sh.688xxx    XX科技   2020-01-01  NULL        1,620     1,200    74.1%   3
  sz.300xxx    XX集团   2015-06-01  2023-08-15  2,010     1,500    74.6%   3
```

#### 3.2.2 周 K 线 (`all_stock_weekly`)

预期计算：股票存续期内（到 `effective_end`），trade_dates 中不同 `(year, week)` 的数量。

```sql
-- 预期周数
SELECT s.code,
    COUNT(DISTINCT strftime('%Y-%W', td.calendar_date)) AS expected_weeks
FROM stock_basic s
JOIN trade_dates td ON td.is_trading_day = 1
    AND td.calendar_date >= s.ipo_date
    AND td.calendar_date <= CASE 
        WHEN s.status = 1 THEN :expected_cutoff
        ELSE MIN(COALESCE(s.out_date, :expected_cutoff), :expected_cutoff)
    END
WHERE s.type = 1
GROUP BY s.code;
```

#### 3.2.3 月 K 线 (`all_stock_monthly`)

预期计算：股票存续期内（到 `effective_end`），trade_dates 中不同 `(year, month)` 的数量。

```sql
-- 预期月数
SELECT s.code,
    COUNT(DISTINCT strftime('%Y-%m', td.calendar_date)) AS expected_months
FROM stock_basic s
JOIN trade_dates td ON td.is_trading_day = 1
    AND td.calendar_date >= s.ipo_date
    AND td.calendar_date <= CASE 
        WHEN s.status = 1 THEN :expected_cutoff
        ELSE MIN(COALESCE(s.out_date, :expected_cutoff), :expected_cutoff)
    END
WHERE s.type = 1
GROUP BY s.code;
```

---

### 3.3 L3 — K 线日期连续性（空洞检测）

**不做粗筛，所有股票都检查具体缺失日期。**

#### 3.3.1 日 K 线空洞

批量方式，一次查出所有缺失：

```sql
SELECT s.code, s.code_name, s.ipo_date, s.out_date, s.status, td.calendar_date AS missing_date
FROM stock_basic s
JOIN trade_dates td ON td.is_trading_day = 1
    AND td.calendar_date >= s.ipo_date
    AND td.calendar_date <= CASE 
        WHEN s.status = 1 THEN :expected_cutoff
        ELSE MIN(COALESCE(s.out_date, :expected_cutoff), :expected_cutoff)
    END
LEFT JOIN all_stock_daily d
    ON d.code = s.code AND d.date = td.calendar_date AND d.adjustflag = 3
WHERE s.type = 1
  AND d.code IS NULL
ORDER BY s.code, td.calendar_date;
```

**注意**：三种 adjustflag 分别检查。如果某只股票 adjustflag=3 有数据但 adjustflag=1 缺失，也需要报告。

#### 3.3.2 最新数据截止日检查（关键检查）

**这是确保"数据至少到前一天"的核心检查。**

对于上市中股票 (`status=1`)，其最新数据日期应 >= `expected_cutoff`。如果最新数据日期 < `expected_cutoff`，说明缺少最近几天的数据。

```sql
-- 找出最新数据日期 < expected_cutoff 的上市中股票
SELECT 
    s.code,
    s.code_name,
    s.ipo_date,
    MAX(d.date) AS latest_data_date,
    :expected_cutoff AS expected_cutoff,
    -- 缺失的交易日数：expected_cutoff 与 latest_data_date 之间的交易日
    (SELECT COUNT(*) FROM trade_dates td 
     WHERE td.is_trading_day = 1 
     AND td.calendar_date > MAX(d.date) 
     AND td.calendar_date <= :expected_cutoff
    ) AS missing_recent_days
FROM stock_basic s
JOIN all_stock_daily d ON d.code = s.code AND d.adjustflag = 3
WHERE s.type = 1 AND s.status = 1  -- 只检查上市中股票
GROUP BY s.code
HAVING latest_data_date < :expected_cutoff
ORDER BY missing_recent_days DESC;
```

**对于退市股票**，最新数据日期应 >= `min(out_date, expected_cutoff)` 对应的最近交易日：

```sql
-- 找出退市股票数据不完整的情况
SELECT 
    s.code,
    s.code_name,
    s.ipo_date,
    s.out_date,
    MAX(d.date) AS latest_data_date,
    -- 退市股票的预期终点：out_date 之前的最近交易日
    (SELECT MAX(calendar_date) FROM trade_dates 
     WHERE is_trading_day = 1 AND calendar_date <= s.out_date
    ) AS expected_latest_for_delisted,
    -- 缺失的交易日数
    (SELECT COUNT(*) FROM trade_dates td 
     WHERE td.is_trading_day = 1 
     AND td.calendar_date > MAX(d.date) 
     AND td.calendar_date <= (SELECT MAX(calendar_date) FROM trade_dates 
                              WHERE is_trading_day = 1 AND calendar_date <= s.out_date)
    ) AS missing_days
FROM stock_basic s
JOIN all_stock_daily d ON d.code = s.code AND d.adjustflag = 3
WHERE s.type = 1 AND s.status = 0  -- 只检查退市股票
  AND s.out_date IS NOT NULL
GROUP BY s.code
HAVING latest_data_date < expected_latest_for_delisted
ORDER BY missing_days DESC;
```

**输出示例**：

```
最新数据截止日检查 (expected_cutoff = 2026-07-25)
───────────────────────────────────────────────────
上市中股票缺失最近数据:
  code         name       latest_date  expected  missing_days
  sh.688xxx    XX科技     2026-07-20   2026-07-25    3 天
  sz.300xxx    XX集团     2026-07-18   2026-07-25    5 天

退市股票缺失数据:
  code         name       out_date    latest_date  expected  missing_days
  sh.600xxx    XX股份     2024-03-15  2024-03-10   2024-03-15    3 天
```

#### 3.3.3 周线/月线空洞

同理，但需要将交易日映射到对应的自然周/月，检查是否有遗漏。

---

### 3.4 L4 — 财务数据覆盖率

#### 3.4.1 预期季度计算

财务数据的预期计算严格对齐 `financial_downloader.py` 的实际逻辑：

```
对于股票 s (type=1, 包括退市):
    start_year = max(2007, YEAR(s.ipo_date))
    end_year   = min(当前年份, YEAR(COALESCE(s.out_date, '9999-12-31')))

    对于每个 (year, quarter) 其中 year in [start_year, end_year], quarter in [1,2,3,4]:
        季度截止日: Q1=03-31, Q2=06-30, Q3=09-30, Q4=12-31

        跳过条件 1: year == 当前年份 AND quarter IN (当前季度, 当前季度-1)
                    -- 发布窗口期，数据尚不存在
        跳过条件 2: table == 'growth_data' AND year == ipo_year
                    -- IPO 年度无成长能力数据（下载器逻辑）
        跳过条件 3: s.out_date 不为空 AND s.out_date < 季度截止日
                    -- 退市早于季度末，该季度不可能有财报

    预期季度数 = 所有未跳过的 (year, quarter) 组合数
```

#### 3.4.2 校验方法

构建预期季度表，LEFT JOIN 实际数据表，找出缺失的 `(code, year, quarter)`。

6 个财务表分别校验：`profit_data`, `operation_data`, `growth_data`, `balance_data`, `cash_flow_data`, `dupont_data`。

#### 3.4.3 六表一致性

同一股票同一季度，6 个财务表应该同时有数据或同时无数据：

```sql
-- 找出数据不一致的 (code, year, quarter)
-- 如果 profit_data 有但 balance_data 没有，说明下载不完整
```

---

### 3.5 L5 — 分红与复权因子

#### 3.5.1 分红数据 (`dividend`)

```
对于股票 s (type=1, 包括退市):
    start_year = max(2007, YEAR(s.ipo_date))
    end_year   = min(当前年份, YEAR(COALESCE(s.out_date, '9999-12-31')))

    预期: 每年 x 2 种 year_type (report, operate) = 2 x (end_year - start_year + 1) 条记录
    实际: SELECT COUNT(*) FROM dividend WHERE code = s.code

    注意: 某些年份不分红，下载器会写入占位记录 (divid_operate_date = '9999-01-01')
          所以预期数应约等于实际数
```

#### 3.5.2 复权因子 (`adjust_factor`)

复权因子应与分红事件一一对应：

```sql
-- 有实际分红除息日（非占位）就应该有复权因子
SELECT d.code, d.divid_operate_date, d.year, d.year_type
FROM dividend d
LEFT JOIN adjust_factor af
    ON af.code = d.code AND af.divid_operate_date = d.divid_operate_date
WHERE d.divid_operate_date != '9999-01-01'  -- 排除占位记录
  AND af.code IS NULL;
```

---

### 3.6 L6 — 指数 K 线

8 个指数（`sh.000001`, `sh.000002`, `sh.000003`, `sz.399001`, `sz.399006`, `sh.000300`, `sh.000905`, `sz.399005`），从 `2006-01-01` 到 `expected_cutoff`。

```sql
-- 指数日 K 线空洞
WITH index_codes(code) AS (
    VALUES ('sh.000001'),('sh.000002'),('sh.000003'),('sz.399001'),
           ('sz.399006'),('sh.000300'),('sh.000905'),('sz.399005')
),
expected AS (
    SELECT ic.code, td.calendar_date
    FROM index_codes ic
    JOIN trade_dates td ON td.is_trading_day = 1 
        AND td.calendar_date >= '2006-01-01'
        AND td.calendar_date <= :expected_cutoff
)
SELECT e.code, e.calendar_date AS missing_date
FROM expected e
LEFT JOIN index_daily d ON d.code = e.code AND d.date = e.calendar_date
WHERE d.code IS NULL
ORDER BY e.code, e.calendar_date;
```

**指数最新数据截止日检查**：

```sql
-- 每个指数的最新数据日期应 >= expected_cutoff
SELECT 
    ic.code,
    MAX(d.date) AS latest_data_date,
    :expected_cutoff AS expected_cutoff,
    (SELECT COUNT(*) FROM trade_dates td 
     WHERE td.is_trading_day = 1 
     AND td.calendar_date > MAX(d.date) 
     AND td.calendar_date <= :expected_cutoff
    ) AS missing_recent_days
FROM (VALUES ('sh.000001'),('sh.000002'),('sh.000003'),('sz.399001'),
             ('sz.399006'),('sh.000300'),('sh.000905'),('sz.399005')) AS ic(code)
JOIN index_daily d ON d.code = ic.code
GROUP BY ic.code
HAVING latest_data_date < :expected_cutoff;
```

周线/月线同理，按自然周/月聚合。

---

### 3.7 L7 — 宏观数据

| 表 | 校验逻辑 |
|----|----------|
| `deposit_rate` | 行数 >= 20，最新 `pub_date` 在 3 年内 |
| `loan_rate` | 同上 |
| `reserve_ratio` | 行数 >= 30 |
| `money_supply_month` | 行数 >= 200，最新年月距今 <= 6 个月 |
| `money_supply_year` | 行数 >= 20，最新年份 = 去年或今年 |

---

### 3.8 L8 — 数据质量（数值合理性）

| 检查项 | SQL | 说明 |
|--------|-----|------|
| 价格为空 | `COUNT(*) FROM all_stock_daily WHERE close IS NULL` | 不应有 NULL |
| 价格 <= 0 | `COUNT(*) FROM all_stock_daily WHERE close <= 0 AND adjustflag=3` | 不复权价格不应 <= 0 |
| 高低价倒挂 | `COUNT(*) FROM all_stock_daily WHERE high < low` | 最高价 < 最低价 |
| 成交量为负 | `COUNT(*) FROM all_stock_daily WHERE volume < 0` | 不应有负值 |
| 涨跌幅异常 | `code, date, pct_chg FROM all_stock_daily WHERE ABS(pct_chg) > 22` | 超过涨跌停限制 |
| **上市股票无近期数据** | 见下方 SQL | 上市股票数据应至少到 `expected_cutoff` |

**上市股票无近期数据检查**：

```sql
-- 上市中股票在 expected_cutoff 当天无数据
SELECT s.code, s.code_name, MAX(d.date) AS latest_date
FROM stock_basic s
LEFT JOIN all_stock_daily d ON d.code = s.code AND d.adjustflag = 3
WHERE s.type = 1 AND s.status = 1
GROUP BY s.code
HAVING latest_date < :expected_cutoff;
```

---

## 4. 输出格式设计

校验完成后生成两份报告：
1. **JSON 报告** (`data/integrity_report.json`) — 结构化数据，供后续补齐脚本读取
2. **文字报告** (`data/integrity_report.txt`) — 可读性强的完整校验报告，包含汇总说明、问题分析、数据展示

### 4.1 JSON 报告结构

结果写入 `data/integrity_report.json`，后续补齐脚本可直接读取。

```json
{
  "report_time": "2026-07-26T15:30:00",
  "check_date": "2026-07-26",
  "expected_cutoff": "2026-07-25",
  "expected_cutoff_note": "check_date 之前的最近交易日（含 check_date 当天如果是交易日）",
  "db_path": "data/baostock.db",
  "summary": {
    "total_stocks": 5662,
    "active_stocks": 5200,
    "delisted_stocks": 462,
    "trading_days_covered": "1990-12-19 ~ 2026-07-25",
    "overall_completeness": 0.968
  },
  "L1_meta": {
    "status": "pass",
    "trade_dates_latest": "2026-07-25",
    "trade_dates_covers_cutoff": true,
    "issues": []
  },
  "L2_kline_coverage": {
    "daily": {
      "adjustflag_1": {
        "fully_covered": 4812,
        "above_95": 312,
        "below_80": 12,
        "zero_data": 0
      },
      "adjustflag_2": { "..." : "..." },
      "adjustflag_3": { "..." : "..." }
    },
    "weekly": { "..." : "..." },
    "monthly": { "..." : "..." }
  },
  "L3_kline_gaps": {
    "daily": [
      {
        "code": "sh.688xxx",
        "code_name": "XX科技",
        "ipo_date": "2020-01-01",
        "out_date": null,
        "status": 1,
        "adjustflag": 3,
        "expected_days": 1620,
        "actual_days": 1200,
        "latest_data_date": "2026-07-20",
        "missing_recent_days": 3,
        "missing_dates": ["2023-05-15", "2023-05-16", "..."]
      }
    ],
    "weekly": [ "..." ],
    "monthly": [ "..." ]
  },
  "L4_financial": {
    "profit_data": {
      "missing": [
        {"code": "sh.600xxx", "code_name": "XX股份", "year": 2020, "quarter": 2}
      ]
    },
    "operation_data": { "..." : "..." },
    "growth_data": { "..." : "..." },
    "balance_data": { "..." : "..." },
    "cash_flow_data": { "..." : "..." },
    "dupont_data": { "..." : "..." },
    "cross_table_inconsistency": [
      {"code": "sh.600xxx", "year": 2020, "quarter": 2, "present_tables": ["profit_data"], "missing_tables": ["balance_data", "..."]}
    ]
  },
  "L5_dividend": {
    "missing_dividend": [
      {"code": "sh.600xxx", "year": 2019, "year_type": "operate"}
    ],
    "missing_adjust_factor": [
      {"code": "sh.600xxx", "divid_operate_date": "2020-07-15"}
    ]
  },
  "L6_index": {
    "daily_gaps": [
      {"code": "sh.000001", "latest_data_date": "2026-07-22", "missing_recent_days": 3, "missing_dates": ["2026-07-23", "2026-07-24", "2026-07-25"]}
    ],
    "weekly_gaps": [ "..." ],
    "monthly_gaps": [ "..." ]
  },
  "L7_macro": {
    "issues": []
  },
  "L8_quality": {
    "null_close": 0,
    "negative_price": 0,
    "high_low_inverted": 0,
    "negative_volume": 0,
    "abnormal_pct_chg": [
      {"code": "sh.688xxx", "date": "2024-01-15", "pct_chg": 25.3}
    ]
  }
}
```

### 4.2 文字报告格式

文字报告写入 `data/integrity_report.txt`，包含以下内容：

#### 4.2.1 报告结构

```
================================================================================
                    BaoStock 数据完整性校验报告
================================================================================
校验时间:     2026-07-26 15:30:00
校验基准日:   2026-07-26
预期截止日:   2026-07-25 (周五，最近交易日)
数据库路径:   data/baostock.db
数据库大小:   14,965 MB

================================================================================
一、汇总说明
================================================================================

【整体完整度】96.8%

【数据概况】
  • 股票总数:     5,662 只
    - 上市中:     5,200 只
    - 已退市:       462 只
  • 交易日历:     1990-12-19 ~ 2026-07-25 (8,523 个交易日)
  • 数据库总行数: 70,951,264 行

【各层校验结果】
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 层级 │ 检查项              │ 状态  │ 问题数                            │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ L1   │ 基础表完整性        │ ✅ 通过 │ 0                                  │
  │ L2   │ K线覆盖率           │ ⚠️ 警告 │ 70 只股票覆盖率 < 100%             │
  │ L3   │ K线日期连续性       │ ⚠️ 警告 │ 127 只股票存在日期空洞             │
  │ L4   │ 财务数据覆盖率      │ ⚠️ 警告 │ 245 个 (code,year,quarter) 缺失    │
  │ L5   │ 分红与复权因子      │ ✅ 通过 │ 0                                  │
  │ L6   │ 指数K线             │ ⚠️ 警告 │ 2 个指数存在空洞                   │
  │ L7   │ 宏观数据            │ ✅ 通过 │ 0                                  │
  │ L8   │ 数据质量            │ ⚠️ 警告 │ 3 条涨跌幅异常                     │
  └─────────────────────────────────────────────────────────────────────────┘

【关键发现】
  1. 日K线数据完整度最高，95% 以上股票覆盖完整
  2. 财务数据有 245 条缺失，主要集中在 2020-2022 年
  3. 127 只股票存在日期空洞，可能是下载中断导致
  4. 所有上市中股票数据均更新到 expected_cutoff (2026-07-25)

================================================================================
二、基础表完整性 (L1)
================================================================================

【交易日历 trade_dates】
  • 覆盖范围:     1990-12-19 ~ 2026-07-25
  • 交易日总数:   8,523 天
  • 最新交易日:   2026-07-25 (周五)
  • 覆盖校验基准日: ✅ 是

【股票基础信息 stock_basic】
  • 股票总数:     5,662 只
    - 上市中:     5,200 只 (status=1)
    - 已退市:       462 只 (status=0)
  • IPO日期缺失:  12 只 (0.2%) ✅
  • 退市日期缺失: 0 只 ✅

【行业分类 stock_industry】
  • 覆盖股票数:   5,534 只
  • 覆盖率:       97.7% ✅

【指数成分股】
  • 上证50:       50 只 ✅
  • 沪深300:      300 只 ✅
  • 中证500:      500 只 ✅

【结论】基础表数据完整，可用于后续校验。

================================================================================
三、K线数据覆盖率 (L2)
================================================================================

【日K线 all_stock_daily】

  按 adjustflag 统计:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ adjustflag │ 完全覆盖 │ >=95% │ 80%-95% │ <80% │ 零数据 │ 总股票数      │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 1 (后复权) │  4,812   │  312  │   58    │  12  │   0    │   5,662       │
  │ 2 (前复权) │  4,812   │  312  │   58    │  12  │   0    │   5,662       │
  │ 3 (不复权) │  4,812   │  312  │   58    │  12  │   0    │   5,662       │
  └─────────────────────────────────────────────────────────────────────────┘

  低覆盖股票明细 (< 100%):
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ code        │ name     │ ipo_date   │ out_date   │ 预期天数 │ 实际天数 │ 覆盖率 │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sh.688xxx   │ XX科技   │ 2020-01-01 │ -          │  1,620   │  1,200   │ 74.1%  │
  │ sz.300xxx   │ XX集团   │ 2015-06-01 │ 2023-08-15 │  2,010   │  1,500   │ 74.6%  │
  │ ...         │ ...      │ ...        │ ...        │  ...     │  ...     │ ...    │
  └─────────────────────────────────────────────────────────────────────────┘

【周K线 all_stock_weekly】
  • 完全覆盖: 4,950 只 (87.4%)
  • 低覆盖: 70 只 (1.2%)

【月K线 all_stock_monthly】
  • 完全覆盖: 5,100 只 (90.1%)
  • 低覆盖: 30 只 (0.5%)

【问题分析】
  1. 三种 adjustflag 的覆盖率完全一致，说明下载逻辑正常
  2. 低覆盖股票主要集中在:
     - 2020 年后上市的新股 (数据积累时间短)
     - 下载过程中断导致的中间空洞
  3. 无零数据股票，说明所有股票都至少被下载过

================================================================================
四、K线日期连续性 (L3)
================================================================================

【日K线空洞检测】

  统计:
  • 存在空洞的股票: 127 只
  • 总缺失交易日: 3,456 天
  • 平均缺失: 27.2 天/股票

  缺失最严重的 10 只股票:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ code        │ name     │ 预期天数 │ 实际天数 │ 缺失天数 │ 缺失日期范围              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sh.688xxx   │ XX科技   │  1,620   │  1,200   │   420    │ 2023-05-15 ~ 2024-08-20   │
  │ sz.300xxx   │ XX集团   │  2,010   │  1,500   │   510    │ 2022-01-10 ~ 2023-06-30   │
  │ ...         │ ...      │  ...     │  ...     │   ...    │ ...                       │
  └─────────────────────────────────────────────────────────────────────────┘

【最新数据截止日检查】

  上市中股票 (status=1):
  • 数据更新到 expected_cutoff (2026-07-25): 5,200 只 ✅
  • 数据落后于 expected_cutoff: 0 只 ✅

  退市股票 (status=0):
  • 数据更新到退市日: 462 只 ✅
  • 数据落后于退市日: 0 只 ✅

【问题分析】
  1. 127 只股票存在日期空洞，可能原因:
     - 下载过程中网络中断
     - BaoStock API 返回空数据
     - 服务器临时故障
  2. 所有股票最新数据均更新到 expected_cutoff，说明增量更新机制正常
  3. 空洞主要集中在 2022-2024 年，可能是当时下载中断导致

【建议】
  • 对 127 只存在空洞的股票，运行补齐脚本补取缺失日期数据
  • 补齐时按连续日期段批量下载，减少 API 请求次数

================================================================================
五、财务数据覆盖率 (L4)
================================================================================

【各表缺失统计】

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 表名              │ 预期行数  │ 实际行数  │ 缺失数 │ 覆盖率 │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ profit_data       │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  │ operation_data    │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  │ growth_data       │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  │ balance_data      │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  │ cash_flow_data    │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  │ dupont_data       │ 1,234,567 │ 1,234,322 │  245   │ 99.98% │
  └─────────────────────────────────────────────────────────────────────────┘

【缺失数据分布】

  按年份统计:
  • 2020 年: 85 条缺失
  • 2021 年: 92 条缺失
  • 2022 年: 68 条缺失

  按股票统计 (缺失最多的 10 只):
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ code        │ name     │ 缺失季度数 │ 缺失年份范围      │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sh.600xxx   │ XX股份   │  12        │ 2020-2022         │
  │ sz.000xxx   │ XX集团   │   8        │ 2021-2022         │
  │ ...         │ ...      │  ...       │ ...               │
  └─────────────────────────────────────────────────────────────────────────┘

【六表一致性检查】

  • 一致 (6表同时有/无): 99.95%
  • 不一致: 0 条 ✅

  说明: 同一 (code, year, quarter) 的 6 个财务表数据一致，无缺失。

【问题分析】
  1. 245 条缺失集中在 2020-2022 年，可能是当时下载中断
  2. 六表一致性良好，说明下载逻辑正常
  3. 缺失数量占比极低 (0.02%)，整体完整度高

【建议】
  • 对 245 条缺失数据，按 (code, year, quarter) 逐个补取
  • 优先补取 2020-2022 年的数据

================================================================================
六、分红与复权因子 (L5)
================================================================================

【分红数据 dividend】
  • 总记录数: 118,196 条
  • 覆盖股票: 5,200 只
  • 预期覆盖: 5,200 只
  • 覆盖率: 100% ✅

【复权因子 adjust_factor】
  • 总记录数: 54,062 条
  • 覆盖股票: 5,200 只
  • 与分红事件匹配: 100% ✅

【问题分析】
  • 无缺失数据

================================================================================
七、指数K线 (L6)
================================================================================

【指数日K线 index_daily】

  8 个指数的覆盖情况:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 指数代码    │ 指数名称    │ 预期天数 │ 实际天数 │ 缺失天数 │ 最新数据日期 │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sh.000001   │ 上证综指    │  5,120   │  5,120   │    0     │ 2026-07-25   │
  │ sh.000002   │ 上证A股     │  5,120   │  5,118   │    2     │ 2026-07-23   │
  │ sz.399001   │ 深证成指    │  5,120   │  5,120   │    0     │ 2026-07-25   │
  │ ...         │ ...         │  ...     │  ...     │  ...     │ ...          │
  └─────────────────────────────────────────────────────────────────────────┘

【问题分析】
  1. 2 个指数存在少量空洞 (2 天)
  2. 所有指数最新数据均更新到 expected_cutoff

【建议】
  • 补取 sh.000002 和 sh.000003 的缺失日期数据

================================================================================
八、宏观数据 (L7)
================================================================================

【各表统计】

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 表名                  │ 行数  │ 最新日期    │ 状态 │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ deposit_rate          │   29  │ 2025-10-20  │ ✅   │
  │ loan_rate             │   29  │ 2025-10-20  │ ✅   │
  │ reserve_ratio         │   46  │ 2024-09-27  │ ✅   │
  │ money_supply_month    │  318  │ 2026-06     │ ✅   │
  │ money_supply_year     │   25  │ 2025        │ ✅   │
  └─────────────────────────────────────────────────────────────────────────┘

【问题分析】
  • 无异常

================================================================================
九、数据质量 (L8)
================================================================================

【数值合理性检查】

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 检查项              │ 异常数 │ 说明                                    │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 价格为 NULL         │    0   │ ✅ 无异常                               │
  │ 价格 <= 0           │    0   │ ✅ 无异常                               │
  │ 高低价倒挂          │    0   │ ✅ 无异常                               │
  │ 成交量为负          │    0   │ ✅ 无异常                               │
  │ 涨跌幅异常 (>22%)   │    3   │ ⚠️ 科创板/创业板股票，属于正常波动      │
  └─────────────────────────────────────────────────────────────────────────┘

【涨跌幅异常明细】

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ code        │ date       │ pct_chg │ 说明                              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sh.688xxx   │ 2024-01-15 │  25.3%  │ 科创板，首日无涨跌停限制          │
  │ sz.300xxx   │ 2023-08-20 │ -22.5%  │ 创业板，首日无涨跌停限制          │
  │ sh.688xxx   │ 2024-03-10 │  23.8%  │ 科创板，首日无涨跌停限制          │
  └─────────────────────────────────────────────────────────────────────────┘

【问题分析】
  • 3 条涨跌幅异常均为科创板/创业板股票上市首日，属于正常情况
  • 无实质性数据质量问题

================================================================================
十、总结与建议
================================================================================

【整体评估】

  数据完整度: 96.8%
  
  优势:
  • 基础表数据完整，交易日历覆盖到最新交易日
  • 日K线覆盖率高达 95% 以上
  • 财务数据六表一致性良好
  • 所有上市中股票数据均更新到最新交易日

  待改进:
  • 127 只股票存在日期空洞 (共 3,456 天)
  • 245 条财务数据缺失 (集中在 2020-2022 年)
  • 2 个指数存在少量空洞

【补齐建议】

  优先级 1 (高):
  • 补取 127 只股票的 K 线空洞数据 (3,456 天)
  • 补取 245 条财务数据缺失

  优先级 2 (中):
  • 补取 2 个指数的 K 线空洞数据

  优先级 3 (低):
  • 无需处理

【预计补齐工作量】

  • K 线空洞: 约 3,456 次 API 请求
  • 财务数据: 约 245 次 API 请求
  • 指数空洞: 约 4 次 API 请求
  • 总计: 约 3,705 次 API 请求 (约占每日限额的 7.6%)

【下一步操作】

  1. 运行补齐脚本: python scripts/fill_missing_data.py
  2. 补齐完成后，重新运行校验: python scripts/check_data_integrity.py
  3. 确认完整度达到 100%

================================================================================
                              报告结束
================================================================================
```

### 4.3 文字报告生成逻辑

文字报告由 `DataIntegrityChecker.generate_text_report()` 方法生成，基于 JSON 报告数据：

```python
def generate_text_report(self, json_report: dict) -> str:
    """
    生成文字报告
    
    结构:
    1. 报告头 (时间、基准日、截止日、数据库信息)
    2. 汇总说明 (整体完整度、各层状态、关键发现)
    3. 各层详细分析 (L1-L8)
       - 数据展示 (表格)
       - 问题分析
       - 建议
    4. 总结与建议 (整体评估、补齐建议、工作量估算)
    """
    lines = []
    
    # 1. 报告头
    lines.append(self._format_header(json_report))
    
    # 2. 汇总说明
    lines.append(self._format_summary(json_report))
    
    # 3. 各层详细分析
    lines.append(self._format_L1(json_report))
    lines.append(self._format_L2(json_report))
    lines.append(self._format_L3(json_report))
    lines.append(self._format_L4(json_report))
    lines.append(self._format_L5(json_report))
    lines.append(self._format_L6(json_report))
    lines.append(self._format_L7(json_report))
    lines.append(self._format_L8(json_report))
    
    # 4. 总结与建议
    lines.append(self._format_conclusion(json_report))
    
    return "\n".join(lines)
```

### 4.4 补齐任务提取

JSON 报告中的 `L3_kline_gaps` 和 `L4_financial.missing` 可直接转换为补齐任务：

```python
# 后续补齐脚本读取报告后，生成下载任务
report = json.load(open("data/integrity_report.json"))

# K 线补齐任务
for gap in report["L3_kline_gaps"]["daily"]:
    code = gap["code"]
    adjustflag = gap["adjustflag"]
    for date_range in group_consecutive_dates(gap["missing_dates"]):
        # 调用下载器补取 date_range 范围内的数据
        download_kline(code, start_date=date_range[0], end_date=date_range[-1], adjustflag=adjustflag)

# 财务数据补齐任务
for missing in report["L4_financial"]["profit_data"]["missing"]:
    download_profit(code=missing["code"], year=missing["year"], quarter=missing["quarter"])
```

---

## 5. 实现方案

### 5.1 新建脚本

`scripts/check_data_integrity.py`

### 5.2 用法

```bash
# 全部检查（默认 check_date = 今天）
# 生成两份报告: data/integrity_report.json 和 data/integrity_report.txt
.venv/bin/python scripts/check_data_integrity.py

# 指定校验基准日（用于回溯检查历史某天的数据完整性）
.venv/bin/python scripts/check_data_integrity.py --date 2026-07-20

# 仅检查特定层级
.venv/bin/python scripts/check_data_integrity.py --level 1    # 仅基础表
.venv/bin/python scripts/check_data_integrity.py --level 2    # K 线覆盖率
.venv/bin/python scripts/check_data_integrity.py --level 3    # 日期连续性
.venv/bin/python scripts/check_data_integrity.py --level 4    # 财务数据
.venv/bin/python scripts/check_data_integrity.py --level 5    # 分红/复权
.venv/bin/python scripts/check_data_integrity.py --level 6    # 指数 K 线
.venv/bin/python scripts/check_data_integrity.py --level 7    # 宏观数据
.venv/bin/python scripts/check_data_integrity.py --level 8    # 数据质量

# 只检查指定股票
.venv/bin/python scripts/check_data_integrity.py --code sh.600000

# 指定输出文件路径（同时生成 .json 和 .txt）
.venv/bin/python scripts/check_data_integrity.py --output data/my_report

# 仅生成 JSON 报告（不生成文字报告）
.venv/bin/python scripts/check_data_integrity.py --json-only

# 仅生成文字报告（不生成 JSON 报告）
.venv/bin/python scripts/check_data_integrity.py --text-only
```

### 5.3 代码结构

```python
class DataIntegrityChecker:
    def __init__(self, db_path, check_date=None):
        self.conn = sqlite3.connect(db_path)
        self.check_date = check_date or date.today().isoformat()
        self._load_trade_dates()    # 预加载交易日历到内存
        self._load_stock_basic()    # 预加载股票基础信息到内存
        self._compute_expected_cutoff()  # 计算预期截止日

    def _load_trade_dates(self):
        """加载 trade_dates 到内存，后续所有校验复用"""
        self.trading_days = [...]       # 所有交易日列表
        self.latest_trading_day = ...   # 最新交易日

    def _load_stock_basic(self):
        """加载 stock_basic 到内存，后续所有校验复用"""
        self.stocks = {
            code: {ipo_date, out_date, type, status, code_name}
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

    def _effective_end(self, stock) -> str:
        """
        计算单只股票的预期数据终点
        - 上市中股票: expected_cutoff
        - 退市股票: min(out_date, expected_cutoff)
        """
        if stock['status'] == 1:
            return self.expected_cutoff
        else:
            out_date = stock.get('out_date') or '9999-12-31'
            return min(out_date, self.expected_cutoff)

    def _expected_trading_days(self, code) -> int:
        """基于 stock_basic.ipo_date/out_date + trade_dates 计算预期交易日数"""
        stock = self.stocks[code]
        effective_end = self._effective_end(stock)
        return len([d for d in self.trading_days 
                    if stock['ipo_date'] <= d <= effective_end])

    def check_L1_meta(self) -> dict: ...
    def check_L2_kline_coverage(self) -> dict: ...
    def check_L3_kline_gaps(self) -> dict: ...
    def check_L4_financial(self) -> dict: ...
    def check_L5_dividend(self) -> dict: ...
    def check_L6_index(self) -> dict: ...
    def check_L7_macro(self) -> dict: ...
    def check_L8_quality(self) -> dict: ...

    def run_all(self) -> dict:
        """运行所有检查，返回完整 JSON 报告"""
        ...

    def save_json_report(self, report: dict, output_path: str):
        """保存 JSON 报告到文件"""
        ...

    def generate_text_report(self, json_report: dict) -> str:
        """
        生成文字报告
        
        结构:
        1. 报告头 (时间、基准日、截止日、数据库信息)
        2. 汇总说明 (整体完整度、各层状态、关键发现)
        3. 各层详细分析 (L1-L8)
           - 数据展示 (表格)
           - 问题分析
           - 建议
        4. 总结与建议 (整体评估、补齐建议、工作量估算)
        """
        ...

    def save_text_report(self, text_report: str, output_path: str):
        """保存文字报告到文件"""
        ...

    def save_reports(self, json_report: dict, base_path: str):
        """
        同时保存 JSON 和文字报告
        
        参数:
            json_report: JSON 格式的报告数据
            base_path: 基础路径，如 "data/integrity_report"
                       会生成 data/integrity_report.json 和 data/integrity_report.txt
        """
        self.save_json_report(json_report, f"{base_path}.json")
        text_report = self.generate_text_report(json_report)
        self.save_text_report(text_report, f"{base_path}.txt")
```

### 5.4 关键设计决策

| 决策 | 说明 |
|------|------|
| 预加载基础表到内存 | `trade_dates` (~13K 行) 和 `stock_basic` (~5K 行) 数据量小，加载一次后所有层级复用 |
| 退市股票严格校验 | 退市股票在存续期内的数据同样要求完整，不做豁免 |
| 不做粗筛 | 所有股票都做完整的空洞检测，不跳过任何一只 |
| 预期值计算与下载器对齐 | 预期逻辑严格匹配各下载器的实际过滤条件（如财务跳过当前季度、growth_data 跳过 IPO 年等） |
| 批量 SQL 优先 | 空洞检测用 JOIN 而非逐股票循环 |
| 双报告输出 | JSON 报告供程序读取，文字报告供人工阅读 |
| 文字报告结构化 | 包含汇总说明、问题分析、数据展示、建议，便于快速定位问题 |

### 5.5 可复用的现有代码

| 来源 | 可复用内容 |
|------|-----------|
| `scripts/estimate_data_volume.py` | `count_trading_days()`, `load_stock_info()`, `load_trade_dates()` |
| `src/utils/validator.py` | 基础框架（`check_all()`, `summary()`），本方案是其全面升级 |
| `src/db_manager.py` | 表结构定义、`get_max_date()`、`get_downloaded_stocks()` |

---

## 6. 性能预估

| 层级 | 预估耗时 | 说明 |
|------|----------|------|
| L1 | < 1 秒 | 简单 COUNT 查询 |
| L2 | 5-15 秒 | 需对每只股票计算预期天数 |
| L3 | 60-180 秒 | 大表 JOIN，数据量最大 |
| L4 | 10-30 秒 | 6 个表分别 LEFT JOIN |
| L5 | 5-10 秒 | 分红表 JOIN 复权因子表 |
| L6 | 2-5 秒 | 仅 8 个指数 |
| L7 | < 1 秒 | 简单 COUNT |
| L8 | 10-30 秒 | 全表扫描检查异常值 |
| **总计** | **约 2-5 分钟** | |

---

## 7. 后续补齐流程

校验完成后，生成两份报告：
- `data/integrity_report.json` — 结构化数据，供补齐脚本读取
- `data/integrity_report.txt` — 文字报告，供人工阅读和分析

补齐流程：

```
1. 运行校验:    python scripts/check_data_integrity.py
2. 查看文字报告: data/integrity_report.txt (快速了解整体情况)
3. 查看 JSON 报告: data/integrity_report.json (获取详细缺失数据)
4. 补齐 K 线:   读取 L3_kline_gaps，对每只股票的缺失日期段调用下载器
5. 补齐财务:    读取 L4_financial.missing，按 (code, year, quarter) 逐个补取
6. 补齐分红:    读取 L5_dividend.missing_dividend，按 (code, year, year_type) 补取
7. 补齐指数:    读取 L6_index.gaps，按 (code, date_range) 补取
8. 重新校验:    再次运行 check_data_integrity.py 确认补齐完成
```
