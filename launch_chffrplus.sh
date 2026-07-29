#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

function agnos_version_allowed {
  local current_version="$1"
  local expected_version="$2"
  local compat_version

  if [ "$current_version" = "$expected_version" ] || [[ "$current_version" = "$expected_version"-* ]]; then
    return 0
  fi

  IFS=',' read -r -a compat_versions <<< "${AGNOS_COMPAT_VERSIONS:-}"
  for compat_version in "${compat_versions[@]}"; do
    compat_version="${compat_version// /}"
    if [ -n "$compat_version" ] && [ "$current_version" = "$compat_version" ]; then
      return 0
    fi
  done

  return 1
}

function set_lite_hw() {
  # Detect mr.one C3 Lite: tici platform without a cellular modem at i2c 0x10
  if grep -q "tici" /sys/firmware/devicetree/base/model 2>/dev/null; then
    output=$(i2cget -y 0 0x10 0x00 2>/dev/null)
    if [ -z "$output" ]; then
      echo "C3 Lite hardware detected"
      export LITE=1
      echo "1" > /tmp/lite_hw
    fi
  fi
}

function agnos_init {
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # iptables-nft fails on this kernel (no nf_tables module), breaking NM hotspot NAT rules
  if [ "$(readlink /etc/alternatives/iptables)" != "/usr/sbin/iptables-legacy" ]; then
    sudo mount -o remount,rw /
    sudo ln -sf /usr/sbin/iptables-legacy /etc/alternatives/iptables
    sudo ln -sf /usr/sbin/iptables-legacy-restore /etc/alternatives/iptables-restore
    sudo ln -sf /usr/sbin/iptables-legacy-save /etc/alternatives/iptables-save
    sudo mount -o remount,ro /
  fi

  # Check if AGNOS update is required
  CURRENT_AGNOS_VERSION=$(< /VERSION)
  if ! agnos_version_allowed "$CURRENT_AGNOS_VERSION" "$AGNOS_VERSION"; then
    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    MANIFEST="$DIR/system/hardware/tici/agnos.json"
    if [ -f /sys/firmware/devicetree/base/model ]; then
      DEVICE_MODEL="$(tr -d '\0' </sys/firmware/devicetree/base/model)"
      case "$DEVICE_MODEL" in
        *"comma tici"*|*"comma three"*)
          # comma 3 keeps its stock 15.1 bootloaders: comma's 16 abl has a board-id
          # check that rejects comma 3 ("Unsupported firmware detected"). It still gets
          # the IQ boot (comma_tici.dtb) + IQ.OS 3.4 system via this hybrid manifest.
          MANIFEST="$DIR/system/hardware/tici/agnos_tici_15_1.json"
          ;;
      esac
    fi
    if $AGNOS_PY --verify $MANIFEST; then
      sudo reboot
    fi
    # On stock AGNOS the updater picks updater_weston (weston is up), a compiled display binary that
    # can't get a compositor surface on a first boot, so the IQ.OS flash silently wedges on the comma
    # logo. There, flash headless via agnos.py --swap (identical download+write+swap, no surface).
    # On IQ.OS weston is down -> the updater picks updater_magic (DRM), which renders the on-screen
    # progress prompt fine, so fall through and keep it. This mirrors the updater's own weston check.
    if systemctl is-active --quiet weston-ready; then
      if $AGNOS_PY --swap $MANIFEST; then
        sudo reboot
      fi
    fi
    $DIR/system/hardware/tici/updater $AGNOS_PY $MANIFEST
  fi
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi

  # Install/update proprietary runtime bundles.
  if [ -f "$DIR/artifacts/runtime/ensure_private_installed.sh" ]; then
    bash "$DIR/artifacts/runtime/ensure_private_installed.sh" || true
  elif [ -x "$DIR/scripts/iqpilot/ensure_navd_private_installed.sh" ]; then
    # Backward-compat fallback for older trees.
    "$DIR/scripts/iqpilot/ensure_navd_private_installed.sh" || true
  fi

  ln -sfn $(pwd) /data/pythonpath
  export IQPILOT_SOURCE_ROOT="${IQPILOT_SOURCE_ROOT:-$PWD/openpilot}"
  export PYTHONSAFEPATH=1
  VERIFIED_PYTHON_ROOT="/usr/libexec/iqpilot/python"
  if [ -d "$VERIFIED_PYTHON_ROOT" ]; then
    export PYTHONPATH="$VERIFIED_PYTHON_ROOT:$PWD"
  else
    export PYTHONPATH="$PWD"
  fi

  # Install independent systemd services BEFORE build so they run even
  # when openpilot fails to compile — SSH/BLE/hephaestusd must always
  # be reachable for device recovery.
  for service_name in hephaestusd ble-transportd; do
    service_src="$DIR/system/${service_name}.service"
    service_dst="/etc/systemd/system/${service_name}.service"
    service_lib="/lib/systemd/system/${service_name}.service"
    if [ -f "$service_lib" ] && grep -q "/usr/libexec/iqpilot/iqpilot_bundle_runner" "$service_lib"; then
      if [ -f "$service_dst" ]; then
        sudo mount -o remount,rw /
        sudo rm -f "$service_dst"
        sudo systemctl daemon-reload
        sudo mount -o remount,ro /
      fi
      sudo systemctl enable "${service_name}.service"
      if systemctl is-active --quiet "${service_name}.service"; then
        sudo systemctl restart "${service_name}.service"
      else
        sudo systemctl start "${service_name}.service"
      fi
    elif [ -f "$service_src" ]; then
      if [ ! -f "$service_dst" ] || ! cmp -s "$service_src" "$service_dst"; then
        sudo mount -o remount,rw /
        sudo cp "$service_src" "$service_dst"
        sudo systemctl daemon-reload
        sudo systemctl enable "${service_name}.service"
        sudo mount -o remount,ro /
        sudo systemctl restart "${service_name}.service"
      elif ! systemctl is-active --quiet "${service_name}.service"; then
        sudo systemctl start "${service_name}.service"
      fi
    fi
  done

  # detect mr.one C3 Lite hardware
  set_lite_hw

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init

    sudo "$DIR/system/hardware/tici/zram_setup.sh" || true
  fi

  if [ -f "$DIR/artifacts/runtime/apply_boot_branding.py" ]; then
    sudo python3 "$DIR/artifacts/runtime/apply_boot_branding.py" || true
  fi

  # /home is an ephemeral overlay (resets each boot); re-inject the source line. best-effort
  if [ -f "$DIR/tools/iqpilot/git-pretty.sh" ] && [ -w "$HOME/.bashrc" ]; then
    grep -q 'iqpilot/git-pretty.sh' "$HOME/.bashrc" 2>/dev/null || \
      echo "[ -f $DIR/tools/iqpilot/git-pretty.sh ] && source $DIR/tools/iqpilot/git-pretty.sh" >> "$HOME/.bashrc" || true
  fi

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd system/manager
  if [ ! -f $DIR/prebuilt ]; then
    if pkill -f /tmp/installer 2>/dev/null; then sleep 1; fi
    /usr/local/venv/bin/python3 ./build.py
  fi

  /usr/local/venv/bin/python3 ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
