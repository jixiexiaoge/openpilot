#!/bin/bash
# USB mass-storage gadget exposing a snapshot of /data/media/0/realdata (dashcam clips + logs)
# over the same configfs gadget mechanism as /usr/comma/set_adb.sh. openpilot keeps running; the
# export is a read-only snapshot built at enable time, not a live view of realdata.
#
# The device only has one physical USB controller (UDC), so ADB and USB storage must live in the
# SAME composite gadget (/config/usb_gadget/g1) rather than each owning their own. Earlier versions
# of this script called /usr/comma/set_adb.sh as a black box and then unbound/rebound around it,
# but that intermediate bind/unbind churn made the *next* bind flaky (functionfs needs its
# userspace side, adbd, settled before the gadget can (re)bind). So instead we replicate set_adb.sh's
# handful of setup lines directly here and do exactly one bind at the end, covering whichever
# functions (ADB, mass storage) are currently enabled.
#
# Without composing like this, comma's adb-param-watcher systemd unit (which fires whenever
# /data/params/d/AdbEnabled is touched, even to the same value) would rebuild g1 with only its own
# functions and silently drop ours.

set -e

# serialize invocations: rapid toggling can otherwise race on the same /config/usb_gadget/g1 tree
# and leave it in a half-built state
LOCKFILE="/tmp/set_usb_storage.lock"
exec 9>"$LOCKFILE"
flock 9

IMG="/data/media/0/usb_storage.img"
LOOP_MNT="/tmp/usb_storage_mnt"
REALDATA="/data/media/0/realdata"
UDC_NAME="a600000.dwc3"
GADGET="/config/usb_gadget/g1"
SAFETY_MARGIN_KB=$((2 * 1024 * 1024))   # keep 2GB free on /data after the image
CAP_KB=$((4 * 1024 * 1024))             # never build more than a 4GB snapshot (FAT32 + dir overhead eats into this)

build_image() {
  avail_kb=$(df --output=avail -k /data | tail -1)
  budget_kb=$((avail_kb - SAFETY_MARGIN_KB))
  if [ "$budget_kb" -gt "$CAP_KB" ]; then
    budget_kb=$CAP_KB
  fi
  if [ "$budget_kb" -lt $((512 * 1024)) ]; then
    echo "Not enough free space on /data to build a USB storage snapshot" >&2
    exit 1
  fi

  echo "Building ${budget_kb}KB FAT32 snapshot image at $IMG"
  sudo rm -f "$IMG"
  sudo fallocate -l "${budget_kb}K" "$IMG" || sudo dd if=/dev/zero of="$IMG" bs=1M count=$((budget_kb / 1024))
  sudo mkfs.vfat -F 32 -n IQPILOT "$IMG"

  sudo mkdir -p "$LOOP_MNT"
  LOOP_DEV=$(sudo losetup -f)
  sudo losetup "$LOOP_DEV" "$IMG"
  sudo mount -t vfat "$LOOP_DEV" "$LOOP_MNT"

  # select the most recent files up to budget, then copy them in one rsync
  # pass (this script already runs as root, and one process beats thousands
  # of per-file forked sudo/mkdir/cp calls, which was previously the actual
  # bottleneck, not disk throughput).
  copy_budget_kb=$((budget_kb * 90 / 100))
  filelist=$(mktemp)
  find "$REALDATA" -type f -printf '%T@ %s %P\n' 2>/dev/null | sort -rn | awk -v budget="$copy_budget_kb" '
    { used += int(($2 + 1023) / 1024); if (used > budget) { exit } print $3 }
  ' > "$filelist"
  mkdir -p "$LOOP_MNT/realdata"
  # FAT32 has no concept of unix owner/group/perms, so don't ask rsync to preserve them
  rsync -rt --files-from="$filelist" "$REALDATA/" "$LOOP_MNT/realdata/"
  echo "Copied $(wc -l < "$filelist") files into snapshot"
  rm -f "$filelist"

  sudo umount "$LOOP_MNT"
  sudo losetup -d "$LOOP_DEV"
}

unbind() {
  if [ -d "$GADGET" ]; then
    cd "$GADGET"
    echo "" | sudo tee UDC >/dev/null 2>&1 || true
  fi
}

ensure_base() {
  if ! mountpoint -q /config; then
    sudo mount -t configfs none /config
  fi
  sudo mkdir -p "$GADGET/strings/0x409" "$GADGET/configs/c.1/strings/0x409"
  cd "$GADGET"
  [ -s idVendor ] || echo 0x04D8 | sudo tee idVendor >/dev/null
  [ -s idProduct ] || echo 0x1235 | sudo tee idProduct >/dev/null
  [ -s strings/0x409/serialnumber ] || echo "$(cat /proc/cmdline | sed -e 's/^.*androidboot.serialno=//' -e 's/ .*$//')" | sudo tee strings/0x409/serialnumber >/dev/null
  [ -s strings/0x409/manufacturer ] || echo "comma.ai" | sudo tee strings/0x409/manufacturer >/dev/null
  [ -s strings/0x409/product ] || echo "IQ.Pilot" | sudo tee strings/0x409/product >/dev/null
  [ -s configs/c.1/MaxPower ] || echo 250 | sudo tee configs/c.1/MaxPower >/dev/null
  [ -s configs/c.1/strings/0x409/configuration ] || echo "IQ.Pilot" | sudo tee configs/c.1/strings/0x409/configuration >/dev/null
}

add_adb() {
  # same rationale as add_mass_storage: start from a clean slate to avoid stale busy attributes
  remove_adb
  cd "$GADGET"
  sudo mkdir -p functions/ncm.0 functions/ffs.adb
  sudo mkdir -p /dev/usb-ffs/adb
  if ! mountpoint -q /dev/usb-ffs/adb; then
    sudo mount -t functionfs adb /dev/usb-ffs/adb
  fi
  sudo rm -f configs/c.1/ncm.0 configs/c.1/ffs.adb
  sudo ln -s functions/ncm.0 configs/c.1/
  sudo ln -s functions/ffs.adb configs/c.1/
  setprop service.adb.tcp.port -1 2>/dev/null || true
  sudo systemctl start adbd
  # adbd needs a moment to open the ffs endpoint and negotiate descriptors before the gadget can bind
  sleep 1
}

remove_adb() {
  sudo systemctl stop adbd || true
  if [ -d "$GADGET" ]; then
    cd "$GADGET"
    sudo rm -f configs/c.1/ncm.0 configs/c.1/ffs.adb
    sudo umount /dev/usb-ffs/adb 2>/dev/null || true
    sudo rmdir functions/ncm.0 functions/ffs.adb 2>/dev/null || true
  fi
}

add_mass_storage() {
  # a function group that's ever been bound before can refuse attribute writes ("Device or
  # resource busy") until it's torn down and recreated fresh, so always start from a clean slate
  remove_mass_storage
  cd "$GADGET"
  sudo mkdir -p functions/mass_storage.0
  echo 1 | sudo tee functions/mass_storage.0/stall >/dev/null
  echo 1 | sudo tee functions/mass_storage.0/lun.0/removable >/dev/null
  echo 1 | sudo tee functions/mass_storage.0/lun.0/ro >/dev/null
  echo "$IMG" | sudo tee functions/mass_storage.0/lun.0/file >/dev/null
  sudo rm -f configs/c.1/mass_storage.0
  sudo ln -s functions/mass_storage.0 configs/c.1/
}

remove_mass_storage() {
  if [ -d "$GADGET" ]; then
    cd "$GADGET"
    sudo rm -f configs/c.1/mass_storage.0
    sudo rmdir functions/mass_storage.0 2>/dev/null || true
  fi
}

bind() {
  cd "$GADGET"
  for attempt in $(seq 1 20); do
    if echo "$UDC_NAME" | sudo tee UDC >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "$UDC_NAME" | sudo tee UDC
}

read_bool_param() {
  [ -f "$1" ] && [ "$(< "$1")" == "1" ]
}

USB_STORAGE_ENABLE=0
read_bool_param "/data/params/d/UsbStorageEnabled" && USB_STORAGE_ENABLE=1
ADB_ENABLE=0
read_bool_param "/data/params/d/AdbEnabled" && ADB_ENABLE=1

unbind
ensure_base

if [ "$ADB_ENABLE" == "1" ]; then
  add_adb
else
  remove_adb
fi

if [ "$USB_STORAGE_ENABLE" == "1" ]; then
  echo "Enabling USB storage mode"
  if [ ! -f "$IMG" ] || [ "$1" == "--rebuild" ]; then
    build_image
  fi
  add_mass_storage
else
  echo "Disabling USB storage mode"
  remove_mass_storage
fi

bind
