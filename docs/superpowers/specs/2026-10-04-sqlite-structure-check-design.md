# SQLite 结构完整性检查脚本 — 设计方案

- 日期:2026-10-04
- 状态:设计已确认,待实现
- 涉及文件:`scripts/check_sqlite_structure.py`(新增)、`tests/test_check_sqlite_structure.py`(新增)、`README.md`(补充使用说明)

## 背景

`data/baostock.db` 约 15GB(390 万页)。现有 `scripts/check_data_integrity.py` 只做**数据**完整性(L1–L8 完整度/覆盖率/空洞),从不运行 `PRAGMA integrity_check`,因此对**物理结构**损坏(页面、freelist、索引结构)完全不可见。

2026-10-04 曾出现"源 SQLite 文件的页面、freelist 和索引结构损坏"的说法,经全量 `PRAGMA integrity_check`(结果 `ok`)、freelist 链遍历、全表/全索引扫描证实**不成立**;但该结论耗费大量手工排查,因为系统里没有任何工具能给出结构级判定。本设计补齐这一层校验。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| 落点 | **独立脚本** `scripts/check_sqlite_structure.py`,不改动 `check_data_integrity.py` |
| 通知方式 | **检测到损坏时发邮件告警**(复用 `src/utils/email_notifier.py`,仿 `daily_report.py` 用法) |
| 检查深度 | 分层:秒级前置层 + 默认全深度 `PRAGMA integrity_check`;`--quick` 跳过深度层 |
| 报告 | 沿用现有风格:`data/sqlite_structure_report.json` + `.txt` |
| 调度 | 本任务不配置 cron;docstring 建议每周低峰期运行(全深度约 75 分钟) |

## 目标与范围

- 对 `data/baostock.db` 做物理结构校验:页面结构、freelist 链、索引结构、schema 可读性
- 发现任何损坏 → 打印明细 + 保存报告 + 发告警邮件 + 退出码 1
- 全部通过 → 保存报告、不发邮件、退出码 0
- 退出码约定:`0` 健康 / `1` 发现损坏 / `2` 检查器自身出错(如数据库无法打开)

**不做**(YAGNI):

- 不自动修复损坏(`.recover` / `VACUUM` / `REINDEX` 属人工决策,脚本只判定与告警)
- 不修改 `check_data_integrity.py` 或其报告
- 不配置 crontab / 系统调度
- 不做多数据库并行、增量检查、历史趋势对比
- 全部通过时不发"健康"邮件(避免噪音)

## 架构与数据流

```
手动执行 / cron(建议每周低峰)
  → check_sqlite_structure.py --db <path> [--quick] [--no-email]
      → 前置层(秒级,总是运行)
          1. header 检查:文件大小 ↔ page_size × page_count
          2. freelist 检查:遍历 trunk 链(环/越界/重复/计数匹配)
          3. schema 检查:sqlite_master 可读、对象计数
      → 深度层(--quick 时跳过)
          4. PRAGMA integrity_check(预计 60–90 分钟,开始前打印预估提示)
      → 汇总 checks[] → summary.status
  → 保存 data/sqlite_structure_report.{json,txt}
  → status != healthy 且未 --no-email 且 config.yaml email.enabled
      → load_dotenv() / load_email_config() → send_email(cfg, 主题, HTML 正文)
  → exit 0 / 1 / 2(与发信结果无关)
```

## 组件设计

### 1. `scripts/check_sqlite_structure.py`(新增)

CLI:

| 参数 | 默认 | 说明 |
|---|---|---|
| `--db` | `src.config.DB_PATH` | 目标数据库路径 |
| `--quick` | 关 | 跳过深度层,仅跑秒级前置层 |
| `--output` | `data/sqlite_structure_report` | 报告基础路径(输出 `.json` 与 `.txt`) |
| `--no-email` | 关 | 即使发现损坏也不发邮件 |

数据访问约束:

- 头部/freelist 检查用 Python `struct` 直接只读文件字节(与 `sqlite3` 无关,不会触碰 WAL)
- 深度层用 `sqlite3` 连接,只执行只读语句(`PRAGMA integrity_check` 本身只读);不执行任何写语句、不在连接上开事务
- 打开失败/文件缺失 → `summary.status = "error"`,退出码 2(此时不发损坏告警邮件,只打印错误)

### 2. 检查项明细

**前置层(总是运行,合计秒级):**

| # | 检查 | 方法 | 捕获 |
|---|---|---|---|
| 1 | header 一致性 | 解析 100 字节头:`page_size`、`page_count`、`freelist_count`;验证文件大小 = `page_size × page_count`(截断检测);`page_size` 为合法值(512–65536 且为 2 的幂) | 文件截断、头部损坏 |
| 2 | freelist 链 | 从 `freelist_head` 遍历 trunk 链:trunk 记录 `[next_trunk][nleaf][leaf...]`;验证无环、指针均在 `[1, page_count]`、leaf 无重复且不与 trunk 重叠、`trunk+leaf 总数 = header.freelist_count` | freelist 链损坏(环/越界/计数不符) |
| 3 | schema 可读 | `SELECT count(*) FROM sqlite_master`;读取对象清单 | schema 页损坏 |

**深度层(默认运行,`--quick` 跳过):**

| # | 检查 | 方法 | 捕获 |
|---|---|---|---|
| 4 | 全库结构 | `PRAGMA integrity_check` | 页面重复使用/未使用、b-tree 键序、cell 偏移、溢出链、索引↔表内容一致性、freelist 计数、pointer-map(auto-vacuum 时) |

- 运行前打印:`深度层 PRAGMA integrity_check 开始,15GB 库预计 60–90 分钟...`
- 结果 `ok` → pass;否则逐行收集错误,**最多取前 200 条**写入报告,并记录总错误条数

### 3. 报告格式

`data/sqlite_structure_report.json`:

```json
{
  "report_time": "ISO8601",
  "db_path": "...",
  "db_size_mb": 0,
  "mode": "full | quick",
  "checks": [
    {"name": "header", "layer": "preflight", "status": "pass|fail",
     "detail": "page_size=4096, page_count=3919684, file_size match", "errors": [], "elapsed_s": 0.0}
  ],
  "summary": {
    "status": "healthy | corrupted | error",
    "failed_checks": 0,
    "deep_check_skipped": false
  }
}
```

`data/sqlite_structure_report.txt`:仿 `check_data_integrity.py` 的中文报告风格 —— 头部信息(时间/路径/大小/模式)+ 汇总状态表(每项:✅ 通过 / ❌ 失败 + 问题数)+ 各检查明细 + 问题列表(截断 200 条)。

`summary.status` 判定:任一检查 fail → `corrupted`;检查器自身异常(无法打开/读取失败)→ `error`;否则 `healthy`。`--quick` 模式下 `deep_check_skipped=true`,报告头部显著标注"快速模式,未运行完整性深度检查"。

### 4. 告警邮件

- 触发:`summary.status != "healthy"` 且未传 `--no-email` 且 `config.yaml → email.enabled == true`
- 发送:`load_dotenv()` → `load_email_config()` → `send_email(cfg, subject, html, subtype="html")`(与 `daily_report.py` 相同;收件人 = `EMAIL_RECEIVER`)
- 主题:`[BaoStock] SQLite 结构损坏告警: baostock.db`
- 正文(HTML,仿 `daily_report.py` 风格):状态徽章(损坏/检查出错)+ 失败检查项列表 + 每项前 20 条错误 + 报告文件路径 + 建议处置(勿写库,先备份,人工评估 `.recover`)
- 发信失败只打印错误,**不改变退出码**(退出码只反映结构状态)
- `status == "healthy"` 时不发邮件

### 5. 测试(`tests/test_check_sqlite_structure.py`,新增)

全部在**小型临时库**上注入损坏验证报警,不接触 `data/baostock.db`:

| 用例 | 注入方式 | 期望 |
|---|---|---|
| 健康库全通过 | 建 1–2 张小表 | 全部 pass,exit 0,不发邮件 |
| 截断文件 | 削掉文件尾部若干页 | header 检查 fail,exit 1 |
| freelist 计数不符 | 直接改写 header 中 `freelist_count` 字段 | freelist 检查 fail,exit 1 |
| freelist 链成环 | 构造空闲页并把 trunk `next` 指回自身 | freelist 检查 fail(环),exit 1 |
| 索引结构损坏 | 破坏某索引根页字节 | 深度层 fail,exit 1 |
| schema 损坏 | 破坏 `sqlite_master` 所在页字节 | schema 检查 fail,exit 1 |
| `--quick` 跳过深度层 | 任意 | `deep_check_skipped=true`,不执行 integrity_check |
| 邮件接线 | mock `send_email` | status!=healthy 时被调用 1 次,healthy 时 0 次 |
| 检查器自身出错 | `--db` 指向不存在路径 | exit 2,`status="error"`,不发损坏邮件 |

### 6. 文档

`README.md` 增补一小节:脚本用途、运行方式(建议每周低峰、全深度约 75 分钟)、`--quick`/`--no-email` 说明、退出码约定。

## 已知技术注意点

- **WAL 模式**:库当前为 WAL(`-wal` 0 字节、`-shm` 32KB)。深度层以普通方式打开连接(不用 `mode=ro`,避免 WAL 恢复受限导致打不开),但只执行只读语句;进程不持有写锁,不触发 checkpoint。
- **耗时**:`PRAGMA integrity_check` 在此库实测约 75 分钟(390 万页、慢速磁盘)。这是独立周检脚本的可接受成本,故默认开启;`--quick` 供手动排障。
- **误报防护**:freelist 手工遍历只解析 trunk 页结构;leaf 空闲页内容属历史残留数据,**不解析**(初版脚本曾误把 leaf 当 trunk 读出越界指针,属检查器 bug 而非库损坏)。
