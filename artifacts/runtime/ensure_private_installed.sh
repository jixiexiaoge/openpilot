#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." >/dev/null && pwd )"
INSTALL_ROOT="${ROOT_DIR}/.iqpilot"
VERIFY_SCRIPT="${ROOT_DIR}/artifacts/runtime/verify_proprietary_bundle.py"

manifest_hash() {
  local manifest_path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${manifest_path}" | awk '{print $1}'
  else
    shasum -a 256 "${manifest_path}" | awk '{print $1}'
  fi
}

NAVD_BUNDLE="${ROOT_DIR}/artifacts/iqpilot_navd_private"
HEPHA_BUNDLE="${ROOT_DIR}/artifacts/iqpilot_hephaestusd_private"
MODEL_SELECTOR_BUNDLE="${ROOT_DIR}/artifacts/iqpilot_model_selector_private"
ALC_BUNDLE="${ROOT_DIR}/artifacts/iqpilot_alc_private"
VALHALLA_RUNTIME_BUNDLE="${ROOT_DIR}/artifacts/iqpilot_valhalla_runtime"
NAVD_STATE_FILE="${INSTALL_ROOT}/.installed_navd_manifest.sha256"
HEPHA_STATE_FILE="${INSTALL_ROOT}/.installed_hephaestusd_manifest.sha256"
MODEL_SELECTOR_STATE_FILE="${INSTALL_ROOT}/.installed_model_selector_manifest.sha256"
ALC_STATE_FILE="${INSTALL_ROOT}/.installed_alc_manifest.sha256"
VALHALLA_RUNTIME_STATE_FILE="${INSTALL_ROOT}/.installed_valhalla_runtime_manifest.sha256"
NAVD_SENTINEL_BASE="${INSTALL_ROOT}/python/iqpilot_private/navd/navd"
HEPHA_SENTINEL_BASE="${INSTALL_ROOT}/python/iqpilot_private/konn3kt/hephaestus/hephaestusd"
MODEL_SELECTOR_SENTINEL_BASE="${INSTALL_ROOT}/python/iqpilot_private/models/manager"
ALC_SENTINEL_BASE="${INSTALL_ROOT}/python/iqpilot_private/konn3kt/iqlvbs/alc"
VALHALLA_RUNTIME_SENTINEL="${INSTALL_ROOT}/valhalla_runtime/bin/valhalla_service"

NAVD_HASH=""
HEPHA_HASH=""
MODEL_SELECTOR_HASH=""
ALC_HASH=""
VALHALLA_RUNTIME_HASH=""
NEED_INSTALL=0
HAVE_BUNDLE=0

seed_hepha_ble_runtime() {
  if [ ! -f "${HEPHA_BUNDLE}/manifest.json" ]; then
    return 0
  fi

  PYTHONPATH="${ROOT_DIR}" python3 <<'PY'
from pathlib import Path
import os
import secrets

BLE_ENABLE_PARAM = "Konn3ktBleTransportEnabled"
PRIMARY_AUTH_DIR = Path("/data/konn3kt_ble")
FALLBACK_AUTH_DIR = Path("/data/openpilot/.konn3kt_ble")


def ensure_dir(path: Path, mode: int) -> bool:
  try:
    path.mkdir(parents=True, exist_ok=True)
    try:
      os.chmod(path, mode)
    except Exception:
      pass
    return True
  except Exception:
    return False


def write_if_missing(path: Path, contents: str, mode: int) -> None:
  if path.exists():
    return
  path.write_text(contents, encoding="utf-8")
  try:
    os.chmod(path, mode)
  except Exception:
    pass


def seed_ble_enable_param() -> None:
  try:
    from openpilot.common.params import Params
    params = Params()
    if params.get(BLE_ENABLE_PARAM) is None:
      params.put_bool(BLE_ENABLE_PARAM, True)
    return
  except Exception:
    pass

  param_path = Path("/data/params/d") / BLE_ENABLE_PARAM
  if ensure_dir(param_path.parent, 0o755):
    try:
      if not param_path.exists():
        param_path.write_bytes(b"1")
    except Exception:
      pass


def seed_ble_auth_artifacts() -> None:
  auth_dir = None
  for candidate in (PRIMARY_AUTH_DIR, FALLBACK_AUTH_DIR):
    if ensure_dir(candidate, 0o700):
      auth_dir = candidate
      break

  if auth_dir is None:
    return

  write_if_missing(auth_dir / "approved_clients.json", "{}\n", 0o600)
  write_if_missing(auth_dir / "install_credentials.json", "{}\n", 0o600)
  write_if_missing(auth_dir / "dev_secret", f"{secrets.token_hex(32)}\n", 0o600)


seed_ble_enable_param()
seed_ble_auth_artifacts()
PY

  if [ -d /usr/lib/python3/dist-packages/gi ]; then
    ln -sfn /usr/lib/python3/dist-packages/gi "${ROOT_DIR}/gi"
  fi
}

module_present() {
  local base_path="$1"
  if [ -f "${base_path}.pyc" ]; then
    return 0
  fi
  if compgen -G "${base_path}".*.so >/dev/null; then
    return 0
  fi
  return 1
}

if [ -f "${NAVD_BUNDLE}/manifest.json" ]; then
  HAVE_BUNDLE=1
  NAVD_HASH="$(manifest_hash "${NAVD_BUNDLE}/manifest.json")"
  NAVD_DST_HASH=""
  if [ -f "${NAVD_STATE_FILE}" ]; then
    NAVD_DST_HASH="$(cat "${NAVD_STATE_FILE}" 2>/dev/null || true)"
  fi
  if ! module_present "${NAVD_SENTINEL_BASE}" || [ "${NAVD_HASH}" != "${NAVD_DST_HASH}" ]; then
    NEED_INSTALL=1
  fi
fi

if [ -f "${HEPHA_BUNDLE}/manifest.json" ]; then
  HAVE_BUNDLE=1
  HEPHA_HASH="$(manifest_hash "${HEPHA_BUNDLE}/manifest.json")"
  HEPHA_DST_HASH=""
  if [ -f "${HEPHA_STATE_FILE}" ]; then
    HEPHA_DST_HASH="$(cat "${HEPHA_STATE_FILE}" 2>/dev/null || true)"
  fi
  if ! module_present "${HEPHA_SENTINEL_BASE}" || [ "${HEPHA_HASH}" != "${HEPHA_DST_HASH}" ]; then
    NEED_INSTALL=1
  fi
fi

if [ -f "${MODEL_SELECTOR_BUNDLE}/manifest.json" ]; then
  HAVE_BUNDLE=1
  MODEL_SELECTOR_HASH="$(manifest_hash "${MODEL_SELECTOR_BUNDLE}/manifest.json")"
  MODEL_SELECTOR_DST_HASH=""
  if [ -f "${MODEL_SELECTOR_STATE_FILE}" ]; then
    MODEL_SELECTOR_DST_HASH="$(cat "${MODEL_SELECTOR_STATE_FILE}" 2>/dev/null || true)"
  fi
  if ! module_present "${MODEL_SELECTOR_SENTINEL_BASE}" || [ "${MODEL_SELECTOR_HASH}" != "${MODEL_SELECTOR_DST_HASH}" ]; then
    NEED_INSTALL=1
  fi
fi

if [ -f "${ALC_BUNDLE}/manifest.json" ]; then
  HAVE_BUNDLE=1
  ALC_HASH="$(manifest_hash "${ALC_BUNDLE}/manifest.json")"
  ALC_DST_HASH=""
  if [ -f "${ALC_STATE_FILE}" ]; then
    ALC_DST_HASH="$(cat "${ALC_STATE_FILE}" 2>/dev/null || true)"
  fi
  if ! module_present "${ALC_SENTINEL_BASE}" || [ "${ALC_HASH}" != "${ALC_DST_HASH}" ]; then
    NEED_INSTALL=1
  fi
fi

if [ -f "${VALHALLA_RUNTIME_BUNDLE}/manifest.json" ]; then
  HAVE_BUNDLE=1
  VALHALLA_RUNTIME_HASH="$(manifest_hash "${VALHALLA_RUNTIME_BUNDLE}/manifest.json")"
  VALHALLA_RUNTIME_DST_HASH=""
  if [ -f "${VALHALLA_RUNTIME_STATE_FILE}" ]; then
    VALHALLA_RUNTIME_DST_HASH="$(cat "${VALHALLA_RUNTIME_STATE_FILE}" 2>/dev/null || true)"
  fi
  if [ ! -x "${VALHALLA_RUNTIME_SENTINEL}" ] || [ "${VALHALLA_RUNTIME_HASH}" != "${VALHALLA_RUNTIME_DST_HASH}" ]; then
    NEED_INSTALL=1
  fi
fi

if [ "${HAVE_BUNDLE}" -eq 0 ]; then
  exit 0
fi

if [ "${NEED_INSTALL}" -eq 0 ]; then
  seed_hepha_ble_runtime || true
  exit 0
fi

TMP_ROOT="${INSTALL_ROOT}.tmp.$$"
echo "Installing bundled private artifacts..."
rm -rf "${TMP_ROOT}"
mkdir -p "${TMP_ROOT}"

if [ -d "${INSTALL_ROOT}" ]; then
  cp -a "${INSTALL_ROOT}"/. "${TMP_ROOT}/"
fi

if [ -f "${NAVD_BUNDLE}/manifest.json" ]; then
  python3 "${VERIFY_SCRIPT}" "${NAVD_BUNDLE}"
  cp -a "${NAVD_BUNDLE}"/. "${TMP_ROOT}/"
fi

if [ -f "${HEPHA_BUNDLE}/manifest.json" ]; then
  python3 "${VERIFY_SCRIPT}" "${HEPHA_BUNDLE}"
  cp -a "${HEPHA_BUNDLE}"/. "${TMP_ROOT}/"
fi

if [ -f "${MODEL_SELECTOR_BUNDLE}/manifest.json" ]; then
  python3 "${VERIFY_SCRIPT}" "${MODEL_SELECTOR_BUNDLE}"
  cp -a "${MODEL_SELECTOR_BUNDLE}"/. "${TMP_ROOT}/"
fi

if [ -f "${ALC_BUNDLE}/manifest.json" ]; then
  python3 "${VERIFY_SCRIPT}" "${ALC_BUNDLE}"
  cp -a "${ALC_BUNDLE}"/. "${TMP_ROOT}/"
fi

if [ -f "${VALHALLA_RUNTIME_BUNDLE}/manifest.json" ]; then
  python3 "${VERIFY_SCRIPT}" "${VALHALLA_RUNTIME_BUNDLE}"
  cp -a "${VALHALLA_RUNTIME_BUNDLE}"/. "${TMP_ROOT}/"
fi

if [ -d "${INSTALL_ROOT}" ]; then
  rm -rf "${INSTALL_ROOT}.bak"
  mv "${INSTALL_ROOT}" "${INSTALL_ROOT}.bak"
fi

mv "${TMP_ROOT}" "${INSTALL_ROOT}"

if [ -d "${INSTALL_ROOT}.bak" ]; then
  rm -rf "${INSTALL_ROOT}.bak"
fi

if [ -n "${NAVD_HASH}" ]; then
  printf '%s\n' "${NAVD_HASH}" > "${NAVD_STATE_FILE}"
fi
if [ -n "${HEPHA_HASH}" ]; then
  printf '%s\n' "${HEPHA_HASH}" > "${HEPHA_STATE_FILE}"
fi
if [ -n "${MODEL_SELECTOR_HASH}" ]; then
  printf '%s\n' "${MODEL_SELECTOR_HASH}" > "${MODEL_SELECTOR_STATE_FILE}"
fi
if [ -n "${ALC_HASH}" ]; then
  printf '%s\n' "${ALC_HASH}" > "${ALC_STATE_FILE}"
fi
if [ -n "${VALHALLA_RUNTIME_HASH}" ]; then
  printf '%s\n' "${VALHALLA_RUNTIME_HASH}" > "${VALHALLA_RUNTIME_STATE_FILE}"
fi

seed_hepha_ble_runtime || true

echo "Private artifacts installed."
