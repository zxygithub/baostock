# IP 黑名单防护三道闸 — 设计方案

- 日期：2026-10-28
- 状态：**已实现**（2026-10-28 落地：三道闸 + 分页计数 + 日报/monitor 协同，测试 297 例通过；3 项决策按「已确认决策」执行。实现中与本方案的两处口径修正见文末「实现后注记」）
- 触发：GitHub 用户反馈 Windows 环境下仅运行 `scripts/download_all.py` 即被 BaoStock 拉黑
- 反馈原文：
  ```
  [2026-10-22 12:26:18] WARNING - Query failed (attempt 1): 黑名单用户，请与管理员联系
  [2026-10-22 13:08:28] INFO - 今日 API 请求计数: 2804/48000
  login failed!
  [2026-10-22 13:08:29] ERROR - BaoStock IP is blacklisted. Please seek help in the QQ group.
  IP blacklisted.
  ```
  补充信息：Windows 环境；执行期间中断过几次并手工重新触发。
- 涉及文件：
  - `src/utils/blacklist.py`（**新建**，标记读写 + 退避判定的唯一事实源）
  - `src/downloaders/base.py`（启动闸、查询期熔断、请求频率闸、分页计数）
  - `src/downloaders/financial_downloader.py`（`_flush_pending_batches` 的 `"unknown"` fallback，评审问题 E）
  - `src/downloaders/kline_downloader.py`（批间睡眠被空批跳过）
  - `src/utils/helpers.py`（`run_main_with_report` 入口与趟次循环的启动闸）
  - `src/config.py`（`BSERR_BLACKLIST_USER` 常量）
  - `src/config_loader.py` / `config.yaml`（`api.blacklist_backoff_minutes`、`api.min_request_interval`）
  - `scripts/download_all.py` / `scripts/update_daily.py`（`--ignore-blacklist` 旗标）
  - `scripts/daily_report.py`（退避期内不再自行探测）
  - `scripts/monitor_baostock.sh`（退避窗口常量归一，可选，见决策 3）
  - `tests/`（新增 5 组用例）、`README.md` / `docs/download_flow.md` / `docs/improvement_plan.md`（同步）

---

## 1. 背景与证据

### 1.1 现状：`start.sh` 路径上没有任何黑名单前置闸

调用链实测：

```
./start.sh full
  └─ cmd_full()  start.sh:85-88  →  run "$PYTHON scripts/download_all.py $*"   ← 无任何检查
       └─ run_main_with_report(main, loop=True)   helpers.py:237
            └─ main() → refresh_meta_if_due() → MetaDownloader(...)
                 └─ BaseDownloader.__init__   base.py:85-95
                      ├─ _check_daily_limit()   ← 只查本地配额计数，与黑名单无关
                      └─ login()   base.py:173  ← 全链路唯一碰黑名单的地方
```

对全部 `.sh/.py/.yaml/.toml` 执行 `grep blacklisted|check_blacklist|monitor_baostock`，**`start.sh` 零命中**；`start.sh` 也没有 `monitor` 子命令（仅 init/full/update/check/status/logs/clean-logs/clean-tmp/help）。

### 1.2 缺口逐条

| # | 缺口 | 证据 | 后果 |
|---|---|---|---|
| A | 无启动前置闸 | `start.sh:85-88` 直起 python | 封禁期内每次启动都真发一发 login |
| B | 唯一的黑名单判断是 login 的副产物，且只认 login | `base.py:178-182` | 只能"撞墙后退"，不能"先看再决定" |
| C | 退避机制只存在于 monitor，且不可移植 | `monitor_baostock.sh:25,30,108-131,365,419`；`data/.blacklisted` 的**唯一读写方**就是它 | Windows/macOS 完全无保护（`stat -c %Y`、`find -printf` 均为 GNU 专有） |
| D | `query_with_retry` 从不检查 `10001011` | `base.py:296-351`；`:317` 只匹配 `session`/`网络`/`未登录` | `黑名单用户，请与管理员联系` 三词均不含 → 落入通用重试 |
| E | 被封后继续砸服务器 | `financial_downloader.py:114`、`report_downloader.py:55,108`、`dividend_downloader.py:76,273` 全部 `except RuntimeError: continue` | ~5,700 只 × 3 发 ≈ **1.7 万次纯黑名单请求**，直到 ≤9 分钟后 `ensure_login()` 重登录才 SystemExit |
| F | K 线阶段无 RuntimeError 兜底 | `kline_downloader.py:93` 裸调 `query_with_retry` | RuntimeError 冲出 `main()`，整趟崩溃（与反馈者只出现 `attempt 1` 一行相符） |
| G | K 线阶段**零请求间隔** | `kline_downloader.py:115` `if not all_rows: continue` 在 `:134` 的 `time.sleep(batch_sleep)` **之前** | 200 个重查询背靠背发出，仅每批 1s；空批连这 1s 都跳过 |
| H | 分页请求漏计配额 | baostock `data/resultset.py:52-118` 的 `next()` 满页时自行 `send_msg` 取下一页；`_ApiResultWrapper.next()` (`base.py:38-51`) 只数行不计数 | 服务端请求数 > 本地计数，配额闸失真 |

### 1.3 关键推论：配额闸与本次封禁无关

反馈者计数为 `2804/48000`——离上限差 17 倍。**他是在约 2,800 次请求时被封的**，`_check_daily_limit()` 这道闸从头到尾没有起过作用。

而项目现有防线只有「配额闸 + login 撞墙」，**没有频率闸**。对照缺口 G：K 线阶段以网络往返速度连发重查询（首次全量时每次返回约 8,700 行 zlib 压缩数据），2,800 次请求在这种速率下只需几分钟。这与官方访问规则中「短时高频请求」「循环批量下载未加延时」两条封禁诱因完全吻合。

次要诱因（需向反馈者核实，见「即时处置建议」）：
- **共享出口 IP**：家庭宽带在运营商 CGNAT 内多人共用出口，他人滥用导致整段 IP 被拉黑；
- **反复重试延长封禁**：官方规则明确「等待期间切勿反复尝试登录，反复尝试会刷新/延长封禁时间」。反馈者自述「中断几次过我重新触发」，每次重触发都是一发 login（缺口 A）。
- **旧版本**：`48000` 是 2026-04-23～04-25 之间的取值（`f8e02fe`→`631a9d5`），当前 master 为 `46000`（`62557281`，2026-10-06）。说明反馈者跑的是 4 月的旧 checkout，**不含 10-26 的去重修复**——那个版本空转趟会全量重拉指数 K 线与元数据，一天 22 趟、13:16 即烧完配额。其时间戳 12:26 / 13:08 正落在该区间。

### 1.4 已核实的分页漏计实例

`meta_downloader.download_trade_dates()` 默认 `start_date="1990-01-01"`、`end_date=当年-12-31`（`meta_downloader.py:19-25`）→ 约 13,500 行 → **2 页 = 2 次服务端请求，本地计 1 次**。当前每日漏计 1 次，量级很小；但机制性风险在于：分钟线（5 年 5 分钟线约 58,000 行 → 6 页）一旦启用即 6 倍漏计，且日线全历史（约 8,700 行）预计在 2031 年前后越过 10,000 行页界。

---

## 2. 目标与范围

### 2.1 目标

| 指标 | 现状 | 目标 |
|---|---|---|
| 封禁期内启动的 login 探测 | 每次人工/monitor 重启各 1 发，无上限 | **≤1 发 / 120 分钟**，且退避期内零网络请求 |
| 被封后继续发出的请求 | ~1.7 万次（缺口 E） | **0 次**：首个 `10001011` 即熔断退出 |
| K 线阶段请求间隔 | 0（仅每 200 个 1s） | 受 `api.min_request_interval` 硬下限约束 |
| 本地计数 vs 服务端计数 | 分页漏计 | 逐页计数，误差 0 |
| 跨平台一致性 | 退避仅 GNU bash 可用 | 退避判定移入 Python，Win/macOS/Linux 同语义 |
| 死锁风险 | —— | **不存在永久阻塞**（见第 4 章论证） |

### 2.2 不做（硬约束）

- 不改 `target_date = 昨日` 语义、46,000 配额、趟次调度循环的休眠心跳机制（10-26 方案的既有约束沿用）。
- 不引入并发下载（`docs/improvement_plan.md:298` 已实测：2 个 session 即报错）。
- 不改 `monitor_baostock.sh` 的探测节奏、`.server_down` 语义、15 分钟日志静默判卡死逻辑。
- 不做自动换 IP / 代理池（违反平台访问规则，且 baostock 走 10030 端口裸 TCP，普通系统代理无效）。
- 不删除 `.blacklisted` 标记文件约定——保持与 monitor 双向兼容（monitor `touch` 只改 mtime、`rm -f` 清除，均不破坏本方案的 JSON 内容）。

---

## 3. 已确认决策

（2026-10-28 由维护者确认）

| # | 决策点 | 结论 | 否决项与理由 |
|---|---|---|---|
| 1 | `api.min_request_interval` 默认值 | **0.30s** | 0.25s（与 `FINANCIAL_SLEEP` 齐平，最省时，但正是财务阶段已验证的速率，无法证明它对 K 线重查询同样安全）；0.50s（最保守，配额打满需 6.4h，压缩当日完成度）。吞吐对照见 3.1 |
| 2 | 常驻模式（`loop=True`）被封后行为 | **立即终止进程**，把等待交给闸 1 | 休眠退避后自动重试：能让守护进程自愈，但需复用 `_sleep_idle_in_segments` 跨 120 分钟心跳、并新增日报 reason 分支，复杂度显著上升；而 monitor 在 Linux 部署下本就会接管，Windows 下用户手工重启也会被闸 1 以清晰提示拦住，收益不足 |
| 3 | 退避窗口常量的单一事实源 | **`config.yaml` 为准，monitor 经其既有 python heredoc 读 `config_loader`** | 双份各写 120：零改动风险，但两处漂移后 Python 与 monitor 的窗口不一致，标记会被一方提前放行 |

### 3.1 决策 1 的吞吐对照

以每日配额 46,000 次计（`config.yaml:13`）：

| interval | 速率 | 打满配额耗时 | 对各阶段的增量影响 |
|---|---|---|---|
| 0.25s | 4.0 req/s | 3.2 h | K 线 +1.2h；财务无变化（已是 0.25s）；报告/分红无变化（已是 1s/只） |
| **0.30s（已定）** | **3.3 req/s** | **3.8 h** | K 线增量 ~17,100 次 × 0.30s ≈ +1.4h；财务 +20% 时长；报告/分红无变化 |
| 0.50s | 2.0 req/s | 6.4 h | K 线 +2.4h；财务 +100% 时长 |

结论：0.30s 的额外成本主要落在 K 线阶段（正是缺口 G 所在），且当日总耗时仍远在 24h 常驻窗口内（`docs/download_flow.md` §8 估算日增量约 82,600 次 ≈ 2 天配额）。

> **实现后注记（2026-10-28）**：本表「报告/分红无变化（已是 1s/只）」一列在方案定稿后过时——同日落地的批内限速已把报告/分红改为每 200 请求睡 1s（约 0.2s/请求），叠加 0.30s 硬下限后约为 0.30s/请求，仍远快于改造前的 1.2s/只；K 线由约 0.16s/请求升至 0.30s/请求，本表「K 线 +1.4h」口径仍然成立。

### 3.2 决策 2 的落地含义

两种 loop 模式在封禁时**行为一致**（都终止），差异只在退出码与是否发日报：

| 模式 | 触发方 | 被封时行为 | 退出码 | 日报 |
|---|---|---|---|---|
| `loop=True` | `download_all.py`（`./start.sh full` 常驻） | break 出趟次循环 → 终止 | 非 0 | **不发**（沿用既有裁定） |
| `loop=False` | `update_daily.py`、`download_all.py --once` | 原样抛出 → 终止 | 非 0 | **不发** |
| 启动闸命中（两者共用） | 退避期内启动 | 不进入 `main_fn` | **2**（与配额上限的 1 区分） | 不发 |

退出码约定：`1` = 配额上限（既有语义，`run_main_with_report:262-266` 依赖它判定日报 reason，**不得复用**）；`2` = 封禁退避期拒绝启动；`BlacklistedError` 穿透 = 非 0（由 Python 异常退出决定）。

### 3.3 决策 3 的落地方式

`config.yaml` 新增 `api.blacklist_backoff_minutes: 120`，`config_loader.get_blacklist_backoff_minutes()` 为唯一读取口。

`monitor_baostock.sh:30` 的 `BLACKLIST_BACKOFF_MINUTES=120` 改为在其**既有的 python heredoc**（`check_connectivity`，`:66-104` 一带）里调 `config_loader` 读出后回填给 bash 变量；读取失败时回落到硬编码 120 并 `log "WARN"`，保证 monitor 在 config 损坏时仍能工作。其余探测节奏、`.server_down` 语义、15 分钟静默判卡死逻辑一律不动。

### 3.4 新配置项的读取方式：不得复制评审「问题 A」的冻结反模式

`docs/claude评价_第二次.md` §5.1 问题 A（2026-10-28 复核**仍成立**）：

```python
# base.py:77-78 —— 模块导入时求值一次，此后永久冻结
_SOCKET_TIMEOUT = get_socket_timeout()
_DAILY_REQUEST_LIMIT = get_daily_request_limit()
# base.py:82-83 —— 再固化成类属性
SOCKET_TIMEOUT: int = _SOCKET_TIMEOUT
DAILY_REQUEST_LIMIT: int = _DAILY_REQUEST_LIMIT
```

后果：改 `config.yaml` 必须重启进程才生效；且类属性形态让测试只能靠 `monkeypatch.setattr(BaseDownloader, ...)` 而非改配置。

**本方案新增的两个配置项一律不走这条路**：

| 配置项 | 读取方式 | 调用频次 |
|---|---|---|
| `api.min_request_interval` | `BaseDownloader.min_request_interval` **property**，每次访问调 `config_loader.get_min_request_interval()` | 每次请求 1 次（`_throttle()`） |
| `api.blacklist_backoff_minutes` | `blacklist.in_backoff()` 内部调 `config_loader.get_blacklist_backoff_minutes()` | 每次闸门判定 1 次 |

性能顾虑已评估：`config_loader.load_config()` 有模块级 `_config_cache`（`config_loader.py:21,33-35`），首次之后是纯 dict 查找、**无文件 I/O**，故 `_throttle()` 每请求读一次的成本可忽略（相较 0.30s 的睡眠本身）。

**范围界定**：本方案只保证「新增配置项不冻结」，**不顺带重构 `SOCKET_TIMEOUT` / `DAILY_REQUEST_LIMIT`**——那是问题 A 的完整修复，涉及 `:111`、`:164` 两个使用点与既有测试的 monkeypatch 方式，应独立评审。同时须知：因 `_config_cache` 的存在，即便改成 property，**编辑 `config.yaml` 文件本身仍需重启进程**才生效；property 化解决的是「测试可注入」与「未来接入 cache 失效后自动生效」，不是文件热加载。这一点必须在代码注释与文档中写明，避免造成"改了配置就生效"的误解。



---

## 4. 自愈性论证：为什么不会永久阻塞

这是本方案的核心约束。分三层：

**① 闸判的是年龄，不是存在性。**

```
blocked = (mtime 可读) and (0 <= now - mtime < window)
```

窗口一过，闸门自动放行，**不依赖任何外部删除者**。这一点直接照搬 `monitor_baostock.sh:108-131` 的既有正确逻辑。

**② fail-open。** 以下情形一律放行，绝不因本地状态问题把下载永久锁死：

| 异常 | 处理 |
|---|---|
| 标记文件不存在 | 放行 |
| `stat()` 抛 `OSError`（权限/竞态删除） | 放行 + WARN |
| `now - mtime < 0`（时钟回拨/mtime 在未来） | 放行 + WARN |
| JSON 内容损坏或为空（monitor `touch` 出来的空文件） | **回落到纯 mtime 判定**，不报错 |
| `window <= 0`（配置被改成 0 或负数） | 视为禁用闸门 + WARN |
| `BAOSTOCK_IGNORE_BLACKLIST=1` / `--ignore-blacklist` | 无条件放行 |

**③ 退避期内绝不 `touch`。** 只有**真实观测到服务端返回 `10001011`** 才 `arm()`（刷新 mtime）。闸门自身、退避判定、启动流程一律不写标记。

这条不变量是自愈的关键：若退避期内也刷新 mtime，窗口会被自己无限续期，就真的永远起不来了。monitor 现有实现已遵守此不变量（`:351-354` 在退避期内直接 `exit 0`，不探测也不 touch），Python 侧必须一起照搬。

**残留的"永久阻塞"只有一种**：服务器确实仍在封禁。此时每 120 分钟放行一次 → 1 发 login → 仍 `10001011` → 重新 `arm()`。这是**服务端造成的**阻塞，解封那一刻自动恢复（成功 login → `clear()`）。相较现状，探测代价从「用户每手工重试一次一发」降到「最多 120 分钟一发」。

---

## 5. 组件设计

### 组件 1：`src/utils/blacklist.py`（新建）

标记读写与退避判定的唯一事实源，跨平台（`Path.stat().st_mtime` 替代 `stat -c %Y`）。

标记路径：`DB_PATH.parent / ".blacklisted"` = `data/.blacklisted`，与 `monitor_baostock.sh:25` 完全一致。`data/` 已在 `.gitignore:142`。

标记内容（JSON，**仅用于诊断；mtime 才是年龄的权威信号**，因为 monitor 只会 `touch`）：

```json
{
  "first_banned_at": "2026-10-22T12:26:18",
  "last_banned_at":  "2026-10-22T13:08:29",
  "consecutive_hits": 2,
  "source": "query",
  "detail": "query_history_k_data_plus code=sh.600000"
}
```

导出接口：

| 函数 | 签名 | 语义 |
|---|---|---|
| `marker_path` | `() -> Path` | `data/.blacklisted` |
| `in_backoff` | `(marker: Path \| None = None, now: float \| None = None) -> tuple[bool, int]` | 返回 `(是否阻塞, 剩余秒数)`；严格按第 4 章 ② fail-open |
| `arm` | `(source: str, detail: str = "") -> None` | 写/刷新标记；读到既有 JSON 则 `consecutive_hits += 1` 并保留 `first_banned_at`；写失败只 WARN 不抛 |
| `clear` | `() -> None` | 删除标记（成功 login 后调用），文件不存在时静默 |
| `describe` | `() -> str` | 供日志/报错用的一行人类可读状态 |
| `set_bypass` | `(enabled: bool) -> None` | CLI 旗标的进程内开关；`in_backoff` 亦回退检查 `BAOSTOCK_IGNORE_BLACKLIST` 环境变量 |

### 组件 2：启动前退避闸

两处调用，都是 3 行：

1. **`helpers.run_main_with_report`（`helpers.py:237`）**——入口一次 + `while True`（`:272`）每趟一次。覆盖 `download_all.py`（`loop=True`）与 `update_daily.py`（`loop=False`）两条路径，跨平台，且在 DB 初始化之前，零成本。
2. **`BaseDownloader.__init__`（`base.py:85-95`）**——插在 `_check_daily_limit()`（`:94`）**之前**，使封禁期中途新构造的下载器（每个 Phase 各一个）立即止步，而不必等到 login。

阻塞时的行为：

- `loop=False`（人在看着）：打印剩余分钟 + 解除方式，`raise SystemExit(2)`（**退出码 2，与配额上限的 1 区分**，避免被 `run_main_with_report:262-266` 误判为"达到每日请求上限"）。
- `loop=True`（常驻）：同样终止。monitor 在其自身退避期内不会重启（`monitor_baostock.sh:351-354`），Linux 部署下天然静默。

报错文案必须自带解法：

```
ERROR - IP 处于封禁退避期，剩余 87 分钟（标记 data/.blacklisted，窗口 120 分钟）。
        退避期内不发起任何网络请求——官方规则明确反复登录会刷新/延长封禁。
        确认已解封可立即重试：删除 data/.blacklisted，或加 --ignore-blacklist。
```

CLI：`download_all.py` 与 `update_daily.py` 各加 `--ignore-blacklist`（`action="store_true"`），解析后调 `blacklist.set_bypass(True)`。之所以两处都要：`BaseDownloader` 拿不到 argv，而 monitor 启动进程时也无法传旗标，故同时支持环境变量。

### 组件 3：查询期熔断

`src/config.py` 新增 `BSERR_BLACKLIST_USER = "10001011"`（对齐 baostock `common/contants.py`）。

`base.py` 新增异常：

```python
class BlacklistedError(RuntimeError):
    """服务端返回 10001011；必须穿透所有 `except RuntimeError: continue`。"""
```

> **注意继承选择**：若继承 `RuntimeError`，`financial_downloader.py:114` 等 5 处 `except RuntimeError: continue` 会把它吞掉，缺口 E 依旧。故 `BlacklistedError` **直接继承 `Exception`**，不继承 `RuntimeError`。

`query_with_retry`（`base.py:296-351`）在 `rs.error_code == "0"` 判定之后、通用重试分支之前插入：

```
if rs.error_code == BSERR_BLACKLIST_USER:
    self._blacklisted = True
    blacklist.arm(source="query", detail=f"{func_name} {params}")
    self._flush_pending_batches()      # 保住已拉到的数据
    logger.error(<带解法的文案>)
    raise BlacklistedError(...)
```

**不再重试**——重试对封禁毫无意义，且每一发都在延长封禁。

> **前置修补（评审问题 E）**：上面的 `_flush_pending_batches()` 是本方案新增的**第 4 个**调用点（现有 3 处：`base.py:166` 配额熔断、`:201` 日停、`:237` 定义）。而 `financial_downloader.py:199` 的实现是：
> ```python
> self._batch_upsert(combined, getattr(self, "_batch_table", "unknown"))
> ```
> `_batch_table` 未设时会静默建一张名为 `unknown` 的垃圾表（`docs/claude评价_第二次.md` §5.2 问题 E，2026-10-28 复核**仍成立**）。
>
> 实际触发概率低——`_batch_dfs` 只在 `_download_quarterly_data` 内填充，而 `_batch_table` 在 `:104` 与之同时初始化，正常流程下不存在"有数据无表名"的窗口。但黑名单熔断可以在任意 `query_with_retry` 处触发，新增了一条此前不存在的进入路径，故 **Task 3 必须同时把 `"unknown"` fallback 改为显式 `logger.error` + 跳过写入**（评审给出的建议），不得留到以后。

`login()`（`base.py:173-187`）改为同一套：`arm(source="login")` + `raise BlacklistedError`，取代现有的 `raise SystemExit("IP blacklisted.")`。login 成功路径末尾加 `blacklist.clear()`。

> 兼容性：`tests/test_completion_report.py:83-87` 现在断言 `SystemExit("IP blacklisted.")` 原样穿透，需同步改为 `BlacklistedError`。

`close()`（`base.py:224-236`）：新增 `self._blacklisted` 标志，与既有 `_limit_exceeded` 并列——被封时**跳过 logout RPC**（不再多打一发），但必须显式关闭 `baostock.common.context.default_socket`，避免 fd 泄漏（baostock `socketutil.py:34-41` 的 `connect()` 每次 login 新建 socket 并覆盖 `default_socket`，不关旧的）。

`run_main_with_report`：捕获 `BlacklistedError` → **不发日报**（沿用 `docs/superpowers/specs/2026-10-01-daily-report-on-completion-design.md:37` 对 `SystemExit("IP blacklisted.")` 的既有裁定）→ `loop=True` 时 break 出趟次循环并终止（决策 2）；`loop=False` 时原样抛出，退出码非 0。

### 组件 4：请求频率闸（根因防线）

`BaseDownloader` 新增 `_throttle()`，在 `_api_call`（`base.py:142`）与 `query_with_retry`（`:296`）**发起请求之前**各调一次：

```
elapsed = now - self._last_request_ts
if elapsed < interval: sleep(interval - elapsed)
self._last_request_ts = now
```

- 集中在基类，7 个 downloader 全部自动受约束，无需逐个改。
- 与既有 sleep 叠加取**最大值语义**（不重复等待）：`_throttle` 只补足差额，故 `FINANCIAL_SLEEP=0.25` 与 `batch_sleep=1` 的既有节流不会被叠加放大。
- 配置：`api.min_request_interval: 0.30`（决策 1），`config_loader.get_min_request_interval()`，缺省 0.30；`<= 0` 视为禁用。
- 进程内单会话（不支持并发），故无需跨进程锁。monitor 探测与 `daily_report` 黑名单检查是独立进程、各 1~3 发裸调用，量级可忽略，不纳入节流。

**顺带修掉缺口 G 的睡眠跳过**：`kline_downloader.py:115` 的 `if not all_rows: continue` 位于 `:134` 的 `time.sleep(batch_sleep)` 之前，导致空批连批间睡眠都跳过。改为无论 `all_rows` 是否为空都执行批间睡眠（`_throttle` 已提供请求级下限，批间睡眠保留作为额外节奏）。

可选增强（待确认，默认不做）：给 interval 叠加 ±20% 随机抖动，避免形成整点节拍式的机器特征。

### 组件 5：分页请求计数修正

`_ApiResultWrapper.next()`（`base.py:38-51`）在调用底层 `next()` 前后比较 `self._rs.cur_page_num`；发生翻页即回调一次 `_increment_request_count()`（含 `_check_limit_after_increment()`，以便分页途中也能触发配额熔断）。

需给 `_ApiResultWrapper` 注入一个计数回调（构造参数），避免它反向依赖 downloader 实例。

影响面核实：当前默认配置下唯一实际触发者是 `trade_dates`（约 13,500 行 → 2 页），即每日 +1 次计数；分钟线启用后为 6 倍量级；日线全历史预计 2031 年前后越界。属**正确性修复**，非当前封禁的成因，优先级低于组件 1-4。

### 组件 6：日报与 monitor 的协同

- `daily_report.check_blacklist_status()`（`daily_report.py:115-136`）会自行 login + query 探测。改为：**先查 `blacklist.in_backoff()`，命中则直接用标记内容出状态，零网络请求**；未命中才走原探测逻辑。否则日报会在退避期内替我们把封禁续上。
- `monitor_baostock.sh` 按决策 3 处理退避窗口常量；其余逻辑不动。它 `touch` 出的空标记文件由组件 1 的 fail-open 规则兼容。

---

## 6. 实施任务拆分

| Task | 内容 | 文件 | 依赖 |
|---|---|---|---|
| 1 | `src/utils/blacklist.py` + 配置项（**均按 §3.4 动态读取，不得模块级冻结**）+ `BSERR_BLACKLIST_USER` | 新建 `src/utils/blacklist.py`；`src/config.py`；`config.yaml`；`src/config_loader.py` | — |
| 2 | 启动前退避闸 + `--ignore-blacklist`（退出码 2，见 §3.2） | `src/utils/helpers.py`；`src/downloaders/base.py:__init__`；`scripts/download_all.py`；`scripts/update_daily.py` | 1 |
| 3 | 查询期熔断（`BlacklistedError`）+ `close()` 不发 logout + `login()` 成功即 `clear()` + **`financial_downloader.py:199` 的 `"unknown"` fallback 改显式报错**（评审问题 E，见组件 3） | `src/downloaders/base.py`；`src/downloaders/financial_downloader.py`；`tests/test_completion_report.py`（改断言） | 1 |
| 4 | 请求频率闸（`min_request_interval` **property**，见 §3.4）+ K 线批间睡眠跳过修复 | `src/downloaders/base.py`；`src/downloaders/kline_downloader.py` | 1 |
| 5 | 分页计数修正 | `src/downloaders/base.py` | — |
| 6 | 日报/monitor 协同（含 §3.3 的退避窗口常量归一） | `scripts/daily_report.py`；`scripts/monitor_baostock.sh` | 1,3 |
| 7 | （可选，独立议题）K 线阶段补 `except RuntimeError` 兜底 | `src/downloaders/kline_downloader.py:93` | — |
| 8 | 文档同步 | `README.md`（更新日志 + 黑名单检测章节）；`docs/download_flow.md` §6；`docs/improvement_plan.md` §5 API 限制备忘；`docs/claude评价_第二次.md`（问题 A 部分缓解、问题 E 已修，标注复核日期） | 全部 |

Task 7 说明：组件 3 已让封禁不再以 RuntimeError 形式击穿 K 线；但 `kline_downloader.py:93` 对**其他** RuntimeError（如畸形 JSON、瞬时服务端错误）仍无兜底，与 financial/report/dividend 的容错模式不一致，单只股票失败会废掉整趟。属既有缺陷，可独立评审。

**明确不在本次范围**（评审遗留，需独立议题）：问题 A 的完整修复（`SOCKET_TIMEOUT` / `DAILY_REQUEST_LIMIT` property 化）、问题 B（CLI 统一）、问题 C（CI/CD）、问题 D（`download_all.py:52` 函数内 `import sqlite3`）、问题 F（`_find_missing_dividend` 计数可读性）。问题 H（pytest 依赖声明）经复核**已修复**（`pyproject.toml` `[dependency-groups] dev = ["pytest>=9.0.3"]`），无需处理。


---

## 7. 测试计划

命令：`.venv/bin/python -m pytest tests/ -q`（沿用既有约定，全部 mock，不触网）。

| 新增测试文件 | 关键用例 |
|---|---|
| `tests/test_blacklist_marker.py` | ① 标记不存在 → 放行；② mtime 在窗口内 → 阻塞且剩余秒数正确；③ mtime 超窗 → **放行**（自愈核心）；④ `stat` 抛 OSError → 放行；⑤ mtime 在未来 → 放行；⑥ 空文件/损坏 JSON → 回落 mtime 判定；⑦ `window<=0` → 禁用；⑧ `arm()` 后 `consecutive_hits` 递增且 `first_banned_at` 保留；⑨ `clear()` 幂等；⑩ **退避期内 `in_backoff()` 不修改 mtime**（不变量 ③） |
| `tests/test_blacklist_startup_gate.py` | ① `loop=False` 阻塞 → `SystemExit(2)`；② `loop=True` 阻塞 → 终止且不进趟次；③ `--ignore-blacklist` / 环境变量 → 放行；④ 退出码 2 不被误判为配额上限、不发日报 |
| `tests/test_blacklist_circuit_break.py` | ① `query_with_retry` 遇 `10001011` → **只发 1 次请求**即抛 `BlacklistedError`；② `BlacklistedError` 不被 `except RuntimeError: continue` 吞掉；③ 抛出前 `_flush_pending_batches()` 被调用；④ `arm()` 被调用且 source 正确；⑤ `close()` 不发 logout 但关闭 socket；⑥ login 成功 → `clear()`；⑦ login 遇 `10001011` → `arm(source="login")` + `BlacklistedError`；⑧ **`_batch_table` 未设时熔断不写出 `unknown` 表**（评审问题 E 回归） |
| `tests/test_request_throttle.py` | ① 连续两次请求间隔 ≥ `min_request_interval`；② 既有 sleep 更长时不叠加（取最大）；③ `interval<=0` → 禁用；④ K 线空批也执行批间睡眠（回归 `kline_downloader.py:115`）；⑤ **`min_request_interval` 是 property 而非冻结类属性**——清 `config_loader._config_cache` 后改配置即生效（守住 §3.4，防止退化成问题 A） |
| `tests/test_pagination_counting.py` | ① 单页结果计 1 次；② 翻页 2 次计 3 次；③ 分页途中触顶 → `SystemExit(1)` |
| `tests/test_daily_report_blacklist.py` | 退避期内 `check_blacklist_status()` **零网络调用**（断言 `bs.login` 未被调用） |

回归重点：`tests/test_completion_report.py`（断言从 `SystemExit("IP blacklisted.")` 改为 `BlacklistedError`）、`tests/test_pass_scheduler.py`（趟次循环新增的顶部闸门不得影响 4 个既有用例）、`tests/test_request_count.py`。

**顺带补上评审指出的测试空白**：`docs/claude评价_第二次.md` §3.4 与 §6.2 建议 9 均指出「缺少对 `BaseDownloader` 核心逻辑的直接单元测试（重试、限流、信号处理）」。本方案 6 组新测试中有 4 组（marker / startup gate / circuit breaker / throttle）直接打在 `BaseDownloader` 的重试与限流路径上，落地后该空白基本闭合；剩余「信号处理」仍无覆盖，留给独立议题。

---

## 8. 回归风险与缓解

| 风险 | 缓解 |
|---|---|
| 节流拖慢当日完成度 | 决策 1 已给吞吐对照；0.30s 下打满配额 3.8h，远在常驻窗口内；配置可调，`<=0` 即禁用 |
| 闸门把正常用户锁在门外 | 第 4 章三层论证 + 6 条 fail-open + `--ignore-blacklist` + 报错文案自带解法 |
| `BlacklistedError` 改继承链影响既有异常路径 | 直接继承 `Exception`，与 `RuntimeError` 无交集；`tests/test_malformed_json_fail_fast.py` 等既有 RuntimeError 用例不受影响 |
| `SystemExit(2)` 与 monitor 的退出码判定冲突 | 需核实 `monitor_baostock.sh` 的 `start_download` / `check_daily_limit` 是否按退出码分支；Task 6 一并处理 |
| 分页计数使既有配额统计口径变化 | 影响量级已核实为 +1 次/日；`docs/download_flow.md` §6 同步说明 |
| Python 与 monitor 双向写同一标记 | 内容格式对 monitor 透明（它只 `touch`/`rm -f`）；mtime 为唯一权威年龄信号 |
| 测试因 `BaseDownloader.__init__` 新增闸门而失败 | 闸门仅在标记存在且新鲜时触发，测试环境无 `data/.blacklisted`；必要时 fixture 显式 `set_bypass(True)` |
| property 化配置读取（§3.4）被误读为"支持热加载" | `_config_cache` 仍在，改文件依然要重启；代码注释 + README 须明写，`tests/test_request_throttle.py` 用例 ⑤ 固化「是 property 不是冻结类属性」这一契约而非热加载承诺 |
| `_throttle()` 每请求读一次配置的性能开销 | `load_config()` 首次后是纯 dict 查找无文件 I/O（`config_loader.py:21,33-35`）；相对 0.30s 睡眠可忽略，Task 4 验收时用 1,000 次空跑计时对比确认 |
| 问题 E 的 `"unknown"` 修补改变既有容错行为 | 现路径下 `_batch_dfs` 非空必然蕴含 `_batch_table` 已设（`financial_downloader.py:103-104` 同时初始化），故改为报错不影响正常流程；仅在真正的异常状态下由静默写垃圾表变为显式 error |

---

## 9. 给反馈用户的即时处置建议（不依赖本方案落地）

1. **先停止一切重试**。每次启动都会真发一发 login（缺口 A），而官方规则明确反复登录会刷新/延长封禁。
2. 查当前公网出口 IP：`curl ifconfig.me`；对照 baostock.com 的黑名单页（每日更新）确认是否在册、是否为共享出口（家庭宽带 CGNAT / 公司 NAT / 云主机 IP 段均可能整段被封）。
3. 动态公网 IP → 重启光猫/路由器换 IP，通常立即生效。
4. 走代理必须开 **TUN / 全局模式**：baostock 是 10030 端口的裸 TCP（`contants.py:BAOSTOCK_SERVER_PORT`），不吃系统 HTTP 代理。
5. 申诉：邮件 `baostock@163.com`（附公网 IP）或 QQ 群 `1128507078`。
6. **升级到最新 master**。他的 `48000` 说明是 2026 年 4 月的旧 checkout，缺 10-26「消除重复下载与无效趟次循环」修复——旧版空转趟全量重拉指数 K 线与元数据，一天 22 趟、13:16 即烧完配额，本身就是高危行为。
7. **零代码临时降速**（首次全量下载强烈建议）：`config.yaml` 改 `stocks.batch_size: 1`、`stocks.batch_sleep: 1`，使 K 线阶段变成约 1 请求/秒。原理：`kline_downloader.py:134` 的批间睡眠是每批一次，批大小降到 1 即等效于逐请求节流。注意缺口 G 的空批跳过仍会偶发漏睡，故这只是缓解而非等价于组件 4。
8. 首次全量务必带 `--skip-minute`（分钟线默认已关闭，`config.yaml:36`；一旦开启，单只 5 年 5 分钟线约 58,000 行会触发 6 页分页，既是重负载又因缺口 H 漏计配额）。

---

## 10. 参考

- BaoStock 平台访问规则：https://www.baostock.com/mainContent?file=accessRule.md
- 错误码定义：baostock `common/contants.py`（`BSERR_BLACKLIST_USER = "10001011"`、`BSERR_LOGIN_COUNT_LIMIT = "10001005"`、`BAOSTOCK_PER_PAGE_COUNT = 10000`）
- 分页机制：baostock `data/resultset.py:52-118`（`next()` 满页时自行 `send_msg` 取下一页）
- 登录语义：baostock `login/loginout.py:17`（`user_id='anonymous'`，全体用户同一账号 → 封禁必然是 IP 级）
- 共享 IP 被连坐的社区实例：https://github.com/sngyai/Sequoia-X/issues/127
- 解封指引（含 TUN 模式说明）：https://github.com/mark32123/MACD-BottomScreener

---

## 实现后注记（2026-10-28，与方案的口径差异）

1. **组件 3 熔断同时覆盖 `_api_call`**：`meta/macro/component` 共 12 个调用点走 `_api_call` 而非 `query_with_retry`，若只按组件 3 原文只改 `query_with_retry`/`login`，「被封后 0 次请求」（§2.1）在该路径不成立。实现按 §2.1 目标补齐，回归用例 `test_api_call_blacklist_breaks`。
2. **`blacklist.blocked_message(remain)` 文案助手**：组件 2 的固定文案需在 3 个闸点复用（helpers 入口/每趟、`BaseDownloader.__init__`、熔断点），抽为纯格式化函数；接口表的 6 个函数语义不变。
3. **monitor 退避常量归一的实现形态**（决策 3）：用独立的 `load_backoff_minutes()`（python 一行读 `config_loader`，失败回落 120 + WARN）而非塞进 `check_connectivity` 的 heredoc——该 heredoc 以退出码为契约，混入输出解析更脆；「config.yaml 单一事实源 + 失败回落」的决策语义完整保留。
4. **部分构造对象的兜底**：`close()` 对 `_blacklisted` 用 `getattr` 兜底、`_last_request_ts` 提供类级默认值——既有测试夹具以 `object.__new__` 构造部分对象，且 `close()` 有「不得抛」的既有契约；两者均非配置冻结，不违反 §3.4。
5. **测试隔离**：`tests/conftest.py` autouse 旁路黑名单闸（`set_bypass(True)`），避免真实 `data/.blacklisted` 存在时套件被打红；闸门类用例显式 `set_bypass(False)` 并把标记指到 tmp_path。
6. **退出码口径**（§3.2「非 0」的具体化）：`1` = 配额上限、`2` = 启动闸拒绝启动、`3` = 查询期熔断终止（loop=True 被封终止不得退出 0，否则 `start.sh` 会误标 DONE、外部调度误判成功）。
7. **翻页计数按数值比较**：真实 `ResultData.cur_page_num` 是字符串（`body_arr[4]`），字典序比较会在 9→10 页边界漏计；实现统一转 int 比较，测试夹具对齐真实形态（字符串页号）。
