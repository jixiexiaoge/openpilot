#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Provisions the `mapd` routing binary authored by Jacob Pfeifer (github.com/pfeiferj/mapd).
The binary itself is his work; this module only fetches, verifies and stages it on-device.
"""
import hashlib
import logging
import os
import stat
import time
from pathlib import Path

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
_HTTP_TIMEOUT_S = 60
_FETCH_ATTEMPTS = 5
_NET_PROBE_ATTEMPTS = 10
_NET_PROBE_INTERVAL_S = 2


def sha256_of_file(path: str) -> str:
  """Hex SHA-256 digest of a file on disk."""
  digest = hashlib.sha256()
  with open(path, "rb") as handle:
    for block in iter(lambda: handle.read(1 << 20), b""):
      digest.update(block)
  return digest.hexdigest()


def stamp_vendor_version(version: str, params: Params | None = None) -> None:
  (params or Params()).put(_VERSION_PARAM, version)


class VendorMapdInstaller:
  def __init__(self, spinner_ref: Spinner):
    self._spinner = spinner_ref
    self._params = Params()

  # --- externally consumed surface -----------------------------------------
  def get_installed_version(self) -> str:
    return str(self._params.get(_VERSION_PARAM) or "")

  @staticmethod
  def ensure_directories_exist() -> None:
    for directory in (Paths.mapd_root(), VENDOR_MAPD_BIN_DIR):
      os.makedirs(directory, exist_ok=True)

  def check_and_download(self) -> None:
    if not self._binary_up_to_date():
      self._provision()

  def non_prebuilt_install(self) -> None:
    if self._on_metered_link():
      self._say("Metered connection detected — offline maps engine will not download here.")
      time.sleep(5)
      return

    try:
      self.ensure_directories_exist()
      if self._binary_up_to_date():
        self._say("Offline maps engine already present and current.")
        time.sleep(0.1)
        return

      if self._block_until_online():
        self._say(f"Retrieving offline maps engine [{self.get_installed_version() or 'none'}] -> [{VENDOR_RELEASE_TAG}]")
        time.sleep(0.1)
        self._provision()
      self._spinner.close()
    except Exception as exc:  # noqa: BLE001
      self._announce_failure(exc)

  # --- internal ------------------------------------------------------------
  def _expected_hash(self) -> str:
    try:
      with open(_HASH_FILE) as f:
        return f.read().strip()
    except OSError:
      return ""

  def _binary_up_to_date(self) -> bool:
    if not os.path.exists(VENDOR_MAPD_PATH):
      return False
    if self.get_installed_version() != VENDOR_RELEASE_TAG:
      return False
    reference = self._expected_hash()
    if not reference:
      return True
    try:
      return sha256_of_file(VENDOR_MAPD_PATH) == reference
    except OSError:
      return False

  def _provision(self) -> None:
    self.ensure_directories_exist()
    if self._retrieve_binary():
      stamp_vendor_version(VENDOR_RELEASE_TAG, self._params)

  def _retrieve_binary(self) -> bool:
    staging = Path(f"{VENDOR_MAPD_PATH}.part")
    last_error: Exception | None = None
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
      try:
        with requests.get(VENDOR_RELEASE_URL, stream=True, timeout=_HTTP_TIMEOUT_S) as resp:
          resp.raise_for_status()
          with open(staging, "wb") as out:
            for chunk in resp.iter_content(chunk_size=1 << 16):
              out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(staging, os.lstat(staging).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        staging.replace(VENDOR_MAPD_PATH)
        return True
      except requests.exceptions.RequestException as exc:
        last_error = exc
        self._say(f"offline maps fetch attempt {attempt}/{_FETCH_ATTEMPTS} did not complete ({exc})")
        time.sleep(0.5)
    staging.unlink(missing_ok=True)
    logging.error("offline maps engine could not be fetched after %d attempts: %s", _FETCH_ATTEMPTS, last_error)
    return False

  def _on_metered_link(self) -> bool:
    sm = messaging.SubMaster(["deviceState"])
    return bool(sm["deviceState"].networkMetered)

  def _block_until_online(self) -> bool:
    for i in range(1, _NET_PROBE_ATTEMPTS + 1):
      self._say(f"Waiting for a usable network connection... [{i}/{_NET_PROBE_ATTEMPTS}]")
      if self._link_reachable():
        return True
      time.sleep(_NET_PROBE_INTERVAL_S)
    return False

  @staticmethod
  def _link_reachable() -> bool:
    try:
      requests.head(VENDOR_RELEASE_URL, timeout=10, allow_redirects=True)
      return True
    except requests.exceptions.RequestException as exc:
      logging.debug("network probe failed: %s", exc)
      return False

  def _announce_failure(self, exc: Exception) -> None:
    for remaining in range(5, 0, -1):
      self._say(f"Offline maps engine unavailable; navigation stays online-only. Boot continues in {remaining}s...")
      time.sleep(1)
    logging.exception("vendor mapd install failed")
    sentry.init(sentry.SentryProject.SELFDRIVE)
    sentry.capture_exception(exc)

  def _say(self, text: str) -> None:
    self._spinner.update(text)


if __name__ == "__main__":
  spinner = Spinner()
  installer = VendorMapdInstaller(spinner)
  installer.ensure_directories_exist()
  if is_prebuilt():
    spinner.update(f"[DEBUG] Prebuilt build; vendor mapd install skipped. "
                   f"target [{VENDOR_RELEASE_TAG}], param [{installer.get_installed_version()}]")
    stamp_vendor_version(VENDOR_RELEASE_TAG)
  else:
    spinner.update(f"Verifying vendor mapd install. prebuilt [{is_prebuilt()}]")
    installer.non_prebuilt_install()
