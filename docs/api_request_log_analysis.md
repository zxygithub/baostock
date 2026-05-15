# API 请求日志统计分析指南

## 日志格式说明

从 2026-04-30 版本起，每次 BaoStock API 请求完成后会自动记录一行日志：

```
[API_REQ] {api函数名} | params={入参} | rows={返回行数}
```

### 示例

```
[API_REQ] query_trade_dates | params=1990-01-01 2026-12-31 | rows=12917
[API_REQ] query_stock_basic | params= | rows=8710
[API_REQ] query_history_k_data_plus | params=code=sh.600000 start=2026-04-29 end=2026-04-29 frequency=d adjustflag=1 | rows=1
[API_REQ] query_profit_data | params=code=sh.600000 year=2026 quarter=1 | rows=0
```

### 字段说明

| 字段 | 说明 |
|---|---|
| `[API_REQ]` | 统一标记，用于 grep 过滤 |
| `api函数名` | BaoStock SDK 函数名（如 `query_trade_dates`） |
| `params` | 调用时传入的全部参数（空格分隔） |
| `rows` | 实际返回的数据行数（0 表示无数据/停牌/新股） |

---

## 基础统计命令

以下命令假设日志文件在 `logs/` 目录下，根据实际路径调整。

### 1. 统计各 API 调用次数

```bash
grep '\[API_REQ\]' logs/*.log | awk -F'|' '{print $1}' | awk '{print $3}' | sort | uniq -c | sort -rn
```

**输出示例：**
```
  15600 query_history_k_data_plus
   5200 query_profit_data
   1200 query_dividend_data
      8 query_money_supply_data_month
      5 query_deposit_rate_data
```

### 2. 统计各 API 总返回行数

```bash
grep '\[API_REQ\]' logs/*.log | grep 'query_history_k_data_plus' | awk -F'rows=' '{print $2}' | paste -sd+ | bc
```

### 3. 统计今日总请求数

```bash
grep '\[API_REQ\]' logs/$(date +%Y%m%d)*.log 2>/dev/null | wc -l
```

### 4. 统计今日总返回行数

```bash
grep '\[API_REQ\]' logs/$(date +%Y%m%d)*.log 2>/dev/null | awk -F'rows=' '{sum+=$2} END {print sum}'
```

---

## 高级分析

### 5. 找出空结果请求（0 行）

这些通常是新股（上市日期晚于查询日期）、停牌或退市股票：

```bash
grep '\[API_REQ\]' logs/*.log | grep 'rows=0' | wc -l
```

查看具体是哪些股票：

```bash
grep '\[API_REQ\]' logs/*.log | grep 'rows=0' | grep 'code=' | awk -F'code=' '{print $2}' | awk '{print $1}' | sort | uniq -c | sort -rn | head -20
```

### 6. 按复权方式统计 K 线请求

```bash
grep '\[API_REQ\]' logs/*.log | grep 'query_history_k_data_plus' | grep 'adjustflag=' | awk -F'adjustflag=' '{print $2}' | awk '{print $1}' | sort | uniq -c
```

**输出示例：**
```
   5200 1    # 后复权
   5200 2    # 前复权
   5200 3    # 不复权
```

### 7. 按频率统计 K 线请求

```bash
grep '\[API_REQ\]' logs/*.log | grep 'query_history_k_data_plus' | grep 'frequency=' | awk -F'frequency=' '{print $2}' | awk '{print $1}' | sort | uniq -c
```

**输出示例：**
```
   5200 d    # 日线
   5200 w    # 周线
   5200 m    # 月线
```

### 8. 找出响应行数最多的单次请求

```bash
grep '\[API_REQ\]' logs/*.log | sort -t'=' -k4 -rn | head -10
```

### 9. 按表统计请求分布（按 Phase）

```bash
grep '\[API_REQ\]' logs/*.log | awk -F'|' '{print $1}' | awk '{print $3}' | sort | uniq -c | sort -rn
```

### 10. 计算 API 利用率（行数/请求数）

```bash
# 全量下载模式：一次请求返回多行，利用率高
# 增量更新模式：一次请求返回1行，利用率低

# 计算某次下载的总行数/总请求数
TOTAL_ROWS=$(grep '\[API_REQ\]' logs/20260430*.log | awk -F'rows=' '{sum+=$2} END {print sum}')
TOTAL_REQ=$(grep '\[API_REQ\]' logs/20260430*.log | wc -l)
echo "总行数: $TOTAL_ROWS, 总请求: $TOTAL_REQ, 利用率: $(echo "scale=2; $TOTAL_ROWS / $TOTAL_REQ" | bc) 行/请求"
```

---

## 异常排查

### 11. 找出请求失败的情况

```bash
grep -E '\[API_REQ\].*rows=0' logs/*.log | grep -v 'query_dividend_data\|query_adjust_factor\|query_performance\|query_forecast' | head -20
```

> 注意：分红、业绩预告等数据本身可能为空，需排除。

### 12. 统计重试次数

重试的请求会在日志中出现多次相同参数的记录：

```bash
grep '\[API_REQ\]' logs/*.log | awk -F'|' '{print $2}' | sort | uniq -c | sort -rn | awk '$1 > 1' | head -20
```

### 13. 检查 API 上限触发点

```bash
grep -E 'API 请求计数|API 请求已达上限|\[API_REQ\]' logs/*.log | tail -20
```

### 14. 按时间段分析请求密度

```bash
# 按分钟统计请求数，找出高峰期
grep '\[API_REQ\]' logs/*.log | awk '{print substr($1,1,16)}' | sort | uniq -c | sort -rn | head -10
```

---

## 下载效率分析

### 15. 全量 vs 增量对比

| 模式 | 请求数 | 总行数 | 行/请求 | 说明 |
|---|---|---|---|---|
| 全量下载 | ~15,600 | ~36,000,000 | ~2,300 | 一次请求返回历史全部数据 |
| 增量更新 | ~15,600 | ~15,600 | ~1 | 一次请求仅返回1天数据 |

### 16. 计算各表下载耗时

```bash
# 找出每个 API 的首次和末次请求时间
grep '\[API_REQ\].*query_history_k_data_plus' logs/20260430*.log | head -1 | awk '{print $1, $2}'
grep '\[API_REQ\].*query_history_k_data_plus' logs/20260430*.log | tail -1 | awk '{print $1, $2}'
```

### 17. 估算剩余下载时间

```bash
# 当前进度
DONE=$(grep '\[API_REQ\].*query_history_k_data_plus' logs/$(date +%Y%m%d)*.log | wc -l)
TOTAL=15600
REMAINING=$((TOTAL - DONE))
# 假设每分钟处理 200 次请求
ELAPSED_MIN=$(($(date +%s) - $(stat -c %Y logs/$(date +%Y%m%d)*.log | head -1)))
RATE=$((DONE / (ELAPSED_MIN / 60 + 1)))
ETA_MIN=$((REMAINING / RATE))
echo "已完成: $DONE/$TOTAL, 速率: $RATE 次/分, 预计剩余: $ETA_MIN 分钟"
```

---

## 自动化脚本

### 生成每日下载报告

```bash
#!/bin/bash
# daily_api_report.sh - 生成每日 API 请求统计报告

LOG_FILE=$(ls -t logs/$(date +%Y%m%d)*.log 2>/dev/null | head -1)
if [ -z "$LOG_FILE" ]; then
    echo "No log file found for today"
    exit 1
fi

echo "=== Daily API Report: $(date +%Y-%m-%d) ==="
echo ""
echo "--- Request Count by API ---"
grep '\[API_REQ\]' "$LOG_FILE" | awk -F'|' '{print $1}' | awk '{print $3}' | sort | uniq -c | sort -rn
echo ""
echo "--- Total Requests ---"
grep '\[API_REQ\]' "$LOG_FILE" | wc -l
echo ""
echo "--- Total Rows ---"
grep '\[API_REQ\]' "$LOG_FILE" | awk -F'rows=' '{sum+=$2} END {print sum}'
echo ""
echo "--- Zero-Row Requests ---"
grep '\[API_REQ\]' "$LOG_FILE" | grep 'rows=0' | wc -l
echo ""
echo "--- Retry Candidates ---"
grep '\[API_REQ\]' "$LOG_FILE" | awk -F'|' '{print $2}' | sort | uniq -c | sort -rn | awk '$1 > 1' | wc -l
```

---

## 日志文件说明

| 文件 | 说明 |
|---|---|
| `logs/YYYYMMDD_HHMMSS.log` | 单次下载会话日志 |
| `logs/cron_full_download.log` | cron 全量下载日志 |
| `logs/cron_daily_report.log` | cron 日报日志 |

---

*文档最后更新：2026年5月16日*
