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
│  • 检查今日是否为交易日                                  │
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
│  → ~5,524 只股票                                         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 4: 宏观经济数据 (MacroDownloader)                  │
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
              ┌──── 是否交易日? ────┐
              │                    │
            是│                  否│
              ▼                    ▼
   ┌──────────────────┐   ┌──────────────────────────┐
   │ Phase 6: 指数K线  │   │ 跳过 Phase 6-8           │
   │ (IndexDownloader)│   │ (非交易日不拉K线)         │
   │                  │   └──────────────────────────┘
   │ 8个指数 × 3频率  │
   │ 日/周/月各1次    │
   │ API: 24 次       │
   └────────┬─────────┘
            │
            ▼
   ┌──────────────────────────────────────────────────────┐
   │ Phase 7: 股票K线 (KlineDownloader)                   │
   │                                                      │
   │  ┌─ 日线 (frequency="d") ─────────────────────────┐  │
   │  │  for adjustflag in [1, 2, 3]:                  │  │
   │  │    for code in codes (batch=200):              │  │
   │  │      query_history_k_data_plus(                │  │
   │  │        code, fields, start_date,               │  │
   │  │        end_date, "d", adjustflag)              │  │
   │  │    → 每批后 sleep(2s)                          │  │
   │  │  API: 5,524 × 3 = 16,572 次                   │  │
   │  └────────────────────────────────────────────────┘  │
   │                                                      │
   │  ┌─ 周线 (frequency="w") ─────────────────────────┐  │
   │  │  for adjustflag in [1, 2, 3]:                  │  │
   │  │    for code in codes (batch=200):              │  │
   │  │      query_history_k_data_plus(                │  │
   │  │        code, fields, start_date, "w", adj)     │  │
   │  │  API: 5,524 × 3 = 16,572 次                   │  │
   │  └────────────────────────────────────────────────┘  │
   │                                                      │
   │  ┌─ 月线 (frequency="m") ─────────────────────────┐  │
   │  │  for adjustflag in [1, 2, 3]:                  │  │
   │  │    for code in codes (batch=200):              │  │
   │  │      query_history_k_data_plus(                │  │
   │  │        code, fields, start_date, "m", adj)     │  │
   │  │  API: 5,524 × 3 = 16,572 次                   │  │
   │  └────────────────────────────────────────────────┘  │
   │                                                      │
   │  断点续传: 中断后从 last_code 继续                    │
   │  去重: get_last_downloaded() → max(date) 之后开始    │
   └────────┬─────────────────────────────────────────────┘
            │
            ▼
   ┌──────────────────────────────────────────────────────┐
   │ Phase 8: 分钟K线 (KlineDownloader)                   │
   │ (默认关闭, config: kline.minute.enabled=false)       │
   │                                                      │
   │  for freq in [5, 15, 30, 60]:                       │
   │    for adjustflag in [1, 2, 3]:                     │
   │      for code in codes (batch=200):                 │
   │        query_history_k_data_plus(                   │
   │          code, fields, start_date, freq, adj)       │
   │  API: 5,524 × 4 × 3 = 66,288 次                    │
   └────────┬─────────────────────────────────────────────┘
            │
            ▼ (非交易日从 Phase 5 直接到这里)
┌─────────────────────────────────────────────────────────┐
│ Phase 9: 财务数据 (FinancialDownloader)                  │
│                                                         │
│  for table in [profit, operation, growth,               │
│                balance, cash_flow, dupont]:             │
│    for code in codes:                                   │
│      for year in range(start_year, current_year+1):     │
│        for quarter in [1, 2, 3, 4]:                     │
│          if (code,year,quarter) not in existing:        │
│            query_{table}_data(code, year, quarter)      │
│          sleep(0.5s)                                    │
│                                                         │
│  API: 5,524 × 6 × 20 × 4 = ~2,616,000 次              │
│  占总请求的 95%                                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 10: 公司报告 (ReportDownloader)                    │
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
│  API: 5,524 × 2 = 11,048 次                            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 11: 分红与复权 (DividendDownloader)                │
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
│ 更新元数据                                                │
│  • trade_dates          ← 全量刷新                       │
│  • stock_industry       ← 全量刷新                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              ┌──── 是否交易日? ────┐
              │                    │
            否│                  是│
              ▼                    ▼
   ┌──────────────────┐   ┌──────────────────────────────┐
   │ 跳过K线更新       │   │ 周一? → 更新指数成分股       │
   │ 直接去财务更新    │   │ (sz50/hs300/zz500)          │
   └──────────────────┘   └──────────────┬───────────────┘
                                         │
                                         ▼
                                ┌────────────────────────┐
                                │ 更新指数K线             │
                                │  • index_daily          │
                                │  • index_weekly         │
                                │  • index_monthly        │
                                │  start_date=index_start │
                                └──────────────┬─────────┘
                                               │
                                               ▼
                                ┌────────────────────────┐
                                │ 更新股票日线K线         │
                                │ (仅日线, 不含周/月)     │
                                │ start_date=start_date  │
                                │ 3种复权                 │
                                │ API: 5,524 × 3 = 16,572│
                                └──────────────┬─────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────┐
│ 更新财务数据 (仅当前季度)                                 │
│                                                         │
│  if Q1: 查 Q1                                           │
│  else:  查 Q(current-1) 和 Q(current)                   │
│                                                         │
│  API: 5,524 × 6 × 2 = ~66,288 次                       │
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

## 3. K 线下载内部流程

```
┌─────────────────────────────────────────────────────┐
│  download_daily_kline(codes, start_date, end_date)  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  for adjustflag in [1, 2, 3]:  ← 后复权/前复权/不复权│
│  ┌───────────────────────────────────────────────┐  │
│  │  _download_kline_batch()                      │  │
│  │                                               │  │
│  │  for batch in codes (每批200只):              │  │
│  │  ┌─────────────────────────────────────────┐ │  │
│  │  │  for code in batch:                     │ │  │
│  │  │                                         │ │  │
│  │  │  1. 检查断点续传                         │ │  │
│  │  │     if skipping: continue               │ │  │
│  │  │                                         │ │  │
│  │  │  2. 查询已下载的最新日期                  │ │  │
│  │  │     last = get_last_downloaded(table,   │ │  │
│  │  │                          code)          │ │  │
│  │  │                                         │ │  │
│  │  │  3. 计算实际起始日期                     │ │  │
│  │  │     actual_start =                      │ │  │
│  │  │       max(start_date, last)             │ │  │
│  │  │                                         │ │  │
│  │  │  4. 检查是否已完成                       │ │  │
│  │  │     if last >= end_date: continue       │ │  │
│  │  │                                         │ │  │
│  │  │  5. API 调用                            │ │  │
│  │  │     query_with_retry(                   │ │  │
│  │  │       bs.query_history_k_data_plus,     │ │  │
│  │  │       code=code,                        │ │  │
│  │  │       fields=fields,                    │ │  │
│  │  │       start_date=actual_start,          │ │  │
│  │  │       end_date=end_date,                │ │  │
│  │  │       frequency="d",                    │ │  │
│  │  │       adjustflag=str(adjustflag))       │ │  │
│  │  │                                         │ │  │
│  │  │  6. 保存数据 (upsert)                   │ │  │
│  │  │     INSERT OR REPLACE                   │ │  │
│  │  │                                         │ │  │
│  │  │  7. 更新检查点                           │ │  │
│  │  │     _checkpoint_data = {                │ │  │
│  │  │       table, adjustflag, last_code      │ │  │
│  │  │     }                                   │ │  │
│  │  └─────────────────────────────────────────┘ │  │
│  │                                               │  │
│  │  8. 批量写入数据库 (upsert)                   │  │
│  │  9. sleep(2s)  ← 批次间隔                    │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## 4. 请求计数与限流机制

```
┌─────────────────────────────────────────────────────┐
│  每次 API 调用                                       │
│  ┌───────────────────────────────────────────────┐  │
│  │  1. ensure_login()                            │  │
│  │     if time.time() - _login_time > 1800s:     │  │
│  │       logout() → login()                      │  │
│  │                                               │  │
│  │  2. 执行查询                                   │  │
│  │     rs = query_func(**kwargs)                 │  │
│  │                                               │  │
│  │  3. _increment_request_count()                │  │
│  │     UPDATE request_count SET count=count+1    │  │
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

## 5. 各阶段 API 请求汇总

| Phase | 模块 | API 请求数 | 占比 | 耗时 |
|-------|------|-----------|------|------|
| 2 | 元数据 | 3 | <0.1% | <1s |
| 4 | 宏观数据 | 5 | <0.1% | <1s |
| 5 | 指数成分股 | 3 | <0.1% | <1s |
| 6 | 指数 K 线 | 24 | <0.1% | ~1min |
| 7 | 股票 K 线(日/周/月) | 49,716 | 2.8% | ~1天 |
| 8 | 分钟 K 线 | 66,288 | 3.7% | ~1.4天 |
| 9 | 财务数据 | ~2,616,000 | **95.0%** | ~53天 |
| 10 | 公司报告 | 11,048 | 0.6% | ~0.2天 |
| 11 | 分红与复权 | ~226,484 | 12.8% | ~4.6天 |
| **合计** | | **~2,969,571** | 100% | **~60天** |

> 注：Phase 11 分红数据按每年 2 次 (report/operate) 估算，实际可能更少。
> Phase 8 分钟线默认关闭，不计入常规下载。

## 6. 增量更新 API 请求

| 模块 | API 请求数 | 说明 |
|------|-----------|------|
| 元数据刷新 | 2 | trade_dates + stock_industry |
| 指数成分股 | 3 | 仅周一 |
| 指数 K 线 | 24 | 8 指数 × 3 频率 |
| 股票日线 | 16,572 | 5,524 × 3 复权 |
| 财务数据 | ~66,288 | 5,524 × 6 × 2 季度 |
| 分红数据 | ~11,048 | 5,524 × 2 |
| **合计** | **~93,937** | 约 2 天额度 |

## 7. 关键配置参数

| 参数 | 默认值 | 来源 | 作用 |
|------|--------|------|------|
| `daily_request_limit` | 49,000 | config.yaml | 每日 API 请求上限 |
| `batch_size` | 200 | config.yaml | K 线每批处理的股票数 |
| `batch_sleep` | 2s | config.yaml | 批次间休眠时间 |
| `FINANCIAL_SLEEP` | 0.5s | src/config.py | 财务数据每次调用间隔 |
| `LOGIN_REFRESH_INTERVAL` | 1800s | src/config.py | 会话刷新间隔 (30分钟) |
| `MAX_RETRIES` | 3 | src/config.py | 查询失败重试次数 |
| `socket_timeout` | 30s | config.yaml | 网络超时 |
