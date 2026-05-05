# 分红与报告表无效请求修复计划

## TL;DR

> **目标**：为 dividend 和 report 表创建请求记录辅助表，避免重复请求返回空数据的组合，节省 API 配额。
> 
> **方案**：预先检查 `(code, year, year_type)` 是否已请求过，跳过历史年份的无效请求。
> 
> **受影响表**：`dividend`, `adjust_factor`, `performance_express`, `forecast_report`

---

## Context

### 问题分析

当前 `dividend_downloader.py` 和 `report_downloader.py` 存在与财务表相同的问题：
- API 返回空结果时，不写入数据库
- 下次运行时，会再次请求相同的组合
- 无效请求消耗 API 配额

**差异**：
| 对比项 | 财务表 (profit_data) | 分红表 (dividend) |
|---|---|---|
| 主键 | `(code, year, quarter)` | `(code, divid_operate_date, year_type)` |
| API 参数 | 直接对应主键 | `year` 不是主键的一部分 |
| 空壳记录 | 可插入 NULL 记录 | 无法插入（不知道 divid_operate_date） |

### 用户需求

用户提出的方案B规则：
1. 创建辅助表 `dividend_request_log` 跟踪请求记录
2. 当前年份和前一年（如2026、2025）**不跳过**，可能有新分红信息
3. 历史年份（≤2024）如果已请求过，跳过
4. 结合 IPO/退市时间，只请求股票上市后、退市前的年份

---

## TODOs

- [ ] 1. 创建辅助表 `dividend_request_log`

  **What to do**：
  - 在 `db_manager.py` 添加 `_create_dividend_request_log` 函数
  - 在 `migrate_schema` 中调用创建表
  - 表结构：`(code, year, year_type, has_data, request_time)`

  **表结构**：
  ```sql
  CREATE TABLE dividend_request_log (
      code         TEXT NOT NULL,
      year         INTEGER NOT NULL,
      year_type    TEXT NOT NULL,
      has_data     INTEGER,  -- 0=空, 1=有数据
      request_time TEXT,
      PRIMARY KEY (code, year, year_type)
  )
  ```

  **File**: `src/db_manager.py`

---

- [ ] 2. 修改 `download_dividend` 实现预检查逻辑

  **What to do**：
  - 添加 `_get_existing_dividend_requests` 方法查询辅助表
  - 获取股票 IPO/退市年份范围
  - 构建任务列表，跳过已请求的历史年份
  - 请求后记录到辅助表

  **逻辑**：
  ```python
  current_year = datetime.now().year
  skip_recent_years = {current_year, current_year - 1}
  
  for code in codes:
      ipo_y, out_y = stock_years.get(code, (start_year, end_year))
      for year in range(max(start_year, ipo_y), min(end_year, out_y) + 1):
          for year_type in ["report", "operate"]:
              if year in skip_recent_years:
                  tasks.append((code, year, year_type))
              elif (code, year, year_type) not in existing_requests:
                  tasks.append((code, year, year_type))
  ```

  **File**: `src/downloaders/dividend_downloader.py`

---

- [ ] 3. 同样修复 `download_adjust_factor`

  **What to do**：
  - 创建辅助表 `adjust_factor_request_log`
  - adjust_factor 是按 code 整体请求，不是按年份
  - 辅助表结构：`(code, has_data, request_time)`

  **File**: `src/db_manager.py`, `src/downloaders/dividend_downloader.py`

---

- [ ] 4. 修复 `report_downloader.py` 的两个方法

  **What to do**：
  - `download_performance_express`: 按 code 整体请求
  - `download_forecast_report`: 按 code 整体请求
  - 创建辅助表 `report_request_log`：(code, report_type, has_data, request_time)

  **File**: `src/db_manager.py`, `src/downloaders/report_downloader.py`

---

## Final Verification Wave

- [ ] F1. 运行下载测试，验证辅助表记录正确写入
- [ ] F2. 验证重复运行时跳过已请求的历史年份
- [ ] F3. 检查 IPO/退市时间过滤是否生效

---

## Commit Strategy

- Commit 1: 添加辅助表到 db_manager.py
- Commit 2: 修改 dividend_downloader.py
- Commit 3: 修改 report_downloader.py