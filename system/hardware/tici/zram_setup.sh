#!/usr/bin/env bash
# RT control procs (controlsd/card) mlockall their pages, so they are never swapped.
set -e

[ -e /sys/class/zram-control ] || exit 0
grep -q "zram0" /proc/swaps 2>/dev/null && exit 0

DISKSIZE="${ZRAM_DISKSIZE:-2G}"

echo lzo > /sys/block/zram0/comp_algorithm 2>/dev/null || true
echo "$DISKSIZE" > /sys/block/zram0/disksize

mkswap /dev/zram0 >/dev/null 2>&1
swapon -p 100 /dev/zram0

sysctl -q vm.swappiness=100 2>/dev/null || true
sysctl -q vm.page-cluster=0 2>/dev/null || true

echo "zram: $(free -m | awk '/Swap/{print $2}')MB compressed swap active"
