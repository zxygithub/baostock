# 数据拉取完成即发日报 — 设计方案

- 日期:2026-10-01
- 状态:设计已确认,待实现
- 涉及文件:`scripts/daily_report.py`、`scripts/download_all.py`、`scripts/update_daily.py`、`src/utils/helpers.py`、crontab、`tests/`(新增)、`README.md`

## 背景

日报现由 cron `0 0 * * *` 固定在 0:00 发送,按"昨日"口径统计。但拉取任务的实际结束时间不固定:

- 提前耗尽 49,000 次请求上限(`SystemExit(1)`,monitor 检测到上限后当日不再重启下载)
- 到达日停时间 23:55(`DAILY_SHUTDOWN_TIME`,进程保存 checkpoint 后退出)
- 全部数据拉取完成提前收工(含非交易日空跑)
- 手动执行 `./start.sh update` / `full`

需求:**任务完成即发**(而非等 0:00),并**最终保证**当天任务完成后必达报告邮件。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| 即时触发集合 | 上限(49000)、日停(23:55)、正常跑完(含非交易日)、手动运行;一天一封,先到先得 |
| 兜底 | 0:00 兜底 cron(原 cron 改造),`data/.report_sent_<日期>` 标记去重;最迟次日 0:00 必达 |
| 实现方案 | 方案 1:进程内完成钩子 + sent 标记 + 0:00 兜底 |
| 邮件内容 | 沿用现有 HTML 日报;正文信息卡加一行「完成原因」 |
| 主题 | 沿用 `BaoStock 数据下载日报 (<报告日>)`,报告日 = 拉取任务日 |

## 触发 / 不触发矩阵

| 退出方式 | 即时发? | 原因文案 | 说明 |
|---|---|---|---|
| 正常 return(全部阶段跑完) | ✅ | `数据拉取完成(全部已更新)` | 退出时 `is_past_shutdown_time()` 为真则改用日停文案 |
| 正常 return(阶段间日停检查点返回) | ✅ | `达到每日停止时间(23:55)` | update_daily/download_all 各阶段间的日停 return |
| `SystemExit(1)` | ✅ | `达到每日请求上限(49000)` | 全库仅请求上限路径抛 exit 1(含开跑前已达上限) |
| `KeyboardInterrupt`(monitor 卡死 SIGINT) | ❌ | — | 任务未完成,monitor 会重启继续 |
| 其它异常(崩溃) | ❌ | — | 同上,重启继续 |
| `SystemExit("IP blacklisted.")` | ❌ | — | 异常终止,由 0:00 兜底 |
| 23:59 SIGKILL / 整日宕机 | ❌(技术不可达) | — | 由 0:00 兜底补发 |

## 架构与数据流

```
download_all.py / update_daily.py (__main__)
  └─ helpers.run_main_with_report(main_fn)
       ├─ 正常 return ────────────┐
       ├─ SystemExit(1) ──────────┤→ send_daily_report(reason)
       └─ 其它异常 → 原样抛出(不发)   │   └─ subprocess: daily_report.py
                                    │        --if-needed --date <今天> --reason <原因>
                                    │        ├─ 标记已存在 → 静默退出
                                    │        ├─ 生成 HTML → SMTP 发送
                                    │        └─ 成功后写 data/.report_sent_<报告日>
0:00 兜底 cron
  └─ daily_report.py --if-needed --reason 次日0:00兜底补发
       (--date 默认=昨天,与任务日一致)
```

## 组件设计

### 1. `scripts/daily_report.py`(参数化 + 去重)

新增命令行参数:

| 参数 | 语义 |
|---|---|
| `--if-needed` | `data/.report_sent_<报告日>` 存在 → 静默 exit 0;发送**成功后**才写标记(SMTP 失败不写,留给兜底重试) |
| `--date YYYY-MM-DD` | 报告日;替换现有一切 `today-1` 硬编码(请求统计、预估基准、日志解析、主题);**默认=昨天**(适配 0:00 兜底) |
| `--reason` | 正文首张信息卡加一行「✅ 完成原因: {reason}」 |

内容微调:标签「📈 昨日已使用请求次数」→「📈 当日已使用请求次数」(指报告日)。主题日期 = 报告日,格式不变。

### 2. 完成钩子(两脚本共用)

`src/utils/helpers.py` 新增 `run_main_with_report(main_fn, logger=None)`(约 20 行):

| main_fn 退出 | 行为 |
|---|---|
| 正常 return | reason = `达到每日停止时间(23:55)`(若 `is_past_shutdown_time()`)否则 `数据拉取完成(全部已更新)`;调 `send_daily_report` |
| `SystemExit` 且 `code == 1` | reason = `达到每日请求上限(49000)`;调 `send_daily_report` |
| 其它(`KeyboardInterrupt`、任意异常、`SystemExit` 非 1) | **不发**,原样 re-raise |

`send_daily_report(reason)`:subprocess 调 `daily_report.py --if-needed --date <今天> --reason <reason>`,`timeout=120`,异常全吞仅 warning——**发信成败不影响下载退出码**。

`download_all.py` / `update_daily.py` 的 `if __name__ == "__main__": main()` 改为 `run_main_with_report(main)`。手动与 monitor 启动的运行自动同等覆盖。

### 3. 标记文件

`data/.report_sent_YYYY-MM-DD`,内容为发送时间+原因(`data/` 已在 .gitignore)。`--if-needed` 检查存在性;仅发送成功后写入。

### 4. cron 变更(一次性)

```bash
# 旧
0 0 * * * cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py >> logs/cron_daily_report.log 2>&1
# 新
0 0 * * * cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py --if-needed --reason 次日0:00兜底补发 >> logs/cron_daily_report.log 2>&1
```

## 错误处理矩阵

| 情况 | 行为 |
|---|---|
| 完成即发成功 | 写标记;当天其余完成事件静默跳过 |
| 完成即发 SMTP 失败 | warning;不写标记 → 0:00 兜底自动重试一次 |
| 23:59 被 SIGKILL / 进程崩溃未恢复 / 整日宕机 | 无钩子 → 0:00 兜底补发,**最迟次日 0:00 必达** |
| monitor 卡死重启(SIGINT)/ 崩溃重启 | 不发(任务未完成,重启续跑) |
| 发信中下载进程被 kill | 无影响:`kill_baostock.sh` 的 pgrep 模式仅匹配 `baostock.*download`,不杀 `daily_report.py` 子进程,邮件仍会发完 |

## 测试计划

- `tests/test_daily_report_trigger.py`:
  - `--if-needed` 有标记 → 不发信静默退出;无标记 → 发信且成功后写标记
  - 发信失败(`send_email` 返回 False)→ **不写**标记
  - `--date` 生效:请求统计日期、主题日期均取该日;默认 = 昨天
  - `--reason` 出现在 HTML 正文
- `tests/test_completion_report.py`(测 `run_main_with_report`):
  - 正常 return → 发,原因正确(日停 / 全部完成两种)
  - `SystemExit(1)` → 发,原因=上限
  - `KeyboardInterrupt` / 任意异常 / `SystemExit("IP blacklisted")` → 不发且原样抛出
  - subprocess 失败 → 吞掉,不影响 main_fn 退出语义
- 回归:现有 114 测试全过
- 手工:同日连跑两遍 `--if-needed` 只收一封;删标记后兜底补发

## 已知取舍

- **先到先得**:一天多发只发第一封(如 02:00 正常跑完发过,16:00 撞上限不再发,后到增量不补报)。已与需求方确认"一天一封"。
- **SMTP 单次尝试**:即时失败仅靠 0:00 兜底补一次,不做多次重试循环。
- `update_daily.py` 的 "No stock codes found" 等罕见早退按正常完成处理(标记去重兜住,不会重复骚扰)。

## 实现顺序

1. `daily_report.py` 参数化 + 标记 + reason + 测试
2. `helpers.run_main_with_report` + 两脚本接入 + 测试
3. crontab 更新 + README 更新日志
4. 手工验证(连跑去重、兜底补发)
