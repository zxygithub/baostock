#!/bin/bash
# Setup crontab for baostock backup to Baidu Pan
# Usage: bash scripts/setup_backup_cron.sh [hour] [minute]

set -e

HOUR="${1:-14}"     # Default: 2 PM (Sunday)
MINUTE="${2:-0}"    # Default: :00
DOW="${3:-0}"       # Default: Sunday (0)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
BACKUP_SCRIPT="$SCRIPT_DIR/backup_to_baidu.py"
LOG_FILE="$PROJECT_DIR/logs/backup.log"

# Ensure log directory exists
mkdir -p "$PROJECT_DIR/logs"

# Build cron entry
CRON_ENTRY="$MINUTE $HOUR * * $DOW cd $PROJECT_DIR && $PYTHON_BIN $BACKUP_SCRIPT >> $LOG_FILE 2>&1"

# Day of week names
DOW_NAMES=("Sunday" "Monday" "Tuesday" "Wednesday" "Thursday" "Friday" "Saturday")

echo "=========================================="
echo "  Baostock Backup Cron Setup"
echo "=========================================="
echo ""
echo "Scheduled time: Every ${DOW_NAMES[$DOW]} at $(printf '%02d:%02d' $HOUR $MINUTE)"
echo "Script: $BACKUP_SCRIPT"
echo "Log: $LOG_FILE"
echo ""
echo "Cron entry to add:"
echo "  $CRON_ENTRY"
echo ""

# Check if already configured
if crontab -l 2>/dev/null | grep -q "backup_to_baidu.py"; then
    echo "⚠️  A backup cron job already exists."
    read -p "Replace it? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    # Remove old entry
    crontab -l 2>/dev/null | grep -v "backup_to_baidu.py" | crontab -
fi

# Add new cron entry
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "✅ Cron job added successfully!"
echo ""
echo "To verify: crontab -l"
echo "To remove: crontab -l | grep -v 'backup_to_baidu.py' | crontab -"
