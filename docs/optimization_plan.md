# 优化方案：K 线优先 & 财务降级

## 1. 背景与目标
*   **背景**：当前系统每日请求次数受限（约 4.8 万~9.9 万次），财务数据下载消耗了大量请求但数据增量极低，导致核心 K 线数据下载进度缓慢。
*   **目标**：
    1.  **K 线优先**：确保每日请求次数优先用于 K 线数据（日/周/月线）。
    2.  **财务降级**：降低财务数据下载优先级，减少无效请求。
    3.  **避免重复**：确保已有数据绝不重复请求，节省每一次 API 调用。

## 2. 优化策略

### 2.1 调整下载优先级 (`scripts/download_all.py`)
*   **现状**：K 线 (Phase 7) 在 财务 (Phase 9) 之前下载，但缺乏资源保护机制。
*   **改进**：增加**“安全熔断”**机制。
    *   **监控**：在 K 线下载完成后检查 `request_count`。
    *   **熔断**：若当日请求数已超过上限的 **85%**，则**自动跳过**后续的财务、分红、报告等低优先级数据下载。
    *   **日志**：输出明确日志 `[WARNING] API usage high, skipping low-priority downloads to save quota for K-line.`

### 2.2 优化财务数据请求逻辑 (`src/downloaders/financial_downloader.py`)
*   **现状**：代码遍历所有 `code + year + quarter` 组合检查是否存在。虽然不下载，但逻辑冗余且容易产生错觉。
*   **改进**：
    *   **精准预过滤**：在生成任务列表前，通过 SQL 查询数据库中**明确缺失**的 `(code, year, quarter)` 组合。
    *   **按需请求**：只对**真正缺失**的数据发起 API 请求。
    *   **逻辑确认**：确保 `_download_quarterly_data` 中的 `if (code, year, quarter) not in existing:` 逻辑严格生效，拦截所有已存在数据的请求。

### 2.3 确保 K 线数据增量更新 (`src/downloaders/kline_downloader.py`)
*   **现状**：代码中已有 `get_last_downloaded` 逻辑，会从数据库中该股票的最新日期之后开始下载。
*   **确认**：此逻辑是有效的，**不会重复请求已有数据**。
*   **改进**：
    *   在 `update_daily.py` 中增加日志输出，显示“跳过已下载股票”的数量，增加透明度。
    *   验证 `start_date` 计算逻辑，确保不会因日期格式问题导致重复下载。

## 3. 具体执行步骤

<!-- 暂缓执行：安全熔断机制 -->
<!--
1.  **修改 `scripts/download_all.py`**：
    *   引入 `DBManager` 检查当前请求数。
    *   在 Phase 9 (财务) 前增加判断逻辑：`if current_requests > DAILY_LIMIT * 0.85: return`。
-->

2.  **修改 `src/downloaders/financial_downloader.py`**：
    *   优化 `_get_existing_quarters` 方法，确保查询效率。
    *   在 `_download_quarterly_data` 中增加日志，打印 `Total tasks: X, Skipped (existing): Y`。

<!-- 暂不执行：关闭财务数据更新 -->
<!--
3.  **修改 `scripts/update_daily.py`**：
    *   默认**关闭**财务数据更新，或将其注释掉。
    *   仅保留 K 线更新逻辑，确保每日增量更新高效完成。
-->

## 4. 预期效果
*   **K 线进度**：每日可稳定下载约 1.5 万~2 万行 K 线数据。
*   **请求利用率**：API 请求 100% 用于有效数据获取，不再浪费在无效检查上。
*   **系统稳定性**：避免因请求超限导致的 IP 封禁或程序异常退出。
