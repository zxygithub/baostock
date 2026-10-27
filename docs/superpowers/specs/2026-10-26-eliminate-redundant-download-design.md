# 消除重复下载与无效趟次循环 — 设计方案

- 日期:2026-10-26
- 状态:已实现(2026-10-27 并入 master;实现计划见 docs/superpowers/plans/2026-10-26-eliminate-redundant-download.md)
- 涉及文件:
  - `src/downloaders/kline_downloader.py`(退市股跳过)
  - `src/downloaders/index_downloader.py`(增量拉取)
  - `src/downloaders/financial_downloader.py`、`src/downloaders/dividend_downloader.py`、`src/downloaders/report_downloader.py`(探测每日备忘 + 新增行精确计数)
  - `src/downloaders/meta_downloader.py` / `scripts/download_all.py`(元数据每日一次)
  - `src/utils/helpers.py`(`run_main_with_report` 趟次调度,方案 B;心跳日志)
  - `scripts/update_daily.py`(不改行为,仅约束为单趟;见组件 5)
  - `src/db_manager.py`(新表 `daily_probe_memo` + 迁移)、`config.yaml` / `src/config_loader.py`(新增配置)
  - `tests/`(新增 5 组用例)、`README.md` / `docs/download_flow.md`(同步说明)

## 背景

2026-10-25、10-26 两天各跑 22 趟、日下载约 **185 万行**,13:16 即烧完 46,000 请求配额;而 10-24 单趟全天仅 16.1 万行。排查(日志 `logs/2026102*_*.log` 逐趟比对、`data/baostock.db` 抽样验证)定位的根因链:

1. **每趟全量重拉**:指数 K 线从 `2006-01-01` 全量重拉(50,520 行/趟,占 62%),元数据 `trade_dates`/`stock_basic`/`stock_industry` 全量重拉(27,744 行/趟,占 34%);
2. **退市股永不跳过**:K 线跳过条件是 `max(date) >= end_date`,对已退市股票永不成立(其 `max(date)` 停在退市日)。每趟重复请求同一批 **340 只退市股 ×3 个复权 = 1,020 次请求**(每趟请求数的 77%),每次只返回 1 行末日 K 线。已验证 340/340 在 `stock_basic.out_date` 均有值;
3. **永不完成的探测**:财务缺失季度(如 sh.600355 2026Q1 返回 0 行)与复权因子"分红事件未覆盖"的股票每趟重探(约 265 次请求/趟),因永远查不到数据而永不消失;
4. **趟次无"无事可做"终结语义**:`run_main_with_report` 把白天任何正常返回都当"趟次边界",monitor 每 10 分钟重启,上述重复 ×22 倍,直到配额耗尽才停。

10-25 与 10-26 两天总行数几乎逐行相等(1,853,805 / 1,853,814),因为两天空转趟次的目标区间完全相同(`target_date = 昨日` → `end_date` 均为 2026-10-23)。

## 已确认决策

| 决策点 | 结论 | 否决项与理由 |
|---|---|---|
| 趟次终结语义 | **方案 B:无新增 → 休眠 90 分钟复检**,直到 23:55 正常终结发日报 | A"当日终结":晚间发布的财报/公告要等次日;C"定时两趟":16:00 是写死的猜测值,晚间公告仍会漏 |
| 退市股跳过 | `out_date <= end_date` **且** `max(date) >= out_date` 才永久跳过(自愈:数据有缺口则先补到 `out_date` 再跳) | 仅按 `out_date` 跳过:若库中该股历史有缺口则永远补不上 |
| 指数 K 线 | 按 `code + 频率` 取库内 `max(date)` 增量拉取,`>= end_date` 跳过 | 保持全量:占空转行数 62%,不可接受 |
| 元数据 | 当日首趟拉一次,后续趟跳过(标记文件 `data/.meta_fetched_YYYY-MM-DD`) | 每趟重拉:占空转行数 34% |
| 永不完成的探测 | 新表 `daily_probe_memo` 每日只探一次(财务缺失季度、复权因子未覆盖事件) | 每趟重探:约 4.2k 请求/日 纯浪费 |
| "新增行"判定 | **全部数据源统一**按"写入行在库中此前不存在"计数(精确;各表规则见下) | 用 `total_rows` 粗判:复权因子/报表/分红的复拉会误判为"有新增"导致永不休眠 |

## 目标与范围

**目标**(修复后单日预期):

| 指标 | 现状(空转日) | 目标 |
|---|---|---|
| 下载行数 | ~185 万行 | ~9 万行(元数据 2.77 万一次性 + 分红/复权每日刷新),≈ -95% |
| API 请求 | ~44.7k(13:16 耗尽配额) | ~17k(其中分红 operate 探测 + 复权每日刷新是既有设计成本),配额全天有余 |
| 无效趟次 | 22 趟/趟 81.5k 行 | 16 趟左右/趟近零成本,且每趟有 summary 日志可审计 |

**不做**(YAGNI):

- 不改变 `target_date = 昨日` 的时效语义(当日收盘日线仍于次日凌晨入库;这是既有设计,另立议题)
- 不改 46,000 配额、黑名单退避、monitor 探测计量机制;monitor **无需改动**(前提见组件 5:休眠分段心跳写日志,不触发其 15 分钟"日志静默判卡死"逻辑)
- 不动报表(业绩快报/预告)7 天滚动刷新窗口——到期批次(约 700+ code × 2 请求)属既有设计成本,集中在一趟处理
- 不动分钟线、周线/月线的"按需更新"节奏
- 不动财务"跳过当前季度与上一季度"的取数节奏(它导致 Q3 财报延迟到次年才拉,属完整性/时效问题,非本次冗余问题)
- **复权因子每日全量刷新(约 55k 行/日,5.4k 请求)保持现状**,列为后续优化观察项(改增量有漏改历史复权事件的风险)
- 不改日报邮件格式

## 架构与数据流

```
monitor(每 10 分钟,进程存活即不动)
  → ./start.sh full → scripts/download_all.py
      → run_main_with_report(main)  ← 本次改为趟次调度循环
          loop:
            new_rows = main()          # 一趟 = Phase 2~11 各阶段
              Phase 2   元数据        # 仅当日首趟(data/.meta_fetched_YYYY-MM-DD)
              Phase 4-5 宏观/成分      # 现状不变(成本小)
              Phase 6   指数 K 线      # 增量:max(date) 之前跳过
              Phase 7   股票 K 线      # 退市股:out_date<=end_date 且 max(date)>=out_date → 跳过
              Phase 9-11 财务/报告/分红 # 缺失季度、未覆盖事件 → daily_probe_memo 每日一探
            若 SystemExit(1)          → 终结:达到每日请求上限,发日报
            若 已过 23:55              → 终结:达到每日停止时间,发日报
            若 new_rows > 0            → 立即下一趟(数据还在来)
            否则                       → 休眠 90 分钟(上限 23:55)后复检
```

## 组件设计

### 1. 退市股跳过(`kline_downloader.py`)

`_download_kline_batch` 内,对每只股票:

```
skip iff stock_out and stock_out <= end_date and last >= stock_out
```

- `stock_out` 来自现有 `ipo_dates`(即 `stock_basic.out_date`),`last = get_last_downloaded(...)`,均已在作用域内;
- **自愈性**:若 `last < out_date`(退市前数据有缺口),本次仍拉取(`actual_end = min(end_date, stock_out)`),补到 `out_date` 后永久跳过;
- 现有 `if stock_out and stock_out < start_date: continue` 被此规则覆盖(语义更严格),可合并;
- 空转的 340 只股票经抽样验证 `last == out_date`,首轮即跳过。

### 2. 永不完成的探测每日一探(`financial_downloader.py`、`dividend_downloader.py`)

新表(SQLite,`db_manager.migrate_schema` 建表):

```sql
CREATE TABLE IF NOT EXISTS daily_probe_memo (
  scope TEXT NOT NULL,      -- 'fin_missing:<table>' / 'af_uncovered'
  item_key TEXT NOT NULL,   -- 'code|year|quarter' 或 code
  probe_date TEXT NOT NULL, -- 'YYYY-MM-DD'
  PRIMARY KEY (scope, item_key)
);
```

- **财务缺失季度**:`_find_missing_quarters` 的任务集再过滤 `probe_date == 今日` 的条目;任务执行后(无论是否返回行)UPSERT `probe_date = 今日`;
- **复权因子未覆盖事件**(`_find_stale_adjust_factor` 第二个 UNION 分支,即今日每趟 140 只的来源):同样按 code 每日一探;
- 复权因子第一个分支("今日未刷新")维持现状(每日全量刷新,见"不做");
- `probe_date` 按日覆盖写入,表体积 ≤ 条目数,无需清理。

### 3. 指数 K 线增量(`index_downloader.py`)

- 三个方法 `download_index_daily/weekly/monthly` 统一改为:`last = get_last_downloaded(对应表, code)`;`last >= end_date` → 跳过;否则 `actual_start = max(config 起始日, last)`;
- `index_daily` 无 `adjustflag` 列;`index_weekly/monthly` 虽含 `adjustflag` 列(PK 一部分),`get_last_downloaded` 不带 `adjustflag` 调用、取该 code 全表 `max(date)` 作为增量起点即可(起点宁早勿晚,多拉的行由 upsert 幂等吸收);
- 首次迁移对存量无影响(存量 `max(date)` 已是 2026-10-23)。

### 4. 元数据每日一次(`download_all.py`)

- Phase 2 入口判断 `data/.meta_fetched_YYYY-MM-DD` 是否存在(沿用 `.report_sent_YYYY-MM-DD` 标记文件惯例);存在则跳过 `download_all_metadata`,否则执行后落标记;
- 手动单趟运行(`--once`)同样受标记约束,可用 `--force-meta` 强制刷新(新增 CLI 旗标,供排障);
- `codes` 列表来自库内 `_get_stock_codes`,不受影响(新股次日首趟自然进入)。

### 5. 趟次调度(`src/utils/helpers.py::run_main_with_report`,方案 B)

- `main()` 改为返回**本趟新增行数**(int);
- `run_main_with_report(main_fn, *, loop: bool = False)` 改为可选调度循环(见上文数据流),日志措辞相应更新("趟次结束但当日拉取未终结" → "本趟无新增数据,休眠 N 分钟后复检");
- **休眠必须分段(≤5 分钟/段)并每段写一行心跳日志**:monitor 的 `check_process_activity` 以"最新日志 15 分钟未更新"判定进程卡死并 SIGINT 重启(`monitor_baostock.sh:396` 阈值 15 分钟),静默长睡会被打断。心跳同时承担每段醒来检查 23:55 的职责——**这是"monitor 无需改动"成立的前提**;
- 休眠间隔 `download.idle_pass_interval_minutes: 90`(`config.yaml`,`config_loader` 提供 getter);分段上限保证 **23:55 前后能终结发日报**,不允许睡过终结点不发;
- 终结条件与日报触发保持现状:`SystemExit(1)`(配额)或过 23:55,理由文案不变;
- `download_all.py` 新增 `--once`:只跑一趟即退出(不休眠、不循环),供手动/排障用;不带 `--once` 的行为即调度循环;
- **`scripts/update_daily.py` 保持单趟语义**(手动工具,不挂 24 小时):它同样调用 `run_main_with_report`,以默认 `loop=False` 保持现有行为;其 `main()` 无需返回计数(单趟模式下返回值不参与调度)。

### 新增行计数规则(生产性判定)

| 数据 | 计数规则 | 说明 |
|---|---|---|
| 股票/指数 K 线 | `date > 查询前 max(date)` 的行数 | 精确、零成本(比较即可);退市股补缺的旧行不计 |
| 财务缺失季度任务 | 任务生成时经 LEFT JOIN 确认"库中缺失",返回行数即新增 | 精确 |
| 报表(业绩快报/预告) | 保存前对表主键 LEFT JOIN 计数 | 7 天窗口复拉返回的存量行不计(**`report_downloader.py` 纳入本次改动**) |
| 分红 `operate` 每日复探 | 同上,按 `(code, year, year_type)`/主键判重 | 复探返回的存量行不计 |
| 复权因子 | 保存前对 `(code, divid_operate_date)` 做临时表 LEFT JOIN 计数 | 项目已有同款模式(`_find_missing_quarters`);全量刷新的存量行不计 |
| 元数据、宏观、指数成分 | 恒为 0 | 维护性全量小表,不作为"数据在来"的信号(宏观月度数据最多延迟一趟) |

## 测试计划

- `tests/test_dead_stock_skip.py`:退市且完整 → 跳过(0 请求);退市但有缺口 → 拉一次补缺后跳过;未退市 → 正常增量;
- `tests/test_index_kline_incremental.py`:有新增 → 仅拉增量区间;`max(date) >= end_date` → 0 请求;
- `tests/test_meta_daily_once.py`:同日第二次趟跳过元数据;`--force-meta` 强制;
- `tests/test_probe_memo.py`:财务缺失季度/复权未覆盖事件每日一探,次日恢复探测;
- `tests/test_pass_scheduler.py`:有新增 → 立即下一趟;无新增 → 调用 sleep;`SystemExit(1)` → 日报理由=配额;过 23:55 → 日报理由=停止时间;休眠不越过 23:55;
- 全量回归:`.venv/bin/python -m pytest tests/` 现有用例全部通过。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| `out_date` 与真实数据末日不一致(如复牌重上市) | 跳过以 `last >= out_date` 为前提,数据永不完整则永不跳过(自愈);复牌新股按新 code 处理 |
| 生产性判定漏判 → 误睡 90 分钟 | 每趟打 summary 日志(各表新增行数、请求数、下一趟动作),漏判最多延迟一趟,可观测可补拉 |
| 休眠被 monitor 判"卡死"SIGINT 打断(15 分钟日志静默阈值,`monitor_baostock.sh:396`) | 休眠分段 ≤5 分钟/段,每段写心跳日志(组件 5);monitor 无需改动 |
| 休眠越过 23:55 不发日报 | 分段醒来即查 23:55,硬约束不越过终结点;另有 00:00 `--if-needed` 兜底补发(现状已有) |
| `daily_probe_memo` 误标"已探"导致漏数据 | 探测对象均为"库中缺失"条目,漏掉的只是当次空探;次日自动恢复探测 |

## 预期效果与验收

1. 空转日(无新交易数据):单日下载行数 ≤ 10 万(现状 185 万),请求数 ≤ 20k 且全天不触顶;
2. 空转趟次成本 ≤ 50 请求/趟(现状 1,320);报表 7 天窗口到期批次(约 700+ code × 2 请求)集中在单趟处理,属设计内成本,不计此项;
3. 10-25 型场景重放:22 趟 × 81.5k 行的重复下载消失,日志中每趟 summary 可见"新增 0 行";
4. 日报正常于 23:55 终结时发送(或配额耗尽时),格式不变。

## 审阅修订记录(builder check 后裁定)

| # | 审阅发现 | 裁定 |
|---|---|---|
| 1 | monitor 有"最新日志 15 分钟未更新即判卡死、SIGINT 重启"逻辑,静默长睡会被打断,原稿"monitor 无需改动"论据不成立 | **采纳**:休眠分段 ≤5 分钟/段并写心跳日志,monitor 仍不改(组件 5、风险表已修订) |
| 2 | 报表 7 天窗口复拉、分红 `operate` 每日复探返回的多为存量行,"返回行数即新增"只对财务成立;宏观/成分全量刷新未入计数表 | **采纳**:统一精确判重计数,`report_downloader.py` 纳入改动范围;宏观/成分恒计 0(计数表已修订) |
| 3 | `update_daily.py` 与 `download_all` 共用 `run_main_with_report`,其 `main()` 无返回值,循环化会破坏单趟语义 | **采纳**:调度循环做成 `loop` 开关且默认关闭,`update_daily.py` 保持单趟(组件 5 已修订) |
| 4 | 报表 7 天窗口按时间戳滚动,到期批次会摊进空趟成本,与验收"≤50 请求/趟"冲突 | **采纳**:报表刷新节奏不动(既有设计),验收口径改为"不含周期性刷新批次"(验收 2 已修订) |

## 留待实现者

- 各 skip/计数辅助函数的具体落点(基类 vs 各 downloader)与命名;
- 日志 summary 的具体字段与文案;
- 测试夹具的构造方式(参照 `tests/test_financial_skip_logic.py`、`tests/test_download_all_skip_logic.py` 现有模式);
- `docs/download_flow.md`、`README.md` 同步更新的措辞。
