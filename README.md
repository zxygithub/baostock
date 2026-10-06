# BaoStock 数据下载器

从 BaoStock API 下载中国A股市场数据（K线、财务数据、宏观经济数据）到 SQLite 数据库。

## 📋 功能特性

- **完整的数据覆盖**：日/周/月/分钟K线数据，支持3种复权类型
- **财务数据**：利润表、运营能力、成长能力、资产负债表、现金流量表、杜邦分析
- **宏观经济数据**：存款/贷款利率、存款准备金率、货币供应量
- **指数数据**：上证50、沪深300、中证500成分股及指数K线
- **公司报告**：业绩预告、业绩快报、分红送转数据
- **智能下载**：断点续传、批量处理、会话自动重连
- **数据管理**：完整的数据库管理工具和日志系统
- **云端备份**：自动压缩数据库并上传至百度网盘，支持定时备份、旧备份清理和结果邮件通知

## 🚀 快速开始

### 1. 安装依赖
```bash
uv sync
```

### 2. 使用 start.sh（推荐）
```bash
# 初始化数据库
./start.sh init

# 全量数据下载（所有阶段）
./start.sh full

# 每日增量更新
./start.sh update

# 基于调度器下载（V2.1.0 规划中）
./start.sh scheduled

# 检查下载进度
./start.sh status

# 数据完整性校验
./start.sh check                          # 全量检查
./start.sh check --code sh.600000         # 检查单只股票
./start.sh check --level 1 --level 7      # 检查指定层级
./start.sh check --date 2026-07-20        # 指定校验基准日

# SQLite 物理结构检查(页面/freelist/索引/schema)
.venv/bin/python scripts/check_sqlite_structure.py             # 全量检查(15GB 库约 75 分钟,建议每周低峰)
.venv/bin/python scripts/check_sqlite_structure.py --quick     # 秒级快速检查(跳过完整性深度检查)
.venv/bin/python scripts/check_sqlite_structure.py --no-email  # 发现损坏也不发告警邮件
# 退出码:0=健康 1=发现损坏 2=检查器出错
# 损坏时告警邮件复用 .env 的 EMAIL_* 配置,开关为 config.yaml 的 email.enabled

# 查看最近日志
./start.sh logs
```

### 3. 数据管理
```bash
# 列出所有表及其行数
./clean_data.sh --list

# 清空特定表
./clean_data.sh --table all_stock_daily

# 清空所有表（需要确认）
./clean_data.sh --all
```

### 4. 百度网盘备份
```bash
# 首次配置：授权 bypy（百度网盘命令行工具）
pip install bypy
python -m bypy info    # 按提示完成授权

# 手动执行备份
.venv/bin/python scripts/backup_to_baidu.py

# 配置定时备份（默认每周日 14:00）
bash scripts/setup_backup_cron.sh

# 自定义备份时间
bash scripts/setup_backup_cron.sh 2 30 0   # 每周日 02:30
bash scripts/setup_backup_cron.sh 14 0 6   # 每周六 14:00

# 保留指定数量的备份（默认保留 7 份）
.venv/bin/python scripts/backup_to_baidu.py --keep 14

# 备份结束后自动发送结果通知邮件（复用 .env 中 EMAIL_* 配置）
# 主题格式：证券数据baostock百度云备份结果-YYYY年MM月DD日
# 关闭通知：config.yaml 中 email.backup_notify: false
# 手动静默试跑：加 --no-email
.venv/bin/python scripts/backup_to_baidu.py --no-email
```

## 📖 详细文档

- **[执行流程](docs/执行流程.md)** - 详细的项目架构和执行流程说明
- **[数据下载方案](docs/data_download_plan.md)** - 数据库设计和下载策略
- **[数据拉取流程](docs/download_flow.md)** - 全量/增量下载详细流程图
- **[服务器连通性监控](docs/monitor_design.md)** - 服务器监控方案设计
- **[调度方案详细设计](docs/调度方案详细设计.md)** - 任务调度器架构与配置设计
- **[改进计划](docs/improvement_plan.md)** - 已知问题和改进建议
- **[优化方案](docs/optimization_plan.md)** - K 线优先、财务降级优化计划
- **[IPO 日期优化](docs/ipo_based_download_optimization.md)** - 基于 IPO 日期的下载优化
- **[数据分析](docs/数据分析.md)** - 各表 API 拉取前置条件分析
- **[代码审查](docs/code_review_2026-04-28.md)** - 全代码逻辑审查报告
- **[API 请求日志分析](docs/api_request_log_analysis.md)** - 日志统计与异常排查指南
- **[数据完整性校验方案](docs/data_integrity_check_plan.md)** - 数据校验方案设计与实现
- **[BaoStock API](docs/pythonAPI.md)** - BaoStock官方API文档
- **[BaoStock复权因子简介](docs/BaoStock复权因子简介.pdf)** - 复权算法说明（PDF）

## 🗂️ 项目结构

```
baostock/
├── config.yaml              # 下载配置文件（用户可修改）
├── pyproject.toml          # Python项目配置
├── start.sh                # 主要入口脚本
├── clean_data.sh           # 数据管理脚本
├── clean_memory.sh         # 内存清理脚本
├── data/                   # 数据库文件（git忽略）
│   └── baostock.db
├── logs/                   # 日志文件（git忽略）
├── docs/                   # 项目文档
├── scripts/                # 入口脚本
│   ├── download_all.py     # 全量下载
│   ├── update_daily.py     # 增量更新
│   ├── init_db.py          # 数据库初始化
│   ├── check_data_integrity.py  # 数据完整性校验
│   ├── fix_data_gaps.py    # 数据空洞自动修复
│   ├── daily_report.py     # 邮件日报
│   ├── monitor_baostock.sh # 服务器连通性监控
│   ├── kill_baostock.sh    # 进程终止脚本
│   ├── check_blacklist.py  # 黑名单检测
│   ├── analyze_latest_dates.py  # 最新日期分析
│   ├── estimate_data_volume.py  # 数据量估算
│   ├── count_data.py            # 数据统计
│   ├── insert_null_profit_records.py  # 插入空利润记录
│   ├── backup_to_baidu.py      # 百度网盘备份
│   └── setup_backup_cron.sh    # 备份定时任务配置
├── src/                    # 核心代码
│   ├── config.py           # 技术常量和字段定义
│   ├── config_loader.py    # 配置加载器
│   ├── db_manager.py       # 数据库连接和表结构
│   ├── downloaders/        # 数据下载器
│   │   ├── base.py         # 基础下载器
│   │   ├── meta_downloader.py      # 元数据下载
│   │   ├── macro_downloader.py     # 宏观经济数据下载
│   │   ├── component_downloader.py # 指数成分股下载
│   │   ├── index_downloader.py     # 指数K线下载
│   │   ├── kline_downloader.py     # 股票K线下载
│   │   ├── financial_downloader.py # 财务数据下载
│   │   ├── report_downloader.py    # 公司报告下载
│   │   └── dividend_downloader.py  # 分红数据下载
│   └── utils/              # 工具类
│       ├── helpers.py      # 辅助函数（含日报完成钩子）
│       ├── email_notifier.py  # 公共邮件模块
│       └── validator.py    # 数据验证
└── tests/                  # 测试文件
```

## ⚙️ 配置说明

项目采用**三层次配置**设计，职责清晰：

### config.yaml（用户配置）

用户可以自由修改的运行参数（敏感凭据请使用 `.env`）：

```yaml
# API 配置
api:
  socket_timeout: 30          # 网络超时（秒）
  daily_request_limit: 46000  # 每日 API 请求上限

# 下载任务开关与日期范围
download:
  kline:
    daily:
      enabled: true                    # 是否下载日线
      start_date: "1990-12-19"         # 起始日期
      adjustflags: [1, 2, 3]           # 复权方式：1=后复权，2=前复权，3=不复权
    weekly:
      enabled: true
      adjustflags: [1, 2, 3]
    monthly:
      enabled: true
      adjustflags: [1, 2, 3]
    minute:
      enabled: false                   # 分钟数据量较大，默认关闭
      start_date: "2019-01-02"         # 分钟线起始日期（仅支持近5年）
      frequencies: ["5", "15", "30", "60"]
      adjustflags: [3]                 # 分钟线仅不复权
  financial:
    enabled: true
    start_year: 2007                   # 财务数据起始年份
    types: [profit, operation, growth, balance, cashflow, dupont]
  reports:
    enabled: true
    start_date: "2003-01-01"
  dividend:
    enabled: true
    start_year: 2007
  macro:
    enabled: true
  components:
    enabled: true
  index_kline:
    enabled: true
    start_date: "2006-01-01"

# 批处理配置
stocks:
  filter: "type=1 AND status=1"  # 股票筛选条件（SQL WHERE 子句）
  batch_size: 200                # 每批处理的股票数量
  batch_sleep: 1                 # 批次间休眠时间（秒）

# 邮件开关（敏感凭据在 .env 中配置）
email:
  enabled: true        # daily_report.py 日报开关
  backup_notify: true  # backup_to_baidu.py 备份结果通知开关
```

### .env（敏感凭据）

邮箱密码等敏感信息通过 `.env` 文件配置，已加入 `.gitignore` 不会被提交：

```bash
# 复制 .env.example 为 .env 并填入真实凭据
EMAIL_SMTP_SERVER="smtp.qq.com"
EMAIL_SMTP_PORT="465"
EMAIL_SENDER="your_email@qq.com"
EMAIL_PASSWORD="your_smtp_authorization_code"
EMAIL_RECEIVER="your_receiver_email@qq.com"
```

### src/config.py（技术常量）

开发者维护的技术常量，用户通常无需修改：

- **数据库路径**：`DB_PATH`
- **字段定义**：K 线字段、指数字段等
- **指数代码列表**：`INDEX_CODES`
- **内部参数**：`FINANCIAL_SLEEP`、`LOGIN_REFRESH_INTERVAL`、`MAX_RETRIES`

### src/config_loader.py（配置加载器）

统一从 config.yaml 读取配置，提供便捷的访问函数：

```python
from src.config_loader import (
    get_batch_size,          # 获取批处理大小
    get_kline_start_date,    # 获取 K 线起始日期
    is_download_enabled,     # 检查下载开关
    get_financial_start_year # 获取财务起始年份
)
```

**修改建议**：
- 用户只需编辑 `config.yaml` 即可控制所有下载开关和日期范围
- `.env` 用于存储所有敏感凭据（邮箱 SMTP 等）
- `config.py` 仅在需要修改字段定义或内部参数时才需调整

## 📊 数据库设计

项目使用 SQLite 数据库，共设计**33 张表**，涵盖：

- **元数据表**：股票基本信息、交易日历、行业分类
- **K 线数据表**：日/周/月/分钟 K 线（支持 3 种复权）
- **财务数据表**：6 类季频财务指标
- **公司报告表**：业绩预告、业绩快报
- **分红数据表**：除权除息、复权因子
- **指数数据表**：成分股、指数 K 线
- **宏观数据表**：利率、准备金率、货币供应量

### 数据库表概览

| 类别 | 表数量 | 主要表名 |
|------|--------|----------|
| 元数据 | 4 | `trade_dates`, `stock_basic`, `stock_industry`, `all_stock` |
| K线数据 | 11 | `all_stock_daily`, `all_stock_weekly`, `all_stock_monthly`, `all_stock_*min` |
| 财务数据 | 6 | `profit_data`, `operation_data`, `growth_data`, `balance_data`, `cash_flow_data`, `dupont_data` |
| 公司报告 | 2 | `performance_express`, `forecast_report` |
| 分红数据 | 2 | `dividend`, `adjust_factor` |
| 指数数据 | 5 | `index_daily`, `index_weekly`, `index_monthly`, `sz50_stocks`, `hs300_stocks`, `zz500_stocks` |
| 宏观数据 | 4 | `deposit_rate`, `loan_rate`, `reserve_ratio`, `money_supply_*` |
| 系统表 | 1 | `request_count` |

详细表结构见 [数据下载方案](docs/data_download_plan.md)。

## 🛡️ 新增功能（2026-04-24）

### 黑名单检测
```bash
# 检测当前 IP/账号是否被 BaoStock 列入黑名单
.venv/bin/python scripts/check_blacklist.py
```

monitor 连通性检查探测到黑名单（error_code 10001011）时写 `data/.blacklisted` 标记进入 **120 分钟退避期**（`BLACKLIST_BACKOFF_MINUTES`），期内跳过一切探测/重启，避免探测请求延长封禁；退避期过自动复测，恢复正常后删除标记。

### 邮件日报
- 当日拉取**真正终结**（46000 请求上限 / 日停 23:55）时**立即发送**进度邮件（日报生成约 2~3 分钟，邮件随后送达）
- 多趟 pass 的中间退出不发（monitor 会重启续拉，当天任务未完成）
- 包含黑名单状态、请求次数、数据拉取评估表、完成原因
- 一天一封（`data/.report_sent_<日期>` 标记去重）；0:00 cron 兜底补发，最迟次日 0:00 必达
- 配置 `.env` 文件设置 SMTP 信息

### 交易日智能判断
- `update_daily.py` 自动检测是否为交易日
- 非交易日（周末/节假日）自动跳过 K 线下载
- 每年节省约 190 万次无效 API 请求

### 敏感信息保护
- 使用 `.env` 文件存储邮箱密码等敏感信息
- `.env` 已加入 `.gitignore`，不会泄露到 Git

## 🔧 高级用法

### 跳过特定阶段
```bash
# 跳过财务数据和分钟数据下载
./start.sh full --skip-financial --skip-minute
```

### 自定义股票筛选
```bash
# 只下载上证A股（type=1）且正常上市（status=1）的股票
# 在 config.yaml 中配置：
stocks:
  filter: "type=1 AND status=1"
  batch_size: 200
  batch_sleep: 2
```

### 日志管理
```bash
# 查看最新日志
./start.sh logs

# 清理30天前的日志
./start.sh clean-logs 30

# 清理临时表
./start.sh clean-tmp
```

## ⚠️ 注意事项

1. **API限制**：BaoStock API有调用频率限制，项目已内置休眠机制
2. **数据量**：全量下载数据量较大，需要足够的磁盘空间
3. **网络要求**：需要稳定的网络连接
4. **时间消耗**：全量下载可能需要数小时，建议在服务器上运行
5. **数据更新**：财务数据按季度更新，日K线每日更新，周/月K线按周期触发
6. **不支持并发下载**：BaoStock API **不支持真正的并发下载**。多线程/多会话并发下载会导致数据解压错误（UTF-8 解码失败、`invalid distance too far back` 等）。项目采用单会话顺序下载模式，批次间有适当的休眠时间。请勿自行修改代码启用并发下载功能。

## 📈 性能优化

- **断点续传**：支持下载中断后恢复，避免重复下载
- **批量处理**：股票代码分批下载，每批200个
- **会话管理**：自动检测会话超时并重新登录
- **数据库优化**：使用WAL模式提升写入性能

## 🔄 更新日志

- **2026-10-05**：修复交易日历取不到今年全年数据的问题
  - **问题根因**：`download_trade_dates` 调用 `bs.query_trade_dates(start_date, end_date=None)`，baostock 库对 `end_date=None` 默认取**当天**而非年底（`stock_metadata.py` 内 `time.strftime("%Y-%m-%d")`），导致日历永远截止到运行当天。实测 BaoStock 服务端本身支持未来日期（`end_date=2026-12-31` 返回全年 365 行含未发生交易日），交易所年初即公布全年休市安排，服务端数据齐全
  - **修复方案**：(a) `download_trade_dates` 默认 `end_date=当年-12-31`，一次取满全年交易日历（含未来交易日）；(b) 消费点全部按 `calendar_date <= 今天` 过滤，防止未来交易日虚增期望数据量/污染校验：`daily_report.py`（日报进度估算）、`estimate_data_volume.py`（数据量估算）、`check_data_integrity.py`（L1/L3 期望交易日数与 `latest_trading_day`/`expected_cutoff`，含 `--date` 传未来日期的防御）
  - **附带事实**：`end_date` 传下一年（如 2027-12-31）服务端只返回到当年末——次年休市安排一般当年年底才发布，属正常现象；`query_trade_dates` 按条计 1 次请求（10,000 行/页自动翻页），拉全年不增加 API 配额
  - **测试**：新增 `tests/test_trade_dates_full_year.py` 7 例（默认区间、显式区间透传、三个消费点排除未来交易日、未来 `--date` 防御），未修复代码下 5 例精确复现
  - 修改文件：`src/downloaders/meta_downloader.py`、`scripts/daily_report.py`、`scripts/estimate_data_volume.py`、`scripts/check_data_integrity.py`、`tests/test_trade_dates_full_year.py`（新增）、`docs/download_flow.md`、`docs/数据分析.md`
- **2026-10-03**：修复完成即发日报在发信环节被超时强杀的问题
  - **问题根因**：`send_daily_report` 的 `subprocess.run(timeout=120)` 按"发邮件很快"的错误假设写死，但 `daily_report.py` 在 16GB 库上生成需 2~3 分钟（33 张表全表 COUNT 扫描，下载任务并发时更久）。10-03 10:43 撞 49000 上限后钩子正确触发，但子进程 120 秒被杀（日志留有 timed out 记录），当日日报未即时发出（仅靠 0:00 兜底）
  - **修复方案**：超时提至 600 秒（实测最坏约 5 分钟，留一倍余量）；测试断言改为 `timeout >= 300` 契约
  - **验证**：真实调用 `send_daily_report` 走原故障路径，今日终报（完成原因：达到每日请求上限(49000)）发送成功并写入去重标记
  - 修改文件：`src/utils/helpers.py`、`tests/test_completion_report.py`
- **2026-10-02**：修复近三年分红数据不再更新的问题（dividend 表缺 2025/2026）
  - **问题根因**：5-07 的 SQL 存在性检查重构把 `_find_missing_dividend` 的"近三年强制刷新"语义写反（`if year in recent_years` → `if year not in recent_years`），近三年组合永远进不了下载任务；实测 dividend 表最新真实记录停在 year=2024
  - **附带缺陷**：空响应写下的占位记录会永久遮蔽真实数据（实测 sh.600000 等股票 2023/2024 分红被假占位挡死），无复核机制
  - **修复方案**：（a）组合级缺失必查——立即回填 2025/2026；（b）近期 `operate` 组合按日强制重查（新除权事件都落在除权年 operate 口径，单型查询即可全覆盖，`report` 型归属行滞后补齐）；（c）纯占位组合每 30 天复核一次、单批 1000 条限流，治愈假空占位；真实行落库时清除同组合占位
  - **成本**：每日约 1.1 万次近期探测 + 月均约 2 千次占位复核，封顶可控
  - 修改文件：`src/downloaders/dividend_downloader.py`、`tests/test_dividend_refresh.py`（新增）、`tests/test_close_checkpoint.py`（fixture 补列）
- **2026-10-02**：修复复权因子每趟 pass 重复全量拉取（每趟浪费约 5500 次请求）
  - **问题根因**：`download_adjust_factor` 无"已存在检测"，每天 5 趟 pass 每趟都对全部 ~5561 只股票重查复权因子（实测当日重复消耗约 2.2 万次请求配额）
  - **修复方案**：新增 `_find_stale_adjust_factor`（沿用 SQL 临时表 + LEFT JOIN 模式），仅两类股票重查：当日未查过（自然日内每只股票至多一次）或已知分红事件未被复权因子覆盖（L5 期望集模型）；空结果写 `9999-01-01` 占位、真实行落库时清除占位
  - **取舍**：新除权事件捕获延迟由"每趟 pass（≤4h）"放宽为"≤24h"，换取配额约 80% 节省；复权因子行按 (code, 除权日) 只增不改，跳过完整股票是安全的
  - **顺带发现**：`_find_missing_dividend` 的近三年强制刷新语义在 2026-05-07 的 SQL 重构中被反转，dividend 表缺 2025/2026 分红（详见 docs/improvement_plan.md 1.3）
  - 修改文件：`src/downloaders/dividend_downloader.py`、`tests/test_adjust_factor_skip.py`（新增）
- **2026-10-02**：修复日报在拉取中途提前发出的问题
  - **问题根因**：`run_main_with_report` 把 `download_all.py` 的正常退出（`=== Download Complete ===`）当成"当天拉取完成"。实则 monitor 每趟 pass 后都会重启续拉（当日实测 5 趟），当天真正终结只有 49000 上限与 23:55 日停两个时刻——结果第一趟 pass 结束（实测 57% 进度）就发了日报，真正的终报反被去重标记拦住
  - **修复方案**：仅在真正终结时发送（`SystemExit(1)` 上限 / 正常退出且已过 23:55 日停）；pass 边界正常退出不发；0:00 兜底不变
  - 修改文件：`src/utils/helpers.py`、`tests/test_completion_report.py`
- **2026-10-01**：日报改为数据拉取完成即发
  - **行为变更**：拉取任务完成（全部更新 / 49000 请求上限 / 日停 23:55 / 手动运行）时立即发送日报，不再等到 0:00
  - **完成原因**：正文信息卡新增「完成原因」行（数据拉取完成/达到每日停止时间/达到每日请求上限），标签「昨日已使用请求次数」改为「当日已使用请求次数」
  - **一天一封**：`data/.report_sent_<日期>` 标记去重，先到先得；发送失败不写标记
  - **兜底保证**：崩溃/被强杀/整日宕机等无法即时发信的情况，由 0:00 cron 以 `--if-needed` 补发（检查昨日标记），最迟次日 0:00 必达
  - **新参数**：`daily_report.py --if-needed --date YYYY-MM-DD --reason 文本`
  - 修改文件：`scripts/daily_report.py`、`scripts/download_all.py`、`scripts/update_daily.py`、`src/utils/helpers.py`、`tests/test_daily_report_trigger.py`（新增）、`tests/test_completion_report.py`（新增）
- **2026-10-01**：修复百度网盘 token 过期导致备份失败（errno -6）
  - **问题根因**：`backup_to_baidu.py` 直接读取 `~/.bypy/bypy.json` 的 `access_token`，无过期检查。access_token 有效期 30 天，过期后 precreate 返回 `errno: -6`，每周定时备份静默失败（只能靠新通知邮件发现）
  - **修复方案**：
    - **主动刷新**：`load_token()` 按 token 文件 mtime + `expires_in`（提前 1 天余量）判断过期，过期即调百度 OAuth `refresh_token` 流程刷新（refresh_token 有效期 10 年）
    - **被动兜底**：precreate 返回 `errno -6/31045`（token 失效）时自动刷新并重试一次，防时钟漂移
    - **轮转持久化**：每次刷新响应含新的一次性 refresh_token，完整写回 `~/.bypy/bypy.json`（0600）
    - **凭据约束**：刷新必须用签发 app（bypy 内置 app）的凭据，支持 `BAIDU_API_KEY/BAIDU_API_SECRET` 覆盖；刷新失败明确提示 `python -m bypy info` 重新授权
    - **死配置清理**：删除无人引用的 `.baidu_token.json`；`.env.example` 注明 `BAIDU_APP_*` 与 token 刷新无关
  - 修改文件：`scripts/backup_to_baidu.py`、`tests/test_baidu_token.py`（新增）、`.env.example`
- **2026-10-01**：新增百度网盘备份结果邮件通知
  - **新增功能**：每次备份（成功/失败）结束后向 `EMAIL_RECEIVER` 发送一封纯文本通知邮件，主题格式 `证券数据baostock百度云备份结果-YYYY年MM月DD日`（成功失败同主题，正文首行区分）
  - **成功正文**：备份时间、归档文件、归档大小、远端路径、总耗时、保留/清理备份数；**失败正文**：失败阶段（初始化/打包/上传）、错误信息、日志位置 `logs/backup.log`
  - **公共模块**：`src/utils/email_notifier.py`（从 `daily_report.py` 提炼 `load_dotenv` / `load_email_config` / `send_email`），`daily_report.py` 同步迁移，邮件主题/正文/收发件人不变
  - **配置**：`config.yaml` 新增 `email.backup_notify` 开关（与日报 `email.enabled` 互不影响）；发信失败仅记 warning，不改变备份退出码；新增 `--no-email` 参数支持静默试跑
  - 修改文件：`src/utils/email_notifier.py`（新增）、`scripts/backup_to_baidu.py`、`scripts/daily_report.py`、`config.yaml`、`.env.example`、`tests/test_email_notifier.py`（新增）、`tests/test_daily_report_email.py`（新增）、`tests/test_backup_notify.py`（新增）
- **2026-08-21**：修复日报邮件业绩快报预估逻辑不准确问题
  - **问题根因**：日报邮件中 `performance_express`（业绩快报）的预估逻辑基于"每只股票从 max(2003, IPO年份) 到当前年份每年 1 条记录"的理论最大值，但实际上并非所有公司都会发布业绩快报，导致预估总量偏高（75,861 条），进度显示只有 40.1%
  - **修复方案**：将预估逻辑改为基于实际数据模式——查询数据库中已下载股票的平均记录数，乘以总股票数。新预估 34,623 条，与实际数据 30,432 条更匹配（87.9%）
  - **附带优化**：`forecast_report`（业绩预告）采用相同逻辑，预估从 ~75,861 修正为 120,662 条（实际 119,790 条，99.3%）
  - 修改文件：`scripts/daily_report.py`
- **2026-08-12**：新增百度网盘自动备份功能
  - **新增功能**：`scripts/backup_to_baidu.py` 百度网盘备份脚本，自动压缩数据库并上传至百度网盘
  - **功能特性**：
    - 使用 bypy 授权令牌，直接调用百度网盘 API（precreate → 分片上传 → create 三步流程）
    - 流式压缩和分片上传（4MB/chunk），避免大文件 OOM
    - 自动清理旧备份，默认保留最近 7 份
    - 支持 `--keep` 和 `--data-dir` 命令行参数
  - **定时备份**：`scripts/setup_backup_cron.sh` 一键配置 crontab，默认每周日 14:00 执行
  - **依赖更新**：`pyproject.toml` 新增 `requests`、`python-dotenv`、`qrcode[pil]` 依赖
  - 新增文件：`scripts/backup_to_baidu.py`、`scripts/setup_backup_cron.sh`
  - 修改文件：`.env.example`、`.gitignore`、`pyproject.toml`、`uv.lock`
- **2026-08-05**：修复数据全部最新时下载器关闭崩溃（WAL checkpoint 锁）
  - **问题根因**：`_find_missing_quarters` / `_find_missing_dividend` 用 `executemany INSERT` 向临时表写入候选集，Python sqlite3 隐式开启事务，随后 LEFT JOIN 主表在该事务内持有 WAL 读快照。当数据全部已存在、提前返回且后续没有任何 commit 时，遗留事务导致 `close()` 中的 `PRAGMA wal_checkpoint(TRUNCATE)` 抛出 `database table is locked`，连接和 baostock 会话同时泄漏。冒烟测试阶段 7（财务数据）稳定复现；`download_all.py` 在数据齐全的重跑场景下会在 Phase 9 崩溃，中断后续 Phase 10/11
  - **修复方案**：
    - `_find_missing_quarters` / `_find_missing_dividend` 末尾显式 `rollback()` 关闭隐式事务
    - `BaseDownloader.close()` 改为异常安全：checkpoint 失败仅告警，仍关闭连接并登出（checkpoint 失败不丢数据，WAL 稍后仍会被回收）
  - **测试基建**：
    - `pyproject.toml` 限定 pytest 收集范围为 `test_*.py`，避免 `smoke_test.py` / `integration_test.py` 等联网写库的手工脚本（匹配 `*_test.py` 通配符）被 `pytest` 误收集执行
    - 新增 `tests/test_close_checkpoint.py` 回归测试（5 例），未修复代码下其中 4 例可精确复现原错误
  - 修改文件：`src/downloaders/financial_downloader.py`、`src/downloaders/dividend_downloader.py`、`src/downloaders/base.py`、`pyproject.toml`、`tests/test_close_checkpoint.py`（新增）
- **2026-08-05**：修复完整性校验 L6 指数空洞误报
  - **问题根因**：`check_data_integrity.py` 的 L6 层级对所有指数统一按 2006-01-01 起算期望数据，而创业板指（sz.399006）2010-06-01 才发布，发布前的交易日被误报为 1,073 天空洞，并导致 `fix_data_gaps.py` 反复尝试修复无效缺口
  - **修复方案**：L6 按每个指数真实有数据的起始日计算期望范围（创业板指取 2010-06-01），复检后误报消除
  - 修改文件：`scripts/check_data_integrity.py`
- **2026-08-05**：优化月线K线下载逻辑，减少无效 API 请求
  - **问题根因**：月线K线下载逻辑在月初前3个交易日会请求当月未完成的数据，BaoStock API 对未完成月份返回 rows=0，导致约 16,620 次无效请求（5,540 股票 × 3 复权）
  - **修复方案**：
    - **月线完成度检查（month-completion guard）**：如果目标日期仍在当前月份，则只下载到上个月最后一天，避免请求未完成的当月数据
    - **退市股票过滤**：在查询K线数据前检查股票的 `out_date`，如果股票在 `start_date` 之前已退市，则跳过查询，减少约 228 次/会话的无效请求
  - **交易日历逻辑验证**：确认现有的 `get_latest_trading_day_on_or_before()` 逻辑已正确处理周末和节假日
  - **预期效果**：每日减少约 16,848 次无效 API 请求
  - 修改文件：`scripts/update_daily.py`、`scripts/download_all.py`、`src/downloaders/kline_downloader.py`
- **2026-08-02**：文档维护
  - 更新项目结构：补充 `scripts/fix_data_gaps.py`、`scripts/count_data.py`、`scripts/insert_null_profit_records.py` 三个缺失脚本
  - 修改文件：`README.md`
- **2026-07-26**：新增数据空洞自动修复脚本
  - **新增功能**：`scripts/fix_data_gaps.py` 数据空洞自动修复脚本，读取 `data/integrity_report.json` 并自动补齐缺失数据
  - **修复范围**：
    - L3: K线日期空洞（退市股票缺失最后交易日）
    - L5: 复权因子缺失记录（109 只股票，242 条缺失）
    - L6: 指数K线空洞（sz.399006 缺失 2006-2010 年数据）
  - **使用方法**：
    ```bash
    ./start.sh check                                    # 先生成完整性报告
    .venv/bin/python scripts/fix_data_gaps.py          # 自动修复所有空洞
    .venv/bin/python scripts/fix_data_gaps.py --level 5 # 仅修复特定层级
    ```
  - **注意事项**：受 BaoStock API 每日请求限制（49,000 次），如果当日请求已达上限，脚本会提示明日再试
  - 新增文件：`scripts/fix_data_gaps.py`
- **2026-07-26**：修复数据完整性校验脚本输出缓冲问题
  - **问题根因**：`start.sh` 使用管道 (`| tee`) 捕获 Python 输出，导致 Python stdout 使用全缓冲模式。校验脚本需要执行约 16,000+ 次查询（L2 层级 5,538 股票 × 3 复权，L3 层级 5,538 股票 × 2 查询），在数据库并发写入（下载进程或 SQLite TUI 工具）时可能变慢，但用户看不到任何进度输出，误以为脚本卡死
  - **修复方案**：在 `start.sh` 的 `run()` 函数中添加 `export PYTHONUNBUFFERED=1`，禁用 Python stdout 缓冲；在 `check_data_integrity.py` 的 `run_all()` 方法中为每个校验层级添加进度输出（使用 `flush=True` 确保立即刷新）
  - 修改文件：`start.sh`、`scripts/check_data_integrity.py`
- **2026-07-26**：新增数据完整性校验功能
  - **新增功能**：`scripts/check_data_integrity.py` 数据完整性校验脚本，支持 8 层校验（L1-L8）
  - **校验层级**：
    - L1: 基础表完整性（trade_dates、stock_basic、行业分类、指数成分股）
    - L2: K线覆盖率（日/周/月线，3种复权分别统计）
    - L3: K线日期连续性（空洞检测 + 最新数据截止日检查）
    - L4: 财务数据覆盖率（6表 + 六表一致性）
    - L5: 分红与复权因子匹配
    - L6: 指数K线空洞检测
    - L7: 宏观数据校验
    - L8: 数据质量（价格、成交量、涨跌幅异常）
  - **输出报告**：生成 JSON 和文字两份报告（`data/integrity_report.json` 和 `data/integrity_report.txt`）
  - **命令行支持**：`./start.sh check` 命令，支持 `--code`、`--level`、`--date` 参数
  - **设计文档**：`docs/data_integrity_check_plan.md` 完整校验方案设计
  - 新增文件：`scripts/check_data_integrity.py`、`docs/data_integrity_check_plan.md`
  - 修改文件：`start.sh`、`README.md`
- **2026-07-20**：修复监控脚本活跃度检测失效问题
  - **问题根因**：监控脚本使用 `find` 查找最近修改的日志文件来检测进程活跃度，但 `monitor_baostock.log` 本身也在 `logs/` 目录下且每 10 分钟更新一次。导致 `latest_log` 总是指向监控日志而非下载进程日志，活跃度检测形同虚设。2026-07-20 07:50 启动的下载进程在 09:05 卡死（2.5 小时无日志输出），监控一直报"正常"
  - **修复方案**：`find` 命令排除监控相关日志文件（`monitor_baostock.log`、`cron_*.log`、`kill_baostock.log`），确保只检查下载进程的日志文件
  - 修改文件：`scripts/monitor_baostock.sh`
- **2026-07-16**：修复复权因子下载器 (`download_adjust_factor`) 死循环问题
  - **问题根因**：2026-07-15 修复分红下载器死循环时，遗漏了同一文件中的 `download_adjust_factor()` 方法。该方法仍使用 `_api_call()` 而非 `query_with_retry()`，当 BaoStock 会话过期时同样会陷入死循环（CPU 空转、网络 I/O 冻结、无日志输出）
  - **修复方案**：将 `_api_call()` 改为 `query_with_retry()`，并添加 `RuntimeError` 异常捕获，跳过查询失败的股票继续下载。与 `download_dividend()` 保持一致的容错模式
  - 修改文件：`src/downloaders/dividend_downloader.py`
- **2026-07-16**：监控脚本增加进程活跃度检测，自动重启卡死进程
  - **问题根因**：监控脚本仅检查进程是否存在（`pgrep`），不检查进程是否还在工作。当进程卡死时 PID 仍在，监控误判为"正常"，导致从 08:44 到 09:20 长达 36 分钟未触发重启
  - **修复方案**：
    - 新增 `check_process_activity()` 函数：检查日志文件最后修改时间，超过 15 分钟未更新则判定为卡死
    - 新增 `graceful_kill_download()` 函数：先发送 SIGINT 让进程保存 checkpoint，等待最多 10 秒，超时才强制 kill -9
    - 调整主逻辑优先级：先检查请求上限（达到 49000 则不重启），再检查进程活跃度
  - 修改文件：`scripts/monitor_baostock.sh`
- **2026-07-15**：修复分红数据下载器死循环问题
  - **问题根因**：分红下载器使用 `_api_call()` 而非 `query_with_retry()`，当 BaoStock 会话过期时无法自动重登录，导致 `fetch_all_rows()` 陷入死循环（CPU 100%，32 分钟无进展）
  - **修复方案**：
    - 分红下载器改用 `query_with_retry()`，获得会话错误检测和自动重登录能力（最多 3 次重试，指数退避）
    - `fetch_all_rows()` 添加 `max_rows` 安全限制（默认 100,000 行），防止任何情况下无限循环
  - 修改文件：`src/downloaders/dividend_downloader.py`、`src/utils/helpers.py`
- **2026-07-13**：修复分红数据表 PRIMARY KEY 冲突导致 ~15K 次空请求
  - **问题根因**：`dividend` 表主键为 `(code, divid_operate_date, year_type)`，不含 `year`。占位记录统一使用 `divid_operate_date = '9999-01-01'`，导致同一 `(code, year_type)` 下不同年份的占位互相覆盖。`_find_missing_dividend` 的 LEFT JOIN 按 `(code, year, year_type)` 匹配，只能匹配到最后写入的那一年，其他年份被判定为"缺失"→ 重复查询 → rows=0。每只股票约 18 年 × 2 year_type = 36 次空请求，5,200 只股票 × 3 = ~15,000 次
  - **修复方案**：将 `dividend` 表 PRIMARY KEY 改为 `(code, divid_operate_date, year, year_type)`，使每个 `(code, year, year_type)` 组合可独立存储占位记录。迁移逻辑直接删除旧表重建空表（旧占位数据已因覆盖丢失，无法恢复）
  - 修改文件：`src/db_manager.py`
- **2026-07-08**：修复公司报告下载器崩溃问题 + 性能优化
  - **问题根因**：BaoStock 服务端返回的 `sh.600217` (南京高科) 业绩预告数据包含未转义的中文引号（`"非典"`），导致 JSON 解析失败。`query_forecast_report` 未捕获 `RuntimeError`，3 次重试后抛出异常导致整个下载进程崩溃。监控脚本每 10 分钟重启，形成 13 次连续崩溃循环，浪费约 14,000 次 API 请求
  - **修复方案**：在 `download_performance_express` 和 `download_forecast_report` 方法中捕获 `RuntimeError`，单只股票查询失败时跳过并记录警告，不再让整个进程崩溃
  - **性能优化**：缩短下载休眠参数，提升下载速度
    - `FINANCIAL_SLEEP`: 0.5s → 0.25s（财务数据下载提速 ~50%）
    - `LOGIN_REFRESH_INTERVAL`: 900s → 540s（主动刷新，避免被动断线浪费 7s）
    - `batch_sleep`: 2s → 1s（批次间休眠减半）
  - 修改文件：`src/downloaders/report_downloader.py`、`src/config.py`、`config.yaml`
- **2026-07-06**：优化下载器减少无效 API 请求
  - **财务数据下载器添加退市日期过滤**：通过查询 `stock_basic` 表的退市日期，跳过已退市股票在退市后的无效季度查询。新增 `get_stock_out_dates()` 方法和 `QUARTER_PERIOD_END` 常量，根据退市日期与季度截止日期比较，避免查询不可能存在的历史财务数据
  - **公司报告下载器添加 7 天负缓存机制**：新增 `_get_recently_queried_codes()` 方法，查询最近 7 天内已查询过的股票代码并跳过，减少业绩预告和业绩快报的重复查询。适用于增量更新场景，避免短期内重复拉取相同数据
  - 修改文件：`src/downloaders/financial_downloader.py`、`src/downloaders/report_downloader.py`
- **2026-07-05**：修复日报邮件 API 请求统计不准确问题
  - **问题根因**：`parse_api_request_log()` 函数只读取最新修改的一个日志文件，而一天内可能有多个下载会话（多个日志文件）。例如 7 月 4 日有 3 个下载会话，总计 48,941 次 API 请求，但日报只显示最后一次会话的 2,407 次
  - **修复方案**：
    - 修改 `parse_api_request_log()` 函数，接受 `target_date` 参数（格式：YYYYMMDD，默认为昨天）
    - 自动查找该日期的所有日志文件（如 `20260704_*.log`）
    - 汇总所有文件的 API 请求统计，返回新增字段：`log_files`（日志文件列表）、`session_count`（会话数）
    - 更新 `build_api_analysis_section()` 函数，显示多个日志文件信息和下载会话数
    - 在 `main()` 函数中使用 `report_date` 作为参数调用 `parse_api_request_log()`，确保数据一致性
  - 修改文件：`scripts/daily_report.py`
- **2026-07-03**：修复财务数据下载器查询未发布季度导致 ~27K 次空请求
  - **问题根因**：财务数据下载器仅跳过当前季度，未考虑上一季度的财务报告仍在发布窗口期（Q2 中报截止 8/31、Q3 截止 10/31 等）。7 月初运行时，Q2 数据大部分公司尚未发布，BaoStock API 返回 rows=0，导致 6 个财务表 × ~4,500 只股票 = ~27,000 次空请求
  - **修复方案**：在跳过当前季度的基础上，增加跳过上一季度的逻辑（`quarter in (current_quarter, current_quarter - 1)`），避免查询尚在发布窗口期的财务报告
  - 修改文件：`src/downloaders/financial_downloader.py`、`tests/test_financial_skip_logic.py`
- **2026-06-27**：修复周线 K 线未完成周重复下载导致 ~16K 次空请求
  - **问题根因**：周线下载仅用 7 天间隔判断是否触发，未检查 target_date 所在自然周是否已结束。当 cron 在周五凌晨运行（target=周四），请求范围覆盖未完成的当周，BaoStock 对不完整周返回 rows=0，导致 5534 股票 × 3 复权 = 16,602 次空请求
  - **修复方案**：在 `should_update_weekly` 通过后增加**周完成守卫**（week-completion guard），计算 target_date 所在自然周的周五，若周五尚未到达则跳过下载
  - 修改文件：`scripts/download_all.py`、`scripts/update_daily.py`
- **2026-06-18**：新增服务器连通性监控机制
  - **自动监控**：每 10 分钟检测 BaoStock 服务器连通性（3 次确认，间隔 30 秒）
  - **自动恢复**：服务器不可用时终止下载，恢复后自动重启 `./start.sh full`
  - **事件记录**：记录服务器中断、进程终止、恢复、重启等事件
  - **邮件展示**：日报邮件新增"服务器连通性监控"板块，展示事件时间线
  - **关闭窗口**：23:55~00:05 期间监控脚本不干预，避免与定时停止/启动冲突
  - 新增 `scripts/monitor_baostock.sh` 监控脚本
  - 新增 `data/monitor_events.json` 事件记录文件
  - 修改 `scripts/daily_report.py` 读取并展示监控事件
  - Cron 变更：移除 0:05 固定启动，由监控脚本在 0:10 首次运行时启动
- **2026-06-14**：新增每日定时停止功能
  - **定时退出机制**：当时间到达 23:55 时，自动保存数据并结束程序运行
  - 新增 `DAILY_SHUTDOWN_TIME` 常量配置（`src/config.py`）
  - 新增 `is_past_shutdown_time()` 函数，在 `ensure_login()` 中检查时间
  - 到达停止时间时：设置 `_interrupted` 标志、刷写数据到数据库、保存断点
  - 支持断点续传，下次运行可从停止处继续
  - 修改文件：`src/config.py`、`src/downloaders/base.py`、`scripts/download_all.py`、`scripts/update_daily.py`
- **2026-06-13**：优化下载性能，减少无效 API 请求
  - **缩短会话刷新间隔**：`LOGIN_REFRESH_INTERVAL` 从 1800 秒（30 分钟）降至 900 秒（15 分钟），减少 BaoStock 服务端会话过期导致的 "用户未登录" 错误和重试浪费
  - **K 线下载器添加 IPO 日期过滤**：每只股票从 IPO 日期开始拉取 K 线数据，避免新上市股票的 pre-IPO 空请求
  - 新增 `BaseDownloader.get_stock_ipo_dates()` 方法，供 K 线下载器复用
  - 修改文件：`src/config.py`、`src/downloaders/base.py`、`src/downloaders/kline_downloader.py`
- **2026-06-09**：优化 BaoStock 会话重连逻辑，解决长时间运行后下载变慢问题
  - **问题根因**：BaoStock API 会话在长时间运行后失效，返回"用户未登录"错误，但原代码未检测此错误，导致每条请求都失败重试 3 次（每次等待 2→4→8 秒），速度降低 3 倍以上
  - **修复方案**：在 `query_with_retry()` 中增加 `"未登录"` 关键词检测，检测到后等待 2 秒立即重新登录，跳过无效的重试退避
  - 修改文件：`src/downloaders/base.py`
- **2026-05-23**：修复 `download_all.py` 周线/月线无条件下载导致 API 额度耗尽
  - 将周线/月线按需下载逻辑同步到全量下载脚本，避免 cron 任务浪费 ~32K 次 API 请求
- **2026-05-22**：优化增量更新策略，减少无效 API 请求
  - **周线/月线按需下载**：周线从"每天下载"改为"跨周才下载（≥7天）"，月线从"每天下载"改为"每月前3个交易日才下载"
  - 每天节省约 ~30K 次无效 API 请求（5528 股票 × 3 复权 × 2 类型）
  - 新增 `DBManager.get_trading_days_in_range()` 方法
- **2026-05-16**：发布 V2.1.0
  - **新增调度方案设计**：完成数据拉取任务调度器详细设计文档（MD + HTML）
    - 基于数据库表/数据种类的任务配置
    - 支持时间窗口、API 配额分配、优先级排序
    - 新增 4 张调度表设计（scheduler_tasks / scheduler_runs / scheduler_task_runs / quota_allocation）
    - 新增 `start.sh scheduled` 命令规划
- **2026-05-07**：发布 v2.0，包含多项修复与重构
  - **bug 修复**：
    - 修复日报指数 K 线估算错误（周线/月线多乘 3 倍复权因子）
    - 修复 `download_minute_kline()` 传递不存在 `end_date` 参数导致 `TypeError` 的 bug
    - 修复 `ReportDownloader` 去重逻辑阻止增量更新的问题
    - 修复 `_api_call` 未调用 `ensure_login()` 导致会话超时后静默失败的问题
    - 添加 `stock_industry` 迁移数据丢弃前的 warning 日志
  - **性能优化**：
    - 分红和财务下载器的存在性检查从全表扫描改为 SQL 临时表 + LEFT JOIN，避免将 20 万+行加载到内存
    - 添加 32 个单元测试覆盖 `helpers.py` 全部纯函数
  - **代码重构**：
    - 提取 `BaseDownloader.get_stock_years()` 消除 `FinancialDownloader` 和 `DividendDownloader` 的重复 IPO/退市过滤逻辑
    - 集中 139 个列名映射到 `config.py` 的 `RENAME_*` 常量，消除 8 个下载器中的重复定义
  - **安全加固**：
    - 移除 `config.yaml` 中的邮箱明文密码字段，敏感凭据仅从 `.env` 读取
    - `daily_report.py` 邮件配置全面迁移至 `.env`，不再回退到 `config.yaml`
    - `.env.example` 新增 `EMAIL_SMTP_SERVER` 和 `EMAIL_SMTP_PORT` 字段
- **2026-04-24**：
  - 新增黑名单检测脚本 (`check_blacklist.py`)
  - 新增邮件日报功能 (`daily_report.py`)
  - 新增交易日智能判断（非交易日跳过 K 线下载）
  - 新增 `.env` 敏感信息保护机制
  - 修复 API 请求计数问题（失败请求也计数）
  - 优化财务下载器日志（显示跳过数量）
- **2026-04-19**：文档维护更新，修复文档不一致问题
- **2026-04-18**：添加断点续传功能，优化下载性能
- **2026-04-15**：修复分红表主键冲突问题
- **2026-04-10**：添加数据完整性校验功能

## 📄 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献指南

欢迎提交Issue和Pull Request！在贡献之前，请阅读：
1. [改进计划](docs/improvement_plan.md) - 了解当前已知问题和改进方向
2. [执行流程](docs/执行流程.md) - 理解项目架构和执行流程

## ❓ 常见问题

**Q: 下载过程中断怎么办？**
A: 项目支持断点续传，重新运行相同命令会自动从断点处继续下载。

**Q: 如何只更新最近的数据？**
A: 使用 `./start.sh update` 进行每日增量更新。

**Q: 数据库文件太大怎么办？**
A: 可以使用 `./clean_data.sh` 清理不需要的历史数据。

**Q: 如何查看下载进度？**
A: 使用 `./start.sh status` 查看数据库状态，或查看日志文件。

---
*最后更新：2026 年 10 月 3 日*

<!-- 测试 Gitee → GitHub 镜像同步 -->
