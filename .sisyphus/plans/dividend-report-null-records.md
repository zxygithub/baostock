# 分红与报告表空壳记录修复计划

## TL;DR

> **方案**：对空结果写入"空壳记录"（财务表直接写 NULL，分红表用 `9999-01-01` 占位），结合预检查跳过无效请求。
> 
> **规则**：当前年份+前一年不跳过、不写空壳；历史年份已请求则跳过；IPO前/退市后不请求。
> 
> **受影响**：`financial_downloader.py`, `dividend_downloader.py`, `report_downloader.py`

---

## Context

### 用户确认的规则

1. **当前年份和前一年（如2026、2025）→ 不跳过，不写空壳**，每次都请求（可能有新数据）
2. **历史年份 → 已有记录（含空壳）则跳过**
3. **IPO 之前 / 退市之后 → 不请求**

### 空壳记录方案

| 表 | 主键 | 空壳占位符 |
|---|---|---|
| profit_data 等6张财务表 | `(code, year, quarter)` | 直接写 NULL（year/quarter 已知） |
| dividend | `(code, divid_operate_date, year_type)` | `divid_operate_date='9999-01-01'` |
| performance_express | `(code, performance_exp_pub_date)` | `performance_exp_pub_date='9999-01-01'` |
| forecast_report | `(code, profit_forecast_exp_pub_date)` | `profit_forecast_exp_pub_date='9999-01-01'` |

---

## TODOs

- [ ] 1. 修改 `financial_downloader.py` - `_download_quarterly_data` 方法

  **What to do**：
  - 当前已有的空壳记录写入逻辑需要补充规则：当前年份和前一年不写空壳
  - IPO/退市过滤已实现（第36-55行），无需修改

  **修改点**（第95-106行附近）：
  ```python
  current_year, current_quarter = get_current_quarter()
  recent_years = {current_year, current_year - 1}  # 如 {2026, 2025}

  # ... 在循环中 ...
  rows = fetch_all_rows(rs)
  if not rows:
      # 规则: 当前年份和前一年不写空壳，历史年份才写
      if year not in recent_years:
          df = pd.DataFrame(
              [[code] + [pd.NA] * len(column_renames)],
              columns=["code"] + list(column_renames.values()),
          )
          df["year"] = year
          df["quarter"] = quarter
          batch_dfs.append(df)
      time.sleep(FINANCIAL_SLEEP)
      continue
  ```

  **File**: `src/downloaders/financial_downloader.py`

---

- [ ] 2. 修改 `dividend_downloader.py` - `download_dividend` 方法

  **What to do**：
  - 添加 `_get_existing_dividend_years` 方法查询已有 `(code, year, year_type)` 组合
  - 获取股票 IPO/退市年份范围
  - 构建任务列表，应用三条规则
  - 空结果写入空壳记录（`divid_operate_date='9999-01-01'`）

  **预检查逻辑**：
  ```python
  current_year = datetime.now().year
  recent_years = {current_year, current_year - 1}  # 2026, 2025
  
  # 从 dividend 表提取已请求的 (code, year, year_type)
  # 通过 divid_operate_date 判断（9999-01-01 或真实日期都算已请求）
  existing = self._get_existing_dividend_years()
  
  tasks = []
  for code in codes:
      ipo_y, out_y = stock_years.get(code, (start_year, end_year))
      eff_start = max(start_year, ipo_y)
      eff_end = min(end_year, out_y)
      for year in range(eff_start, eff_end + 1):
          for year_type in ["report", "operate"]:
              # 规则1: 当前年份和前一年不跳过
              if year in recent_years:
                  tasks.append((code, year, year_type))
              # 规则2: 历史年份已请求则跳过
              elif (code, year, year_type) not in existing:
                  tasks.append((code, year, year_type))
  ```

  **空壳记录写入**：
  ```python
  if not rows:
      df = pd.DataFrame(
          [[code, '9999-01-01', year, year_type]],
          columns=['code', 'divid_operate_date', 'year', 'year_type']
      )
      # 其他字段 NULL
      self.save_df(df, "dividend", if_exists="upsert")
      continue
  ```

  **File**: `src/downloaders/dividend_downloader.py`

---

- [ ] 2. 修改 `report_downloader.py` - `download_performance_express` 方法

  **What to do**：
  - 报表是按 code 整体请求，不是按年份
  - 需要不同的空壳策略

  **方案选项**：
  - A: 创建辅助表 `report_request_log(code, report_type, has_data)`
  - B: 用占位主键值写入空壳（类似 dividend）

  **report 表主键**：
  - `performance_express`: `(code, performance_exp_pub_date)`
  - `forecast_report`: `(code, profit_forecast_exp_pub_date)`

  **空壳策略**：`performance_exp_pub_date = '9999-01-01'`

  **File**: `src/downloaders/report_downloader.py`

---

- [ ] 3. 修改 `report_downloader.py` - `download_forecast_report` 方法

  **What to do**：同上，空壳 `profit_forecast_exp_pub_date = '9999-01-01'`

  **File**: `src/downloaders/report_downloader.py`

---

## 预检查方法实现

```python
def _get_existing_dividend_years(self) -> set[tuple[str, int, str]]:
    """查询 dividend 表已有的 (code, year, year_type) 组合"""
    rows = self.conn.execute("""
        SELECT code, year, year_type FROM dividend
    """).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}
```

---

## 空壳记录示例

```sql
-- dividend 空壳记录
INSERT INTO dividend (
    code, divid_operate_date, year, year_type, update_time
) VALUES (
    'sh.600000', '9999-01-01', 2007, 'report', '2026-05-05 08:00:00'
);

-- performance_express 空壳记录
INSERT INTO performance_express (
    code, performance_exp_pub_date, update_time
) VALUES (
    'sh.600000', '9999-01-01', '2026-05-05 08:00:00'
);
```

---

## Final Verification

- [ ] F1. 重复运行下载，验证历史年份被跳过
- [ ] F2. 验证当前年份+前一年每次都请求
- [ ] F3. 验证 IPO 前/退市后不请求
- [ ] F4. 查询空壳记录：`WHERE divid_operate_date = '9999-01-01'`

---

## Commit Strategy

- Commit 1: `dividend_downloader.py` 改动
- Commit 2: `report_downloader.py` 改动