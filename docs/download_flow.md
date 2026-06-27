# BaoStock 数据拉取流程

## 1. 全量下载流程 (`./start.sh full`)

```
┌─────────────────────────────────────────────────────────┐
│                    启动全量下载                          │
│              scripts/download_all.py                     │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 1: 数据库初始化                                    │
│  • DBManager.init_all_tables()  → 创建所有表             │
│  • DBManager.migrate_schema()   → 迁移 schema            │
│  • 计算 target_date = 昨天                               │
│  • 查找 kline_end_date =                                │
│    get_latest_trading_day_on_or_before(target_date)      │
│    （若昨天非交易日，追溯到最近交易日）                    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 2: 元数据下载 (MetaDownloader)                     │
│                                                         │
│  1. trade_dates           ← query_trade_dates()          │
│  2. stock_basic           ← query_stock_basic()          │
│  3. stock_industry        ← query_stock_industry()       │
│                                                         │
│  每步间 sleep(2s)                                        │
│  API 请求: 3 次                                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 加载股票代码列表                                          │
│  SELECT code FROM stock_basic WHERE type = 1            │
│  → ~5,524 只股票（含退市）                               │
│  注：--codes-file 可从 CSV/TXT 加载自定义列表            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 4: 宏观经济数据 (MacroDownloader)                  │
│  (可通过 --skip-macro 跳过)                              │
│                                                         │
│  1. deposit_rate          ← query_deposit_rate_data()    │
│     ↓ sleep(2s)                                         │
│  2. loan_rate             ← query_loan_rate_data()       │
│     ↓ sleep(2s)                                         │
│  3. reserve_ratio         ← query_required_reserve...()  │
│     ↓ sleep(2s)                                         │
│  4. money_supply_month    ← query_money_supply_data_m()  │
│     ↓ sleep(2s)                                         │
│  5. money_supply_year     ← query_money_supply_data_y()  │
│                                                         │
│  API 请求: 5 次                                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 5: 指数成分股 (ComponentDownloader)                │
│                                                         │
│  1. sz50_stocks           ← query_sz50_stocks()          │
│  2. hs300_stocks          ← query_hs300_stocks()         │
│  3. zz500_stocks          ← query_zz500_stocks()         │
│                                                         │
│  API 请求: 3 次                                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              ┌──── 判断是否有交易日 ────┐
              │ if kline_end_date:       │
              │   → 继续 Phase 6-8       │
              │ else:                    │
              │   → 跳过 Phase 6-8       │
              └────────┬────────────────┘
                       │
              ┌──── 有交易日? ────┐
              │                  │
            否│                是│
              ▼                  ▼
   ┌──────────────────┐   ┌──────────────────────────────┐
   │ 跳过 Phase 6-8   │   │ Phase 6: 指数K线              │
   │ 直接去财务更新    │   │ (IndexDownloader)            │
   │                  │   │ 8个指数 × 3频率 (日/周/月)    │
   │                  │   │ start = 配置起始日期           │
   │                  │   │ end   = kline_end_date         │
   │                  │   │ API: ~24 次                   │
   └──────────────────┘   └──────────────┬───────────────┘
                                         │
                                         ▼
                                ┌────────────────────────┐
                                │ Phase 7: 股票K线         │
                                │ (KlineDownloader)       │
                                │ end = kline_end_date    │
                                │                         │
                                │ ┌─ 日线 (adj=1,2,3) ─┐  │
                                │ │ batch=200, sleep=2s│  │
                                │ │ 断点续传 + 增量检查 │  │
                                │ │ API: ~5,524 × 3    │  │
                                │ └────────────────────┘  │
                                │ ┌─ 周线 (adj=1,2,3) ─┐  │
                                │ │ 同上               │  │
                                │ │ API: ~5,524 × 3    │  │
                                │ └────────────────────┘  │
                                │ ┌─ 月线 (adj=1,2,3) ─┐  │
                                │ │ 同上               │  │
                                │ │ API: ~5,524 × 3    │  │
                                │ └────────────────────┘  │
                                │                         │
                                │ 断点续传: SIGINT/SIGTERM│
                                │   保存 checkpoint 文件   │
                                │ 增量检查: per-code       │
                                │   get_last_downloaded()  │
                                └────────┬────────────────┘
                                         │
                                         ▼
                                ┌────────────────────────┐
                                │ Phase 8: 分钟K线         │
                                │ (默认关闭)              │
                                │ config: minute.enabled  │
                                │ freq: 5/15/30/60        │
                                │ adj: 仅不复权(adj=3)    │
                                │ API: 5,524 × 4 × 1     │
                                └────────┬────────────────┘
                                         │
            ┌────────────────────────────┘
            │ (无交易日从 Phase 5 直接到这里)
            ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 9: 财务数据 (FinancialDownloader)                  │
│  (可通过 --skip-financial 跳过)                          │
│                                                         │
│  for table in [profit, operation, growth,               │
│                balance, cash_flow, dupont]:             │
│    预扫描已有 (code, year, quarter)                      │
│    for code in codes:                                   │
│      for year in range(start_year, current_year+1):     │
│        for quarter in [1, 2, 3, 4]:                     │
│          if (code,year,quarter) not in existing:        │
│            query_{table}_data(code, year, quarter)      │
│          sleep(0.5s)                                    │
│    攒批 upsert (每 500 条提交)                           │
│                                                         │
│  API: 仅下载缺失组合，重跑时请求量最小化                  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 10: 公司报告 (ReportDownloader)                    │
│  (可通过 --skip-reports 跳过)                            │
│                                                         │
│  1. performance_express   ← query_performance_express() │
│     for code in codes:                                  │
│       query_performance_express_report(                 │
│         code, start_date, end_date)                     │
│       sleep(2s)                                         │
│                                                         │
│  2. forecast_report       ← query_forecast_report()     │
│     for code in codes:                                  │
│       query_forecast_report(                            │
│         code, start_date, end_date)                     │
│       sleep(2s)                                         │
│                                                         │
│  start_date = get_reports_start_date() (配置)            │
│  end_date   = 昨天                                      │
│  API: 5,524 × 2 = ~11,048 次                            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 11: 分红与复权 (DividendDownloader)                │
│  (可通过 --skip-dividend 跳过)                           │
│                                                         │
│  1. dividend              ← query_dividend_data()       │
│     for code in codes:                                  │
│       for year in range(2007, current_year+1):          │
│         for year_type in [report, operate]:             │
│           query_dividend_data(code, year, year_type)    │
│       sleep(2s)                                         │
│                                                         │
│  2. adjust_factor         ← query_adjust_factor()       │
│     for code in codes:                                  │
│       query_adjust_factor(code, start_date, end_date)   │
│       sleep(2s)                                         │
│                                                         │
│  API: 5,524 × 20 × 2 + 5,524 = ~226,484 次            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 12: 数据验证 (可选, --validate)                    │
│  • DataValidator.check_all()                            │
│  • 输出各表行数统计                                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     下载完成                              │
│  • 清理 checkpoint 文件                                  │
│  • 输出各阶段下载统计                                    │
└─────────────────────────────────────────────────────────┘
```

## 2. 增量更新流程 (`./start.sh update`)

```
┌─────────────────────────────────────────────────────────┐
│                  启动增量更新                             │
│              scripts/update_daily.py                     │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 初始化数据库 & 计算增量起始日期                           │
│                                                         │
│  last_daily = MAX(date) FROM all_stock_daily            │
│  start_date = last_daily + 1 天                         │
│                                                         │
│  last_index = MAX(date) FROM index_daily                │
│  index_start = last_index + 1 天                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 加载股票列表（过滤条件：type=1 AND status=1）             │
│  → 仅正常上市的A股，不含退市/指数/ETF等                   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 更新元数据                                                │
│  • trade_dates          ← 全量刷新                       │
│  • stock_industry       ← 全量刷新                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 计算 K 线结束日期                                         │
│  target_date = 昨天                                      │
│  kline_end_date =                                        │
│    get_latest_trading_day_on_or_before(target_date)      │
│                                                         │
│  if kline_end_date >= start_date → 有数据可拉            │
│  else → 跳过 K 线更新（非交易日/周末/节假日）              │
└──────────────────────┬──────────────────────────────────┘
                       │
              ┌──── 有数据可拉? ────┐
              │                    │
            否│                  是│
              ▼                    ▼
   ┌──────────────────┐   ┌──────────────────────────────┐
   │ 跳过K线更新       │   │ 周一? → 更新指数成分股       │
   │ 直接去财务更新    │   │ (target_date weekday==0)    │
   │                  │   │ → sz50/hs300/zz500           │
   └──────────────────┘   └──────────────┬───────────────┘
                                         │
                                         ▼
                                ┌────────────────────────┐
                                │ 更新指数K线             │
                                │  • index_daily          │
                                │  • index_weekly         │
                                │  • index_monthly        │
                                │  start=index_start      │
                                │  end=kline_end_date     │
                                └──────────────┬─────────┘
                                               │
                                               ▼
                                ┌────────────────────────┐
                                │ 更新股票日线K线         │
                                │ (仅日线, 不含周/月)     │
                                │ start=start_date        │
                                │ end=kline_end_date      │
                                │ 3种复权 (adj=1,2,3)     │
                                │ API: N_stocks × 3      │
                                │ per-code增量检查        │
                                └──────────────┬─────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────┐
│ 更新财务数据 (仅当前/上季度)                              │
│                                                         │
│  if Q1: 查 Q1                                           │
│  else:  查 Q(current-1) 和 Q(current)                   │
│  预扫描已有 (code, year, quarter)，仅下载缺失组合         │
│                                                         │
│  API: 仅新增季度，大幅少于全量                            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 更新分红数据 (仅当年)                                     │
│  • dividend (current_year)                              │
│  • adjust_factor (start_date 至今)                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     更新完成                              │
└─────────────────────────────────────────────────────────┘
```

## 3. 各阶段数据下载策略与更新策略

### Phase 2: 元数据下载 (MetaDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `trade_dates` | 全量拉取所有交易日 | **replace** (删表重建) | 无 | 每次全量覆盖 |
| `stock_basic` | 全量拉取所有股票基本信息 | **replace** (删表重建) | 无 | 每次全量覆盖 |
| `stock_industry` | 全量拉取所有行业分类 | **replace** (删表重建) | 无 | 每次全量覆盖 |

**说明:**
- 元数据量小，采用最简单的 **DROP TABLE → CREATE TABLE → INSERT** 全量替换策略
- 不做差异比较，每次都是整表重写
- `if_exists="replace"` 走的是 pandas `to_sql(if_exists="replace")` 路径

---

### Phase 4: 宏观数据下载 (MacroDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `deposit_rate` | 从 start_date(2000-01-01) 拉取 | **upsert** | 无预检查 | INSERT OR REPLACE |
| `loan_rate` | 从 start_date(2000-01-01) 拉取 | **upsert** | 无预检查 | INSERT OR REPLACE |
| `reserve_ratio` | 从 start_date(2000-01-01) 拉取 | **upsert** | 无预检查 | INSERT OR REPLACE |
| `money_supply_month` | 从 start_date(2000) 拉取 | **upsert** | 无预检查 | INSERT OR REPLACE |
| `money_supply_year` | 从 start_date(2000) 拉取 | **upsert** | 无预检查 | INSERT OR REPLACE |

**说明:**
- 通过临时表 + `INSERT OR REPLACE INTO table SELECT ... FROM tmp` 实现 upsert
- 不预查已有数据，每次从 start_date 全量拉取后 upsert
- 去重依赖表的主键/唯一约束，无约束时等同于 append
- 宏观数据量小，重复 upsert 开销可接受

---

### Phase 5: 指数成分股下载 (ComponentDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `sz50_stocks` | 全量拉取上证50成分股 | **replace** (删表重建) | 无 | 每次全量覆盖 |
| `hs300_stocks` | 全量拉取沪深300成分股 | **replace** (删表重建) | 无 | 每次全量覆盖 |
| `zz500_stocks` | 全量拉取中证500成分股 | **replace** (删表重建) | 无 | 每次全量覆盖 |

**说明:**
- 成分股数量少（几十到几百只），采用全表替换策略
- 增量更新时仅周一执行

---

### Phase 6: 指数 K 线下载 (IndexDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `index_daily` | 8指数 × 日线，start_date ~ kline_end_date | **upsert** | 无预检查 | 配置起始日期，截止最近交易日 |
| `index_weekly` | 8指数 × 周线，start_date ~ kline_end_date | **upsert** | 无预检查 | 配置起始日期，截止最近交易日 |
| `index_monthly` | 8指数 × 月线，start_date ~ kline_end_date | **upsert** | 无预检查 | 配置起始日期，截止最近交易日 |

**说明:**
- `start_date` 来自 `get_index_kline_start_date()` 配置，非数据库 MAX(date)
- `end_date` = `kline_end_date`（最近交易日，全量下载）或数据库 MAX(date)+1（增量更新）
- 每次重新拉取整个配置日期范围，通过 upsert 去重
- 不做 per-code 的增量检查
- 每个指数间 sleep(batch_sleep)

---

### Phase 7: 股票 K 线下载 (KlineDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `all_stock_daily` | 逐股票 × 3种复权，批量200只 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | **增量 + 断点续传** |
| `all_stock_weekly` | 逐股票 × 3种复权，批量200只 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | **增量 + 断点续传** |
| `all_stock_monthly` | 逐股票 × 3种复权，批量200只 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | **增量 + 断点续传** |

**日期范围:**
- 全量下载: `start_date` = 配置值, `end_date` = `kline_end_date` (最近交易日)
- 增量更新: `start_date` = 数据库 MAX(date)+1, `end_date` = `kline_end_date`

**per-code 去重逻辑:**
```
last = get_last_downloaded(table, code, adjustflag=adjustflag)  # 含复权过滤
actual_start = max(start_date, last) if last else start_date
if last and last >= end_date: continue    # 已完成则跳过
```

**断点续传逻辑 (日线/周线/月线均支持):**
```
# 中断时保存 checkpoint: {table, adjustflag, last_code}
resume = _get_resume_code(table, adjustflag, codes)
# 恢复时从 last_code 之后继续，跳过已处理的股票
```

**说明:**
- 每批200只股票攒成一个 DataFrame，统一 upsert
- 日线/周线/月线均有断点续传（SIGINT/SIGTERM 时保存 checkpoint 文件）
- `_interrupted` 标志控制流程：中断后跳过后续频率下载
- 批次间 sleep(batch_sleep)

**周线/月线跳过策略（download_all.py / update_daily.py）:**

```
# 周线：距上次周线数据 >= 7 天才下载（节省 ~16K 次/天）
should_update_weekly = (target_dt - latest_weekly).days >= 7

# 月线：仅每月前 3 个交易日下载（节省 ~16K 次/天）
should_update_monthly = len(trading_days_in_month_so_far) <= 3
```

**周线周完成守卫（week-completion guard）：**
当周线下载触发后，还需检查 target_date 所在自然周是否已结束。BaoStock 的周线数据仅在完整交易周（Mon-Fri）结束后才返回，对未完成的周返回 rows=0。计算 target_date 所在周的周五，若周五尚未到达则跳过：

```
friday_of_target_week = target_dt + timedelta(days=(4 - target_dt.weekday()))
if friday_of_target_week.date() > target_dt.date():
    skip  # 周完成守卫：本周尚未结束，无完整新周可拉取
```

> 此守卫避免了 cron 在周五凌晨运行时（target=周四）对未完成当周发起的 ~16,600 次空请求。

**月线同月守卫（same-month guard）：**
当月线下载触发后，还需检查 `monthly_start`（latest_monthly + 1天）是否与 `latest_monthly` 处于同一自然月。若同月，说明该月数据已下载完毕且下月尚未结束，跳过下载：

```
monthly_start_dt = latest_monthly + timedelta(days=1)
if monthly_start_dt.month == latest_monthly.month:
    skip  # 同月守卫：无完整新月份可拉取
```

> 此守卫避免了每月初前 2-3 个交易日重复触发月线下载导致的 ~16,600 次空请求（详见 `docs/rows_zero_analysis_2026-06-03.md`）。

---

### Phase 8: 分钟 K 线下载 (KlineDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `all_stock_5min` | 逐股票 × 配置复权，批量200只 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | 增量（无断点续传） |
| `all_stock_15min` | 同上 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | 增量（无断点续传） |
| `all_stock_30min` | 同上 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | 增量（无断点续传） |
| `all_stock_60min` | 同上 | **upsert** | **per-code+adjustflag**: `get_last_downloaded()` | 增量（无断点续传） |

**说明:**
- 默认关闭 (`config.kline.minute.enabled=false`)
- 复权方式从配置读取: `kline.minute.adjustflags` (默认仅 `[3]` 不复权)
- 与 Phase 7 共享 `_download_kline_batch` 方法
- 有 per-code 增量检查，无断点续传
- 无 `end_date` 限制（传 None，拉取全量）

---

### Phase 9: 财务数据下载 (FinancialDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `profit_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |
| `operation_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |
| `growth_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |
| `balance_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |
| `cash_flow_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |
| `dupont_data` | 逐股票 × 年 × 季度 | **batch upsert** (自定义) | **预扫描**: `SELECT code,year,quarter` | **跳过已存在** |

**预扫描去重逻辑:**
```
existing = _get_existing_quarters(table_name)    # 预加载所有 (code, year, quarter)
for code, year, quarter in all_combinations:
    if (code, year, quarter) not in existing:
        tasks.append(...)                         # 仅下载缺失的
    else:
        skipped += 1                              # 跳过已存在的
```

**自定义 batch upsert:**
```
# 攒满 500 个 DataFrame 后批量写入
# 临时表 + INSERT OR REPLACE，列名用双引号引用（避免保留字冲突）
```

**说明:**
- **最激进的去重策略**：预扫描全表，只下载缺失的 (code, year, quarter) 组合
- 无断点续传，但重跑时 API 调用量最小化
- 批量刷新，每 500 个 DataFrame 提交一次

---

### Phase 10: 公司报告下载 (ReportDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `performance_express` | 逐股票，从配置 start_date 拉取业绩快报 | **upsert** | 无预检查 | 配置驱动起始日期 |
| `forecast_report` | 逐股票，从配置 start_date 拉取业绩预告 | **upsert** | 无预检查 | 配置驱动起始日期 |

**说明:**
- `start_date` 来自 `get_reports_start_date()` 配置
- 不做 per-code 增量检查，每次重新拉取整个日期范围
- 去重依赖 `INSERT OR REPLACE` 的表约束

---

### Phase 11: 分红与复权下载 (DividendDownloader)

| 表 | 下载策略 | 保存模式 | 去重策略 | 更新策略 |
|---|---|---|---|---|
| `dividend` | 逐股票 × 年(2007至今) × 类型(report/operate) | **upsert** | 无预检查 | 遍历年份，无增量跳过 |
| `adjust_factor` | 逐股票，从 start_date 拉取复权因子 | **upsert** | 无预检查 | 配置驱动起始日期 |

**说明:**
- 分红数据遍历所有年份 × 两种类型，无预检查已存在数据
- 完全依赖 `INSERT OR REPLACE` 去重
- 增量更新时仅下载当年 (`current_year`) 数据
- `download_all_dividend` 支持传入 `start_year/end_year` 和 `start_date/end_date`
- `_api_call` 包装 BaoStock API，自动递增请求计数

---

## 4. 保存模式汇总

| 模式 | 实现方式 | 行为 | 适用场景 |
|------|---------|------|---------|
| **replace** | `df.to_sql(if_exists="replace")` | DROP TABLE → CREATE → INSERT | 小表全量刷新（元数据、成分股） |
| **upsert** | 临时表 + `INSERT OR REPLACE INTO table SELECT ... FROM tmp` | 按主键/唯一键覆盖 | 中等表，可能重复拉取 |
| **batch upsert** | 自定义临时表 + `INSERT OR REPLACE`（列名加双引号） | 攒批后按主键覆盖 | 大表批量写入（财务数据） |
| **append** | `df.to_sql(if_exists="append")` | 直接追加，不去重 | 未使用 |

## 5. K 线下载内部流程

```
┌─────────────────────────────────────────────────────┐
│  download_daily_kline(codes, start_date, end_date)  │
│  download_weekly_kline(...) / download_monthly...() │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  for adjustflag in [1, 2, 3]:  ← 后复权/前复权/不复权│
│  ┌───────────────────────────────────────────────┐  │
│  │  resume = _get_resume_code(table, adj, codes) │  │
│  │  _download_kline_batch(codes, ..., adj, resume)│ │
│  │                                               │  │
│  │  for batch in codes (每批200只):              │  │
│  │  ┌─────────────────────────────────────────┐ │  │
│  │  │  for code in batch:                     │ │  │
│  │  │                                         │ │  │
│  │  │  1. 检查中断标志                         │ │  │
│  │  │     if _interrupted: return total_rows  │ │  │
│  │  │                                         │ │  │
│  │  │  2. 检查断点续传                         │ │  │
│  │  │     if skipping: continue               │ │  │
│  │  │     if code == resume_from: skipping=False││  │
│  │  │                                         │ │  │
│  │  │  3. 查询已下载的最新日期 (含adj过滤)     │ │  │
│  │  │     last = get_last_downloaded(         │ │  │
│  │  │              table, code,               │ │  │
│  │  │              adjustflag=adjustflag)     │ │  │
│  │  │                                         │ │  │
│  │  │  4. 计算实际起始日期                     │ │  │
│  │  │     actual_start =                      │ │  │
│  │  │       max(start_date, last) if last     │ │  │
│  │  │       else start_date                   │ │  │
│  │  │                                         │ │  │
│  │  │  5. 检查是否已完成                       │ │  │
│  │  │     if last and last >= end_date:       │ │  │
│  │  │       保存 checkpoint, continue         │ │  │
│  │  │                                         │ │  │
│  │  │  6. API 调用 (带重试)                    │ │  │
│  │  │     query_with_retry(                   │ │  │
│  │  │       bs.query_history_k_data_plus,     │ │  │
│  │  │       code, fields,                     │ │  │
│  │  │       actual_start, end_date,           │ │  │
│  │  │       frequency, str(adjustflag))       │ │  │
│  │  │                                         │ │  │
│  │  │  7. 保存 checkpoint                      │ │  │
│  │  │     _checkpoint_data = {table, adj,     │ │  │
│  │  │                          last_code: code}│ │  │
│  │  └─────────────────────────────────────────┘ │  │
│  │                                               │  │
│  │  8. 字段重命名 (pctChg→pct_chg 等)           │  │
│  │  9. 类型转换 (数值/turn/整型)                 │  │
│  │  10. 批量写入数据库 (upsert)                  │  │
│  │  11. sleep(batch_sleep)                       │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  if _interrupted: break  ← 跳过后续频率              │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  download_minute_kline(codes, frequency="5", ...)    │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  adjustflags = config.kline.minute.adjustflags [3]  │
│  for adjustflag in adjustflags:                     │
│    _download_kline_batch(codes, ..., adj)           │
│    → 同上，但无断点续传，无 end_date                 │
└─────────────────────────────────────────────────────┘
```

## 6. 请求计数与限流机制

```
┌─────────────────────────────────────────────────────┐
│  每次 API 调用                                       │
│  ┌───────────────────────────────────────────────┐  │
│  │  1. ensure_login()                            │  │
│  │     if time.time() - _login_time > 900s:     │  │
│  │       logout() → login()                      │  │
│  │                                               │  │
│  │  2. 执行查询                                   │  │
│  │     rs = query_func(**kwargs)                 │  │
│  │                                               │  │
│  │  3. _increment_request_count()                │  │
│  │     INSERT ... ON CONFLICT DO UPDATE          │  │
│  │     SET count = count + 1                     │  │
│  │     WHERE date = today                        │  │
│  │                                               │  │
│  │  4. 检查是否超限                               │  │
│  │     if new_count >= DAILY_REQUEST_LIMIT:      │  │
│  │       raise SystemExit(1)  ← 程序退出         │  │
│  │                                               │  │
│  │  5. 失败重试 (max 3次)                        │  │
│  │     指数退避: sleep(2s) → sleep(4s) → sleep(8s)│  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**说明:**
- `_increment_request_count` 使用直接 SQL（UPSERT），避免 DBManager 迁移开销
- 失败请求也会计数（服务器端已计数）
- 请求计数表 `request_count` 在 `migrate_schema()` 中自动创建

## 7. 各阶段 API 请求汇总（估算）

| Phase | 模块 | API 请求数 | 占比 | 耗时 |
|-------|------|-----------|------|------|
| 2 | 元数据 | 3 | <0.1% | <1s |
| 4 | 宏观数据 | 5 | <0.1% | <10s |
| 5 | 指数成分股 | 3 | <0.1% | <1s |
| 6 | 指数 K 线 | 24 | <0.1% | ~1min |
| 7 | 股票 K 线(日/周/月) | ~49,716 | 2.8% | ~1天 |
| 8 | 分钟 K 线 | ~22,096* | 1.2%* | ~8h* |
| 9 | 财务数据 | ~2,616,000* | 95%* | ~53天* |
| 10 | 公司报告 | ~11,048 | 0.6% | ~6h |
| 11 | 分红与复权 | ~226,484 | 12.8% | ~4.6天 |
| **合计** | | **~2,925,379** | 100% | **~60天** |

> 注：
> - Phase 8 分钟线默认关闭，复权方式从配置读取（默认仅 adj=3）
> - Phase 9 财务数据有预扫描去重，重跑时仅下载缺失组合
> - Phase 11 分红数据按每年 2 次 (report/operate) 估算
> - 非交易日自动跳过 K 线下载（节省约 190 万次/年无效请求）

## 8. 增量更新 API 请求

| 模块 | API 请求数 | 说明 |
|------|-----------|------|
| 元数据刷新 | 2 | trade_dates + stock_industry |
| 指数成分股 | 3 | 仅周一 |
| 指数 K 线 | 24 | 8 指数 × 3 频率 |
| 股票日线 | N_stocks × 3 | per-code 增量检查，仅新增数据 |
| 财务数据 | ~66,288* | 5,524 × 6 × 2 季度（预扫描去重） |
| 分红数据 | ~11,048 | 5,524 × 2（仅当年） |
| 复权因子 | ~5,524 | 从 start_date 至今 |
| **合计** | **~82,600** | 约 2 天额度 |

> 注：非交易日（周末/节假日）自动跳过 K 线更新，进一步节省请求

## 9. 关键配置参数

| 参数 | 默认值 | 来源 | 作用 |
|------|--------|------|------|
| `daily_request_limit` | 49,000 | config.yaml | 每日 API 请求上限 |
| `socket_timeout` | 30 | config.yaml | 网络超时（秒） |
| `batch_size` | 200 | config.yaml | K 线每批处理的股票数 |
| `batch_sleep` | 2 | config.yaml | 批次间休眠时间（秒） |
| `stocks.filter` | type=1 AND status=1 | config.yaml | 股票筛选条件（SQL WHERE） |
| `kline.daily.adjustflags` | [1, 2, 3] | config.yaml | 日线复权方式 |
| `kline.minute.adjustflags` | [3] | config.yaml | 分钟线复权方式（默认仅不复权） |
| `kline.minute.enabled` | false | config.yaml | 是否下载分钟数据 |
| `financial.start_year` | 2007 | config.yaml | 财务数据起始年份 |
| `reports.start_date` | 2003-01-01 | config.yaml | 公司报告起始日期 |
| `index_kline.start_date` | 2006-01-01 | config.yaml | 指数 K 线起始日期 |
| `FINANCIAL_SLEEP` | 0.5 | src/config.py | 财务数据每次调用间隔 |
| `LOGIN_REFRESH_INTERVAL` | 900 | src/config.py | 会话刷新间隔（15分钟） |
| `MAX_RETRIES` | 3 | src/config.py | 查询失败重试次数 |

---

*文档最后更新：2026年6月27日*
