#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Downloads per-region raster display-tile bundles (.mbtiles) for the offline on-screen map.

These are a separate asset from mapd's routing/speed-limit data: mapd pulls OSM way tiles
into Paths.mapd_root(), while the on-screen map (OsmOfflineProvider) reads raster .mbtiles
from offline_map_root()/regions/<selector>/tiles/offline.mbtiles. Bundles are built per
state/nation by scripts/iqpilot/build_state_tile_bundles.py and hosted behind a static base
URL that serves:

  <base>/index.json                       {"version": 1, "regions": {<selector>: entry}}
  <base>/<entry["path"]>                  the raster .mbtiles for that region

Entry fields: path, bytes, sha256, bounds ("minLon,minLat,maxLon,maxLat"), minzoom, maxzoom.
Selectors match the mapd region menu naming: us_state.CA, nation.US.
"""
import hashlib
import json
import platform
import threading
import time
from pathlib import Path

import requests

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.ui.onroad.offline_tiles import offline_map_root

# Proprietary auth + hosted endpoints (gitea raw with an embedded read-only PAT, same
# pattern as the model selector). Optional: without the private bundle the downloader
# still works anonymously against OfflineTilesBaseUrl (e.g. a public R2 bucket).
try:
  from openpilot.iqpilot.iq_maps.tiles_auth import get_base_urls as _private_base_urls, get_requests_auth as _private_auth
except Exception:  # ProprietaryModuleMissing or import errors in stripped builds
  _private_base_urls = None
  _private_auth = None

# R2 bucket iqnav behind the public custom domain (see scripts/iqpilot/tile_factory/r2_sync_watch.py)
DEFAULT_TILE_BUNDLE_BASE_URL = "https://maps.konn3kt.com/iqosmd/v1"
BASE_URL_PARAM = "OfflineTilesBaseUrl"
PROGRESS_PARAM = "OfflineTilesDownloadProgress"
REQUEST_PARAM = "OfflineTilesDownloadRequest"
CHUNK_BYTES = 1 << 20
HTTP_TIMEOUT_S = 30.0
STREAM_RETRIES = 8


def candidate_base_urls(params: Params) -> list[str]:
  """Hosts to try in order: user/param override first, then the embedded private
  endpoints (gitea raw), then the public default."""
  override = params.get(BASE_URL_PARAM)
  if isinstance(override, bytes):
    override = override.decode("utf-8", errors="ignore")
  override = (override or "").strip()
  if override:
    return [override.rstrip("/")]
  urls: list[str] = []
  if _private_base_urls is not None:
    try:
      urls.extend(url.rstrip("/") for url in _private_base_urls())
    except Exception:
      pass
  urls.append(DEFAULT_TILE_BUNDLE_BASE_URL)
  return urls


def request_auth() -> tuple[str, str] | None:
  if _private_auth is None:
    return None
  try:
    return _private_auth()
  except Exception:
    return None


def fetch_index(base_url: str, session: requests.Session) -> dict:
  response = session.get(f"{base_url}/index.json", timeout=HTTP_TIMEOUT_S, auth=request_auth())
  response.raise_for_status()
  index = response.json()
  regions = index.get("regions")
  if not isinstance(regions, dict):
    raise ValueError("tile bundle index has no regions")
  return regions


def region_bundle_dir(selector: str) -> Path:
  return offline_map_root() / "regions" / selector


def region_bundle_path(selector: str) -> Path:
  return region_bundle_dir(selector) / "tiles" / "offline.mbtiles"


def region_bundle_installed(selector: str) -> bool:
  return region_bundle_path(selector).exists()


def installed_region_selectors() -> list[str]:
  regions_root = offline_map_root() / "regions"
  if not regions_root.exists():
    return []
  return sorted(
    child.name for child in regions_root.iterdir()
    if child.is_dir() and (child / "tiles" / "offline.mbtiles").exists()
  )


def _hash_existing(path: Path) -> tuple["hashlib._Hash", int]:
  digest = hashlib.sha256()
  size = 0
  with open(path, "rb") as f:
    while True:
      chunk = f.read(CHUNK_BYTES)
      if not chunk:
        break
      digest.update(chunk)
      size += len(chunk)
  return digest, size


def _write_manifest(selector: str, entry: dict) -> None:
  manifest = {
    "region": selector,
    "version": entry.get("version", ""),
    "mbtiles": {
      "bounds": entry.get("bounds", ""),
      "minzoom": entry.get("minzoom"),
      "maxzoom": entry.get("maxzoom"),
      "bytes": entry.get("bytes"),
      "sha256": entry.get("sha256", ""),
    },
  }
  if entry.get("day_path"):
    manifest["mbtiles_day"] = {
      "bytes": entry.get("day_bytes"),
      "sha256": entry.get("day_sha256", ""),
    }
  manifest_path = region_bundle_dir(selector) / "manifest.json"
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  manifest_path.write_text(json.dumps(manifest, indent=2))


class TileBundleDownloader:
  """Streams region bundles to disk with resume + sha256 verify + atomic install.

  Cancellation matches the mapd flow: the caller sets REQUEST_PARAM in mem params while a
  download runs; removing it (konn3kt cancel RPC or settings) aborts between chunks. The
  partial .part file is kept so a retry resumes instead of restarting.
  """

  def __init__(self, params: Params | None = None, mem_params: Params | None = None,
               abort_check=None):
    self.params = params if params is not None else Params()
    if mem_params is not None:
      self.mem_params = mem_params
    else:
      self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params
    self.session = requests.Session()
    self._cancelled = threading.Event()
    # optional external cancel signal, e.g. the orchestrator's OSMDownloadLocations removal
    self._abort_check = abort_check

  def cancel(self) -> None:
    self._cancelled.set()

  def _should_abort(self) -> bool:
    if self._cancelled.is_set():
      return True
    if not self.mem_params.get(REQUEST_PARAM):
      # request flag was removed out from under us -> user cancelled
      self._cancelled.set()
      return True
    if self._abort_check is not None and self._abort_check():
      self._cancelled.set()
      return True
    return False

  def _publish_progress(self, region: str, downloaded: int, total: int, active: bool) -> None:
    self.mem_params.put(PROGRESS_PARAM, {
      "active": active,
      "region": region,
      "downloaded_bytes": int(downloaded),
      "total_bytes": int(total),
    })

  def _download_one(self, selector: str, entry: dict, base_url: str,
                    progress_offset: int, progress_total: int) -> bool:
    """Download a region: the night bundle, plus the optional day-style variant."""
    night_path = region_bundle_path(selector)
    ok = self._download_file(
      selector, base_url, entry["path"], int(entry.get("bytes", 0)),
      str(entry.get("sha256", "")).strip().lower(), night_path,
      progress_offset, progress_total,
    )
    if not ok:
      return False
    if entry.get("day_path"):
      day_ok = self._download_file(
        selector, base_url, entry["day_path"], int(entry.get("day_bytes", 0)),
        str(entry.get("day_sha256", "")).strip().lower(),
        night_path.with_name("offline_day.mbtiles"),
        progress_offset + int(entry.get("bytes", 0)), progress_total,
      )
      if not day_ok:
        # the night set is complete and usable; a failed day variant retries next pass
        cloudlog.warning(f"iq_maps: day-style bundle failed for {selector}; night set installed")
    # manifest last: bounds drive region matching, so it must describe installed files
    _write_manifest(selector, entry)
    cloudlog.info(f"iq_maps: installed tile bundle {selector}")
    return True

  def _download_file(self, selector: str, base_url: str, remote_path: str, expected_bytes: int,
                     expected_sha: str, final_path: Path,
                     progress_offset: int, progress_total: int) -> bool:
    url = f"{base_url}/{remote_path.lstrip('/')}"
    part_path = final_path.with_name(final_path.name + ".part")
    part_path.parent.mkdir(parents=True, exist_ok=True)

    # A cellular/hotspot link routinely kills a multi-hundred-MB stream mid-flight; retry
    # each interruption from the current .part offset instead of failing the whole region.
    downloaded = 0
    digest = hashlib.sha256()
    last_error: Exception | None = None
    for attempt in range(STREAM_RETRIES):
      if self._should_abort():
        cloudlog.warning(f"iq_maps: tile bundle download cancelled for {selector}")
        return False
      if attempt:
        time.sleep(min(30.0, 2.0 * attempt))
      try:
        digest = hashlib.sha256()
        resume_from = 0
        if part_path.exists():
          digest, resume_from = _hash_existing(part_path)
          if expected_bytes and resume_from > expected_bytes:
            part_path.unlink()
            digest = hashlib.sha256()
            resume_from = 0

        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
        auth = request_auth()
        response = self.session.get(url, headers=headers, stream=True, timeout=HTTP_TIMEOUT_S, auth=auth)
        if resume_from and response.status_code != 206:
          # server ignored the Range request -> restart from scratch
          digest = hashlib.sha256()
          resume_from = 0
          part_path.unlink(missing_ok=True)
          if response.status_code == 416:
            response = self.session.get(url, stream=True, timeout=HTTP_TIMEOUT_S, auth=auth)
        response.raise_for_status()

        downloaded = resume_from
        mode = "ab" if resume_from else "wb"
        with open(part_path, mode) as f:
          for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
            if self._should_abort():
              cloudlog.warning(f"iq_maps: tile bundle download cancelled for {selector}")
              return False
            f.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            self._publish_progress(selector, progress_offset + downloaded, progress_total, active=True)
        break
      except requests.RequestException as exc:
        last_error = exc
        cloudlog.warning(f"iq_maps: tile bundle stream interrupted for {selector} "
                         + f"(attempt {attempt + 1}/{STREAM_RETRIES}): {exc}")
    else:
      raise requests.RequestException(f"stream failed after {STREAM_RETRIES} attempts") from last_error

    if expected_bytes and downloaded != expected_bytes:
      cloudlog.error(f"iq_maps: tile bundle size mismatch for {selector}: {downloaded} != {expected_bytes}")
      part_path.unlink(missing_ok=True)
      return False
    if expected_sha and digest.hexdigest() != expected_sha:
      cloudlog.error(f"iq_maps: tile bundle sha256 mismatch for {selector}")
      part_path.unlink(missing_ok=True)
      return False

    part_path.replace(final_path)
    return True

  def download_regions(self, selectors: list[str]) -> bool:
    """Download the display-tile bundles for the given region selectors. Returns True if all
    requested bundles are installed and current when done."""
    self._cancelled.clear()
    ok = True
    try:
      self.mem_params.put(REQUEST_PARAM, {"regions": list(selectors)})
      regions = None
      base_url = ""
      for candidate in candidate_base_urls(self.params):
        try:
          regions = fetch_index(candidate, self.session)
          base_url = candidate
          break
        except (requests.RequestException, ValueError, json.JSONDecodeError):
          cloudlog.warning(f"iq_maps: tile bundle index unavailable at {candidate}")
      if regions is None:
        cloudlog.error("iq_maps: no tile bundle host reachable")
        return False

      wanted: list[tuple[str, dict]] = []
      for selector in selectors:
        entry = regions.get(selector)
        if entry is None:
          cloudlog.warning(f"iq_maps: no tile bundle published for {selector}")
          ok = False
          continue
        if region_bundle_installed(selector) and self._installed_matches(selector, entry):
          continue
        wanted.append((selector, entry))

      progress_total = sum(int(entry.get("bytes", 0)) + int(entry.get("day_bytes", 0)) for _, entry in wanted)
      progress_offset = 0
      for selector, entry in wanted:
        if self._should_abort():
          return False
        try:
          if not self._download_one(selector, entry, base_url, progress_offset, progress_total):
            ok = False
        except (requests.RequestException, OSError):
          cloudlog.exception(f"iq_maps: tile bundle download failed for {selector}")
          ok = False
        progress_offset += int(entry.get("bytes", 0)) + int(entry.get("day_bytes", 0))
      return ok
    finally:
      self._publish_progress("", 0, 0, active=False)
      try:
        self.mem_params.remove(REQUEST_PARAM)
      except Exception:
        pass

  @staticmethod
  def _installed_matches(selector: str, entry: dict) -> bool:
    manifest_path = region_bundle_dir(selector) / "manifest.json"
    try:
      manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
      return False
    installed_sha = str(manifest.get("mbtiles", {}).get("sha256", "")).strip().lower()
    expected_sha = str(entry.get("sha256", "")).strip().lower()
    if not expected_sha or installed_sha != expected_sha:
      return False
    if entry.get("day_path"):
      # a published day variant must be installed and current too
      day_file = region_bundle_dir(selector) / "tiles" / "offline_day.mbtiles"
      installed_day = str(manifest.get("mbtiles_day", {}).get("sha256", "")).strip().lower()
      expected_day = str(entry.get("day_sha256", "")).strip().lower()
      if not day_file.exists() or installed_day != expected_day:
        return False
    return True
