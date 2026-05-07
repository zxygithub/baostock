# BaoStock 数据下载器 - 文档索引

欢迎使用 BaoStock 数据下载器文档！本文档提供了项目的完整技术文档和使用指南。

## 📚 文档目录

### 1. 入门指南
- **[项目README](../README.md)** - 项目概览、快速开始、功能特性
- **[执行流程](执行流程.md)** - 详细的项目架构和执行流程说明

### 2. 技术设计
- **[数据下载方案](data_download_plan.md)** - 数据库设计、表结构、下载策略
- **[改进计划](improvement_plan.md)** - 已知问题、改进建议和实施路线图
- **[优化方案](optimization_plan.md)** - K 线优先、财务降级优化计划

### 3. API 参考
- **[BaoStock Python API](pythonAPI.md)** - BaoStock 官方API文档（复制版）
- **[BaoStock复权因子简介](BaoStock复权因子简介.pdf)** - 复权算法说明（PDF）
- **[API 请求日志分析](api_request_log_analysis.md)** - 日志格式、统计命令、异常排查

### 4. 配置说明
- **[配置文件说明](../config.yaml)** - 下载配置参数详解
- **[数据库设计](data_download_plan.md#2-数据库设计)** - 33张表的详细结构

## 🎯 快速导航

### 新用户入门
1. 阅读 **[项目README](../README.md)** 了解项目概览
2. 查看 **[执行流程](执行流程.md)** 理解项目架构
3. 按照快速开始指南进行首次数据下载

### 开发者参考
1. 研究 **[数据下载方案](data_download_plan.md)** 了解数据库设计
2. 查看 **[改进计划](improvement_plan.md)** 了解当前开发方向
3. 参考 **[BaoStock Python API](pythonAPI.md)** 了解底层API

### 运维管理
1. 配置 **[config.yaml](../config.yaml)** 调整下载参数
2. 使用 `./start.sh` 脚本进行日常维护
3. 使用 `./clean_data.sh` 管理数据库数据

## 📊 数据库表概览

项目共设计 **33 张表**，分为以下几类：

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

## 🔧 常用命令

```bash
# 初始化数据库
./start.sh init

# 全量数据下载
./start.sh full

# 每日增量更新
./start.sh update

# 查看数据库状态
./start.sh status

# 查看日志
./start.sh logs

# 数据管理
./clean_data.sh --list      # 列出所有表
./clean_data.sh --table <表名>  # 清空特定表
```

## ⚠️ 注意事项

1. **API限制**：BaoStock API有调用频率限制，请合理配置批次大小和休眠时间
2. **数据量**：全量下载数据量较大，建议在服务器上运行
3. **网络要求**：需要稳定的网络连接，下载过程中请保持网络畅通
4. **存储空间**：全量数据预计需要 2-5GB 存储空间

## 🔄 更新日志

- **2026-05-07**：发布 v2.0，修复日报指数 K 线估算错误；移除 `config.yaml` 中的邮箱明文密码，敏感凭据仅从 `.env` 读取
- **2026-04-24**：新增黑名单检测、邮件日报、交易日智能判断
- **2026-04-19**：文档维护更新，修复文档不一致问题
- **2026-04-18**：添加断点续传功能，优化下载性能
- **2026-04-15**：修复分红表主键冲突问题
- **2026-04-10**：添加数据完整性校验功能

## 🤝 贡献与反馈

如果您发现文档中的错误或有改进建议，请：
1. 提交 Issue 报告问题
2. 提交 Pull Request 贡献改进
3. 参考 [改进计划](improvement_plan.md) 了解当前开发方向

---
*文档最后更新：2026年5月7日*
