#!/bin/bash
# Kill all running baostock processes

LOGFILE="/home/workspace/baostock/logs/kill_baostock.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking for baostock processes..." >> "$LOGFILE"

PIDS=$(pgrep -f "baostock.*download" 2>/dev/null)

if [ -z "$PIDS" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No baostock processes found." >> "$LOGFILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Found processes: $PIDS" >> "$LOGFILE"
    for PID in $PIDS; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Killing PID $PID..." >> "$LOGFILE"
        kill "$PID" 2>/dev/null
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Force killing PID $PID..." >> "$LOGFILE"
            kill -9 "$PID" 2>/dev/null
        fi
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done." >> "$LOGFILE"
fi
