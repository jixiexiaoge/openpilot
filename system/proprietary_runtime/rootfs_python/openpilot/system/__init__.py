from __future__ import annotations

import os
from pathlib import Path


def _resolve_source_pkg() -> Path:
  raw_root = os.environ.get("IQPILOT_SOURCE_ROOT") or os.environ.get("OPENPILOT_SOURCE_ROOT") or "/data/openpilot/openpilot"
  source_root = Path(raw_root)
  if source_root.name == "openpilot":
    return source_root / "system"
  return source_root / "openpilot" / "system"


def _extend_package_path() -> None:
  source_pkg = _resolve_source_pkg()
  if source_pkg.is_dir():
    pkg_path = str(source_pkg)
    if pkg_path not in __path__:
      __path__.append(pkg_path)


_extend_package_path()
