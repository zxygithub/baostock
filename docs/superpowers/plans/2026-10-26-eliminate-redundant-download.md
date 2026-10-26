# 消除重复下载与无效趟次循环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除下载管道中的重复下载(指数/元数据全量重拉、退市股永久重探、探测空转)并将趟次重启循环改为"无新增即休眠复检"(方案 B),空转日行数 185 万 → ≤10 万。

**Architecture:** 各 downloader 内做"增量/跳过/每日一探"收紧(`BaseDownloader` 提供 `count_new_rows` 与 `daily_probe_memo` 两个基础设施),`run_main_with_report` 增加可选趟次调度循环(分段心跳休眠),`download_all.main()` 聚合返回"本趟新增行数"供调度器决策。

**Tech Stack:** Python 3.12(`.venv`)、pandas、SQLite(WAL)、pytest;进程编排为 bash(crontab + `monitor_baostock.sh`,本次不改)。

**Spec:** `docs/superpowers/specs/2026-10-26-eliminate-redundant-download-design.md`(设计已批准;以其"已确认决策"与"审阅修订记录"为准)

## Global Constraints

- 测试命令:`.venv/bin/python -m pytest tests/ -q`,每任务结束全量通过(至少涉及文件不回归)。
- 提交信息中文、`feat:/fix:/docs:` 前缀,每任务一次提交。
- 设计"不做"清单硬约束:不改 `target_date = 昨日` 语义、46,000 配额与黑名单机制、`monitor_baostock.sh`、报表 7 天滚动窗口、复权因子每日全量刷新。
- 新增行计数必须排除占位行(key 列值 `'9999-01-01'`,含财务 NaN 季度占位——财务占位不计入)。
- 休眠分段 ≤300 秒且每段写一条心跳日志(monitor 以"日志 15 分钟静默"判卡死:`monitor_baostock.sh:396`)。
- `daily_probe_memo.probe_date` 用 Python 本地 `date.today().isoformat()`(禁用 SQLite `date('now')` 的 UTC 口径)。
- temp 表 + LEFT JOIN 查询后必须 `self.conn.rollback()`(`_find_missing_quarters` 已注释的 wal_checkpoint(TRUNCATE) 锁库地雷)。

## Review Focus

1. **休眠期无心跳或心跳间隔 >15 分钟** → monitor 判卡死 SIGINT 重启,方案 B 退化为 15 分钟循环 —— `tests/test_pass_scheduler.py::test_idle_pass_sleeps_in_segments_with_heartbeat`。
2. **占位行被计为"新增"** → 有占位写的趟永不休眠 —— `tests/test_downloader_new_rows.py::test_placeholder_rows_not_counted`。
3. **`update_daily.py` 被循环化** → 手动命令挂 24 小时 —— `tests/test_pass_scheduler.py::test_loop_false_runs_single_pass`。
4. **休眠跨 23:55 不发日报** —— `tests/test_pass_scheduler.py::test_sleep_crossing_shutdown_sends_report`。
5. **退市股历史缺口被永久跳过** → 漏补数据 —— `tests/test_dead_stock_skip.py::test_delisted_with_gap_still_fetches`。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `src/downloaders/base.py` | `new_rows` 累加器、`count_new_rows`、`is_probed_today`/`mark_probed`(共用基础设施) |
| `src/db_manager.py` | `daily_probe_memo` 建表(`_create_daily_probe_memo`,init + migrate 双入口) |
| `src/downloaders/kline_downloader.py` | 退市股跳过 + K 线新增行计数 |
| `src/downloaders/index_downloader.py` | 指数 K 线增量 + 新增行计数 |
| `src/downloaders/financial_downloader.py` | 缺失季度每日一探(备忘)+ 新增计数 |
| `src/downloaders/dividend_downloader.py` | 复权未覆盖事件每日一探(备忘)+ 新增计数 |
| `src/downloaders/report_downloader.py` | 新增行精确计数 |
| `src/utils/helpers.py` | 趟次调度循环(方案 B)+ 心跳休眠 |
| `src/config_loader.py` / `config.yaml` | `download.idle_pass_interval_minutes: 90` |
| `scripts/download_all.py` | `main() -> int` 聚合新增行;元数据每日一次;`--once`/`--force-meta` |
| `tests/` | 6 组新测试(见各任务);文档同步在 `README.md`、`docs/download_flow.md` |

---

### Task 1: 新增行计数基础设施(`BaseDownloader`)

**Files:**
- Modify: `src/downloaders/base.py`(`__init__`、新增 `count_new_rows`)
- Test: `tests/test_count_new_rows.py`(新建)

**Interfaces:**
- Produces: `BaseDownloader.new_rows: int`(实例属性,初值 0);`BaseDownloader.count_new_rows(self, df: pd.DataFrame, table: str, key_cols: list[str]) -> int` —— 返回 `df` 中主键组合 `(key_cols...)` 在 `table` 里不存在的行数;`df` 为空返回 0;`key_cols` 任一列值为 `'9999-01-01'` 的行(占位行)不计。
- 后续任务依赖:`self.new_rows` 累加语义 = "此前不在库中的真实数据行"。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_count_new_rows.py —— 夹具参照 tests/test_adjust_factor_skip.py(临时 sqlite + 属性注入/monkeypatch login)
def test_all_rows_missing_counts_all(...)
def test_existing_rows_count_zero(...)
def test_partial_overlap_counts_only_missing(...)
def test_placeholder_rows_not_counted(...)      # key 值 '9999-01-01' 的行恒不计
def test_empty_df_returns_zero(...)
```
断言:2 行 df 打中已有 1 行的表 → 返回 1;含 1 行占位的 df 打空表 → 返回 0。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_count_new_rows.py -q`
Expected: FAIL(`AttributeError: ... count_new_rows`)

- [ ] **Step 3: 实现 `__init__` 中 `self.new_rows: int = 0` 与 `count_new_rows`**

签名见 Interfaces。实现用临时表 + LEFT JOIN(仿 `_find_missing_quarters`),结尾 `self.conn.rollback()`(Global Constraints 的锁库地雷)。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_count_new_rows.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/base.py tests/test_count_new_rows.py
git commit -m "feat: BaseDownloader 新增行精确计数基础设施"
```

### Task 2: K 线退市股跳过 + 新增行计数

**Files:**
- Modify: `src/downloaders/kline_downloader.py:39-90`(`_download_kline_batch`)
- Test: `tests/test_dead_stock_skip.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `self.new_rows`;现有 `get_last_downloaded(table, code, adjustflag=...)`、`ipo_dates: dict[str, tuple[str|None, str|None]]`。
- Produces: 跳过规则(设计组件 1):`effective_end = end_date or "9999-99-99"`,**skip iff `stock_out and stock_out <= effective_end and last and last >= stock_out`**;被跳过时与现有 `last >= end_date` 分支一样先写 `self._checkpoint_data` 再 `continue`。K 线计数:`date_idx = fields.split(",").index("date")`,每 code 查询后 `self.new_rows += sum(1 for r in rows if last is None or r[date_idx] > last)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dead_stock_skip.py —— 直接调 _download_kline_batch,mock query_with_retry/save_df/get_last_downloaded
def test_delisted_and_complete_skips_query(...)      # out_date=2009-12-29, last=2009-12-29 → query 调用 0 次
def test_delisted_with_gap_still_fetches(...)        # out_date=2022-06-28, last=2022-01-31 → query 1 次
def test_live_stock_fetches(...)                     # out_date=None → query 1 次
def test_out_date_after_end_date_fetches(...)        # out_date > end_date → query 1 次
def test_new_rows_counts_only_rows_after_last(...)   # last=2026-10-23, 返回 [2026-10-23, 2026-10-26] 两行 → new_rows=1
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_dead_stock_skip.py -q`
Expected: FAIL(退市股仍发起查询 / `new_rows` 未计)

- [ ] **Step 3: 实现跳过规则与计数**

按 Interfaces 的规则替换现有 `if stock_out and stock_out < start_date: continue` 一行(新规则覆盖其语义);计数插在 `rows = fetch_all_rows(rs)` 之后。周/月线共用该方法,自动生效。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_dead_stock_skip.py tests/test_close_checkpoint.py -q`
Expected: PASS(含 checkpoint 回归)

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/kline_downloader.py tests/test_dead_stock_skip.py
git commit -m "feat: K线退市股自愈跳过与新增行计数"
```

### Task 3: `daily_probe_memo` 表 + 探测备忘 helper

**Files:**
- Modify: `src/db_manager.py`(`init_all_tables` schema 块 + `migrate_schema` 守卫 + `_create_daily_probe_memo`)
- Modify: `src/downloaders/base.py`(新增 `is_probed_today`、`mark_probed`)
- Test: `tests/test_probe_memo.py`(新建)

**Interfaces:**
- Produces: 表 `daily_probe_memo(scope TEXT NOT NULL, item_key TEXT NOT NULL, probe_date TEXT NOT NULL, PRIMARY KEY(scope, item_key))`;
  `BaseDownloader.is_probed_today(self, scope: str, item_key: str) -> bool` —— `probe_date == date.today().isoformat()` 为 True;
  `BaseDownloader.mark_probed(self, scope: str, item_key: str) -> None` —— UPSERT `probe_date = 今日`,立即 commit。
- 后续约定 scope 命名:`"fin_missing:<table>"`(item_key `"<code>|<year>|<quarter>"`)、`"af_uncovered"`(item_key `"<code>"`)。

- [ ] **Step 1: 写失败测试**

```python
def test_mark_then_probed_same_day(...)        # mark 后 is_probed_today True
def test_yesterday_mark_not_probed(...)        # probe_date 昨日 → False
def test_mark_upserts_overwrite(...)           # 重复 mark 不报错,单行
def test_missing_table_recreated_on_migrate(...)  # 对旧库跑 migrate_schema 后表存在
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_probe_memo.py -q`
Expected: FAIL(方法/表不存在)

- [ ] **Step 3: 实现建表与 helper**

`_create_daily_probe_memo(conn)` 仿 `_create_request_count`;`migrate_schema` 加 `if "daily_probe_memo" not in tables:` 守卫;helper 用 Python 本地日期(Global Constraints)。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_probe_memo.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db_manager.py src/downloaders/base.py tests/test_probe_memo.py
git commit -m "feat: daily_probe_memo 探测备忘表与 helper"
```

### Task 4: 指数 K 线增量拉取

**Files:**
- Modify: `src/downloaders/index_downloader.py`(`download_index_daily/weekly/monthly`)
- Test: `tests/test_index_kline_incremental.py`(新建)

**Interfaces:**
- Consumes: `get_last_downloaded(table, code)`(不带 adjustflag;`index_weekly/monthly` 含 adjustflag 列也按全表 max 取,设计组件 3 已裁定)、Task 1 的 `self.new_rows`。
- Produces: 每 code:`last >= end_date`(end_date 非空时)→ 跳过;否则 `actual_start = max(start_date, last) if last else start_date`;计数同 K 线 `sum(1 for r in rows if last is None or r[date_idx] > last)`。方法签名不变。

- [ ] **Step 1: 写失败测试**

```python
def test_up_to_date_index_skipped(...)       # last == end_date → query 0 次
def test_incremental_start_from_last(...)    # 断言 query 的 start_date == max(配置起始, last)
def test_first_time_full_range(...)          # 无存量 → start_date == 配置起始日
def test_new_rows_counts_after_last(...)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_index_kline_incremental.py -q`
Expected: FAIL

- [ ] **Step 3: 实现增量逻辑(三个方法同构)**

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_index_kline_incremental.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/index_downloader.py tests/test_index_kline_incremental.py
git commit -m "feat: 指数K线按 code 增量拉取"
```

### Task 5: 财务缺失季度 / 复权未覆盖事件 每日一探

**Files:**
- Modify: `src/downloaders/financial_downloader.py`(`_find_missing_quarters`、`_download_quarterly_data` 任务循环)
- Modify: `src/downloaders/dividend_downloader.py`(`_find_stale_adjust_factor` 第二 UNION 分支、`download_adjust_factor` 循环)
- Test: `tests/test_probe_memo.py`(追加用例)

**Interfaces:**
- Consumes: Task 3 的 `is_probed_today`/`mark_probed`,scope 命名同 Task 3。
- Produces:
  - `_find_missing_quarters(self, table_name, candidates, today: str | None = None)`(新增 `today` 参数,缺省 Python 本地今日;SQL 增加 `NOT EXISTS (... probe_date >= today)`)。返回签名不变。
  - `_download_quarterly_data` 任务循环:query 成功后(空结果同样)`self.mark_probed(f"fin_missing:{table_name}", f"{code}|{year}|{quarter}")`;`RuntimeError` 路径**不** mark(留给下趟重试);`total_rows += len(df)` 处同步 `self.new_rows += len(df)`。
  - `_find_stale_adjust_factor` 第二 UNION 分支加 `AND NOT EXISTS (... m.scope='af_uncovered' AND m.item_key=c.code AND m.probe_date >= ?)`;`download_adjust_factor` 中每次 query 成功后(含空结果路径,与现有 `_mark_adjust_checked` 并列)`self.mark_probed("af_uncovered", code)`(对两分支探测到的 code 统一 mark——全量历史刚拉过,未覆盖事件确实已查)。

- [ ] **Step 1: 写失败测试**

```python
def test_fin_missing_probed_once_per_day(...)     # 空结果任务当日第二趟不再出现在 tasks
def test_fin_missing_reprobed_next_day(...)       # probe_date 置昨日 → 重新出现
def test_fin_missing_not_marked_on_error(...)     # RuntimeError → 不 mark,下趟仍在
def test_af_uncovered_probed_once_per_day(...)    # 未覆盖事件 code 当日第二趟不重探
def test_af_uncovered_reprobed_next_day(...)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_probe_memo.py -q`
Expected: FAIL(新增用例)

- [ ] **Step 3: 实现备忘过滤与标记(SQL 过滤 + 循环标记)**

- [ ] **Step 4: 运行确认通过(含既有回归)**

Run: `.venv/bin/python -m pytest tests/test_probe_memo.py tests/test_financial_skip_logic.py tests/test_adjust_factor_skip.py tests/test_dividend_refresh.py -q`
Expected: PASS(既有测试若因签名/SQL 变化失败,按本任务 Interfaces 更新断言)

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/financial_downloader.py src/downloaders/dividend_downloader.py tests/test_probe_memo.py
git commit -m "feat: 财务缺失季度与复权未覆盖事件每日一探"
```

### Task 6: 报表 / 分红 / 复权因子 新增行精确计数

**Files:**
- Modify: `src/downloaders/report_downloader.py`(两处 save 后)
- Modify: `src/downloaders/dividend_downloader.py`(`download_dividend` 真实行、`download_adjust_factor`)
- Test: `tests/test_downloader_new_rows.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `count_new_rows(df, table, key_cols)`、`self.new_rows`。
- Produces: 各 save 站点计数:
  - `performance_express` → `count_new_rows(df, "performance_express", ["code", "performance_exp_pub_date"])`;
  - `forecast_report` → `["code", "profit_forecast_exp_pub_date"]`;
  - `dividend` 真实行 → `["code", "divid_operate_date", "year", "year_type"]`;
  - `adjust_factor` → `["code", "divid_operate_date"]`。
  - 占位行(`'9999-01-01'` 及批量 placeholder df)**不计**(任务生成方自知哪些是占位,不调用计数)。

- [ ] **Step 1: 写失败测试**

```python
def test_placeholder_rows_not_counted(...)      # Review Focus 2:占位 df 写入后 new_rows 仍为 0
def test_report_refetch_of_existing_rows_counts_zero(...)   # 7 天窗口复拉存量行 → 0
def test_dividend_new_rows_counted(...)         # 新 (code,date,year,year_type) → 1
def test_adjust_factor_new_rows_counted(...)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_downloader_new_rows.py -q`
Expected: FAIL

- [ ] **Step 3: 在四个 save 站点接线计数**

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_downloader_new_rows.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/report_downloader.py src/downloaders/dividend_downloader.py tests/test_downloader_new_rows.py
git commit -m "feat: 报表/分红/复权因子新增行精确计数"
```

### Task 7: 趟次调度循环(方案 B)+ 心跳休眠

**Files:**
- Modify: `src/utils/helpers.py`(`run_main_with_report`)
- Modify: `src/config_loader.py`(新增 `get_idle_pass_interval_minutes`)、`config.yaml`(`download.idle_pass_interval_minutes: 90`)
- Test: `tests/test_pass_scheduler.py`(新建)

**Interfaces:**
- Consumes: `main_fn()` 返回 int(新增行数)或 None(None 视作 0);`is_past_shutdown_time()`(已有)、`send_daily_report(reason, logger)`(已有)。
- Produces: `run_main_with_report(main_fn, logger=None, *, loop: bool = False) -> None`:
  - `loop=False`(`update_daily.py`、`--once` 用):保持现状——`SystemExit(1)`→发日报(配额理由);正常返回且过 23:55→发日报(停止时间理由);否则打"趟次结束"日志返回。
  - `loop=True`(`download_all` 默认):`while True` 跑趟;`SystemExit(1)` 或过 23:55 → 发日报并 return;返回新增行 >0 → 立即下一趟;否则休眠 `get_idle_pass_interval_minutes()` 分钟,**按 ≤300 秒分段**,每段 `logger.info` 一条心跳(含已休眠/总时长),每段醒后查 `is_past_shutdown_time()`,过点即终结发日报。
  - `get_idle_pass_interval_minutes() -> int`:读 `download.idle_pass_interval_minutes`,缺省 90。

- [ ] **Step 1: 写失败测试**

```python
def test_loop_false_runs_single_pass(...)              # Review Focus 3:loop=False 只调 main_fn 一次
def test_productive_pass_runs_immediately(...)         # 返回 5 → 第二趟紧接执行,无 sleep
def test_idle_pass_sleeps_in_segments_with_heartbeat(...)  # Review Focus 1:断言 sleep 实参 ≤300 且被调多次、每段有 log
def test_sleep_crossing_shutdown_sends_report(...)     # Review Focus 4:分段醒来过 23:55 → send_daily_report("达到每日停止时间(23:55)")
def test_systemexit_1_sends_limit_reason_loop(...)     # 循环模式下配额理由不变
def test_idle_interval_from_config(...)                # monkeypatch 配置 → sleep 总时长一致
```
(既有 `tests/test_completion_report.py` 须保持通过:loop 默认 False,行为不变。)

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_pass_scheduler.py -q`
Expected: FAIL

- [ ] **Step 3: 实现调度循环与配置项**

心跳日志是硬约束(Global Constraints):monitor `check_process_activity` 15 分钟阈值见 `monitor_baostock.sh:396`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_pass_scheduler.py tests/test_completion_report.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/helpers.py src/config_loader.py config.yaml tests/test_pass_scheduler.py
git commit -m "feat: 趟次调度循环与心跳休眠(方案B)"
```

### Task 8: 元数据每日一次 + CLI 旗标

**Files:**
- Modify: `scripts/download_all.py`(Phase 2 门控、argparse、模块底部调用)
- Test: `tests/test_meta_daily_once.py`(新建)

**Interfaces:**
- Consumes: Task 7 的 `run_main_with_report(..., loop=)`。
- Produces: 标记文件 `DB_PATH.parent / f".meta_fetched_{date.today():%Y-%m-%d}"`(沿用 `.report_sent_*` 惯例);`download_all_metadata()` 成功后落标记;标记存在且无 `--force-meta` → 跳过 Phase 2。argparse 新增 `--once`(单趟即退)、`--force-meta`(强制刷新元数据);模块底部 `run_main_with_report(main, loop="--once" not in sys.argv)`。

- [ ] **Step 1: 写失败测试**

```python
def test_meta_skipped_when_marker_exists(...)
def test_meta_runs_and_writes_marker(...)
def test_force_meta_overrides_marker(...)
```
(门控逻辑若在 main() 内,先抽成可单测的小函数 `should_refresh_meta(force: bool) -> bool` 再测。)

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_meta_daily_once.py -q`
Expected: FAIL

- [ ] **Step 3: 实现门控与旗标**

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_meta_daily_once.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/download_all.py tests/test_meta_daily_once.py
git commit -m "feat: 元数据每日一次与 --once/--force-meta 旗标"
```

### Task 9: `main()` 聚合新增行 + 文档同步 + 全量回归

**Files:**
- Modify: `scripts/download_all.py`(各阶段后累加 `dl.new_rows`,`main() -> int`)
- Modify: `README.md`、`docs/download_flow.md`(同步趟次/跳过/备忘语义)
- Test: 无新增(聚合逻辑由 Task 7 的调度测试覆盖 main_fn 契约;此处做回归)

**Interfaces:**
- Consumes: 各 downloader 的 `self.new_rows`(Task 2/4/5/6 累加)。
- Produces: `scripts/download_all.main() -> int` = 本趟各阶段 `new_rows` 之和(元数据/宏观/成分不累加,天然为 0)。

- [ ] **Step 1: 实现聚合(每个 `with ... as dl:` 块结束后 `new_rows += dl.new_rows`),`return new_rows`**

- [ ] **Step 2: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS(既有用例不回归;若 `test_download_all_skip_logic.py` 等引用 main 返回值,按 int 契约微调)

- [ ] **Step 3: 文档同步**

README 与 `docs/download_flow.md` 补:退市股跳过条件、指数增量、元数据/探测每日一次、趟次调度(90 分钟复检、23:55 终结)、`--once`/`--force-meta` 用法。措辞简短,与设计稿一致。

- [ ] **Step 4: Commit**

```bash
git add scripts/download_all.py README.md docs/download_flow.md
git commit -m "feat: main() 返回趟次新增行数并同步下载流程文档"
```

- [ ] **Step 5: 验收对照(设计"预期效果与验收")**

手工核对:空转趟成本 ≤50 请求(日志 summary)、无新增趟次 summary 显示"新增 0 行"、日报 23:55 正常。此为观察项,由日志与次日日报确认,不阻塞合入。
