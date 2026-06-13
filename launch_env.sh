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
    *"comma tici"*|*"comma three"*)
      export AGNOS_VERSION="15.1"
      ;;
    *)
      export AGNOS_VERSION="16"
      ;;
  esac
fi

export STAGING_ROOT="/data/safe_staging"
