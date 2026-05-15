# 基于 IPO 日期的数据下载优化方案

## 1. 背景与目标

### 1.1 问题

当前代码对所有股票使用统一的固定起始日期拉取数据：

| 数据类型 | 当前起始值 | 问题 |
|---------|-----------|------|
| K 线（日/周/月） | `1990-12-19` | 2020 年上市的股票也会从 1990 年开始请求，返回空数据 |
| 财务数据 | `2007` 年 | 2015 年上市的股票也会从 2007 年开始请求，返回空数据 |
| 公司报告 | `2003-01-01` | 同上 |

这些请求消耗 API 配额但返回空结果。据估算，**约 54% 的财务请求和大量 K 线请求是无效的**。

### 1.2 目标

1. **消除无效请求**：每只股票仅从其 IPO 日期开始拉取数据
2. **缩短总耗时**：全量数据从 ~55 天降至 ~26 天
3. **不遗漏**：IPO 日期之前的数据本就不存在，不会遗漏
4. **不重复**：已有数据通过 `get_last_downloaded` 机制跳过
5. **兼容退市股票**：已退市股票只拉到 `out_date`

---

## 2. 优化策略

### 2.1 核心思路

`stock_basic` 表（Phase 2 下载）已包含每只股票的 `ipo_date` 和 `out_date`。后续所有数据下载阶段，从数据库读取该信息，动态计算每只股票的起止范围。

```
Phase 2: 下载 stock_basic → 获得所有股票的 ipo_date / out_date
    ↓
Phase 7: K 线下载 → 按每只股票的 ipo_date 作为 start_date
Phase 9: 财务下载 → 按 max(2007, ipo_year) 作为 start_year
Phase 10: 公司报告 → 按 ipo_date 作为 start_date
```

### 2.2 数据范围计算规则

| 数据类型 | start 计算 | end 计算 |
|---------|-----------|----------|
| K 线 | `max(config.start_date, ipo_date)` | `out_date`（退市）或 `None`（上市中） |
| 财务 | `max(2007, ipo_year)` | 当前年份 |
| 公司报告 | `max(config.start_date, ipo_date)` | `out_date` 或 `None` |
| 分红 | IPO 后任意时间（按股票查询，API 自动返回全部） | — |

**注意**：`config.yaml` 中的 `start_date` 仍保留作为兜底值。如果某只股票的 `ipo_date` 为空或异常，则回退到配置的默认起始日期。

---

## 3. 具体修改方案

### 3.1 新增：IPO 日期查询工具方法

**文件**：`src/downloaders/base.py`

在 `BaseDownloader` 中新增方法，供所有子类复用：

```python
def get_stock_ipo_dates(self) -> dict[str, tuple[str | None, str | None]]:
    """从 stock_basic 表获取所有股票的 (ipo_date, out_date)。

    Returns:
        {code: (ipo_date, out_date), ...}
        ipo_date/out_date 为 None 表示未知或未退市
    """
    rows = self.conn.execute(
        "SELECT code, ipo_date, out_date FROM stock_basic WHERE type = 1"
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}
```

**职责**：
- 一次性从数据库读取所有股票的 IPO 信息
- 返回字典便于快速查找
- 处理 `ipo_date` 为 NULL 的情况（回退到默认值）

### 3.2 修改：K 线下载器

**文件**：`src/downloaders/kline_downloader.py`

#### 3.2.1 修改 `_download_kline_batch` 方法签名

增加 `ipo_dates` 参数，在循环中为每只股票动态计算 `actual_start`：

```python
def _download_kline_batch(
    self,
    codes: list[str],
    start_date: str,          # 全局兜底起始日期
    end_date: str | None,
    frequency: str,
    fields: str,
    table: str,
    adjustflag: int = 3,
    resume_from: str | None = None,
    ipo_dates: dict | None = None,  # 新增：{code: (ipo_date, out_date)}
) -> int:
```

#### 3.2.2 修改循环内的日期计算逻辑

**原逻辑**（第 50-51 行）：
```python
last = self.get_last_downloaded(table, code)
actual_start = max(start_date, last) if last else start_date
```

**新逻辑**：
```python
last = self.get_last_downloaded(table, code)

# 获取该股票的 IPO 日期
stock_ipo = None
stock_out = None
if ipo_dates and code in ipo_dates:
    stock_ipo, stock_out = ipo_dates[code]

# 计算实际起始日期：优先使用 IPO 日期，兜底使用配置的 start_date
effective_start = stock_ipo if stock_ipo else start_date
actual_start = max(effective_start, last) if last else effective_start

# 计算实际结束日期：已退市股票不拉超出退市日期的数据
effective_end = end_date
if stock_out:
    effective_end = min(end_date, stock_out) if end_date else stock_out
```

#### 3.2.3 修改 `download_daily_kline` 等方法

在调用 `_download_kline_batch` 前加载 IPO 信息并传入：

```python
def download_daily_kline(
    self,
    codes: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    if start_date is None:
        start_date = get_kline_start_date("daily")

    # 加载 IPO 信息
    ipo_dates = self.get_stock_ipo_dates()
    self.logger.info(f"Loaded IPO dates for {len(ipo_dates)} stocks")

    total_rows = 0
    for adjustflag in [1, 2, 3]:
        self.logger.info(f"Downloading daily K-line (adjustflag={adjustflag})...")
        resume = self._get_resume_code("all_stock_daily", adjustflag, codes)
        count = self._download_kline_batch(
            codes, start_date, end_date, "d",
            DAILY_KLINE_FIELDS, "all_stock_daily",
            adjustflag, resume, ipo_dates=ipo_dates,  # 传入 IPO 信息
        )
        ...
```

**周线、月线、分钟线**同理修改。

### 3.3 修改：财务数据下载器

**文件**：`src/downloaders/financial_downloader.py`

#### 3.3.1 修改 `_download_quarterly_data` 方法

**原逻辑**（第 38-51 行）：
```python
for code in codes:
    for year in range(start_year, end_year + 1):
        for quarter in quarters:
            if (code, year, quarter) not in existing:
                tasks.append((code, year, quarter))
```

**新逻辑**：
```python
# 在方法开头加载 IPO 信息
ipo_dates = self.get_stock_ipo_dates()

for code in codes:
    # 获取该股票的 IPO 年份
    stock_ipo_year = start_year  # 默认使用配置的起始年
    if code in ipo_dates:
        ipo_date, _ = ipo_dates[code]
        if ipo_date:
            try:
                stock_ipo_year = max(start_year, int(ipo_date[:4]))
            except (ValueError, IndexError):
                stock_ipo_year = start_year  # 解析失败则回退

    # 从 IPO 年份开始遍历，而非统一从 start_year
    for year in range(stock_ipo_year, end_year + 1):
        for quarter in quarters:
            if (code, year, quarter) not in existing:
                tasks.append((code, year, quarter))
```

### 3.4 修改：公司报告下载器

**文件**：`src/downloaders/report_downloader.py`

需要先查看当前实现：

```python
# 类似 K 线的修改方式
# 在循环中为每只股票计算 actual_start = max(config_start_date, ipo_date)
```

### 3.5 修改：分红下载器

**文件**：`src/downloaders/dividend_downloader.py`

分红数据按股票查询（`query_dividend_data(code)`），API 返回该股票的全部历史分红记录。因此**不需要修改**，每只股票 1 次请求，天然精准。

---

## 4. 不遗漏、不重复的保证机制

### 4.1 不遗漏

| 场景 | 保证方式 |
|------|---------|
| IPO 日期为空 | 回退到 `config.yaml` 中的默认 `start_date` |
| IPO 日期解析失败 | 同上，回退到默认值 |
| 新上市股票 | `stock_basic` 包含最新上市信息（Phase 2 每次全量刷新） |
| 历史数据已存在 | `get_last_downloaded` 从已有数据的最大日期之后开始 |

### 4.2 不重复

| 场景 | 保证方式 |
|------|---------|
| 已有数据 | `get_last_downloaded()` 查询该股票在表中的 `MAX(date)`，从该日期之后开始 |
| 断点续传 | `_get_resume_code()` 从上次中断的股票之后继续 |
| 财务数据 | `_get_existing_quarters()` 检查 `(code, year, quarter)` 是否已存在 |
| 数据库写入 | 使用 `INSERT OR REPLACE`（upsert），即使重复请求也不会产生重复行 |

### 4.3 边界情况处理

| 边界情况 | 处理方式 |
|---------|---------|
| 退市股票 | `out_date` 不为空时，`effective_end = out_date`，不拉退市后数据 |
| IPO 日期晚于 config.start_date | `max(start_date, ipo_date)` 确保取较晚者 |
| IPO 日期早于 config.start_date | 同上，取较晚者（如某股票 1985 年上市，仍从 1990-12-19 开始） |
| 同一天上市多只股票 | 无影响，每只股票独立处理 |

---

## 5. 预期效果

### 5.1 API 请求数对比

| 模块 | 优化前 | 优化后 | 减少 |
|------|--------|--------|------|
| K 线（日/周/月） | 49,050 | 49,050 | 0（K 线本身每股票 1 次请求） |
| 财务数据 | 2,616,000 | ~1,200,000 | **~54%** |
| 公司报告 | ~10,900 | ~8,000 | **~27%** |
| **总计** | **~2,680,000** | **~1,290,000** | **~52%** |

### 5.2 时间对比

| 配置 | 优化前 | 优化后 |
|------|--------|--------|
| 全量数据（49,000 次/天） | ~55 天 | **~26 天** |
| 仅 K 线 | ~1 天 | ~1 天（不变） |

### 5.3 增量更新不受影响

每日增量更新只拉最新交易日数据，与 IPO 日期无关，保持 ~16,350 次/天，仍可在 1 天内完成。

---

## 6. 实施步骤

### Step 1：`base.py` 新增 `get_stock_ipo_dates()` 方法
- 添加方法，从 `stock_basic` 读取 IPO 信息
- 单元测试：验证返回值格式正确

### Step 2：`kline_downloader.py` 修改
- 修改 `_download_kline_batch` 接受 `ipo_dates` 参数
- 修改 `download_daily_kline`、`download_weekly_kline`、`download_monthly_kline` 加载并传入 IPO 信息
- 测试：验证新上市股票从 IPO 日期开始拉取

### Step 3：`financial_downloader.py` 修改
- 修改 `_download_quarterly_data` 按 IPO 年份过滤
- 测试：验证 2015 年上市的股票不从 2007 年开始请求

### Step 4：`report_downloader.py` 修改
- 类似 K 线的修改方式

### Step 5：验证
- 使用少量股票（如 10 只）测试完整流程
- 对比优化前后的请求日志，确认空请求消除
- 验证数据完整性：抽样检查 IPO 前后的数据记录

---

## 7. 风险提示

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| `stock_basic` 中 `ipo_date` 为空 | 回退到默认日期，不产生问题 | 兜底逻辑已覆盖 |
| `stock_basic` 数据不准确 | 可能遗漏极少量数据 | BaoStock 的 IPO 数据来自交易所，可信度高 |
| 代码修改引入 bug | 下载中断或数据错误 | 逐步修改、每步测试、保留断点续传 |

---

## 8. 后续优化方向（本方案范围外）

- [ ] 周线/月线从日线聚合生成，减少 API 请求
- [ ] 财务数据按年批量查询（如果 BaoStock 支持）
- [ ] 增加请求配额安全熔断机制（参考 `docs/optimization_plan.md`）
- [ ] 支持多线程/多进程并发下载（需评估 BaoStock 限制）

---

*文档最后更新：2026年5月16日（维护检查，内容未变更）*
