#!/bin/bash
#
# clean_memory.sh - Free memory by dropping caches and reclaiming unused kernel memory
#
# This script:
#   1. Syncs pending disk writes to ensure data integrity
#   2. Drops pagecache, dentries, and inodes from kernel caches
#   3. Attempts to reclaim slab objects and compact memory
#
# Requires: root/sudo privileges
# Warning: May temporarily degrade system performance after execution.
#          The kernel will rebuild caches as needed.

set -euo pipefail

# ─── Color output ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ─── Helpers ────────────────────────────────────────────────────────────────
print_header() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Memory Cleaner${NC}"
    echo -e "${GREEN}========================================${NC}"
}

print_mem() {
    local label="$1"
    echo -e "${YELLOW}${label}${NC}"
    free -h
    echo ""
}

# ─── Root check ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root (sudo).${NC}"
    exit 1
fi

print_header
echo ""

# ─── Before snapshot ────────────────────────────────────────────────────────
print_mem "[Before] Current memory usage:"

# ─── Step 1: Flush filesystem buffers ───────────────────────────────────────
echo -e "${YELLOW}[1/4] Flushing filesystem buffers...${NC}"
sync
echo "  Done."
echo ""

# ─── Step 2: Drop caches ────────────────────────────────────────────────────
# 1 = pagecache
# 2 = dentries and inodes
# 3 = pagecache + dentries + inodes
echo -e "${YELLOW}[2/4] Dropping caches (pagecache + dentries + inodes)...${NC}"
echo 3 > /proc/sys/vm/drop_caches
echo "  Done."
echo ""

# ─── Step 3: Reclaim slab objects ───────────────────────────────────────────
echo -e "${YELLOW}[3/4] Attempting slab reclaim...${NC}"
# Write 1 to trigger one round of slab reclaim
echo 1 > /proc/sys/vm/drop_caches 2>/dev/null || true
echo "  Done."
echo ""

# ─── Step 4: Compact memory (reduce fragmentation) ─────────────────────────
echo -e "${YELLOW}[4/4] Compacting memory...${NC}"
if [[ -f /proc/sys/vm/compact_memory ]]; then
    echo 1 > /proc/sys/vm/compact_memory
    echo "  Done."
else
    echo "  Skipped (compact_memory not available)."
fi
echo ""

# ─── After snapshot ─────────────────────────────────────────────────────────
print_mem "[After] Memory usage after cleanup:"

# ─── Summary ────────────────────────────────────────────────────────────────
echo -e "${GREEN}Memory cleanup complete.${NC}"
echo ""
echo "Note: The kernel will rebuild caches as needed. A temporary performance"
echo "      dip is normal and expected immediately after cache drops."
