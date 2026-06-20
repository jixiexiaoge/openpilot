import os
import sqlite3
import json

from openpilot.selfdrive.ui.iqpilot.onroad import offline_tiles


PNG_1X1 = (
  b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
  b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
  b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_mbtiles(path):
  conn = sqlite3.connect(path)
  conn.execute("CREATE TABLE metadata (name text, value text)")
  conn.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
  conn.execute("INSERT INTO metadata (name, value) VALUES ('format', 'png')")
  conn.execute("INSERT INTO metadata (name, value) VALUES ('minzoom', '1')")
  conn.execute("INSERT INTO metadata (name, value) VALUES ('maxzoom', '3')")
  conn.execute(
    "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
    (1, 1, offline_tiles.xyz_to_tms_y(1, 0), PNG_1X1),
  )
  conn.commit()
  conn.close()


def test_xyz_to_tms_y():
  assert offline_tiles.xyz_to_tms_y(1, 0) == 1
  assert offline_tiles.xyz_to_tms_y(1, 1) == 0


def test_find_offline_mbtiles_path_from_env(tmp_path, monkeypatch):
  mbtiles = tmp_path / "demo.mbtiles"
  _write_mbtiles(mbtiles)
  monkeypatch.setenv(offline_tiles.OFFLINE_MBTILES_ENV, str(mbtiles))
  assert offline_tiles.find_offline_mbtiles_path() == mbtiles


def test_find_offline_xyz_root(tmp_path, monkeypatch):
  root = tmp_path / "tiles"
  (root / "15" / "10500").mkdir(parents=True)
  monkeypatch.setenv(offline_tiles.OFFLINE_TILE_ROOT_ENV, str(root))
  assert offline_tiles.find_offline_xyz_root() == root


def test_load_raster_tile_blob_from_mbtiles(tmp_path):
  mbtiles = tmp_path / "offline.mbtiles"
  _write_mbtiles(mbtiles)
  conn = offline_tiles.open_mbtiles(mbtiles)
  try:
    assert offline_tiles.mbtiles_is_raster(conn) is True
    assert offline_tiles.mbtiles_zoom_bounds(conn) == (1, 3)
    assert offline_tiles.load_raster_tile_blob(conn, 1, 1, 0) == PNG_1X1
  finally:
    conn.close()


def test_load_raster_tile_blob_from_xyz_dir(tmp_path, monkeypatch):
  root = tmp_path / "offline_tiles"
  tile_path = root / "14" / "2625"
  tile_path.mkdir(parents=True)
  (tile_path / "6335@2x.png").write_bytes(PNG_1X1)
  monkeypatch.setenv(offline_tiles.OFFLINE_TILE_ROOT_ENV, str(root))
  assert offline_tiles.xyz_zoom_bounds(root) == (14, 14)
  assert offline_tiles.load_raster_xyz_tile_blob(root, 14, 2625, 6335) == PNG_1X1


def test_find_offline_region_root_by_bounds(tmp_path, monkeypatch):
  root = tmp_path / "offline_maps"
  il = root / "regions" / "illinois"
  ca = root / "regions" / "california"
  (il / "tiles").mkdir(parents=True)
  (ca / "tiles").mkdir(parents=True)
  (il / "manifest.json").write_text(json.dumps({"mbtiles": {"bounds": "-91.6,36.9,-87.4,42.6"}}))
  (ca / "manifest.json").write_text(json.dumps({"mbtiles": {"bounds": "-124.5,32.4,-114.1,42.1"}}))

  monkeypatch.setenv(offline_tiles.OFFLINE_TILE_ROOT_ENV, str(root / "tiles"))
  assert offline_tiles.find_offline_region_root(41.88, -87.63) == il
  assert offline_tiles.find_offline_region_root(34.05, -118.24) == ca


def test_find_offline_mbtiles_path_uses_selected_region(tmp_path, monkeypatch):
  root = tmp_path / "offline_maps"
  il = root / "regions" / "illinois"
  ca = root / "regions" / "california"
  (il / "tiles").mkdir(parents=True)
  (ca / "tiles").mkdir(parents=True)
  (il / "manifest.json").write_text(json.dumps({"mbtiles": {"bounds": "-91.6,36.9,-87.4,42.6"}}))
  (ca / "manifest.json").write_text(json.dumps({"mbtiles": {"bounds": "-124.5,32.4,-114.1,42.1"}}))
  _write_mbtiles(il / "tiles" / "offline.mbtiles")
  _write_mbtiles(ca / "tiles" / "offline.mbtiles")

  monkeypatch.setenv(offline_tiles.OFFLINE_TILE_ROOT_ENV, str(root / "tiles"))
  assert offline_tiles.find_offline_mbtiles_path(41.88, -87.63) == il / "tiles" / "offline.mbtiles"
  assert offline_tiles.find_offline_mbtiles_path(34.05, -118.24) == ca / "tiles" / "offline.mbtiles"
