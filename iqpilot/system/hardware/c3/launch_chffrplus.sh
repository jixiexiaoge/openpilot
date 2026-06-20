#!/usr/bin/env bash

IQ_C3_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
DIR="$( cd "$IQ_C3_DIR/../../../.." >/dev/null 2>&1 && pwd )"

source "$IQ_C3_DIR/launch_env.sh"

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


  CURRENT_AGNOS_VERSION=$(< /VERSION)
  if ! agnos_version_allowed "$CURRENT_AGNOS_VERSION" "$AGNOS_VERSION"; then
    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    MANIFEST="$IQ_C3_DIR/agnos.json"
    if $AGNOS_PY --verify $MANIFEST; then
      sudo reboot
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
  export PYTHONPATH="$PWD"

  # Install independent systemd services BEFORE build so they run even
  # when openpilot fails to compile — SSH/BLE/hephaestusd must always
  # be reachable for device recovery.
  for service_name in hephaestusd ble-transportd; do
    service_src="$DIR/system/${service_name}.service"
    service_dst="/etc/systemd/system/${service_name}.service"
    if [ -f "$service_src" ]; then
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

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
  fi

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd $DIR/system/manager
  if [ ! -f $DIR/prebuilt ]; then
    ./build.py
  fi

  ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
