#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="${IQPILOT_VERIFIED_RUNTIME_ROOT:-/usr/libexec/iqpilot}"
PYTHON_ROOT="${RUNTIME_ROOT}/python"
TARGET_EXT_DIR="${PYTHON_ROOT}/openpilot/system/proprietary_runtime"
MANIFEST_SRC="${ROOT}/system/proprietary_runtime/rootfs_integrity.json"
MANIFEST_SIG_SRC="${ROOT}/system/proprietary_runtime/rootfs_integrity.json.sig"

RUNNER_SRC="${ROOT}/system/proprietary_runtime/iqpilot_bundle_runner"
EXT_SRC="${ROOT}/system/proprietary_runtime/_verified_import.so"
STUB_ROOT="${ROOT}/system/proprietary_runtime/rootfs_python"

if [ ! -x "${RUNNER_SRC}" ]; then
  echo "missing runner: ${RUNNER_SRC}"
  exit 1
fi

if [ ! -f "${EXT_SRC}" ]; then
  echo "missing extension: ${EXT_SRC}"
  exit 1
fi

if [ ! -f "${MANIFEST_SRC}" ] || [ ! -f "${MANIFEST_SIG_SRC}" ]; then
  if [ -n "${IQPILOT_SIGNING_KEY:-}" ]; then
    "${ROOT}/.venv/bin/python" \
      "${ROOT}/scripts/iqpilot/build_proprietary_runtime_manifest.py" \
      --repo-root "${ROOT}" \
      --output "${MANIFEST_SRC}"
  fi
fi

if [ ! -f "${MANIFEST_SRC}" ] || [ ! -f "${MANIFEST_SIG_SRC}" ]; then
  echo "missing rootfs runtime integrity manifest or signature"
  exit 1
fi

sudo mount -o remount,rw /
trap 'sudo mount -o remount,ro /' EXIT

sudo mkdir -p "${RUNTIME_ROOT}" "${TARGET_EXT_DIR}"
sudo install -m 0755 "${RUNNER_SRC}" "${RUNTIME_ROOT}/iqpilot_bundle_runner"
sudo install -m 0755 "${EXT_SRC}" "${TARGET_EXT_DIR}/_verified_import.so"
sudo install -m 0644 "${MANIFEST_SRC}" "${RUNTIME_ROOT}/runtime_integrity.json"
sudo install -m 0644 "${MANIFEST_SIG_SRC}" "${RUNTIME_ROOT}/runtime_integrity.json.sig"
sudo install -m 0644 "${STUB_ROOT}/openpilot/__init__.py" "${PYTHON_ROOT}/openpilot/__init__.py"
sudo mkdir -p "${PYTHON_ROOT}/openpilot/system"
sudo install -m 0644 "${STUB_ROOT}/openpilot/system/__init__.py" "${PYTHON_ROOT}/openpilot/system/__init__.py"
sudo install -m 0644 "${STUB_ROOT}/openpilot/system/proprietary_runtime/__init__.py" "${TARGET_EXT_DIR}/__init__.py"

echo "installed verified runtime to ${RUNTIME_ROOT}"
