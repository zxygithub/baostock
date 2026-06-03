# 空结果请求 (rows=0) 分析报告

> 分析日期：2026-06-03
> 日志文件：`logs/20260603_000501.log`
> 运行脚本：`start.sh full`（cron 每天 00:05 触发）

---

## 一、总览

| 指标 | 数值 |
|------|------|
| 空结果请求 (rows=0) | **16,745** |
| 任务最终状态 | FAILED (exit 1) |

### 空请求分类

| 类型 | API 函数 | rows=0 次数 | 占比 |
|------|---------|------------|------|
| 月线 K 线 | query_history_k_data_plus (frequency=m) | **16,596** | 99.1% |
| 运营数据 | query_operation_data | 78 | 0.5% |
| 增长数据 | query_growth_data | 71 | 0.4% |
| **合计** | | **16,745** | 100% |

---

## 二、根因分析：月线 K 线空请求（16,596 次）

### 触发时间线

| 日期 | latest_monthly | should_update | monthly_start | kline_end_date | 结果 |
|------|---|---|---|---|---|
| 6/1 | 2026-04-30 | False（18个交易日） | — | — | 跳过 ✅ |
| 6/2 | 2026-04-30 | True（第1个交易日） | 2026-05-01 | 2026-06-01 | 下载 5208 rows ✅ |
| **6/3** | **2026-05-29** | **True（第2个交易日）** | **2026-05-30** | **2026-06-02** | **全部 rows=0** ❌ |

### 根本原因

6月2日成功下载了5月月线后，`latest_monthly` 更新为 `2026-05-29`。6月3日仍满足月初 `trading_days_so_far <= 3` 条件，触发月线下载：

- `monthly_start = 2026-05-30`（latest_monthly + 1天）
- `kline_end_date = 2026-06-02`
- 请求范围 `2026-05-30 → 2026-06-02` 不覆盖任何**已完成月份**
  - 5月最后一个交易日是29日，30日不在范围内
  - 6月尚未结束，无月线数据
- 每只股票 × 3 个 adjustflag = ~5,532 × 3 = **16,596 次空请求**

### 影响

- 每月浪费 ~16,600 次 API 请求（月初前 2-3 天重复触发）
- 任务耗时过长，最终 FAILED (exit 1)

---

## 三、财务数据空请求（149 次）

| 类型 | rows=0 次数 | 原因 |
|------|------------|------|
| query_operation_data | 78 | 部分公司未披露特定季度运营数据 |
| query_growth_data | 71 | 次新股/科创板历史缺口 |

属于正常现象，无需优化。

---

## 四、修复方案

### 同月守卫（same-month guard）

在 `download_all.py` 和 `update_daily.py` 中，`should_update_monthly` 通过后增加检查：

如果 `monthly_start`（latest_monthly + 1天）与 `latest_monthly` 处于同一自然月，说明该月已下载完毕且下月尚未结束，跳过下载。

```python
monthly_start_dt = latest_monthly + timedelta(days=1)
monthly_start = monthly_start_dt.strftime("%Y-%m-%d")
if monthly_start_dt.month == latest_monthly.month and monthly_start_dt.year == latest_monthly.year:
    logger.info(
        f"Skipping monthly K-line: start {monthly_start} still in same month as latest data "
        f"({latest_monthly.strftime('%Y-%m-%d')}), no complete new month to fetch."
    )
elif kline_end_date >= monthly_start:
    # 正常下载流程
```

### 逐日验证

| 日期 | latest_monthly | monthly_start | 同月? | 行为 |
|------|---|---|---|---|
| 6/1 | 4/30 | — (should_update=False) | — | 跳过 ✅ |
| 6/2 | 4/30 | **5/1** | 5月≠4月 | 下载 ✅ |
| 6/3 | 5/29 | **5/30** | **5月=5月** | **跳过** ✅ |
| 6/4 | 5/29 | 5/30 | 5月=5月 | 跳过 ✅ |
| 月末边界 | 1/31 | 2/1 | 2月≠1月 | 下载 ✅ |
| 闰年边界 | 2/29 | 3/1 | 3月≠2月 | 下载 ✅ |
| 跨年边界 | 12/31 | 1/1 | 1月≠12月 | 下载 ✅ |

### 效果

每月仅触发一次有效月线下载（月初第1-3个交易日中首次拉取上月数据），之后不再重复请求，节省约 16,600 次/月 API 请求。

### 修改文件

- `scripts/download_all.py` — 全量下载同月守卫
- `scripts/update_daily.py` — 增量更新同月守卫
- `tests/test_download_all_skip_logic.py` — 新增 `TestMonthlySameMonthGuard` 测试类（7 个用例）

---

*报告生成时间：2026-06-03*
