#!/usr/bin/env python3
"""
IQ.OS compatibility check + in-place AGNOS update for the setup flow.

A chosen IQ.Pilot channel may target a newer IQ.OS than the device is running
(its cloned tree pins the required version in launch_env.sh AGNOS_VERSION). When
that differs from the running /VERSION, the setup flow flashes the target IQ.OS
via comma's own agnos.py BEFORE writing continue.sh, so the single reboot lands
on a compatible OS. The risky flashing is delegated entirely to agnos.py; this
module only reads versions, picks the right manifest, and streams coarse
progress.
"""
import json
import os
import re
import subprocess
import threading
from typing import Callable

VERSION_PATH = "/VERSION"


def current_os_version() -> str:
  try:
    with open(VERSION_PATH) as f:
      return f.read().strip()
  except Exception:
    return ""


def required_agnos_version(install_path: str) -> str:
  """Read the target OS version the cloned fork pins in launch_env.sh."""
  path = os.path.join(install_path, "launch_env.sh")
  try:
    with open(path) as f:
      for line in f:
        m = re.search(r'AGNOS_VERSION\s*=\s*"([^"]+)"', line)
        if m:
          return m.group(1).strip()
  except Exception:
    pass
  return ""


def agnos_manifest_path(install_path: str, device_type: str) -> str:
  # comma 3 (tici) uses a different AGNOS manifest than comma 3x (tizi) / comma 4 (mici).
  fname = "agnos_tici_15_1.json" if device_type == "tici" else "agnos.json"
  return os.path.join(install_path, "system", "hardware", "tici", fname)


def os_update_needed(install_path: str) -> tuple[bool, str, str]:
  """Returns (needed, current, required)."""
  current = current_os_version()
  required = required_agnos_version(install_path)
  needed = bool(required and current and required != current)
  return needed, current, required


ProgressCb = Callable[[int, str], None]


def run_agnos_update(install_path: str, device_type: str, progress_cb: ProgressCb) -> bool:
  """Flash + swap to the target IQ.OS. Streams coarse partition-level progress
  via progress_cb(percent, note). Returns True on success. The device must be
  rebooted by the caller afterward for the new slot to take effect."""
  manifest = agnos_manifest_path(install_path, device_type)
  agnos_py = os.path.join(install_path, "system", "hardware", "tici", "agnos.py")
  if not os.path.isfile(manifest) or not os.path.isfile(agnos_py):
    progress_cb(0, "manifest_missing")
    return False

  try:
    total_partitions = max(1, len(json.load(open(manifest))))
  except Exception:
    total_partitions = 1

  progress_cb(1, "starting")
  try:
    proc = subprocess.Popen(
      ["python3", agnos_py, "--swap", manifest],
      cwd=install_path,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True,
      env={**os.environ, "PYTHONPATH": install_path},
    )
  except Exception:
    progress_cb(0, "launch_failed")
    return False

  completed = 0
  swapping = False
  assert proc.stdout is not None
  for line in proc.stdout:
    line = line.strip()
    if "Downloading and writing" in line or "Already flashed" in line:
      completed += 1
      pct = min(94, int((completed / total_partitions) * 90) + 2)
      progress_cb(pct, "flashing")
    elif "Swapping to slot" in line or "AGNOS ready" in line:
      swapping = True
      progress_cb(96, "swapping")
  proc.wait()
  if proc.returncode == 0:
    progress_cb(100, "done")
    return True
  progress_cb(0, "failed" if not swapping else "swap_failed")
  return False


class OsUpdateCoordinator:
  """Bridges the setup UI's install thread and the BLE confirmation from the app.
  The install thread posts a required-update, waits for the phone's confirm, then
  runs the flash. On-screen setup can confirm locally too."""

  def __init__(self):
    self.confirmed = threading.Event()
    self.needed = False
    self.current = ""
    self.required = ""

  def request(self, current: str, required: str) -> None:
    self.needed = True
    self.current = current
    self.required = required
    self.confirmed.clear()

  def confirm(self) -> None:
    self.confirmed.set()

  def wait_for_confirm(self, timeout: float) -> bool:
    return self.confirmed.wait(timeout=timeout)
