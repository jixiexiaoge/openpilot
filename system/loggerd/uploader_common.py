#!/usr/bin/env python3
import os

from openpilot.common.swaglog import cloudlog


def get_directory_sort(d: str) -> list[str]:
  prefix = ["0"] if d.startswith("2024-") else ["1"]
  return prefix + [s.rjust(10, "0") for s in d.rsplit("--", 1)]


def listdir_by_creation(d: str) -> list[str]:
  if not os.path.isdir(d):
    return []

  try:
    paths = [f for f in os.listdir(d) if os.path.isdir(os.path.join(d, f))]
    return sorted(paths, key=get_directory_sort)
  except OSError:
    cloudlog.exception("uploader_common.listdir_by_creation_failed")
    return []
