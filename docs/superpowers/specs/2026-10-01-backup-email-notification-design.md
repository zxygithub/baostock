# 百度网盘备份邮件通知 — 设计方案

- 日期:2026-10-01
- 状态:设计已确认,待实现
- 涉及文件:`src/utils/email_notifier.py`(新增)、`scripts/backup_to_baidu.py`、`scripts/daily_report.py`、`config.yaml`、`.env.example`、`README.md`、`tests/`(新增 2 个测试文件)

## 背景

`scripts/backup_to_baidu.py` 每周日 14:00(crontab)将 SQLite 数据库压缩并上传至百度网盘,执行结果只写入 `logs/backup.log`,无法及时感知备份成败。需求:每次备份(手动或定时)结束后,向邮箱发送一封结果通知邮件。

项目已有完整 SMTP 发信能力(`scripts/daily_report.py` 中的 `load_dotenv` / `get_email_config` / `send_email`,凭据在 `.env`),本设计将其提炼为公共模块并接入备份脚本。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| 触发条件 | 成功与失败都发通知(每次备份运行结束必发一封) |
| 实现方案 | 方案 1:备份脚本内挂钩 + 抽出公共邮件模块 |
| 邮件正文 | **纯文本**,能说清楚字段即可 |
| 邮件主题 | **固定格式:`证券数据baostock百度云备份结果-YYYY年MM月DD日`**(备份执行日期,月/日两位补零,例:`证券数据baostock百度云备份结果-2026年10月01日`) |
| 收件人 | 系统配置的收件人,即 `.env` 中 `EMAIL_RECEIVER`(单收件人) |
| 成功/失败区分 | 主题相同,正文首行标明结果(「成功」/「失败」) |

## 目标与范围

- 每次备份运行结束(成功或失败)发送一封通知邮件,手动执行与 crontab 定时执行均覆盖
- 复用 `.env` 的 `EMAIL_*` SMTP 配置,收件人 = `EMAIL_RECEIVER`
- `config.yaml` 提供独立开关 `email.backup_notify`(与日报 `email.enabled` 互不影响)

**不做**(YAGNI):

- 失败自动重试/自动重跑备份
- 多收件人/抄送/富文本 HTML
- 进程被 SIGKILL/OOM 等极端情况的兜底通知(此时发不出邮件,查 `logs/backup.log`)
- 改动 daily_report 邮件正文内容(仅替换其邮件发送底层实现)

## 架构与数据流

```
cron(周日 14:00) / 手动执行
  → backup_to_baidu.py
      → load_dotenv() / load_email_config()
      → 打包 data/baostock.db* → /tmp/baostock_backup_TS.tar.gz
      → 百度网盘分片上传 (precreate → upload → create)
      → 清理旧备份(保留 N 份,尽力而为)
      → 汇总 result(成功/失败 + 详情)
  → email_notifier.send_email(cfg, subject, 纯文本正文)
      → SMTP(465 SSL / 其他端口 STARTTLS) → EMAIL_RECEIVER
  → exit 0 / exit 1(按备份结果,与发信结果无关)
```

## 组件设计

### 1. `src/utils/email_notifier.py`(新增)

公共邮件模块,从 `scripts/daily_report.py` 提炼。项目根路径按模块位置推算(`Path(__file__).resolve().parents[2]`)。

接口:

- `load_dotenv(env_path: Path | None = None) -> None`
  从项目根 `.env` 逐行读取并 `os.environ.setdefault`(原样搬移现有实现:跳过注释/空行,剥离引号,不覆盖已有环境变量)。
- `load_email_config() -> dict | None`
  读取 `EMAIL_SMTP_SERVER` / `EMAIL_SMTP_PORT` / `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVER` 五项。任一缺失或 `EMAIL_SMTP_PORT` 非整数 → 返回 `None`。**模块不做开关判断、不退出进程**,策略留给调用方。
- `send_email(cfg: dict, subject: str, body: str, subtype: str = "plain") -> bool`
  构造 `MIMEText(body, subtype, "utf-8")`,设置 `Subject`/`From`/`To`;`smtp_port == 465` 走 `SMTP_SSL`,否则 `SMTP` + `starttls()`;登录、`send_message`、`quit()`。**任何异常 → warning 日志 + 返回 `False`**,不抛出、不 `sys.exit`。备份通知用默认 `subtype="plain"`;daily_report 迁移后传 `subtype="html"` 保持其 HTML 日报不变。

### 2. `scripts/backup_to_baidu.py`(修改)

- 增加 `sys.path.insert(0, str(Path(__file__).parent.parent))`(与 `download_all.py` 一致),`from src.utils.email_notifier import load_dotenv, load_email_config, send_email`。
- `main()` 出口收敛:现有散落的 `sys.exit(1)` 路径改为先维护结果结构再统一退出:

  ```python
  result = {
      "success": bool,
      "stage": str,          # 失败阶段:"初始化" | "打包" | "上传"(成功时无意义)
      "error": str | None,   # 错误信息
      "archive_name": str,
      "archive_size": int,   # 字节,删除临时归档前采集
      "remote_path": str,
      "duration": float,     # 秒,脚本开始到结束
      "keep_count": int,     # --keep 配置的保留份数
      "deleted_old": int,    # 本次清理旧备份数量
  }
  ```

- 备份流程结束(无论成败)后统一调用通知,主题与正文如下(**纯文本**):

  主题(成功与失败相同):

  ```
  证券数据baostock百度云备份结果-2026年10月01日
  ```

  成功正文:

  ```
  证券数据baostock百度云备份已完成。
  结果:成功
  备份时间:2026-10-01 14:00:32
  归档文件:baostock_backup_20261001_140032.tar.gz
  归档大小:1.2 GB(1,234,567,890 字节)
  远端路径:/apps/bypy/证券数据备份/baostock_backup_20261001_140032.tar.gz
  总耗时:85 秒
  保留策略:保留最近 7 份,本次清理旧备份 1 份
  ```

  失败正文:

  ```
  证券数据baostock百度云备份失败,请尽快处理。
  结果:失败
  失败阶段:上传
  错误信息:Chunk 3 failed after 3 attempts: Connection reset
  备份时间:2026-10-01 14:00:32
  归档文件:baostock_backup_20261001_140032.tar.gz
  详细日志:logs/backup.log
  ```

- 新增参数 `--no-email`:跳过通知(手动试跑/调试用)。
- 通知跳过条件(仅 warning 日志,**不影响备份退出码**):
  1. `--no-email`
  2. `config.yaml` 中 `email.backup_notify` 为 false(配置节缺失视为 true,即默认通知)
  3. `load_email_config()` 返回 `None`(`.env` 未配置完整)
  4. `send_email()` 返回 `False`
- 退出码语义与现状一致:按备份结果退出(成功 0 / 失败 1),发信结果不改变退出码。
- 备份逻辑本身(打包、分片上传、清理)不改,仅收敛出口与采集结果字段。

### 3. `scripts/daily_report.py`(修改)

- 删除本地 `load_dotenv` / `get_email_config` / `send_email`,改为 `from src.utils.email_notifier import load_dotenv, load_email_config, send_email`。
- 行为完全不变:
  - `config.yaml` 的 `email.enabled` 开关判断保留在 `daily_report.main()`(公共模块不管开关);
  - 缺配置 → 打印提示并 `sys.exit(1)`;
  - 发信失败 → `sys.exit(1)`(在 `main()` 中根据 `send_email` 返回值处理);
  - 邮件主题、HTML 正文、收发件人完全一致(`build_email` 机械调整为产出 `(subject, html)`,`send_email(..., subtype="html")` 发送)。
- 邮件正文构建函数(`build_email` 及各 section 构建)内容不动。

### 4. 配置与文档

- `config.yaml`:`email:` 块新增 `backup_notify: true`。
- `.env.example`:`EMAIL_*` 字段已有,无需新增;可在注释中注明备份通知复用同一组配置。
- `README.md`:「百度网盘备份」章节补充通知说明,更新日志补一条。

## 错误处理矩阵

| 情况 | 通知 | 退出码 | 日志 |
|---|---|---|---|
| 备份成功、发信成功 | 成功邮件 | 0 | info |
| 备份成功、发信失败 | 无 | 0 | warning |
| 备份失败、发信成功 | 失败邮件 | 1 | error |
| 备份失败、发信失败 | 无 | 1 | error + warning |
| `email.backup_notify: false` | 无 | 按备份结果 | warning |
| `.env` `EMAIL_*` 缺失 | 无 | 按备份结果 | warning |
| `--no-email` | 无 | 按备份结果 | info |
| 进程被 kill / OOM | 无 | (无) | `logs/backup.log` 可查 |

## 测试计划

新增测试(`tests/`,mock 网络与 SMTP,不发真实邮件):

1. `tests/test_email_notifier.py`
   - `load_dotenv` 解析 `.env`:引号剥离、注释/空行跳过、`setdefault` 不覆盖已有值
   - `load_email_config`:五项齐全 → dict;缺任一项 → None;端口非整数 → None
   - `send_email`:mock `smtplib`;成功 → True;登录/发送抛异常 → False(不向外抛出)
   - 端口分支:465 走 `SMTP_SSL`,其他端口走 `SMTP` + `starttls`
   - `subtype` 参数:plain / html 均正确构造 MIMEText
2. `tests/test_backup_notify.py`
   - 成功路径触发通知,主题精确等于 `证券数据baostock百度云备份结果-YYYY年MM月DD日`,正文含归档名/大小/远端路径/耗时/清理数
   - 失败路径(模拟上传失败)触发失败通知,正文含失败阶段与错误信息、日志位置
   - `--no-email` 不发信
   - `email.backup_notify: false` 不发信;配置节缺失时默认发信
   - 发信失败时备份退出码仍为 0(成功场景)/ 1(失败场景)

回归:

- 现有 `pytest` 全过(含 `tests/test_close_checkpoint.py`、`tests/test_financial_skip_logic.py` 等)
- `daily_report.py` 迁移后验证主题/正文/收发件人与迁移前一致

手工验证:

- `.venv/bin/python scripts/backup_to_baidu.py` 试跑,收真实成功邮件核对主题与纯文本正文
- 临时使用无效 token 跑一次,收真实失败邮件核对失败阶段与错误信息

## 已知取舍

- 进程被 kill / OOM 时发不出通知(方案 1 已知边界,`logs/backup.log` 兜底可查)。
- 成功与失败邮件主题相同,仅正文首行区分;如日后想在主题上区分(如失败加后缀),改动点仅 `backup_to_baidu.py` 的主题构造一处。
- 清理旧备份为尽力而为(现状即如此):清理失败只记 warning,不视为备份失败,不进失败邮件。

## 实现顺序(供 writing-plans 参考)

1. 新增 `src/utils/email_notifier.py` + `tests/test_email_notifier.py`
2. `daily_report.py` 迁移到公共模块 + 回归
3. `backup_to_baidu.py` 接入通知 + `tests/test_backup_notify.py`
4. `config.yaml` / `.env.example` / `README.md` 更新
