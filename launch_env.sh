#!/usr/bin/env bash

export FINGERPRINT='VOLKSWAGEN_ID4_MK1'
export SKIP_FW_QUERY=1

if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="12.4"
fi

export STAGING_ROOT="/data/safe_staging"
