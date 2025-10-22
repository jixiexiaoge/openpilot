#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export FINGERPRINT='VOLKSWAGEN_ID4_MK1'
export ATHENA_HOST=wss://athena.konik.ai
export MAPS_HOST=https://api.konik.ai/maps
export SKIP_FW_QUERY=1

if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="12.4"
fi

export STAGING_ROOT="/data/safe_staging"
