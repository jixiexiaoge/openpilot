import sqlite3

from scripts.iqpilot.package_xyz_tiles_to_mbtiles import build_mbtiles
from scripts.iqpilot.render_raster_tiles_from_vector_mbtiles import tile_range_for_bounds


PNG_1X1 = (
  b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
  b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
  b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_tile_range_for_bounds_returns_non_empty_ranges():
  x_range, y_range = tile_range_for_bounds((-88.15, 41.65, -88.02, 41.76), 14)
  assert len(list(x_range)) > 0
  assert len(list(y_range)) > 0


def test_build_mbtiles_from_xyz_tiles(tmp_path):
  source = tmp_path / "xyz"
  tile_dir = source / "14" / "2625"
  tile_dir.mkdir(parents=True)
  (tile_dir / "6335@2x.png").write_bytes(PNG_1X1)

  output = tmp_path / "offline.mbtiles"
  build_mbtiles(source, output, bounds="-88.15,41.65,-88.02,41.76")

  conn = sqlite3.connect(output)
  try:
    fmt = conn.execute("SELECT value FROM metadata WHERE name='format'").fetchone()[0]
    bounds = conn.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
  finally:
    conn.close()

  assert fmt == "png"
  assert bounds == "-88.15,41.65,-88.02,41.76"
  assert count == 1
