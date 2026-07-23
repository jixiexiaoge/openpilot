import os
import json
import time
from typing import Any
from pathlib import Path

try:
  import sqlite3
except Exception:
  sqlite3 = None  # type: ignore[assignment]


OFFLINE_MBTILES_ENV = "IQPILOT_OFFLINE_MBTILES"
OFFLINE_TILE_ROOT_ENV = "IQPILOT_OFFLINE_TILE_ROOT"
DEFAULT_OFFLINE_TILE_ROOT = Path("/data/offline_maps/tiles" if Path("/data").exists() else "/tmp/offline_maps/tiles")
DEFAULT_OFFLINE_MAP_ROOT = Path("/data/offline_maps" if Path("/data").exists() else "/tmp/offline_maps")
SQLITE_ERRORS = (sqlite3.Error,) if sqlite3 is not None else (Exception,)
SQLiteConnection = Any


def offline_tile_root() -> Path:
  override = os.getenv(OFFLINE_TILE_ROOT_ENV)
  return Path(override) if override else DEFAULT_OFFLINE_TILE_ROOT


def offline_map_root() -> Path:
  root = offline_tile_root()
  if root.name == "tiles":
    return root.parent
  if root.name == "xyz":
    return root.parent.parent if root.parent.name == "tiles" else root.parent
  return DEFAULT_OFFLINE_MAP_ROOT


def _parse_bounds(bounds: str) -> tuple[float, float, float, float] | None:
  try:
    min_lon, min_lat, max_lon, max_lat = [float(part) for part in bounds.split(",")]
  except (ValueError, AttributeError):
    return None
  return min_lat, min_lon, max_lat, max_lon


def _bounds_contains(bounds: tuple[float, float, float, float], latitude: float, longitude: float) -> bool:
  min_lat, min_lon, max_lat, max_lon = bounds
  return min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon


def _bounds_area(bounds: tuple[float, float, float, float]) -> float:
  min_lat, min_lon, max_lat, max_lon = bounds
  return max(max_lat - min_lat, 0.0) * max(max_lon - min_lon, 0.0)


# Manual cache that only stores hits: caching a None (manifest not written yet — e.g. a
# bundle download in flight) would otherwise pin the miss for the life of the process.
_region_bounds_cache: dict[Path, tuple[float, float, float, float]] = {}


def _load_region_bounds(region_root: Path) -> tuple[float, float, float, float] | None:
  cached = _region_bounds_cache.get(region_root)
  if cached is not None:
    return cached
  bounds = _load_region_bounds_uncached(region_root)
  if bounds is not None:
    if len(_region_bounds_cache) > 64:
      _region_bounds_cache.clear()
    _region_bounds_cache[region_root] = bounds
  return bounds


def _load_region_bounds_uncached(region_root: Path) -> tuple[float, float, float, float] | None:
  manifest_path = region_root / "manifest.json"
  if manifest_path.exists():
    try:
      manifest = json.loads(manifest_path.read_text())
      bounds = manifest.get("mbtiles", {}).get("bounds")
      parsed = _parse_bounds(bounds) if bounds else None
      if parsed is not None:
        return parsed
    except (OSError, json.JSONDecodeError):
      pass

  mbtiles_path = region_root / "tiles" / "offline.mbtiles"
  if not mbtiles_path.exists():
    return None

  try:
    conn = open_mbtiles(mbtiles_path)
    row = conn.execute("SELECT value FROM metadata WHERE name = 'bounds'").fetchone()
    conn.close()
  except SQLITE_ERRORS:
    return None

  return _parse_bounds(row["value"]) if row is not None else None


# Short-TTL cache instead of lru_cache: region bundles can be downloaded while the UI is
# running, and a forever-cached candidate list would hide them until the process restarts.
_REGION_ROOTS_TTL_S = 15.0
_region_roots_cache: tuple[float, Path, tuple[Path, ...]] | None = None


def _candidate_region_roots() -> tuple[Path, ...]:
  global _region_roots_cache
  root = offline_map_root()
  now = time.monotonic()
  if _region_roots_cache is not None:
    cached_at, cached_root, cached = _region_roots_cache
    if cached_root == root and now - cached_at < _REGION_ROOTS_TTL_S:
      return cached

  candidates: list[Path] = []
  if (root / "tiles").exists():
    candidates.append(root)

  regions_root = root / "regions"
  if regions_root.exists():
    for child in sorted(regions_root.iterdir()):
      if child.is_dir() and (child / "tiles").exists():
        candidates.append(child)

  result = tuple(candidates)
  _region_roots_cache = (now, root, result)
  return result


def _region_covers_point(region_root: Path, latitude: float, longitude: float) -> bool:
  mb = region_root / "tiles" / "offline.mbtiles"
  if not mb.exists():
    return True  # xyz-only / unknown layout: don't second-guess the bbox match
  try:
    conn = open_mbtiles(mb)
    try:
      _, max_zoom = mbtiles_zoom_bounds(conn)
      z = max_zoom if max_zoom is not None else 14
      import math
      n = 2 ** z
      lat_r = math.radians(max(min(latitude, 85.05112878), -85.05112878))
      x = int((longitude + 180.0) / 360.0 * n)
      y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
      # 3x3 cluster: tolerate an empty sub-tile at the exact point (a z15 child with no road)
      # while still rejecting a neighbor whose coverage doesn't reach this area at all.
      for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
          if load_raster_tile_blob(conn, z, x + dx, y + dy) is not None:
            return True
      return False
    finally:
      conn.close()
  except SQLITE_ERRORS:
    return True


def find_offline_region_root(latitude: float | None = None, longitude: float | None = None) -> Path | None:
  candidates = _candidate_region_roots()
  if not candidates:
    return None

  if latitude is None or longitude is None:
    return candidates[0]

  bounded: list[tuple[float, Path]] = []
  for candidate in candidates:
    bounds = _load_region_bounds(candidate)
    if bounds is None:
      continue
    if _bounds_contains(bounds, latitude, longitude):
      bounded.append((_bounds_area(bounds), candidate))

  if bounded:
    if len(bounded) == 1:
      return bounded[0][1]
    # multiple bboxes overlap this point (border zone): prefer the smallest-area region that
    # ACTUALLY has tiles here, so we don't pick a neighbor whose bundle is empty at the border.
    bounded.sort(key=lambda item: item[0])
    for _, candidate in bounded:
      if _region_covers_point(candidate, latitude, longitude):
        return candidate
    return bounded[0][1]

  return candidates[0]


def find_offline_mbtiles_path(latitude: float | None = None, longitude: float | None = None,
                              day: bool = False) -> Path | None:
  explicit = os.getenv(OFFLINE_MBTILES_ENV)
  if explicit:
    path = Path(explicit)
    if day:
      day_path = path.with_name("offline_day.mbtiles")
      if day_path.exists():
        return day_path
    return path if path.exists() else None

  region_root = find_offline_region_root(latitude, longitude)
  if region_root is None:
    return None

  # day variant is optional: regions built before the day palette fall back to the night set
  if day:
    day_preferred = region_root / "tiles" / "offline_day.mbtiles"
    if day_preferred.exists():
      return day_preferred

  preferred = region_root / "tiles" / "offline.mbtiles"
  if preferred.exists():
    return preferred

  matches = sorted(p for p in (region_root / "tiles").glob("*.mbtiles") if "_day" not in p.name or day)
  return matches[0] if matches else None


def find_offline_xyz_root(latitude: float | None = None, longitude: float | None = None) -> Path | None:
  root = offline_tile_root()
  if not root.exists():
    region_root = find_offline_region_root(latitude, longitude)
    if region_root is None:
      return None
    root = region_root / "tiles"

  if any(child.is_dir() and child.name.isdigit() for child in root.iterdir()):
    return root

  xyz_dir = root / "xyz"
  if xyz_dir.exists() and any(child.is_dir() and child.name.isdigit() for child in xyz_dir.iterdir()):
    return xyz_dir

  return None


def xyz_to_tms_y(z: int, y: int) -> int:
  return (2 ** z - 1) - y


def open_mbtiles(path: Path) -> SQLiteConnection:
  if sqlite3 is None:
    raise RuntimeError("sqlite3 unavailable")
  conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
  conn.row_factory = sqlite3.Row
  return conn


def mbtiles_is_raster(conn: SQLiteConnection) -> bool:
  row = conn.execute("SELECT value FROM metadata WHERE name = 'format'").fetchone()
  if row is None:
    return False
  return row["value"] in {"png", "jpg", "jpeg", "webp"}


def mbtiles_zoom_bounds(conn: SQLiteConnection) -> tuple[int | None, int | None]:
  rows = {
    row["name"]: row["value"]
    for row in conn.execute("SELECT name, value FROM metadata WHERE name IN ('minzoom', 'maxzoom')")
  }
  min_zoom = int(rows["minzoom"]) if "minzoom" in rows else None
  max_zoom = int(rows["maxzoom"]) if "maxzoom" in rows else None
  return min_zoom, max_zoom


def xyz_zoom_bounds(root: Path) -> tuple[int | None, int | None]:
  zoom_dirs = sorted(
    int(child.name)
    for child in root.iterdir()
    if child.is_dir() and child.name.isdigit()
  )
  if not zoom_dirs:
    return None, None
  return zoom_dirs[0], zoom_dirs[-1]


def load_raster_tile_blob(conn: SQLiteConnection, z: int, x: int, y: int) -> bytes | None:
  row = conn.execute(
    """
    SELECT tile_data
    FROM tiles
    WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
    """,
    (z, x, xyz_to_tms_y(z, y)),
  ).fetchone()
  return bytes(row["tile_data"]) if row is not None else None


def load_raster_xyz_tile_blob(root: Path, z: int, x: int, y: int) -> bytes | None:
  for suffix in ("png", "webp", "jpg", "jpeg"):
    for filename in (f"{y}.{suffix}", f"{y}@2x.{suffix}"):
      tile_path = root / str(z) / str(x) / filename
      if tile_path.exists():
        return tile_path.read_bytes()
  return None
