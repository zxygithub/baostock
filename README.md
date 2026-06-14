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

## 📖 详细文档

- **[执行流程](docs/执行流程.md)** - 详细的项目架构和执行流程说明
- **[数据下载方案](docs/data_download_plan.md)** - 数据库设计和下载策略
- **[数据拉取流程](docs/download_flow.md)** - 全量/增量下载详细流程图
- **[调度方案详细设计](docs/调度方案详细设计.md)** - 任务调度器架构与配置设计
- **[改进计划](docs/improvement_plan.md)** - 已知问题和改进建议
- **[优化方案](docs/optimization_plan.md)** - K 线优先、财务降级优化计划
- **[IPO 日期优化](docs/ipo_based_download_optimization.md)** - 基于 IPO 日期的下载优化
- **[数据分析](docs/数据分析.md)** - 各表 API 拉取前置条件分析
- **[代码审查](docs/code_review_2026-04-28.md)** - 全代码逻辑审查报告
- **[API 请求日志分析](docs/api_request_log_analysis.md)** - 日志统计与异常排查指南
- **[BaoStock API](docs/pythonAPI.md)** - BaoStock官方API文档

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
│   ├── daily_report.py     # 邮件日报
│   ├── check_blacklist.py  # 黑名单检测
│   ├── analyze_latest_dates.py  # 最新日期分析
│   └── estimate_data_volume.py  # 数据量估算
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
│       ├── helpers.py      # 辅助函数
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
  daily_request_limit: 49000  # 每日 API 请求上限

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
  batch_sleep: 2                 # 批次间休眠时间（秒）

# 邮件日报开关（敏感凭据在 .env 中配置）
email:
  enabled: true
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

详细表结构见 [数据下载方案](docs/data_download_plan.md)。

## 🛡️ 新增功能（2026-04-24）

### 黑名单检测
```bash
# 检测当前 IP/账号是否被 BaoStock 列入黑名单
.venv/bin/python scripts/check_blacklist.py
```

### 邮件日报
- 每日 7:00 自动发送数据下载进度邮件
- 包含黑名单状态、请求次数、数据拉取评估表
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
*最后更新：2026 年 6 月 13 日*
