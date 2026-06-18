# BaoStock 服务器连通性监控方案设计

## 背景

BaoStock 服务器偶尔会出现连接中断（如"网络接收错误"、"Broken pipe"），导致下载任务在重试多次后失败退出。当前机制下，程序会持续重试浪费大量时间，且无法自动恢复。

## 目标

1. 每 10 分钟检测 BaoStock 服务器连通性
2. 服务器不可用时，自动终止下载进程
3. 服务器恢复后，自动重启下载服务
4. 在每日邮件中展示当天的连通性和重启情况

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  cron */10 → monitor_baostock.sh                             │
│                                                              │
│  1. 跳过关闭窗口 (23:55 ~ 0:05)                              │
│  2. 3 次连通性检测（间隔 30 秒）                             │
│  3. 不通 → kill 进程 + 记录事件                              │
│  4. 通了 + 有标记 → ./start.sh full + 记录事件               │
│  5. 每日 0:00 邮件读取事件记录展示当天情况                   │
└──────────────────────────────────────────────────────────────┘
```

## 时间线

| 时间 | 任务 |
|------|------|
| 0:00 | 发送邮件日报（读取昨天的监控事件） |
| 0:03 | 清理内存 |
| 0:10 | 监控脚本首次运行 → 启动下载 |
| ... | 每 10 分钟监控 |
| 23:55 | 程序内部定时停止 |
| 23:59 | kill 脚本兜底 |

**关闭窗口**：23:55 ~ 0:05（约 10 分钟），此期间监控脚本不干预。

## 连通性检测流程

```
monitor_baostock.sh 每 10 分钟运行:

1. 如果在关闭窗口 (23:55 ~ 0:05) → 跳过

2. 连通性检测（3 次确认）:
   第 1 次检测 → 不通
     ↓ 等 30 秒
   第 2 次检测 → 不通
     ↓ 等 30 秒
   第 3 次检测 → 不通
     ↓ 确认不通（总耗时 ~60 秒）

3. 确认不通后:
   ├─ 有下载进程 → kill + 记录事件
   └─ 创建 .server_down 标记

4. 如果任意一次通了 → 走"通了"逻辑
```

## 状态机

```
每 10 分钟:
│
├─ 在关闭窗口 (23:55~0:05)? → 跳过
│
├─ 检测连通性:
│   ├─ 第1次通 → 走"通了"逻辑
│   └─ 第1次不通 → 等30s
│       ├─ 第2次通 → 走"通了"逻辑
│       └─ 第2次不通 → 等30s
│           ├─ 第3次通 → 走"通了"逻辑
│           └─ 第3次不通 → 确认DOWN
│
├─ 确认DOWN:
│   ├─ 有下载进程 → kill + 记录事件 "进程已终止"
│   └─ 创建 .server_down（如果不存在）
│
└─ 确认UP:
    ├─ .server_down 存在 + 无下载进程 → ./start.sh full + 记录事件
    └─ 否则 → 正常，不操作
```

## 文件设计

| 文件 | 作用 |
|------|------|
| `scripts/monitor_baostock.sh` | 监控脚本，cron 每 10 分钟调用 |
| `data/monitor_events.json` | 当天事件记录（每日邮件发送后清空） |
| `data/.server_down` | 状态标记文件，存在 = 上次因服务器不可用而停止 |
| `logs/monitor_baostock.log` | 监控日志 |

## 事件记录格式

`data/monitor_events.json`:

```json
{
  "date": "2026-06-17",
  "events": [
    {"time": "09:03", "type": "server_down", "msg": "3次检测均失败"},
    {"time": "09:04", "type": "killed", "msg": "PID 12345 已终止"},
    {"time": "10:15", "type": "server_up", "msg": "连通性恢复"},
    {"time": "10:15", "type": "restarted", "msg": "./start.sh full 启动"}
  ],
  "server_down_count": 1,
  "restart_count": 1
}
```

## 邮件新增内容

```
📡 服务器连通性监控
─────────────────────────────────
• 服务器中断次数: 1
• 自动重启次数: 1
• 事件时间线:
  09:03 ❌ 服务器不可达 (3次检测均失败)
  09:04 🛑 终止下载进程 (PID 12345)
  10:15 ✅ 服务器恢复
  10:15 🔄 重新启动下载 (./start.sh full)
```

## Cron 变更

```diff
  0 0 * * * cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py >> logs/cron_daily_report.log 2>&1
  3 0 * * * /home/workspace/baostock/clean_memory.sh >> /home/workspace/baostock/logs/cron_clean_memory.log 2>&1
- 5 0 * * * cd /home/workspace/baostock && ./start.sh full >> logs/cron_full_download.log 2>&1
+ */10 * * * * /home/workspace/baostock/scripts/monitor_baostock.sh
  59 23 * * * /home/workspace/baostock/scripts/kill_baostock.sh
```

## 关键逻辑

1. **首次启动**（0:10 后）：无 `.server_down`，无下载进程 → 服务器通就启动下载
2. **服务器宕机**：3 次检测确认 → kill 进程 → 创建 `.server_down` → 等恢复
3. **服务器恢复**：检测到 `.server_down` → 启动 `./start.sh full` → 删除标记
4. **23:55 内部停止**：正常退出，不创建 `.server_down` → 监控不会重启
5. **23:59 kill 脚本**：兜底清理

## 实现清单

- [ ] `scripts/monitor_baostock.sh` - 监控脚本
- [ ] `scripts/daily_report.py` - 读取事件并展示
- [ ] Cron 配置更新
- [ ] 文档更新
