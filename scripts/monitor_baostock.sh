#!/bin/bash
#
# monitor_baostock.sh - BaoStock 服务器连通性监控
#
# 功能:
#   1. 每 10 分钟检测 BaoStock 服务器连通性
#   2. 服务器不可用时，终止下载进程
#   3. 服务器恢复后，自动重启下载服务
#   4. 记录事件供邮件日报展示
#
# 由 cron 调用: */10 * * * * /home/workspace/baostock/scripts/monitor_baostock.sh

set -uo pipefail

# ─── 路径配置 ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
LOG_DIR="${PROJECT_DIR}/logs"
DATA_DIR="${PROJECT_DIR}/data"

LOG_FILE="${LOG_DIR}/monitor_baostock.log"
EVENTS_FILE="${DATA_DIR}/monitor_events.json"
SERVER_DOWN_FLAG="${DATA_DIR}/.server_down"

# ─── 常量 ───────────────────────────────────────────────────────────────────
CHECK_INTERVAL=30      # 每次检测间隔（秒）
CHECK_COUNT=3          # 检测次数
SHUTDOWN_HOUR=23       # 关闭开始小时
SHUTDOWN_MIN=55        # 关闭开始分钟
STARTUP_HOUR=0         # 启动小时
STARTUP_MIN=5          # 启动分钟

# ─── 日志函数 ───────────────────────────────────────────────────────────────
log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*" >> "$LOG_FILE"
}

# ─── 检查是否在关闭窗口内 ───────────────────────────────────────────────────
# 关闭窗口: 23:55 ~ 00:05
is_in_shutdown_window() {
    local current_hour current_min current_total shutdown_total startup_total
    
    current_hour=$(date +%H | sed 's/^0//')
    current_min=$(date +%M | sed 's/^0//')
    current_total=$((current_hour * 60 + current_min))
    
    # 23:55 = 23*60+55 = 1435
    shutdown_total=$((SHUTDOWN_HOUR * 60 + SHUTDOWN_MIN))
    
    # 00:05 = 0*60+5 = 5
    startup_total=$((STARTUP_HOUR * 60 + STARTUP_MIN))
    
    # 如果在 23:55 ~ 23:59 或 00:00 ~ 00:05
    if [ "$current_total" -ge "$shutdown_total" ] || [ "$current_total" -le "$startup_total" ]; then
        return 0  # true, 在窗口内
    fi
    return 1  # false, 不在窗口内
}

# ─── 检测服务器连通性 ───────────────────────────────────────────────────────
check_connectivity() {
    timeout 15 "$PYTHON" -c "
import baostock as bs
import socket
socket.setdefaulttimeout(10)
lg = bs.login()
if lg.error_code == '0':
    rs = bs.query_stock_basic(code='sh.600000')
    bs.logout()
    exit(0 if rs.error_code == '0' else 1)
else:
    bs.logout()
    exit(1)
" 2>/dev/null
    return $?
}

# ─── 3 次确认检测 ───────────────────────────────────────────────────────────
# 返回: 0=确认UP, 1=确认DOWN
check_with_retry() {
    local i
    for i in $(seq 1 $CHECK_COUNT); do
        log "INFO" "连通性检测 ($i/$CHECK_COUNT)..."
        if check_connectivity; then
            log "INFO" "检测通过 ($i/$CHECK_COUNT)"
            return 0  # UP
        fi
        log "WARN" "检测失败 ($i/$CHECK_COUNT)"
        if [ "$i" -lt "$CHECK_COUNT" ]; then
            sleep "$CHECK_INTERVAL"
        fi
    done
    log "ERROR" "3次检测均失败，确认服务器不可达"
    return 1  # DOWN
}

# ─── 检查今日请求是否已达上限 ───────────────────────────────────────────────
check_daily_limit() {
    local today count limit
    today=$(date '+%Y-%m-%d')
    limit=49000
    
    count=$("$PYTHON" -c "
import sqlite3
conn = sqlite3.connect('${DATA_DIR}/baostock.db')
row = conn.execute('SELECT count FROM request_count WHERE date = ?', ('$today',)).fetchone()
print(row[0] if row else 0)
conn.close()
" 2>/dev/null)
    
    if [ -z "$count" ]; then
        count=0
    fi
    
    if [ "$count" -ge "$limit" ]; then
        log "WARN" "今日请求已达上限 ($count/$limit)，不再启动下载"
        return 0  # true, 已达上限
    fi
    
    log "INFO" "今日请求计数: $count/$limit"
    return 1  # false, 未达上限
}

# ─── 检查下载进程 ───────────────────────────────────────────────────────────
get_download_pid() {
    # 查找 download_all.py 或 update_daily.py 进程
    pgrep -f "baostock.*(download_all|update_daily|start\.sh)" 2>/dev/null | head -1
}

# ─── 终止下载进程 ───────────────────────────────────────────────────────────
kill_download_process() {
    local pid
    pid=$(get_download_pid)
    if [ -z "$pid" ]; then
        log "INFO" "无下载进程运行"
        return 1  # 没有进程需要终止
    fi
    
    log "WARN" "终止下载进程 PID=$pid"
    kill "$pid" 2>/dev/null
    sleep 2
    
    if kill -0 "$pid" 2>/dev/null; then
        log "WARN" "强制终止 PID=$pid"
        kill -9 "$pid" 2>/dev/null
    fi
    
    record_event "killed" "PID $pid 已终止"
    return 0
}

# ─── 启动下载服务 ───────────────────────────────────────────────────────────
start_download() {
    log "INFO" "启动下载服务: ./start.sh full"
    
    # 后台启动
    cd "$PROJECT_DIR"
    nohup ./start.sh full >> "${LOG_DIR}/cron_full_download.log" 2>&1 &
    
    record_event "restarted" "./start.sh full 启动"
    
    # 删除服务器下线标记
    rm -f "$SERVER_DOWN_FLAG"
}

# ─── 记录事件 ───────────────────────────────────────────────────────────────
record_event() {
    local type="$1"
    local msg="$2"
    local today time_now
    
    today=$(date '+%Y-%m-%d')
    time_now=$(date '+%H:%M')
    
    # 如果文件不存在或日期不匹配，创建新文件
    if [ ! -f "$EVENTS_FILE" ]; then
        echo "{\"date\": \"$today\", \"events\": [], \"server_down_count\": 0, \"restart_count\": 0}" > "$EVENTS_FILE"
    fi
    
    # 检查日期是否需要重置
    local file_date
    file_date=$("$PYTHON" -c "import json; print(json.load(open('$EVENTS_FILE'))['date'])" 2>/dev/null)
    if [ "$file_date" != "$today" ]; then
        echo "{\"date\": \"$today\", \"events\": [], \"server_down_count\": 0, \"restart_count\": 0}" > "$EVENTS_FILE"
    fi
    
    # 添加事件
    "$PYTHON" -c "
import json
with open('$EVENTS_FILE', 'r') as f:
    data = json.load(f)
data['events'].append({'time': '$time_now', 'type': '$type', 'msg': '$msg'})
if '$type' == 'server_down':
    data['server_down_count'] = data.get('server_down_count', 0) + 1
elif '$type' == 'restarted':
    data['restart_count'] = data.get('restart_count', 0) + 1
with open('$EVENTS_FILE', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
" 2>/dev/null
    
    log "INFO" "记录事件: type=$type, msg=$msg"
}

# ─── 主逻辑 ─────────────────────────────────────────────────────────────────
main() {
    mkdir -p "$LOG_DIR" "$DATA_DIR"
    
    log "INFO" "=== 监控脚本启动 ==="
    
    # 1. 检查是否在关闭窗口内
    if is_in_shutdown_window; then
        log "INFO" "当前在关闭窗口内 (23:55~00:05)，跳过"
        exit 0
    fi
    
    # 2. 检测连通性（3次确认）
    if check_with_retry; then
        # 服务器 UP
        log "INFO" "服务器连通"
        
        # 检查是否有 .server_down 标记
        if [ -f "$SERVER_DOWN_FLAG" ]; then
            log "INFO" "检测到 .server_down 标记，服务器已恢复"
            record_event "server_up" "连通性恢复"
            
            if ! get_download_pid > /dev/null; then
                if ! check_daily_limit; then
                    start_download
                fi
            else
                log "INFO" "下载进程已在运行，跳过启动"
                rm -f "$SERVER_DOWN_FLAG"
            fi
        else
            if ! get_download_pid > /dev/null; then
                if ! check_daily_limit; then
                    log "INFO" "无下载进程，启动下载服务"
                    start_download
                fi
            else
                log "INFO" "下载进程运行中，正常"
            fi
        fi
    else
        # 服务器 DOWN
        log "ERROR" "服务器不可达"
        record_event "server_down" "3次检测均失败"
        
        # 终止下载进程
        kill_download_process || true
        
        # 创建标记
        touch "$SERVER_DOWN_FLAG"
        log "WARN" "创建 .server_down 标记"
    fi
    
    log "INFO" "=== 监控脚本结束 ==="
}

main "$@"
