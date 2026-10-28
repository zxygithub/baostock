# IP 黑名单防护三道闸 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已批准设计实现黑名单三道闸(启动退避闸、查询期熔断、请求频率闸)+ 分页计数修正 + 日报/monitor 协同,封禁期内零网络请求、被封后零后续请求。

**Architecture:** 新建 `src/utils/blacklist.py` 作为标记读写与退避判定的唯一事实源(fail-open、判年龄不判存在性、退避期绝不 touch);启动闸挂在 `run_main_with_report` 入口/每趟与 `BaseDownloader.__init__`,`BlacklistedError(Exception)` 从 `query_with_retry`/`_api_call`/`login` 穿透所有 `except RuntimeError: continue`;`_throttle()` 在基类提供 `api.min_request_interval` 硬下限。

**Tech Stack:** Python 3.11+,pytest(仅收集 `test_*.py`,全 mock 不触网),bash(monitor,仅退避常量归一)。

**Spec:** `docs/superpowers/specs/2026-10-28-blacklist-guard-design.md`(已批准,3 项决策已确认;本计划的值、文案、签名均以其为准)

## Global Constraints

- 常量与取值以 spec 为准:`BSERR_BLACKLIST_USER = "10001011"`、`api.min_request_interval: 0.30`(决策 1)、`api.blacklist_backoff_minutes: 120`(决策 3)、退出码 `2`=封禁闸、`1`=配额上限(**不得复用/混淆**)。
- 被封行为(决策 2):`loop=True`/`loop=False` 一律终止进程;`BlacklistedError` 穿透不发日报(沿用既有裁定);启动闸命中不进 `main_fn`、不发日报。
- 新配置项**不得**模块级冻结(§3.4):`min_request_interval` 用 `BaseDownloader` property 每次访问读 `config_loader`;`blacklist_backoff_minutes` 在 `in_backoff()` 内读。**不**顺带重构 `SOCKET_TIMEOUT`/`DAILY_REQUEST_LIMIT`。
- `BlacklistedError` **直接继承 `Exception`**(继承 `RuntimeError` 会被 `financial/report/dividend` 的 `except RuntimeError: continue` 吞掉,缺口 E 重现)。
- 自愈不变量(§4):闸判年龄不判存在性;fail-open 六条(文件不存在/stat OSError/mtime 在未来/JSON 损坏或空/window<=0/`--ignore-blacklist` 或 `BAOSTOCK_IGNORE_BLACKLIST=1`);**退避期内绝不 `touch`/`arm`**,只有真实观测到 `10001011` 才 `arm()`。
- 硬约束(§2.2):不改 `target_date=昨日`、46,000 配额、趟次休眠心跳;不引入并发;不动 monitor 探测节奏/`.server_down`/15 分钟静默判卡死;不做换 IP/代理;不删除 `.blacklisted` 文件约定(monitor 只 `touch`/`rm -f`,必须双向兼容)。
- 测试命令 `.venv/bin/python -m pytest tests/ -q`;测试不得触网、不得读写生产 `data/baostock.db` 与生产标记 `data/.blacklisted`。
- 提交主题沿用仓库惯例 `<type>: <描述>`(作者名 Developer 不进主题);type ∈ feat/fix/docs/test/refactor。

## Review Focus

1. **monitor `touch` 出的空标记必须回落 mtime 判定**——monitor 与 Python 双向写同一文件,空文件/损坏 JSON 不能报错或永久锁死。→ Task 1 用例 ⑥;monitor 侧 Task 6 核对只 `touch`/`rm -f`。
2. **退避期内绝不续期 mtime(自愈核心)**——若 `in_backoff()` 或启动流程 `touch` 标记,窗口被自己无限续期,就真的永远起不来。→ Task 1 用例 ⑩;Task 3 断言 `arm()` 只在真实 `10001011` 时调用。
3. **测试与生产标记隔离**——`marker_path()` 默认指向仓库 `data/.blacklisted`,真实封禁后跑测试会被启动闸打红。→ Task 2 的 `tests/conftest.py` autouse `set_bypass(True)`,闸门用例显式 `set_bypass(False)` + monkeypatch `marker_path` 到 tmp_path。
4. **`BlacklistedError` 不得被 `except RuntimeError` 吞掉**——继承链是唯一防线。→ Task 3 用例 ②(构造 `except RuntimeError: continue` 的真实循环路径验证穿透)。
5. **退出码与日报语义**——`SystemExit(2)` 不得被 `run_main_with_report` 误判为配额上限(reason 文案/日报),`BlacklistedError` 不得触发日报。→ Task 2 用例 ④、Task 3 既有 `test_completion_report.py` 断言迁移。

---

### Task 1: `src/utils/blacklist.py` + 配置项 + 常量

**Files:**
- Create: `src/utils/blacklist.py`
- Modify: `src/config.py`(新增 `BSERR_BLACKLIST_USER = "10001011"`,放在错误码/常量区)
- Modify: `src/config_loader.py`(`get_socket_timeout` 附近新增两个 getter)
- Modify: `config.yaml`(`api:` 段新增两键)
- Test: `tests/test_blacklist_marker.py`(新建)

**Interfaces:**
- Produces(后续任务全部依赖):
  - `blacklist.marker_path() -> Path` = `DB_PATH.parent / ".blacklisted"`(调用时求值,不缓存)
  - `blacklist.in_backoff(marker: Path | None = None, now: float | None = None) -> tuple[bool, int]`——`(是否阻塞, 剩余秒数)`;严格按 §4 ② fail-open;`window = get_blacklist_backoff_minutes()*60`,`<= 0` 视为禁用;旁路(`set_bypass(True)` 或环境变量 `BAOSTOCK_IGNORE_BLACKLIST=1`)→ `(False, 0)`
  - `blacklist.arm(source: str, detail: str = "") -> None`——写/刷新 JSON(`first_banned_at` 保留、`last_banned_at` 更新、`consecutive_hits += 1`),写失败只 WARN 不抛
  - `blacklist.clear() -> None`——删标记,不存在时静默
  - `blacklist.describe() -> str`——一行人类可读状态
  - `blacklist.set_bypass(enabled: bool) -> None`——进程内旁路开关
  - `config_loader.get_min_request_interval() -> float`(`api.min_request_interval`,缺省 0.30)
  - `config_loader.get_blacklist_backoff_minutes() -> int`(`api.blacklist_backoff_minutes`,缺省 120)
  - `config.BSERR_BLACKLIST_USER: str = "10001011"`

- [ ] **Step 1: 写失败测试**(`tests/test_blacklist_marker.py`,10 例对应 spec §7 表 ①-⑩;标记一律用 `tmp_path`,显式传 `marker=` 或 monkeypatch `marker_path`)

```python
def test_no_marker_allows()                      # ① 不存在 → (False, 0)
def test_fresh_marker_blocks_with_remaining()    # ② 现在-120s 内 → (True, 剩余秒≈窗口-age)
def test_expired_marker_allows()                 # ③ 超窗 → (False, 0) 自愈核心
def test_stat_oserror_allows(monkeypatch)        # ④ stat 抛 OSError → (False, 0)
def test_future_mtime_allows()                   # ⑤ now - mtime < 0 → (False, 0)
def test_corrupt_or_empty_marker_falls_back_to_mtime()  # ⑥ 空文件/坏 JSON → 按 mtime 判定,不抛
def test_non_positive_window_disables_gate()     # ⑦ window<=0 → (False, 0)
def test_arm_increments_hits_and_keeps_first()   # ⑧ arm 两次:consecutive_hits==2 且 first_banned_at 不变
def test_clear_idempotent()                      # ⑨ clear 两次不抛,之后 (False, 0)
def test_in_backoff_never_touches_marker()       # ⑩ 连续调用 in_backoff 不改变 mtime(用 stat 比对)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_blacklist_marker.py -q`
Expected: FAIL(ImportError:`src.utils.blacklist` 不存在)

- [ ] **Step 3: 实现 `src/utils/blacklist.py` 与配置项**

`in_backoff` 算法:`blocked = (mtime 可读) and (0 <= now - mtime < window)`,剩余秒 `window - (now - mtime)`;JSON 解析失败/为空 → 仅按 mtime 判定。`window <= 0` → `(False, 0)` + WARN。`arm`/`clear`/`in_backoff` 全部**不**调用 `touch`;`arm` 是唯一写入口。两个 getter 照 `get_socket_timeout` 同款 dict 查找(不冻结)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_blacklist_marker.py -q`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add src/utils/blacklist.py src/config.py src/config_loader.py config.yaml tests/test_blacklist_marker.py
git commit -m "feat: 黑名单标记与退避判定单一事实源(自愈 fail-open)+ 配置项"
```

---

### Task 2: 启动前退避闸 + `--ignore-blacklist` + 测试隔离

**Files:**
- Modify: `src/utils/helpers.py`(`run_main_with_report` 入口一次 + `while True` 每趟一次)
- Modify: `src/downloaders/base.py`(`__init__` 内 `_check_daily_limit()` **之前**)
- Modify: `scripts/download_all.py`、`scripts/update_daily.py`(各加 `--ignore-blacklist`)
- Create: `tests/conftest.py`
- Test: `tests/test_blacklist_startup_gate.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `in_backoff()/set_bypass()/marker_path()`。
- Produces: 无新公共接口;行为契约——闸命中:打印 spec §5 组件 2 的报错文案(原文含三行,剩余分钟/窗口/解法)后 `raise SystemExit(2)`;`--ignore-blacklist` → `blacklist.set_bypass(True)`。

- [ ] **Step 1: 写失败测试**

```python
def test_loop_false_blocked_exits_2(monkeypatch, tmp_path)      # ① 阻塞 → SystemExit(2),main_fn 不被调用
def test_loop_true_blocked_terminates_without_pass(monkeypatch) # ② loop=True 阻塞 → 终止且不进趟次
def test_ignore_flag_or_env_allows(monkeypatch)                 # ③ set_bypass(True)/BAOSTOCK_IGNORE_BLACKLIST=1 → 放行并进入 main_fn
def test_exit_2_not_reported_as_quota(monkeypatch)              # ④ 退出码 2:sent == [](不发日报)且异常不是 SystemExit(1)
```

`tests/conftest.py`:`@pytest.fixture(autouse=True) def _blacklist_bypass(): blacklist.set_bypass(True); yield; blacklist.set_bypass(False)`;闸门用例内显式 `set_bypass(False)` 并 monkeypatch `blacklist.marker_path` 指向 `tmp_path / ".blacklisted"`(fresh mtime)。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_blacklist_startup_gate.py -q`
Expected: FAIL(闸未实现,SystemExit(2) 不出现)

- [ ] **Step 3: 实现两处闸与 CLI 旗标**

`helpers.run_main_with_report`:函数入口、以及 `while True` 循环体顶部各一处,3 行——`blocked, remain = blacklist.in_backoff()`;命中则 `logger.error(<spec 文案,remain 转分钟>)` + `raise SystemExit(2)`。`BaseDownloader.__init__`:同样 3 行插在 `self._check_daily_limit()` 之前。两个 CLI 的 `parser.add_argument("--ignore-blacklist", action="store_true")`,解析后 `if args.ignore_blacklist: blacklist.set_bypass(True)`。

- [ ] **Step 4: 跑测试确认通过(含既有套件)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed(`test_pass_scheduler.py`/`test_completion_report.py` 在 conftest 旁路下不受影响)

- [ ] **Step 5: 提交**

```bash
git add src/utils/helpers.py src/downloaders/base.py scripts/download_all.py scripts/update_daily.py tests/conftest.py tests/test_blacklist_startup_gate.py
git commit -m "feat: 启动前退避闸与 --ignore-blacklist(封禁期零网络请求,退出码 2)"
```

---

### Task 3: 查询期熔断 `BlacklistedError` + login/close 语义 + 问题 E 修补

**Files:**
- Modify: `src/downloaders/base.py`(`BlacklistedError`;`query_with_retry`、`_api_call` 熔断;`login` 成功 `clear()`/失败 `arm(source="login")`;`close()` 被封跳过 logout 但关 `default_socket`)
- Modify: `src/utils/helpers.py`(`run_main_with_report` 捕获 `BlacklistedError`:不发日报,loop=True 终止,loop=False 原样抛出)
- Modify: `src/downloaders/financial_downloader.py`(`_flush_pending_batches` 的 `"unknown"` fallback 改显式 `logger.error` + 跳过写入)
- Modify: `tests/test_completion_report.py`(`test_systemexit_string_propagates_and_skips` 断言改 `BlacklistedError`)
- Test: `tests/test_blacklist_circuit_break.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `arm()/clear()`、`config.BSERR_BLACKLIST_USER`。
- Produces: `class BlacklistedError(Exception)`(定义于 `src/downloaders/base.py`,导出供 helpers/tests 使用)。

- [ ] **Step 1: 写失败测试**

```python
def test_query_blacklist_single_request_then_break()     # ① 10001011 → 只发 1 次请求即抛 BlacklistedError(计数器断言)
def test_error_not_swallowed_by_runtime_error_continue() # ② 仿 financial 循环 except RuntimeError: continue → 仍穿透
def test_flush_pending_batches_called_before_raise()     # ③ 抛出前 _flush_pending_batches 被调用
def test_arm_called_with_source_query()                  # ④ arm(source="query", detail 含函数名)
def test_close_skips_logout_but_closes_socket()          # ⑤ 被封 close():logout 未被调用,socket.close 被调用
def test_login_success_clears_marker()                   # ⑥ 成功 login → clear() 被调用
def test_login_blacklist_arms_login_source()             # ⑦ login 遇 10001011 → arm(source="login") + BlacklistedError(不再 SystemExit("IP blacklisted."))
def test_flush_without_batch_table_writes_no_unknown()   # ⑧ 问题 E 回归:_batch_table 未设 → 不建 unknown 表,error 日志
def test_api_call_blacklist_breaks()                     # ⑨ _api_call 路径同样熔断(spec 目标"被封后 0 次请求")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_blacklist_circuit_break.py -q`
Expected: FAIL(`BlacklistedError` 未定义/无熔断)

- [ ] **Step 3: 实现熔断与配套语义**

`query_with_retry`:`if rs.error_code == "0": return wrapped` 之后、`msg = rs.error_msg.lower()` 之前插入熔断块(`self._blacklisted = True`、`blacklist.arm(...)`、`self._flush_pending_batches()`、`logger.error(<spec 文案>)`、`raise BlacklistedError(...)`),**不重试**。`_api_call` 同款插块(用 `BSERR_BLACKLIST_USER` 判 `rs.error_code`)。`login()`:`10001011` → `arm(source="login")` + `raise BlacklistedError`,成功路径末尾 `blacklist.clear()`。`close()`:`if not (self._limit_exceeded or self._blacklisted): self.logout()`;`self._blacklisted` 为真时关闭 `baostock.common.context.default_socket` 并置 None(防 fd 泄漏)。`helpers.run_main_with_report`:`except BlacklistedError: if loop: break 出循环后直接 return(不发日报) else: raise`。`financial_downloader._flush_pending_batches`:`getattr(self, "_batch_table", None)` 为假 → `logger.error` + 跳过写入。

- [ ] **Step 4: 跑测试确认通过(含迁移断言)**

Run: `.venv/bin/python -m pytest tests/test_blacklist_circuit_break.py tests/test_completion_report.py tests/test_malformed_json_fail_fast.py -q`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add src/downloaders/base.py src/utils/helpers.py src/downloaders/financial_downloader.py tests/test_blacklist_circuit_break.py tests/test_completion_report.py
git commit -m "feat: 查询期熔断 BlacklistedError(被封后零后续请求)+ 修 _flush_pending_batches 的 unknown 兜底"
```

---

### Task 4: 请求频率闸 `_throttle()` + K 线空批睡眠修复

**Files:**
- Modify: `src/downloaders/base.py`(`min_request_interval` property、`_last_request_ts`、`_throttle()`,`_api_call` 与 `query_with_retry` 发请求前各调一次)
- Modify: `src/downloaders/kline_downloader.py`(`if not all_rows: continue` 改为空批也执行批间睡眠)
- Test: `tests/test_request_throttle.py`(新建)

**Interfaces:**
- Consumes: `config_loader.get_min_request_interval()`。
- Produces: `BaseDownloader.min_request_interval -> float`(property,**每次访问**读配置,不冻结);`BaseDownloader._throttle() -> None`——`elapsed < interval` 时只补足差额(与既有 sleep 取最大值语义,不叠加)。

- [ ] **Step 1: 写失败测试**

```python
def test_min_interval_enforced_between_requests()      # ① 两次请求间隔 >= min_request_interval(monkeypatch time.sleep 记录补足量)
def test_no_double_sleep_when_existing_sleep_longer()  # ② 既有 sleep(如 RequestPacer 1s)更长时不叠加:补足量为 0
def test_non_positive_interval_disables()              # ③ <=0 → 不睡
def test_kline_empty_batch_still_sleeps(tmp_path, monkeypatch)  # ④ 回归:空批也执行批间睡眠(sleeps 记录含 batch_sleep)
def test_min_request_interval_is_property_not_frozen() # ⑤ 清 config_loader._config_cache 后改配置即生效(属性读取,非类常量)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_request_throttle.py -q`
Expected: FAIL(`_throttle`/property 不存在;空批睡眠用例复现缺口 G)

- [ ] **Step 3: 实现 `_throttle()` 与 K 线修复**

`__init__` 加 `self._last_request_ts: float = 0.0`;`_throttle()` 按 §5 组件 4 伪码实现(interval 由 `self.min_request_interval` property 每次现读);`_api_call` 与 `query_with_retry` 在 `func(**kwargs)` 发起前调用。K 线:把 `if not all_rows: continue` 改为 `if all_rows:` 包住保存逻辑,`time.sleep(batch_sleep)` 移到无条件执行。spec §8 要求的 1,000 次空跑计时对比写入 Step 4 输出(确认配置读取开销可忽略)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_request_throttle.py tests/test_dead_stock_skip.py -q`
Expected: 全部 passed(附 1,000 次 `_throttle()` 空跑耗时输出)

- [ ] **Step 5: 提交**

```bash
git add src/downloaders/base.py src/downloaders/kline_downloader.py tests/test_request_throttle.py
git commit -m "feat: 请求频率闸 min_request_interval 硬下限,修 K 线空批跳过批间睡眠"
```

---

### Task 5: 分页请求计数修正

**Files:**
- Modify: `src/downloaders/base.py`(`_ApiResultWrapper.__init__` 增 `on_page: Callable[[], None] | None = None`,`next()` 比较 `self._rs.cur_page_num` 翻页即回调;`query_with_retry`/`_api_call` 构造处注入 `self._increment_request_count`)
- Test: `tests/test_pagination_counting.py`(新建)

**Interfaces:**
- Consumes: `_increment_request_count()`(已含配额记账;翻页回调后仍走 `_check_limit_after_increment()` 以便分页途中触顶熔断)。
- Produces: `_ApiResultWrapper(rs, func_name, params, logger, on_page=None)`(向后兼容,缺省不回调)。

- [ ] **Step 1: 写失败测试**

```python
def test_single_page_counts_once()        # ① 不翻页 → 计数 1(查询本身)
def test_two_page_turns_count_three()     # ② 翻 2 页 → 计数 3(1 查询 + 2 翻页)
def test_quota_hit_mid_pagination_exits_1() #  ③ 翻页途中触顶 → SystemExit(1)(_check_limit_after_increment 生效)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_pagination_counting.py -q`
Expected: FAIL(翻页不计数,② 得 1)

- [ ] **Step 3: 实现翻页回调**

`next()` 在调用底层 `next()` 前记录 `getattr(self._rs, "cur_page_num", 0)`,返回后若增大则 `self._on_page()`;两处构造点传 `on_page=self._increment_request_count`(回调内不做上限检查,由既有 `_check_limit_after_increment` 在下一次查询/翻页后触顶;spec 要求翻页计数含触顶检查 → 回调用 `lambda: (self._increment_request_count(), self._check_limit_after_increment())` 的等价小方法 `_count_page_turn`)。

- [ ] **Step 4: 跑测试确认通过(回归 request_count 口径)**

Run: `.venv/bin/python -m pytest tests/test_pagination_counting.py tests/test_request_count.py tests/test_bare_call_metering.py -q`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add src/downloaders/base.py tests/test_pagination_counting.py
git commit -m "fix: 分页翻页逐页计数,消除配额漏计(单页 1 次、翻 N 页 N+1 次)"
```

---

### Task 6: 日报/monitor 协同(退避窗口常量归一)

**Files:**
- Modify: `scripts/daily_report.py`(`check_blacklist_status()` 先查 `blacklist.in_backoff()`,命中零网络出状态)
- Modify: `scripts/monitor_baostock.sh`(`BLACKLIST_BACKOFF_MINUTES` 改为经 `config_loader` 读取,失败回落 120 + `log WARN`)
- Test: `tests/test_daily_report_blacklist.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `in_backoff()/marker_path()`、`config_loader.get_blacklist_backoff_minutes()`。
- Produces: monitor 的 `load_backoff_minutes()`(bash 函数,`$PYTHON -c` 读 config_loader 输出整数,非法回落 120)。

- [ ] **Step 1: 写失败测试**

```python
def test_daily_report_skips_probe_during_backoff(monkeypatch)  # 退避期内 check_blacklist_status() 零网络(断言 bs.login 未被调用),返回黑名单状态含剩余分钟
def test_daily_report_probes_when_not_blocked(monkeypatch)     # 未在退避期才走原探测逻辑(bs.login 被调用)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_daily_report_blacklist.py -q`
Expected: FAIL(当前必调 `bs.login`)

- [ ] **Step 3: 实现协同**

`check_blacklist_status()` 开头:`blocked, remain = blacklist.in_backoff()`;命中 → `return "❌ 黑名单", f"IP 处于封禁退避期,剩余 {remain//60} 分钟(标记 data/.blacklisted)"`,不发任何请求。monitor:`BLACKLIST_BACKOFF_MINUTES="$(load_backoff_minutes)"`,函数体按 Interfaces;其余逻辑(探测节奏/`.server_down`/静默判卡死)不动;顺带核实 `start_download`/`check_daily_limit` 不按下载进程退出码分支(SystemExit(2) 无冲突),结果写入提交说明。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_daily_report_blacklist.py tests/test_daily_report_trigger.py -q`
Expected: 全部 passed;`bash -n scripts/monitor_baostock.sh` 语法通过

- [ ] **Step 5: 提交**

```bash
git add scripts/daily_report.py scripts/monitor_baostock.sh tests/test_daily_report_blacklist.py
git commit -m "feat: 日报退避期零网络探测,monitor 退避窗口常量归一 config.yaml"
```

---

### Task 7: 文档同步 + 全量回归 + 推送远程

**Files:**
- Modify: `README.md`(更新日志 + 黑名单检测/处置章节,含 §9 即时处置建议要点)
- Modify: `docs/download_flow.md`(§6 配额/限流相关段落 + §9 配置表新增两键)
- Modify: `docs/improvement_plan.md`(§5 API 限制备忘)
- Modify: `docs/claude评价_第二次.md`(问题 A 部分缓解、问题 E 已修,标注复核日期 2026-10-28)
- Modify: `docs/superpowers/specs/2026-10-28-blacklist-guard-design.md`(状态行「尚未实现」→「已实现」)
- Modify: 本计划文件(随文档提交)

**Interfaces:**
- Consumes: Task 1-6 全部行为;spec §3.1 吞吐表。
- Produces: 文档与代码一致;`origin/master` 含全部提交。

- [ ] **Step 1: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed(基线 261 + 新增约 30 例)

- [ ] **Step 2: 更新四份文档 + spec 状态**

除上述四份外,**必须修正 spec §3.1 表的过时表述**:该表写"报告/分红无变化(已是 1s/只)",但 2026-10-28 的批内限速(每 200 请求 1s)已让二者约 0.2s/请求,叠加 0.30s 硬下限后变为约 0.30s/请求——仍远快于改造前的 1.2s/只。README 与 download_flow 同步该交互说明(`_throttle` 与 `RequestPacer` 取最大值语义、`stocks.batch_size`/`batch_sleep` 仍为批内节奏)。

- [ ] **Step 3: 提交文档**

```bash
git add README.md docs/download_flow.md docs/improvement_plan.md docs/claude评价_第二次.md docs/superpowers/specs/2026-10-28-blacklist-guard-design.md docs/superpowers/plans/2026-10-28-blacklist-guard.md
git commit -m "docs: 黑名单三道闸落地同步(更新日志/限流口径/评审问题复核)"
```

- [ ] **Step 4: 推送(合并方式沿用仓库线性历史)**

```bash
git fetch origin && git rebase origin/master   # 如远端已前进
git log --oneline -8
# 经 finishing-a-development-branch:回 master 快进合并后
git push origin master
```
Expected: push 成功,`origin/master` 含 Task 1-7 全部提交,工作区 clean。

---

## 明确不在本次范围(按 spec §6/§3.4)

- spec 的 Task 7(kline `except RuntimeError` 兜底)——spec 自标"可选,独立议题",留待独立评审。
- `_throttle` 的 ±20% 随机抖动——spec "待确认,默认不做"。
- 问题 A 完整修复(`SOCKET_TIMEOUT`/`DAILY_REQUEST_LIMIT` property 化)、问题 B/C/D/F、信号处理测试空白——spec 明确排除。

## Self-Review 记录

- 覆盖:spec §5 组件 1-6 全部有任务(组件 3 的 `_api_call` 熔断按 §2.1"被封后 0 次请求"目标补入 Task 3 用例 ⑨,属 spec 内部缺口);§7 六组测试全部落到 Task 1/2/3/4/5/6;§9 处置建议落 README(Task 7)。
- 类型一致:`in_backoff -> tuple[bool, int]`、`BlacklistedError(Exception)`、`_ApiResultWrapper(..., on_page=None)`、`min_request_interval` property 在各任务引用一致。
- Review Focus 五项各绑定到具体用例(Task 1 ⑥⑩、Task 2 conftest、Task 3 ②、Task 2 ④/Task 3 迁移断言)。
- spec 漂移已裁决并记录:§3.1 吞吐表"报告/分红无变化"因 2026-10-28 批内限速过时,Task 7 强制修正文档。
