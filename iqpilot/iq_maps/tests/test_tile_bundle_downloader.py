import hashlib
import json
import sqlite3
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest

from openpilot.iqpilot.iq_maps import tile_bundle_downloader as tbd
from openpilot.iqpilot.ui.onroad import offline_tiles


PNG_1X1 = (
  b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01" +
  b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf" +
  b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeParams:
  def __init__(self):
    self.store: dict[str, object] = {}

  def get(self, key, return_default=False):
    return self.store.get(key)

  def get_bool(self, key):
    return bool(self.store.get(key))

  def put(self, key, value):
    self.store[key] = value

  def put_bool(self, key, value):
    self.store[key] = bool(value)

  def remove(self, key):
    self.store.pop(key, None)


def _make_mbtiles(path):
  conn = sqlite3.connect(path)
  conn.execute("CREATE TABLE metadata (name text, value text)")
  conn.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
  conn.executemany("INSERT INTO metadata (name, value) VALUES (?, ?)",
                   [("format", "png"), ("minzoom", "10"), ("maxzoom", "16"),
                    ("bounds", "-124.5,32.4,-114.1,42.1")])
  conn.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (10, 163, 396, PNG_1X1))
  conn.commit()
  conn.close()


@pytest.fixture
def hosting(tmp_path, monkeypatch):
  """Local static host serving index.json + a us_state.CA bundle; offline root redirected."""
  serve_root = tmp_path / "serve"
  serve_root.mkdir()
  bundle = serve_root / "us_state.CA.mbtiles"
  _make_mbtiles(bundle)
  payload = bundle.read_bytes()
  index = {
    "version": 1,
    "regions": {
      "us_state.CA": {
        "path": "us_state.CA.mbtiles",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bounds": "-124.5,32.4,-114.1,42.1",
        "minzoom": 10,
        "maxzoom": 16,
        "version": "20260709",
      }
    },
  }
  (serve_root / "index.json").write_text(json.dumps(index))

  handler = partial(SimpleHTTPRequestHandler, directory=str(serve_root))
  server = HTTPServer(("127.0.0.1", 0), handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()

  offline_root = tmp_path / "offline_maps"
  monkeypatch.setenv(offline_tiles.OFFLINE_TILE_ROOT_ENV, str(offline_root / "tiles"))
  offline_tiles._region_roots_cache = None
  offline_tiles._region_bounds_cache.clear()

  params = FakeParams()
  params.put(tbd.BASE_URL_PARAM, f"http://127.0.0.1:{server.server_address[1]}")
  sessions: list = []
  real_ctor = tbd.TileBundleDownloader.__init__

  def tracking_ctor(self, *args, **kwargs):
    real_ctor(self, *args, **kwargs)
    sessions.append(self.session)

  monkeypatch.setattr(tbd.TileBundleDownloader, "__init__", tracking_ctor)
  try:
    yield params, index, offline_root
  finally:
    for session in sessions:
      session.close()
    server.shutdown()
    server.server_close()


def test_download_installs_bundle_and_manifest(hosting):
  params, index, offline_root = hosting
  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is True

  installed = offline_root / "regions" / "us_state.CA" / "tiles" / "offline.mbtiles"
  assert installed.exists()
  manifest = json.loads((installed.parent.parent / "manifest.json").read_text())
  assert manifest["mbtiles"]["bounds"] == "-124.5,32.4,-114.1,42.1"
  assert manifest["mbtiles"]["sha256"] == index["regions"]["us_state.CA"]["sha256"]
  # request/progress params cleaned up
  assert params.get(tbd.REQUEST_PARAM) is None
  assert params.get(tbd.PROGRESS_PARAM)["active"] is False

  # and the on-screen map provider can find + read it
  assert offline_tiles.find_offline_mbtiles_path(37.0, -120.0) == installed
  conn = offline_tiles.open_mbtiles(installed)
  try:
    assert offline_tiles.mbtiles_is_raster(conn)
    assert offline_tiles.load_raster_tile_blob(conn, 10, 163, 2 ** 10 - 1 - 396) == PNG_1X1
  finally:
    conn.close()


def test_skips_already_installed_matching_sha(hosting):
  params, _, offline_root = hosting
  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is True
  installed = offline_root / "regions" / "us_state.CA" / "tiles" / "offline.mbtiles"
  first_mtime = installed.stat().st_mtime_ns
  assert dl.download_regions(["us_state.CA"]) is True
  assert installed.stat().st_mtime_ns == first_mtime


def test_unknown_region_fails_cleanly(hosting):
  params, _, offline_root = hosting
  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.ZZ"]) is False
  assert not (offline_root / "regions" / "us_state.ZZ").exists()


def test_resume_from_partial(hosting):
  params, _, offline_root = hosting
  part = offline_root / "regions" / "us_state.CA" / "tiles" / "offline.mbtiles.part"
  part.parent.mkdir(parents=True)
  # pre-seed the first half as an interrupted download
  full = (offline_root / ".." / "serve" / "us_state.CA.mbtiles").resolve().read_bytes()
  part.write_bytes(full[: len(full) // 2])

  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is True
  installed = part.parent / "offline.mbtiles"
  assert installed.read_bytes() == full
  assert not part.exists()


def test_cancel_aborts_before_install(hosting):
  params, _, offline_root = hosting
  dl = tbd.TileBundleDownloader(params=params, mem_params=params, abort_check=lambda: True)
  assert dl.download_regions(["us_state.CA"]) is False
  assert not (offline_root / "regions" / "us_state.CA" / "tiles" / "offline.mbtiles").exists()
  # request param cleaned up so the UI doesn't show a stuck download
  assert params.get(tbd.REQUEST_PARAM) is None


def test_sha_mismatch_rejected(hosting):
  params, index, offline_root = hosting
  index["regions"]["us_state.CA"]["sha256"] = "0" * 64
  serve_root = (offline_root / ".." / "serve").resolve()
  (serve_root / "index.json").write_text(json.dumps(index))
  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is False
  assert not (offline_root / "regions" / "us_state.CA" / "tiles" / "offline.mbtiles").exists()


def test_new_region_visible_without_process_restart(hosting):
  """Regression: lru_cache on _candidate_region_roots hid freshly downloaded regions."""
  params, _, offline_root = hosting
  # UI already scanned (and found nothing)
  offline_tiles._region_roots_cache = None
  assert offline_tiles.find_offline_mbtiles_path(37.0, -120.0) is None

  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is True

  # TTL cache: expire it and the new region shows up in the same process
  offline_tiles._region_roots_cache = None
  found = offline_tiles.find_offline_mbtiles_path(37.0, -120.0)
  assert found is not None and found.exists()


def test_candidate_base_urls_param_override_wins():
  params = FakeParams()
  params.put(tbd.BASE_URL_PARAM, "https://my-r2.example.com/v1/")
  assert tbd.candidate_base_urls(params) == ["https://my-r2.example.com/v1"]


def test_candidate_base_urls_private_endpoints_first():
  params = FakeParams()
  urls = tbd.candidate_base_urls(params)
  # embedded private endpoints (gitea) come before the public default
  assert urls[-1] == tbd.DEFAULT_TILE_BUNDLE_BASE_URL
  if tbd._private_base_urls is not None:
    assert any("git.konn3kt.com" in url for url in urls[:-1])
    assert tbd.request_auth() is not None


def test_day_variant_downloaded_and_manifested(hosting, tmp_path):
  params, index, offline_root = hosting
  serve_root = (offline_root / ".." / "serve").resolve()
  day_bundle = serve_root / "us_state.CA_day.mbtiles"
  _make_mbtiles(day_bundle)
  day_payload = day_bundle.read_bytes()
  entry = index["regions"]["us_state.CA"]
  entry["day_path"] = "us_state.CA_day.mbtiles"
  entry["day_bytes"] = len(day_payload)
  entry["day_sha256"] = hashlib.sha256(day_payload).hexdigest()
  (serve_root / "index.json").write_text(json.dumps(index))

  dl = tbd.TileBundleDownloader(params=params, mem_params=params)
  assert dl.download_regions(["us_state.CA"]) is True
  tiles = offline_root / "regions" / "us_state.CA" / "tiles"
  assert (tiles / "offline.mbtiles").exists()
  assert (tiles / "offline_day.mbtiles").exists()
  manifest = json.loads((tiles.parent / "manifest.json").read_text())
  assert manifest["mbtiles_day"]["sha256"] == entry["day_sha256"]
  # installed-and-current check must account for the day file
  assert dl._installed_matches("us_state.CA", entry) is True
  (tiles / "offline_day.mbtiles").unlink()
  assert dl._installed_matches("us_state.CA", entry) is False
