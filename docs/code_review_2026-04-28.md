# 全代码逻辑审查报告

> **日期**: 2026-04-28  
> **审查范围**: 27 个 Python 文件，约 5,200 行代码  
> **项目**: BaoStock 数据下载器  

---

## 🔴 严重 Bug（会导致数据损坏或功能错误）

### 1. `src/downloaders/base.py` — `_increment_request_count()` 每次调用都跑 `migrate_schema()`

**文件**: `src/downloaders/base.py`  
**位置**: 第 59-74 行  

```python
def _increment_request_count(self):
    from src.db_manager import DBManager
    db = DBManager(str(self.db_path))
    db.migrate_schema()   # ← 每次 +1 都跑完整迁移！
    new_count = db.increment_request_count(1)
```

**问题**: `migrate_schema()` 会检查所有 30+ 张表的列是否缺失，执行多次 `PRAGMA table_info`。一个全量下载会有 **上万次** API 调用，这意味着 `migrate_schema()` 被调用了上万次——严重浪费 IO 和 CPU。

**影响**: 全量下载时性能显著下降，每次 API 请求后都执行一次不必要的完整 schema 检查。

**修复建议**: 采用 **方案C** — 直接执行裸 SQL `INSERT/UPDATE`，不通过 `DBManager`，从而彻底避免 `migrate_schema()` 的调用。

**已选方案（方案C）实现**:
```python
def _increment_request_count(self):
    """Increment today's API request count by 1, using direct SQL."""
    from datetime import date
    import sqlite3

    today = date.today().isoformat()
    conn = sqlite3.connect(str(self.db_path))
    conn.execute(
        "INSERT INTO request_count (date, count) VALUES (?, 1) "
        "ON CONFLICT(date) DO UPDATE SET count = count + 1",
    )
    conn.commit()
    # 读取并检查是否超出限制
    cursor = conn.execute("SELECT count FROM request_count WHERE date = ?", (today,))
    row = cursor.fetchone()
    new_count = row[0] if row else 0
    conn.close()

    if new_count >= self.DAILY_REQUEST_LIMIT:
        self._limit_exceeded = True
        self.logger.error(
            f"今日 API 请求已达上限 ({new_count}/{self.DAILY_REQUEST_LIMIT})，"
            f"为避免进入黑名单，程序已退出。请明日再试。"
        )
        raise SystemExit(1)
```

**方案C 优势**:
- 零 schema 检查开销，每次仅执行一条 SQL
- 不依赖 `DBManager`，无额外对象创建/销毁
- 将 INSERT+UPDATE 合并为一条语句（顺便修复了问题 8 的双写模式）

---

### 2. `src/db_manager.py` — `is_trading_day()` 类型不匹配

**文件**: `src/db_manager.py`  
**位置**: 第 671-680 行  

```python
def is_trading_day(self, date_str: str) -> bool:
    conn = self.get_connection()
    cursor = conn.execute(
        "SELECT is_trading_day FROM trade_dates WHERE calendar_date = ?",
        (date_str,)
    )
    row = cursor.fetchone()
    if row:
        return row[0] == "1"    # ← 整数 1 ≠ 字符串 "1" → 永远返回 False
    return False
```

**问题**: 列 `is_trading_day` 在表中定义为 `INTEGER`，SQLite 存储的是整数 `1`。Python 中 `1 == "1"` 是 `False`。如果这个方法被调用，**所有交易日判定都会错误地返回 `False`**。

**影响**: 当前代码中似乎没有地方直接调用此方法（主要的交易日判断用的是 SQL `WHERE is_trading_day = 1`，在 SQL 层面是正确的），但这是 public API，存在隐患。

**修复建议**:
```python
return row[0] == 1   # 或 int(row[0]) == 1
```

---

### 3. `src/db_manager.py` — `migrate_stock_industry()` 用字面量占位符覆盖数据

**文件**: `src/db_manager.py`  
**位置**: 第 784-791 行  

```python
def _migrate_stock_industry(self, conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE stock_industry RENAME TO stock_industry_old")
    self._create_stock_industry(conn)
    conn.execute("""
        INSERT INTO stock_industry (code, code_name, industry, industry_classification, update_date)
        SELECT "1", "2", "3", "4", "0" FROM stock_industry_old
    """)
    conn.execute("DROP TABLE stock_industry_old")
```

**问题**: 迁移行业分类表时，用字符串字面量 `"1"`, `"2"`, `"3"`, `"4"`, `"0"` 代替了实际列名。**所有行业数据被销毁**，替换成无意义的占位符。

**影响**: 如果此迁移已执行过，行业分类表中的数据已被不可逆地摧毁。需要重新从 API 下载 `stock_industry` 数据。

**修复建议**: 根据旧表结构的实际列名做正确映射。如果旧表的列名与新表一致：
```sql
INSERT INTO stock_industry (code, code_name, industry, industry_classification, update_date)
SELECT code, code_name, industry, industry_classification, update_date FROM stock_industry_old
```

---

## 🟠 功能 Bug（影响下载逻辑）

### 4. `src/downloaders/kline_downloader.py` — 分钟线迭代全部 3 种复权

**文件**: `src/downloaders/kline_downloader.py`  
**位置**: 第 205 行  

```python
def download_minute_kline(self, codes, frequency, start_date):
    for adjustflag in [1, 2, 3]:  # ← 分钟线只有 adjustflag=3 有效！
```

**问题**: BaoStock 分钟线数据仅支持 `adjustflag=3`（不复权）。`config.yaml` 中 `kline.minute.adjustflags` 也仅配置了 `[3]`，但代码中硬编码循环 `[1, 2, 3]`，配置未被使用。

**影响**: 每分钟频率多浪费 2 次 API 调用。全量下载约 5000 只股票 × 4 频率 × 2 = **约 40,000 次无效 API 调用**。

**修复建议**:
```python
# 从配置读取 adjustflags，或直接硬编码为 [3]
from src.config_loader import get_nested_value
adjustflags = get_nested_value(
    get_download_config(), ["kline", "minute", "adjustflags"], [3]
)
for adjustflag in adjustflags:
    ...
```

---

### 5. `scripts/update_daily.py` — 未过滤非股票类型

**文件**: `scripts/update_daily.py`  
**位置**: 第 44 行  

```python
codes = db.get_downloaded_stocks("stock_basic")
```

**问题**: `get_downloaded_stocks` 返回 `stock_basic` 表中的所有代码，包括类型 2（指数）、4（可转债）、5（ETF）。但 `config.yaml` 中配置的是 `filter: "type=1 AND status=1"`，只应下载股票。

**影响**: 每天更新时会尝试下载指数、可转债、ETF 的 K 线数据，浪费大量 API 请求，且可能收到空数据或因代码不存在而报错。

**修复建议**:
```python
# 使用 SQL 过滤
conn = sqlite3.connect(str(DB_PATH))
codes = conn.execute(
    "SELECT code FROM stock_basic WHERE type = 1 AND status = 1"
).fetchall()
codes = [row[0] for row in codes]
conn.close()
```

---

### 6. `scripts/daily_report.py` — 剩余天数计算逻辑错误

**文件**: `scripts/daily_report.py`  
**位置**: 第 291-302 行  

```python
daily_limit = conn.execute(
    "SELECT count FROM request_count WHERE date = date('now')"
).fetchone()
daily_limit = daily_limit[0] if daily_limit else 49000  # 变量名误导：存的是今日请求数
# ...
"days_remaining": round((total - (daily_limit or 0)) / 49000, 1)
```

**问题**: 
1. 变量名 `daily_limit` 实际存的是今日请求次数，不是每日限制值
2. `days_remaining` 计算公式为 `(总请求数 - 今日请求数) / 49000`，逻辑上应为 `总请求数 / 每日限制`

**影响**: 日报中的"剩余天数"显示值不正确。

**修复建议**:
```python
DAILY_LIMIT = 49000  # 或从 config 读取
days_remaining = round(total / DAILY_LIMIT, 1)
```

---

### 7. `src/downloaders/financial_downloader.py` — 内存泄漏

**文件**: `src/downloaders/financial_downloader.py`  
**位置**: 第 33 行和第 85 行  

```python
all_dfs: list[pd.DataFrame] = []   # ← 声明
# ...
all_dfs.append(df)                  # ← 不断累积，但从未被读取
```

**问题**: `all_dfs` 列表累积了全部下载的 DataFrame，但函数中从未读取它。实际使用的是 `batch_dfs`（每 500 条刷新释放）。对于几千只股票的多年度数据，`all_dfs` 会占用大量内存。

**影响**: 大数据量下载时内存持续增长，可能导致 OOM。

**修复建议**: 删除 `all_dfs` 变量，仅保留 `batch_dfs`。

---

## 🟡 性能/设计问题

### 8. `src/db_manager.py` — `increment_request_count()` 使用双写模式

**文件**: `src/db_manager.py`  
**位置**: 第 808-828 行  

```python
# 第一次写入：插入或占位（增量为 0）
conn.execute(
    "INSERT INTO request_count (date, count) VALUES (?, 0) "
    "ON CONFLICT(date) DO UPDATE SET count = count + excluded.count",
    (today,),
)
# 第二次写入：真正的增量
conn.execute(
    "UPDATE request_count SET count = count + ? WHERE date = ?",
    (n, today),
)
```

**问题**: 第一步 INSERT 的 `excluded.count` 永远是 `0`（硬编码在 VALUES 中），实际的增量由第二条 UPDATE 完成。两步可以合并成一步。

**影响**: 每次计数需要两次写操作，性能略差。

**修复建议**:
```python
conn.execute(
    "INSERT INTO request_count (date, count) VALUES (?, ?) "
    "ON CONFLICT(date) DO UPDATE SET count = count + excluded.count",
    (today, n),
)
```

---

### 9. `src/config_loader.py` — 每次函数调用都重新读取 YAML 文件

**文件**: `src/config_loader.py`  
**位置**: 各 convenience 函数  

```python
def get_batch_size() -> int:
    return get_stocks_config().get("batch_size", 200)

def get_stocks_config() -> dict[str, Any]:
    config = load_config()   # ← 每次重新读文件、解析 YAML
```

**问题**: 每个配置读取函数都独立调用 `load_config()`，无缓存。高频场景下重复 IO。

**影响**: 性能浪费，但不影响正确性。

**修复建议**: 添加模块级缓存：
```python
_config_cache: dict[str, Any] | None = None

def load_config(config_path=None):
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    # ... 读取文件 ...
    _config_cache = config
    return config
```

---

### 10. `scripts/estimate_data_volume.py` — 分钟线估算使用错误柱数

**文件**: `scripts/estimate_data_volume.py`  
**位置**: 第 184 行  

```python
total += stock_days * MINUTE_BARS_PER_DAY * MINUTE_FREQUENCIES
# MINUTE_BARS_PER_DAY = 48，但各频率柱数不同
```

**问题**: 
- 5 分钟 ≈ 48 柱/天
- 15 分钟 ≈ 16 柱/天  
- 30 分钟 ≈ 8 柱/天
- 60 分钟 ≈ 4 柱/天

统一用 48 会高估 15/30/60 分钟的数据量约 3-12 倍。

**影响**: 仅影响估算脚本输出，不影响实际下载。

---

## 🔵 代码一致性问题

### 11. `src/downloaders/kline_downloader.py` — turn 字段转换逻辑与 `helpers.py` 重复

**文件**: `src/downloaders/kline_downloader.py` 第 98-100 行 vs `src/utils/helpers.py` 第 74-85 行  

kline_downloader 中内联实现了 `convert_turn_field` 的相同逻辑：

```python
# kline_downloader.py（重复实现）
df["turn"] = df["turn"].apply(
    lambda x: 0.0 if not x or str(x).strip() == "" else float(x)
)

# helpers.py（已有通用函数）
def convert_turn_field(value: str) -> float:
    if not value or value.strip() == "":
        return 0.0
    return float(value)
```

**修复建议**: 使用已有的 `convert_turn_field` 函数。

---

### 12. `download_all.py` — `kline_end_date` 被错误地传递为 reports 的 end_date

**文件**: `scripts/download_all.py`  
**位置**: 第 177-180 行  

```python
with ReportDownloader(str(DB_PATH), logger) as dl:
    report_results = dl.download_all_reports(
        codes,
        start_date=args.start_date or get_reports_start_date(),
        end_date=args.end_date or kline_end_date,  # ← K线最晚交易日作报告截止日？
    )
```

**问题**: 报告数据不受交易日约束，用 K 线的"最晚交易日"来限制报告查询截止日期在语义上不合理。虽然实际影响很小（报告通常按日查询，范围覆盖完整即可），但概念上不正确。

**修复建议**: 使用前一天的实际日期而非交易日期：
```python
end_date = args.end_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
```

---

## 📊 总结

| 级别 | 数量 | 关键项 |
|------|------|--------|
| 🔴 数据损坏/破坏性 Bug | 3 | `migrate_stock_industry` 数据销毁、`is_trading_day` 类型错误、每 API 调用跑 `migrate_schema` |
| 🟠 功能错误 | 4 | 分钟线多余 API 调用、未过滤非股票、剩余天数计算错、内存泄漏 |
| 🟡 性能/设计 | 2 | 估算错误、重复读 YAML（注：双写模式已被问题1的方案C一并修复） |
| 🔵 一致性 | 2 | turn 重复逻辑、end_date 语义错 |

### 修复优先级建议

1. **已选定方案**: `_increment_request_count()` 采用 **方案C**（直接 SQL，不通过 DBManager）— 同时修复问题 1 和问题 8（双写模式）
2. **立即修复**: `migrate_stock_industry()` — 数据已经被销毁的话，需要重新下载行业分类数据
3. **尽快修复**: `is_trading_day()` 类型错误 — 虽然目前未被调用但随时可能引入 bug
4. **本次迭代修复**: 分钟线 adjustflag 循环、每日更新股票过滤
5. **下次迭代**: 内存泄漏、配置缓存
