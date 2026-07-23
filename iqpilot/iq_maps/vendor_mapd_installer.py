#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Installs the `mapd` binary by Jacob Pfeifer (github.com/pfeiferj/mapd) — the binary is his work.
"""
import hashlib
import logging
import os
import stat
import time
import traceback
from pathlib import Path
from urllib.request import urlopen

import requests

from cereal import messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.system.hardware.hw import Paths
from openpilot.system.version import is_prebuilt
from openpilot.iqpilot.iq_maps import VENDOR_MAPD_BIN_DIR, VENDOR_MAPD_PATH
import openpilot.system.sentry as sentry

VENDOR_RELEASE_TAG = "v2.0.6"
VENDOR_RELEASE_URL = f"https://github.com/pfeiferj/mapd/releases/download/{VENDOR_RELEASE_TAG}/mapd"

_VERSION_PARAM = "MapdVersion"
_HASH_FILE = os.path.join(BASEDIR, "iqpilot", "iq_maps", "tests", "mapd_hash")
_DOWNLOAD_TIMEOUT_S = 60
_MAX_DOWNLOAD_TRIES = 5


def get_file_hash(path: str) -> str:
  """Hex SHA-256 of a file's contents."""
  with open(path, "rb") as handle:
    return hashlib.file_digest(handle, "sha256").hexdigest()


def stamp_vendor_version(version: str, params: Params | None = None) -> None:
  (params or Params()).put(_VERSION_PARAM, version)


def _pinned_hash() -> str:
  try:
    with open(_HASH_FILE) as f:
      return f.read().strip()
  except OSError:
    return ""


class VendorMapdInstaller:
  def __init__(self, spinner_ref: Spinner):
    self._spinner = spinner_ref
    self._params = Params()

  def get_installed_version(self) -> str:
    return str(self._params.get(_VERSION_PARAM) or "")

  @staticmethod
  def ensure_directories_exist() -> None:
    for d in (Paths.mapd_root(), VENDOR_MAPD_BIN_DIR):
      os.makedirs(d, exist_ok=True)

  def download_needed(self) -> bool:
    if not os.path.exists(VENDOR_MAPD_PATH):
      return True
    if self.get_installed_version() != VENDOR_RELEASE_TAG:
      return True
    pinned = _pinned_hash()
    if not pinned:
      return False
    try:
      return get_file_hash(VENDOR_MAPD_PATH) != pinned
    except OSError:
      return True

  def check_and_download(self) -> None:
    if self.download_needed():
      self.fetch()

  def fetch(self) -> None:
    self.ensure_directories_exist()
    if self._pull_binary():
      stamp_vendor_version(VENDOR_RELEASE_TAG, self._params)

  def _pull_binary(self) -> bool:
    scratch = Path(f"{VENDOR_MAPD_PATH}.tmp")
    for attempt in range(1, _MAX_DOWNLOAD_TRIES + 1):
      try:
        resp = requests.get(VENDOR_RELEASE_URL, stream=True, timeout=_DOWNLOAD_TIMEOUT_S)
        resp.raise_for_status()
        with open(scratch, "wb") as out:
          out.write(resp.content)
          out.flush()
          os.fsync(out.fileno())
        mode = stat.S_IMODE(os.lstat(scratch).st_mode)
        os.chmod(scratch, mode | stat.S_IEXEC)
        scratch.replace(VENDOR_MAPD_PATH)
        return True
      except requests.exceptions.RequestException as e:
        self._spinner.update(f"mapd download failed ({e}); retry {attempt}/{_MAX_DOWNLOAD_TRIES}")
        time.sleep(0.5)
    scratch.unlink(missing_ok=True)
    logging.error("mapd binary download failed after %d attempts", _MAX_DOWNLOAD_TRIES)
    return False

  def wait_for_internet_connection(self, return_on_failure: bool = False) -> bool:
    attempts = 10
    for i in range(attempts + 1):
      self._spinner.update(f"Waiting for internet connection... [{i}/{attempts}]")
      time.sleep(2)
      try:
        urlopen("https://sentry.io", timeout=10)
        return True
      except Exception as e:  # noqa: BLE001
        print(f"Wait for internet failed: {e}")
        if return_on_failure and i == attempts:
          return False
    return False

  def non_prebuilt_install(self) -> None:
    sm = messaging.SubMaster(["deviceState"])
    if sm["deviceState"].networkMetered:
      self._spinner.update("Can't proceed with mapd install since network is metered!")
      time.sleep(5)
      return

    try:
      self.ensure_directories_exist()
      if not self.download_needed():
        self._spinner.update("Offline maps binary is ready.")
        time.sleep(0.1)
        return

      if self.wait_for_internet_connection(return_on_failure=True):
        self._spinner.update(f"Downloading vendor mapd [{self.get_installed_version()}] => [{VENDOR_RELEASE_TAG}].")
        time.sleep(0.1)
        self.check_and_download()
      self._spinner.close()
    except Exception:  # noqa: BLE001
      for i in range(6):
        self._spinner.update("Failed to download OSM maps won't work until properly downloaded!"
                             f"Try again manually rebooting. Boot will continue in {5 - i}s...")
        time.sleep(1)
      sentry.init(sentry.SentryProject.SELFDRIVE)
      traceback.print_exc()
      sentry.capture_exception()


if __name__ == "__main__":
  spinner = Spinner()
  installer = VendorMapdInstaller(spinner)
  installer.ensure_directories_exist()
  if is_prebuilt():
    spinner.update(f"[DEBUG] Prebuilt build; no vendor mapd install required. "
                   f"VERSION: [{VENDOR_RELEASE_TAG}], Param [{installer.get_installed_version()}]")
    stamp_vendor_version(VENDOR_RELEASE_TAG)
  else:
    spinner.update(f"Checking if vendor mapd is installed and valid. Prebuilt [{is_prebuilt()}]")
    installer.non_prebuilt_install()
