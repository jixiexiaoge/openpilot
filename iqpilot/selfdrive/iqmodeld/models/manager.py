#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import asyncio
import hashlib
import os
import time
from pathlib import Path

import aiohttp
from cereal import custom
from openpilot.common.realtime import Ratekeeper
from openpilot.common.time_helpers import system_time_valid
from openpilot.iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths

_TIME_SYNC_WAIT_TIMEOUT_S = 30.0
_TIME_SYNC_POLL_S = 0.5


def _wait_for_valid_clock(timeout: float = _TIME_SYNC_WAIT_TIMEOUT_S) -> None:
  if system_time_valid():
    return
  cloudlog.warning("models_manager: system clock not yet valid, waiting for NTP before fetching")
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    if system_time_valid():
      cloudlog.warning("models_manager: system clock is now valid, resuming")
      return
    time.sleep(_TIME_SYNC_POLL_S)
  cloudlog.warning("models_manager: gave up waiting for a valid clock, proceeding anyway")

try:
  load_private_module(__name__, "iqpilot_private.models.manager")
  _BaseIQModelManager = IQModelManager  # noqa: F821
except ProprietaryModuleMissing:
  from iqpilot.models_private_src.manager import IQModelManager as _BaseIQModelManager

from openpilot.iqpilot.selfdrive.iqmodeld.models.git_auth import get_aiohttp_auth
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import (
  bundle_files_ready,
  get_active_bundle,
  get_runtime_bundle_upgrade,
  persist_active_bundle,
)


_ACTIVE_BUNDLE_KEY = "ModelManager_ActiveBundle"
_DOWNLOAD_INDEX_KEY = "ModelManager_DownloadIndex"
_RUNNER_CACHE_KEY = "ModelRunnerTypeCache"


class IQModelManager(_BaseIQModelManager):
  def __init__(self):
    super().__init__()
    self._validated_active_key: tuple[tuple[str, str], ...] | None = None

  @staticmethod
  def _bundle_index(bundle) -> int | None:
    try:
      return int(getattr(bundle, "index", -1))
    except (TypeError, ValueError):
      return None

  @staticmethod
  def _bundle_files(bundle) -> list[tuple[str, str]]:
    files = []
    for model in getattr(bundle, "models", []) or []:
      for artifact in (getattr(model, "metadata", None), getattr(model, "artifact", None)):
        filename = getattr(artifact, "fileName", "") if artifact is not None else ""
        if not filename:
          continue
        download_uri = getattr(artifact, "downloadUri", None)
        sha256 = getattr(download_uri, "sha256", "") if download_uri is not None else ""
        files.append((filename, sha256 or ""))
    return files

  @staticmethod
  def _safe_model_path(filename: str) -> Path | None:
    if not filename or os.path.basename(filename) != filename:
      cloudlog.warning(f"Ignoring unsafe model filename {filename!r}")
      return None

    root = Path(Paths.model_root()).resolve()
    path = (root / filename).resolve()
    try:
      path.relative_to(root)
    except ValueError:
      cloudlog.warning(f"Ignoring model path outside model root {path}")
      return None
    return path

  @staticmethod
  def _verify_file_sync(path: Path, expected_hash: str) -> bool:
    if not path.is_file():
      return False
    if not expected_hash:
      return True

    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
      for chunk in iter(lambda: f.read(1024 * 1024), b""):
        sha256_hash.update(chunk)
    return sha256_hash.hexdigest().lower() == expected_hash.lower()

  def _bundle_validation_key(self, bundle) -> tuple[tuple[str, str], ...]:
    return tuple(self._bundle_files(bundle))

  def _bundle_files_valid(self, bundle) -> bool:
    for filename, expected_hash in self._bundle_files(bundle):
      path = self._safe_model_path(filename)
      if path is None or not self._verify_file_sync(path, expected_hash):
        return False
    return True

  def _remove_bundle_files(self, bundle) -> None:
    for filename, _expected_hash in self._bundle_files(bundle):
      path = self._safe_model_path(filename)
      if path is None:
        continue
      for candidate in (path, Path(f"{path}.download")):
        try:
          if candidate.is_file():
            candidate.unlink()
        except OSError as e:
          cloudlog.exception(f"Failed to remove model artifact {candidate}: {e}")

  def _find_available_bundle(self, target):
    target_index = self._bundle_index(target)
    target_ref = getattr(target, "ref", None)
    target_internal = getattr(target, "internalName", None)
    target_display = getattr(target, "displayName", None)

    for bundle in self.available_models:
      if target_index is not None and self._bundle_index(bundle) == target_index:
        return bundle
      if target_ref and getattr(bundle, "ref", None) == target_ref:
        return bundle
      if target_internal and getattr(bundle, "internalName", None) == target_internal:
        return bundle
      if target_display and getattr(bundle, "displayName", None) == target_display:
        return bundle
    return None

  def _bundle_matches(self, left, right) -> bool:
    if left is None or right is None:
      return False

    left_index = self._bundle_index(left)
    right_index = self._bundle_index(right)
    if left_index is not None and right_index is not None and left_index == right_index:
      return True

    for attr in ("ref", "internalName", "displayName"):
      left_value = getattr(left, attr, None)
      if left_value and left_value == getattr(right, attr, None):
        return True
    return False

  def _clear_active_bundle(self) -> None:
    self.params.remove(_ACTIVE_BUNDLE_KEY)
    self.params.remove(_RUNNER_CACHE_KEY)
    self.active_bundle = None
    self._validated_active_key = None

  def _download_request_matches(self, bundle) -> bool:
    bundle_index = self._bundle_index(bundle)
    return bundle_index is not None and self._download_index() == bundle_index

  def _queue_active_redownload_if_invalid(self) -> None:
    if self.active_bundle is None:
      self._validated_active_key = None
      return

    validation_key = self._bundle_validation_key(self.active_bundle)
    if validation_key == self._validated_active_key:
      return

    if self._bundle_files_valid(self.active_bundle):
      self._validated_active_key = validation_key
      return

    bundle = self._find_available_bundle(self.active_bundle) or self.active_bundle
    bundle_index = self._bundle_index(bundle)
    cloudlog.warning(f"Active model {_display_bundle_name(self.active_bundle)} is missing or corrupt; queueing redownload")
    self._remove_bundle_files(bundle)
    self._clear_active_bundle()
    if bundle_index is not None and self._download_index() is None:
      self.params.put(_DOWNLOAD_INDEX_KEY, bundle_index)

  async def _download_file(self, url: str, path: str, model) -> None:
    temp_path = f"{path}.download"
    self._download_start_times[model.fileName] = time.monotonic()

    try:
      if os.path.exists(temp_path):
        os.remove(temp_path)

      async with aiohttp.ClientSession(auth=get_aiohttp_auth()) as session:
        async with session.get(url) as response:
          response.raise_for_status()
          total_size = int(response.headers.get("content-length", 0))
          bytes_downloaded = 0

          with open(temp_path, "wb") as f:
            async for chunk in response.content.iter_chunked(self._chunk_size):
              f.write(chunk)
              bytes_downloaded += len(chunk)

              if self._download_index() is None:
                raise Exception("Download cancelled")

              if total_size > 0:
                progress = (bytes_downloaded / total_size) * 100
                model.downloadProgress.status = custom.IQModelManager.DownloadStatus.downloading
                model.downloadProgress.progress = progress
                model.downloadProgress.eta = self._calculate_eta(model.fileName, progress)
                self._report_status()

            f.flush()
            os.fsync(f.fileno())

      os.replace(temp_path, path)

    except Exception:
      if os.path.exists(temp_path):
        os.remove(temp_path)
      raise

    finally:
      self._download_start_times.pop(model.fileName, None)

  async def _download_bundle(self, model_bundle: custom.IQModelManager.ModelBundle, destination_path: str) -> None:
    self.selected_bundle = model_bundle
    self.selected_bundle.status = custom.IQModelManager.DownloadStatus.downloading
    os.makedirs(destination_path, exist_ok=True)

    try:
      if not self._download_request_matches(model_bundle):
        raise RuntimeError("Download cancelled")

      tasks = [self._process_model(model, destination_path) for model in self.selected_bundle.models]
      await asyncio.gather(*tasks)

      if not self._download_request_matches(model_bundle):
        raise RuntimeError("Download cancelled")

      self.active_bundle = self.selected_bundle
      self.active_bundle.status = custom.IQModelManager.DownloadStatus.downloaded
      self.params.put(_ACTIVE_BUNDLE_KEY, self.active_bundle.to_dict())
      self.params.remove(_RUNNER_CACHE_KEY)
      self.selected_bundle = None

    except Exception:
      if self._download_request_matches(model_bundle) and self.selected_bundle is not None:
        self.selected_bundle.status = custom.IQModelManager.DownloadStatus.failed
      else:
        self.selected_bundle = None
      raise

    finally:
      self._report_status()

  def download(self, model_bundle: custom.IQModelManager.ModelBundle, destination_path: str) -> None:
    asyncio.run(self._download_bundle(model_bundle, destination_path))

  def _queue_tinygrad_upgrade(self) -> None:
    if self.active_bundle is None:
      return

    replacement = get_runtime_bundle_upgrade(self.active_bundle, self.params, self.available_models)
    if replacement is None or replacement is self.active_bundle:
      return

    if bundle_files_ready(replacement):
      persist_active_bundle(self.params, replacement)
      self.active_bundle = replacement
      return

    if self._download_index() is None and getattr(replacement, "index", None) is not None:
      self.params.put("ModelManager_DownloadIndex", int(replacement.index))
      cloudlog.warning(f"Queued tinygrad upgrade for retired bundle {getattr(self.active_bundle, 'internalName', '<unknown>')}")

  def main_thread(self) -> None:
    _wait_for_valid_clock()
    rk = Ratekeeper(1, print_delay_threshold=None)

    while True:
      try:
        # before NTP the TLS cert reads "not yet valid" and every fetch SSL-fails; one line, not spam
        if not system_time_valid():
          if not getattr(self, "_ntp_wait_logged", False):
            cloudlog.warning("models_manager: waiting for NTP before fetching (system clock not valid)")
            self._ntp_wait_logged = True
          rk.keep_time()
          continue
        self._ntp_wait_logged = False

        self.available_models = self.model_fetcher.get_available_bundles()
        self.active_bundle = get_active_bundle(self.params)
        self._queue_active_redownload_if_invalid()
        self._queue_tinygrad_upgrade()

        if (index_to_download := self._download_index()) is not None:
          if model_to_download := next((model for model in self.available_models if model.index == index_to_download), None):
            try:
              self.download(model_to_download, Paths.model_root())
            except Exception as e:
              cloudlog.exception(e)
            finally:
              self.params.remove("ModelManager_DownloadIndex")
              self.selected_bundle = None

        if self.params.get("ModelManager_ClearCache"):
          self.clear_model_cache()
          self.params.remove("ModelManager_ClearCache")

        self._report_status()
        rk.keep_time()

      except Exception as e:
        cloudlog.exception(f"Error in main thread: {str(e)}")
        rk.keep_time()


def _display_bundle_name(bundle) -> str:
  return getattr(bundle, "internalName", None) or getattr(bundle, "displayName", None) or "<unknown>"


def main():
  IQModelManager().main_thread()

if __name__ == "__main__":
  main()
