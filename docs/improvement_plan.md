# BaoStock 数据下载系统改进建议

## 1. 运行中发现的问题

### 1.1 已修复问题

| 序号 | 问题 | 原因 | 修复方式 | 状态 |
|------|------|------|----------|------|
| 1 | SQLite 变量超限 | pandas `method="multi"` 批量插入超出 999 变量限制 | 移除 `method="multi"` | ✅ 已修复 |
| 2 | SHIBOR 下载失败 | BaoStock 无 `query_shibor_data` 接口 | 从 macro_downloader 移除 | ✅ 已修复 |
| 3 | 成分股列数不匹配 | 接口返回 3 列 (updateDate, code, code_name)，代码硬编码 2 列 | 使用 `rs.fields` 动态获取 | ✅ 已修复 |
| 4 | 分红表主键冲突 | 主键 `(code, divid_operate_date)` 未包含 `year_type` | 重建表，主键增加 `year_type` | ✅ 已修复 |
| 5 | K线重复插入冲突 | 测试数据未清理导致 UNIQUE 约束冲突 | 下载前清理或改用 `INSERT OR IGNORE` | ✅ 已修复 |
| 6 | 会话超时未重连 | BaoStock 会话超时后未自动重连 | 添加会话超时检测和自动重连机制 | ✅ 已实现 |
| 7 | 无断点续传机制 | 中断后需重新下载 | 添加断点续传功能，记录已下载数据 | ✅ 已实现 |
| 8 | 无进度反馈 | 用户无法了解下载进度 | 添加进度条显示 | ✅ 已实现 |
| 9 | API 请求计数不准确 | 失败请求不计数，导致本地计数低于服务器 | 无论成功失败都计数 | ✅ 已实现 |
| 10 | 非交易日浪费请求 | 周末/节假日仍下载 K 线，返回 0 行 | 增加交易日判断，非交易日跳过 | ✅ 已实现 |
| 11 | 无黑名单检测 | 无法及时发现 IP 被封禁 | 新增 check_blacklist.py 脚本 | ✅ 已实现 |
| 12 | 敏感信息泄露风险 | 邮箱密码等明文存储在 config.yaml | 使用.env 文件 + .gitignore | ✅ 已实现 |

### 1.2 未解决的性能瓶颈

| 序号 | 问题 | 影响 | 状态 |
|------|------|------|------|
| 1 | 全量 K 线下载耗时过长 | 100 只股票 × 3 种复权 = 10 分钟，5000+ 股票预计 8-10 小时 | 🔄 部分缓解（断点续传） |
| 2 | 串行下载 | 每只股票串行请求，未利用并发 | ⚠️ BaoStock API 不支持并发 |
| 3 | 财务数据逐股逐年查询 | 10 只股票 × 2 年 × 4 季度 × 6 类 = 480 次 API 调用 | 🔄 批量预加载优化 |
| 4 | 数据库写入性能 | 大量数据写入时性能下降 | 🔄 使用 WAL 模式优化 |
| 5 | 财务数据日志不透明 | 无法看到跳过了多少已存在数据 | 增加详细日志输出 | ✅ 已实现 |

---

## 2. 改进方案

### 2.1 高优先级（立即实施）

#### A. 断点续传机制

**问题**：下载中断后无法恢复，需从头开始。

**方案**：

```python
# 在 BaseDownloader 中添加
def get_last_downloaded(self, table: str, code: str, date_col: str = "date") -> str | None:
    """获取某只股票已下载的最新日期"""
    try:
        row = self.conn.execute(
            f"SELECT MAX({date_col}) FROM {table} WHERE code = ?", (code,)
        ).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None

def download_daily_kline(self, codes: list[str], ...):
    for code in codes:
        last_date = self.get_last_downloaded("all_stock_daily", code)
        start = last_date or DAILY_KLINE_START
        # 仅下载 last_date 之后的数据
        rs = bs.query_history_k_data_plus(code, ..., start_date=start, ...)
```

**收益**：中断后仅下载增量数据，节省 90%+ 时间。

#### B. 进度条

**方案**：使用 `tqdm` 库。

```python
from tqdm import tqdm

for code in tqdm(codes, desc="Downloading daily K-line"):
    # 下载逻辑
    pass
```

**依赖添加**：
```bash
uv add tqdm
```

#### C. 幂等写入（UPSERT）

**问题**：重复运行导致主键冲突。

**方案**：使用 `INSERT OR REPLACE` 替代 `append`。

```python
# 在 save_df 中
def save_df(self, df, table, if_exists="append"):
    if if_exists == "upsert":
        # 先写入临时表，再 MERGE
        df.to_sql(f"{table}_tmp", self.conn, if_exists="replace", index=False)
        self.conn.execute(f"""
            INSERT OR REPLACE INTO {table}
            SELECT * FROM {table}_tmp
        """)
        self.conn.execute(f"DROP TABLE IF EXISTS {table}_tmp")
    else:
        df.to_sql(table, self.conn, if_exists=if_exists, index=False)
```

#### D. 会话超时自动重连

**问题**：BaoStock 会话超时后未自动重连，导致后续请求失败。

**方案**：在 `query_with_retry` 中检测会话超时特征。

```python
def query_with_retry(self, query_func, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        self.ensure_login()
        rs = query_func(**kwargs)
        if rs.error_code == '0':
            return rs
        if "session" in rs.error_msg.lower() or rs.error_code == '-1':
            self.logger.warning("Session expired, re-logging in...")
            self.logout()
            self.login()
            continue
        # 其他错误正常重试
        time.sleep(2 ** attempt)
```

### 2.2 中优先级（短期实施）

#### E. ~~分批并发下载~~ → 已验证不可行

**测试结果**：

| 模式 | 并发数 | 结果 |
|------|--------|------|
| Multi-Session（各自 login） | 1 | ✅ 正常，0.4s |
| Multi-Session（各自 login） | 2 | ❌ 第2个worker查询返回"网络接收错误" |

**结论**：BaoStock 服务端**不支持任何并发连接**，即使每个 worker 独立登录，第2个并发请求立即失败。

**替代方案**：使用**批量预加载**优化串行下载。

```python
def download_daily_kline(self, codes, start_date=None, end_date=None):
    # 预先收集所有需要下载的股票和日期范围
    tasks = []
    for code in codes:
        last_date = self.get_last_downloaded("all_stock_daily", code)
        tasks.append((code, last_date or start_date, end_date))

    # 串行执行，但带进度条和断点续传
    for code, start, end in tqdm(tasks, desc="Downloading daily K-line"):
        self._download_single_stock(code, start, end)
```

**收益**：虽不能并发，但通过断点续传减少重复下载，实际效果接近并发。

#### F. 下载配置文件

**方案**：使用 YAML/JSON 配置文件管理下载参数。

```yaml
# config.yaml
download:
  kline:
    daily:
      enabled: true
      adjustflags: [1, 2, 3]
      start_date: "1990-12-19"
      batch_size: 50
    minute:
      enabled: false
      frequencies: ["5", "15", "30", "60"]
  financial:
    enabled: true
    start_year: 2007
    types: ["profit", "operation", "growth", "balance", "cashflow", "dupont"]
  stocks:
    filter: "type=1 AND status=1"
    exclude: ["sh.688xxx"]  # 排除科创板
```

#### G. 数据完整性校验

**方案**：下载完成后校验数据完整性。

```python
def validate_data(self):
    """校验数据完整性"""
    issues = []

    # 1. 检查交易日历连续性
    trading_days = self.conn.execute(
        "SELECT COUNT(*) FROM trade_dates WHERE is_trading_day = 1"
    ).fetchone()[0]

    # 2. 检查每只股票的 K 线天数是否合理
    cursor = self.conn.execute("""
        SELECT code, COUNT(*) as days
        FROM all_stock_daily
        WHERE adjustflag = 3
        GROUP BY code
        HAVING days < 100
    """)
    for code, days in cursor:
        issues.append(f"{code}: only {days} days of data")

    return issues
```

### 2.3 低优先级（长期规划）

#### H. 数据库迁移至 PostgreSQL

**当前**：SQLite 单文件，适合个人使用。

**迁移时机**：数据量超过 10GB 或需要多用户并发访问时。

**改动量**：仅需修改 `db_manager.py` 的连接字符串，pandas `to_sql` 自动适配。

#### I. 定时任务调度

**方案**：使用 `APScheduler` 或系统 cron。

```python
# 每日 18:00 自动更新
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()
scheduler.add_job(run_daily_update, "cron", hour=18, minute=0)
scheduler.start()
```

#### J. 数据压缩与分区

**方案**：对历史 K 线数据按年份分区存储。

```python
# 按年分表
def save_yearly_kline(self, df, year):
    table = f"all_stock_daily_{year}"
    df.to_sql(table, self.conn, if_exists="append", index=False)
```

---

## 3. 实施优先级矩阵

| 改进项 | 实施难度 | 收益 | 优先级 | 预计工时 |
|--------|----------|------|--------|----------|
| A. 断点续传 | 低 | 高 | P0 | 2h |
| B. 进度条 | 极低 | 中 | P0 | 30min |
| C. 幂等写入 | 低 | 高 | P0 | 1h |
| D. 会话重连 | 低 | 高 | P0 | 1h |
| E. 批量预加载+断点续传 | 低 | 高 | P1 | 2h |
| F. 配置文件 | 中 | 中 | P1 | 2h |
| G. 数据校验 | 中 | 中 | P2 | 2h |
| H. PostgreSQL 迁移 | 高 | 低 | P3 | 8h |
| I. 定时任务 | 低 | 中 | P2 | 1h |
| J. 数据分区 | 高 | 低 | P3 | 4h |

---

## 4. 推荐实施顺序

```
Phase 1 (1天): A + B + C + D
  → 解决所有运行中发现的 bug，提升稳定性

Phase 2 (0.5天): E + F
  → 批量预加载+断点续传提升下载效率，添加配置文件

Phase 3 (0.5天): G + I
  → 数据质量保障和自动化

Phase 4 (按需): H + J
  → 数据量增长后考虑
```

---

## 5. 已知 API 限制备忘

| API | 限制 | 应对策略 |
|-----|------|----------|
| `query_history_k_data_plus` | 单次请求返回数据量有限 | 按股票分批 |
| `query_dividend_data` | 同一 (code, date) 可能有 report/operate 两种类型 | 主键包含 year_type |
| `query_sz50/hs300/zz500_stocks` | 返回 updateDate 字段 | 使用 rs.fields 动态获取列名 |
| 会话超时 | 约 30 分钟无操作自动断开 | 每 25 分钟重连 |
| 无 SHIBOR 接口 | BaoStock 不提供 | 从方案中移除 |
| 分钟线 | 仅提供近 5 年数据 | 设置合理的 start_date |
| 财务数据 | 仅提供 2007 年至今 | 设置 FINANCIAL_DATA_START_YEAR=2007 |
| **并发连接** | **不支持任何并发，2个session即报错** | **必须串行下载，不可并发** |
