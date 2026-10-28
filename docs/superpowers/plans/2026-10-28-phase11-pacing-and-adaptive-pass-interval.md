# Phase 11 批内限速与自适应趟次间隔 实施计划(A1 + B2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除分红/复权/报表阶段逐请求 `sleep(1)`(每晚约 4.5 小时纯休眠),并把趟次调度从固定 90 分钟改为"有新增 10 分钟、连续空趟指数退避封顶 90 分钟"。

**Architecture:** A1 — 在 `helpers` 增加 `RequestPacer`(每 N 次请求睡一次,与 K 线"每批 200 只睡 1 秒"等价),替换 4 处逐请求 `time.sleep(batch_sleep)`。B2 — 趟次间隔由纯函数 `compute_pass_interval_minutes(new_rows, idle_count)` 计算:有新增→基础间隔并清零空趟计数;空趟→`base * 2**(idle_count-1)` 封顶 `idle_pass_interval_minutes`;`run_main_with_report` 循环体不再对有新增趟次 `continue` 直连,统一走分段休眠。

**Tech Stack:** Python 3.11+,pytest(仅收集 `test_*.py`),SQLite(测试用 tmp_path 临时库),uv(.venv)。

**Spec:** 本计划即规范(A1+B2 为 2026-10-28 诊断后经人工确认的两项);行为基线见 `docs/download_flow.md` 第 10 节与 `tests/test_pass_scheduler.py`。

## Global Constraints

- Python >= 3.11;测试命令统一用 `.venv/bin/python -m pytest tests/ -q`(单文件可加 `-x -q`)。
- 配置读取统一走 `src/config_loader.py`,不得在下载器里直接读 YAML;缺省值与 `config.yaml` 显式值保持一致。
- 任何趟次休眠必须继续经 `_sleep_idle_in_segments`(≤300 秒分段 + 心跳日志 + 每段检查 23:55),不得改回整段 `time.sleep`。
- 逐请求 `time.sleep(batch_sleep)` 全部移除;`batch_sleep` 语义变为"每 `batch_size` 次请求后的停顿秒数"(限速窗口),注释同步。
- 测试不得访问 `data/baostock.db`(16 GB 生产库)、不得联网;沿用 `tests/test_dividend_refresh.py` 的 `object.__new__(Downloader)` + tmp_path 夹具风格。
- 提交信息沿用仓库风格:`Developer <type>: <中文描述>`;type ∈ feat/fix/docs/test/refactor。

## Review Focus

1. **限速提高后的封禁风险**:分红/复权/报表请求速率从 ~0.8 req/s 提到 ~5 req/s(与 K 线同速率)。若服务端返回 error_code 10001011(封禁),monitor 有 120 分钟退避兜底;回滚手段是把 `stocks.batch_size` 调小(如 50)以降低速率。→ Task 1/2 的集成测试断言"睡眠次数 = ceil(请求数/batch_size)",README 更新日志里写明观察窗口。
2. **请求计数与额度**:`query_with_retry` 内 `_increment_request_count()` 不受影响;`RequestPacer.tick()` 不得替代或包裹请求计数。→ Task 1 单测只测睡眠节奏,不碰计数。
3. **23:55 停止语义不变**:任何趟次休眠(含 10 分钟短睡)期间跨过 23:55 仍须返回 True 并发日报。→ Task 3 保留 `test_sleep_crossing_shutdown_sends_report` 并新增短间隔跨 23:55 用例。
4. **非正间隔钳位**:间隔 ≤0 仍钳位到 1 分钟,不得热循环;退避指数不得溢出到异常值。→ Task 3 的纯函数单测覆盖 cap=0、base=0。
5. **空趟计数持久性**:进程内计数,趟次间不落库;`main_fn` 抛 `SystemExit(1)`(额度用尽)时不再睡眠、直接发日报。→ Task 3 用例 `test_systemexit_1_sends_limit_reason_loop` 保持通过。

---

### Task 1: `RequestPacer` + 分红/复权循环批内限速(A1 前半)

**Files:**
- Modify: `src/utils/helpers.py`(新增 `RequestPacer`,放在 `batch_iterable` 之后)
- Modify: `src/downloaders/dividend_downloader.py`(两处循环:分红任务循环、复权 stale_codes 循环)
- Test: `tests/test_request_pacer.py`(新建)

**Interfaces:**
- Consumes: `src.config_loader.get_batch_size()`(每批请求数,默认 200)、`get_batch_sleep()`(批间停顿秒,默认 1)。
- Produces: `RequestPacer(requests_per_sleep: int, sleep_seconds: float, sleep: Callable[[float], None] | None = None)`;方法 `tick() -> None`——每调用一次计 1 次请求,累计满 `requests_per_sleep` 次时执行一次 `sleep(sleep_seconds)` 并清零计数。后续 Task 2 复用同一类。

- [ ] **Step 1: 写失败测试**(新建 `tests/test_request_pacer.py`)

```python
def test_pacer_sleeps_once_per_window():
    sleeps = []
    pacer = RequestPacer(3, 1.5, sleep=sleeps.append)
    for _ in range(7):
        pacer.tick()
    assert sleeps == [1.5, 1.5]      # 第 3、6 次后各睡一次;第 7 次不满窗口不睡

def test_pacer_window_of_one_sleeps_every_tick():
    sleeps = []
    pacer = RequestPacer(1, 2.0, sleep=sleeps.append)
    for _ in range(3):
        pacer.tick()
    assert sleeps == [2.0, 2.0, 2.0]

def test_pacer_non_positive_window_clamps_to_one():
    sleeps = []
    pacer = RequestPacer(0, 1.0, sleep=sleeps.append)
    for _ in range(2):
        pacer.tick()
    assert sleeps == [1.0, 1.0]      # 不得除零,也不得漏睡

def test_pacer_defaults_to_time_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)   # 经 helpers.time 解析,与现有测试同款
    pacer = RequestPacer(2, 0.5)
    for _ in range(2):
        pacer.tick()
    assert sleeps == [0.5]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py -q`
Expected: FAIL(ImportError / `RequestPacer` 未定义)

- [ ] **Step 3: 在 `src/utils/helpers.py` 实现 `RequestPacer`**

`sleep=None` 时在 **tick 调用时** 才解析 `time.sleep`(保证 monkeypatch 生效);`requests_per_sleep <= 0` 视为 1。类之外不加额外封装。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py -q`
Expected: 4 passed

- [ ] **Step 5: 写分红循环集成测试(失败)**

同一文件新增(夹具风格对齐 `tests/test_dividend_refresh.py` 的 `_make_dl`):

```python
def test_dividend_loop_paces_per_batch_not_per_request(tmp_path, monkeypatch):
    # 5 个 (code, year, year_type) 任务全部返回空行;requests_per_sleep=2
    # 断言 time.sleep 被调用 2 次(任务 2、4 之后各一次),而非每任务 1 次(5 次)
```

构造 `DividendDownloader`(object.__new__ + tmp_path 建 `dividend` 表),`monkeypatch.setattr(dl, "query_with_retry", ...)` 返回假结果、`monkeypatch.setattr(dl, "fetch_all_rows", lambda rs: [])`,`monkeypatch.setattr(div_mod, "get_batch_size", lambda: 2)`、`monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 1.0)`、`monkeypatch.setattr(time, "sleep", sleeps.append)`。调用被测方法后 `assert len(sleeps) == 2`。

- [ ] **Step 6: 跑集成测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py -q -k dividend`
Expected: FAIL(当前每任务都 sleep,`len(sleeps) == 5`)

- [ ] **Step 7: 改造 `src/downloaders/dividend_downloader.py` 两处循环**

方法签名不变。两处循环各做同一件事:循环前 `pacer = RequestPacer(get_batch_size(), get_batch_sleep())`,把该循环内所有 `time.sleep(batch_sleep)` 替换为 `pacer.tick()`(分红循环 3 处:RuntimeError 分支、空行占位分支、正常分支;复权循环 3 处同构)。不再需要局部变量 `batch_sleep`(改用 `get_batch_sleep()` 传入 pacer)。不得改动 `count_new_rows`/`save_df`/占位删除等既有语义。

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py tests/test_dividend_refresh.py tests/test_adjust_factor_skip.py -q`
Expected: 全部 passed(既有分红/复权跳过逻辑用例不得回归)

- [ ] **Step 9: 提交**

```bash
git add src/utils/helpers.py src/downloaders/dividend_downloader.py tests/test_request_pacer.py
git commit -m "Developer perf: 分红/复权逐请求休眠改为批内限速(每 200 请求睡 1 秒)"
```

---

### Task 2: 报表循环批内限速(A1 后半)

**Files:**
- Modify: `src/downloaders/report_downloader.py`(`download_performance_express`、`download_forecast_report`)
- Test: `tests/test_request_pacer.py`(追加用例)

**Interfaces:**
- Consumes: Task 1 的 `RequestPacer`、`get_batch_size()`、`get_batch_sleep()`。
- Produces: 无新接口;两个方法签名与返回值(int)不变。

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_request_pacer.py`)

```python
def test_performance_express_loop_paces_per_batch_not_per_request(tmp_path, monkeypatch):
    # 3 个 code 全部返回空行;requests_per_sleep=2 → sleeps 2 次(第 2 个 code 后、不足窗口不睡)
    # 断言 len(sleeps) == 1(3 个请求、窗口 2:仅第 2 次后睡一次)
```

夹具仿 `test_dividend_refresh.py`,建 `performance_express` 表(code, performance_exp_pub_date 主键),`query_with_retry`/`fetch_all_rows` 同款打桩;注意 `ReportDownloader._get_recently_queried_codes` 查的是库内占位行,空库时返回空集即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py -q -k performance`
Expected: FAIL(当前每 code 都 sleep,`len(sleeps) == 3`)

- [ ] **Step 3: 改造 `src/downloaders/report_downloader.py` 两个循环**

与 Task 1 Step 7 同构:每方法循环前建 pacer,方法内 2 处 `time.sleep(batch_sleep)` 换 `pacer.tick()`(空行占位分支 1 处、正常分支 1 处;RuntimeError 分支本就无 sleep,不动)。删除局部 `batch_sleep` 变量。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_request_pacer.py tests/test_financial_skip_logic.py -q`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add src/downloaders/report_downloader.py tests/test_request_pacer.py
git commit -m "Developer perf: 报表逐请求休眠改为批内限速,与分红/复权同款"
```

---

### Task 3: 自适应趟次间隔(B2)

**Files:**
- Modify: `src/config_loader.py`(新增 `get_productive_pass_interval_minutes`)
- Modify: `src/utils/helpers.py`(新增 `compute_pass_interval_minutes`,改 `run_main_with_report` loop 分支)
- Modify: `config.yaml`(`download` 段新增 `productive_pass_interval_minutes: 10`,`idle_pass_interval_minutes` 注释改为"上限")
- Test: `tests/test_pass_scheduler.py`(改 1 个用例、新增 4 个用例)

**Interfaces:**
- Consumes: `get_idle_pass_interval_minutes()`(默认 90,现语义=退避封顶)。
- Produces:
  - `config_loader.get_productive_pass_interval_minutes() -> int`(默认 10)
  - `helpers.compute_pass_interval_minutes(new_rows: int, idle_count: int) -> tuple[int, int]`——返回 `(sleep_minutes, next_idle_count)`:`new_rows > 0` → `(get_productive_pass_interval_minutes(), 0)`;否则 `idle_count += 1` 后 `(min(base * 2 ** (idle_count - 1), cap), idle_count)`,`cap = get_idle_pass_interval_minutes()`。

- [ ] **Step 1: 写失败测试**

`tests/test_pass_scheduler.py`:

```python
def test_compute_interval_productive_resets_idle_count(monkeypatch):
    monkeypatch.setattr(helpers, "get_productive_pass_interval_minutes", lambda: 10)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 90)
    assert helpers.compute_pass_interval_minutes(5, 3) == (10, 0)

def test_compute_interval_idle_backoff_doubles_until_cap(monkeypatch):
    monkeypatch.setattr(helpers, "get_productive_pass_interval_minutes", lambda: 10)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 90)
    got, n = [], 0
    for _ in range(6):
        minutes, n = helpers.compute_pass_interval_minutes(0, n)
        got.append(minutes)
    assert got == [10, 20, 40, 80, 90, 90]

def test_compute_interval_cap_zero_clamps_in_sleeper(monkeypatch):
    monkeypatch.setattr(helpers, "get_productive_pass_interval_minutes", lambda: 10)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 0)
    assert helpers.compute_pass_interval_minutes(0, 1) == (0, 2)  # 0 交给休眠器钳位到 1 分钟

def test_productive_pass_sleeps_base_interval(monkeypatch):
    # 两趟:第一趟返回 5(有新增),第二趟 SystemExit(1)
    # 断言 sleeps 总时长 == 10 分钟(有新增不再直连下一趟),且分段 <= 300 秒

def test_backoff_resets_after_productive_pass(monkeypatch):
    # 趟次序列:0,0,5,0 → 各趟前睡眠时长 10,20,10,10 分钟(第三次有新增后归零)
```

同时改写 `test_productive_pass_runs_immediately` → `test_productive_pass_sleeps_base_interval`(见上;原断言 `sleeps == []` 与 B2 冲突,属预期行为变更)。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_pass_scheduler.py -q`
Expected: 新增用例 FAIL(`compute_pass_interval_minutes` 未定义、有新增趟次仍直连)

- [ ] **Step 3: 实现配置项与纯函数,改造 `run_main_with_report`**

`config_loader.get_productive_pass_interval_minutes()` 读 `download.productive_pass_interval_minutes`,默认 10。`helpers` 顶部 from-import 同步补该函数。

`run_main_with_report` loop 分支:用 `idle_count = 0` 初始化;`else` 分支改为——`is_past_shutdown_time()` 为真则发日报;否则 `minutes, idle_count = compute_pass_interval_minutes(new_rows, idle_count)`,打一条日志(`本趟新增 %d 行 → %d 分钟后下一趟(连续空趟 %d)`),再 `_sleep_idle_in_segments(minutes, log, is_past_shutdown_time)`,返回 True 则发日报。**删除 `elif new_rows > 0: continue` 直连分支**。`loop=False` 分支不动。

`config.yaml`:`download.idle_pass_interval_minutes: 90  # 空闲趟次退避封顶分钟数(指数退避,连续空趟翻倍)`;新增 `download.productive_pass_interval_minutes: 10  # 有新增数据趟次后的下一趟间隔分钟数`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_pass_scheduler.py -q`
Expected: 全部 passed(含既有 6 个用例:`test_idle_pass_sleeps_in_segments_with_heartbeat`、`test_sleep_crossing_shutdown_sends_report`、`test_systemexit_1_sends_limit_reason_loop`、`test_idle_interval_from_config`、`test_non_positive_interval_clamps_to_min_sleep`、`test_idle_interval_default`)

- [ ] **Step 5: 提交**

```bash
git add src/config_loader.py src/utils/helpers.py config.yaml tests/test_pass_scheduler.py
git commit -m "Developer feat: 趟次间隔自适应——有新增 10 分钟、空趟指数退避封顶 90 分钟"
```

---

### Task 4: 全量回归 + 文档维护 + 推远程

**Files:**
- Modify: `docs/download_flow.md`(第 208 行流程图、~604 行分红流程、698-707 配置表、712-727 第 10 节趟次调度)
- Modify: `config.yaml`(Task 3 已改;本任务核对 `batch_size`/`batch_sleep` 注释与新语义一致)
- Modify: `README.md`(更新日志新增一条)
- Test: 全量 `tests/`

**Interfaces:**
- Consumes: Task 1-3 的全部行为。
- Produces: 文档描述与代码一致;远端 `origin/master` 包含本次全部提交。

- [ ] **Step 1: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed(仅 `test_*.py` 被收集;`smoke_test.py`/`integration_test.py` 不在收集范围)

- [ ] **Step 2: 更新 `docs/download_flow.md`**

四处同步:
1. 流程图 `• 无新增 → 休眠 90 分钟后复检` 改为 `• 有新增 → 10 分钟后复检;无新增 → 指数退避(10/20/40/80…封顶 90 分钟)`;
2. 分红/报表流程里的逐请求 `sleep(batch_sleep)` 改为 `每 batch_size 次请求 sleep(batch_sleep)`(限速窗口);
3. 配置表:`batch_size` 释义补"限速窗口=每批请求数",`batch_sleep` 改为"每窗口停顿秒数",`idle_pass_interval_minutes` 改为"空趟退避封顶",新增 `productive_pass_interval_minutes` 行;
4. 第 10 节趟次调度:删去"无新增 → 休眠 90 分钟"的固定描述,写明退避序列与重置规则,保留"≤5 分钟分段心跳/23:55 检查/非正钳位"三条不变项。

- [ ] **Step 3: 更新 `README.md` 更新日志**

按现有条目格式新增一条:说明两项提速(A1 批内限速:分红/复权/报表每晚约省 4 小时纯休眠;B2 自适应趟次:白天有新增即 10 分钟复检,空趟退避 90 分钟封顶)。

- [ ] **Step 4: 提交文档**

```bash
git add docs/download_flow.md README.md config.yaml
git commit -m "Developer docs: 同步批内限速与自适应趟次间隔的下载流程/配置/更新日志"
```

- [ ] **Step 5: 推远程**

```bash
git pull --rebase origin master
git push origin master
git log --oneline -6
```
Expected: push 成功,远端含 Task 1-4 的 4 个提交,工作区 clean。

---

## Self-Review 记录

- 覆盖:A1(Task 1+2,四处处 `time.sleep(batch_sleep)` 全覆盖)、B2(Task 3);用户要求的"完成后测试→维护文档→推远程"即 Task 4。
- 类型一致:`RequestPacer.tick() -> None`、`compute_pass_interval_minutes(int, int) -> tuple[int, int]` 在各任务引用一致;`get_productive_pass_interval_minutes()` 命名统一。
- Review Focus 五项各归属到 Task 1/3 的测试步骤(封禁风险→回滚手段写入 README;计数不受影响→pacer 单测只测睡眠;23:55→保留用例;非正钳位→纯函数用例;SystemExit→既有用例)。
- 行为变更点(有新增趟次由"直连下一趟"改为"10 分钟后下一趟")已作为预期变更改写既有用例 `test_productive_pass_runs_immediately`。
