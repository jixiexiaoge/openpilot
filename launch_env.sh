#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# models get lower priority than ui
# - ui is ~5ms
# - modeld is 20ms
# - DM is 10ms
# in order to run ui at 60fps (16.67ms), we need to allow
# it to preempt the model workloads. we have enough
# headroom for this until ui is moved to the CPU.
export QCOM_PRIORITY=12

if [ -z "$AGNOS_VERSION" ]; then
  DEVICE_MODEL=""
  if [ -f /sys/firmware/devicetree/base/model ]; then
    DEVICE_MODEL="$(tr -d '\0' </sys/firmware/devicetree/base/model)"
  fi

  case "$DEVICE_MODEL" in
    *)
      export AGNOS_VERSION="IQ.OS 3.7"
      # comma 3 (tici) now runs the same IQ.OS image (boot has comma_tici.dtb); stock 15.1
      # devices get flashed up to IQ.OS 3.7 on update. no compat list = force the upgrade.
      # 3.5 adds screen_calibration.service (per-unit DWO panel gamma on comma 4/mici).
      # 3.6 fixes the setup Beta picker installing release-new (BETA_URL -> IQLvbs/beta).
      # 3.7 fixes screen_calibration running too early (DWO mipi_command write was EINVAL);
      #     now runs After=weston-ready + retries until the panel accepts the gamma write.
      ;;
  esac
fi

export STAGING_ROOT="/data/safe_staging"
