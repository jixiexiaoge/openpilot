from __future__ import annotations

import os
from pathlib import Path


VERIFIED_RUNTIME_ROOT = Path("/usr/libexec/iqpilot")
VERIFIED_RUNNER_PATH = VERIFIED_RUNTIME_ROOT / "iqpilot_bundle_runner"
VERIFIED_PYTHON_ROOT = VERIFIED_RUNTIME_ROOT / "python"
FALLBACK_RUNNER_PATH = Path("/data/openpilot/system/proprietary_runtime/iqpilot_bundle_runner")
DEFAULT_SOURCE_ROOT = Path("/data/openpilot/openpilot")


def verified_runtime_present() -> bool:
  return VERIFIED_RUNNER_PATH.is_file() and os.access(VERIFIED_RUNNER_PATH, os.X_OK)


def preferred_runner_path() -> Path:
  if verified_runtime_present():
    return VERIFIED_RUNNER_PATH
  if os.getenv("IQPILOT_ALLOW_DEV_FALLBACKS") == "1" and FALLBACK_RUNNER_PATH.is_file():
    return FALLBACK_RUNNER_PATH
  return VERIFIED_RUNNER_PATH


def preferred_pythonpath(existing: str = "") -> str:
  parts: list[str] = []
  if VERIFIED_PYTHON_ROOT.is_dir():
    parts.append(str(VERIFIED_PYTHON_ROOT))
  if existing:
    parts.append(existing)
  return ":".join(parts)
