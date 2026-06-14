import os
import math
import threading
import time
from typing import Any
from pathlib import Path

try:
  import sqlite3
except Exception:
  sqlite3 = None  # type: ignore[assignment]

import pyray as rl
import requests

from openpilot.common.issue_debug import log_issue_limited
from openpilot.common.params import Params, UnknownKeyName
from openpilot.selfdrive.ui.iqpilot.onroad.offline_tiles import (
  find_offline_mbtiles_path,
  find_offline_xyz_root,
  load_raster_tile_blob,
  load_raster_xyz_tile_blob,
  mbtiles_is_raster,
  mbtiles_zoom_bounds,
  open_mbtiles,
  xyz_zoom_bounds,
)
from openpilot.selfdrive.ui.iqpilot.onroad.nav_map_utils import (
  build_mapbox_tile_url,
  choose_nav_camera,
  mercator_world_px_at_zoom,
  project_nav_point,
  project_nav_polyline,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget

PANEL_WIDTH = 560
PANEL_HEIGHT = 600
PANEL_MARGIN_RIGHT = 28
PANEL_MARGIN_TOP = 92
CARD_RADIUS = 0.055
MAP_HEIGHT = 392
SPLIT_HEADER_HEIGHT = 160
SPLIT_FOOTER_HEIGHT = 112
ICON_ASSET_DIR = Path(__file__).resolve().parents[4] / "iqpilot" / "selfdrive" / "assets" / "navigation"
STAT_GAP = 10
TILE_SIZE = 256
TILE_SCALE = 2
MAX_INFLIGHT_TILES = 8
CAMERA_SMOOTHING = 0.18
CACHE_MARGIN_TILES = 2
CACHE_LIMIT = 96
PARAMS_REFRESH_S = 0.5
MAP_PROVIDER_UPDATE_S = 0.25
OFFLINE_PROVIDER_UPDATE_S = 1.0
ROUTE_PROJECTION_UPDATE_S = 0.15
TILE_CACHE_ROOT = Path(
  os.getenv(
    "IQPILOT_NAV_TILE_CACHE",
    "/data/iqpilot_nav_tiles" if Path("/data").exists() else "/tmp/iqpilot_nav_tiles",
  )
)
MAPBOX_PROVIDER_DISABLED = os.getenv("IQPILOT_DISABLE_MAPBOX_PROVIDER", "0") == "1"
MAPBOX_CACHE_DISABLED = os.getenv("IQPILOT_DISABLE_MAPBOX_CACHE", "0") == "1"
SQLITE_ERRORS = (sqlite3.Error,) if sqlite3 is not None else (Exception,)


class MapboxTileProvider:
  def __init__(self):
    self._params = Params()
    self._session = requests.Session()
    self._pending_tiles: dict[tuple[int, int, int], bytes] = {}
    self._inflight: set[tuple[int, int, int]] = set()
    self._textures: dict[tuple[int, int, int], rl.Texture] = {}
    self._lock = threading.Lock()
    self._status = "idle"
    self._cache_root = TILE_CACHE_ROOT
    self._cache_root.mkdir(parents=True, exist_ok=True)
    self._provider_disabled = MAPBOX_PROVIDER_DISABLED
    self._cache_disabled = MAPBOX_CACHE_DISABLED

  def _token(self) -> str:
    token = self._params.get("MapboxToken")
    if isinstance(token, bytes):
      token = token.decode("utf-8")
    return token or ""

  def _fetch_worker(self, tile_key: tuple[int, int, int], token: str) -> None:
    z, x, y = tile_key
    url = build_mapbox_tile_url(z, x, y, tile_size=TILE_SIZE, scale=TILE_SCALE)
    try:
      response = self._session.get(url, params={"access_token": token}, timeout=1.5)
      response.raise_for_status()
      if not self._cache_disabled:
        cache_path = self._cache_path(tile_key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
      with self._lock:
        self._pending_tiles[tile_key] = response.content
      self._status = "ready"
    except requests.RequestException:
      if not self._queue_cached_tile(tile_key):
        self._status = "error"
    finally:
      self._inflight.discard(tile_key)

  def _cache_path(self, tile_key: tuple[int, int, int]) -> Path:
    z, x, y = tile_key
    return self._cache_root / str(z) / str(x) / f"{y}@{TILE_SCALE}x.png"

  def _queue_cached_tile(self, tile_key: tuple[int, int, int]) -> bool:
    if self._cache_disabled:
      return False
    if tile_key in self._textures or tile_key in self._pending_tiles:
      return True

    cache_path = self._cache_path(tile_key)
    if not cache_path.exists():
      return False

    try:
      payload = cache_path.read_bytes()
    except OSError:
      return False

    with self._lock:
      self._pending_tiles[tile_key] = payload
    self._status = "offline_cache"
    return True

  def _consume_pending(self) -> None:
    with self._lock:
      pending = list(self._pending_tiles.items())
      self._pending_tiles.clear()

    for tile_key, payload in pending:
      image = rl.load_image_from_memory(self._image_ext(payload), payload, len(payload))
      texture = rl.load_texture_from_image(image)
      rl.unload_image(image)
      rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
      old_texture = self._textures.get(tile_key)
      if old_texture is not None:
        rl.unload_texture(old_texture)
      self._textures[tile_key] = texture

  def _visible_tile_keys(self, latitude: float, longitude: float, zoom: float, width: float, height: float) -> tuple[int, float, float, float, list[tuple[int, int, int]]]:
    z = max(0, min(22, int(round(zoom))))
    scale = 2.0 ** (zoom - z)
    center_x, center_y = mercator_world_px_at_zoom(latitude, longitude, z, tile_size=TILE_SIZE)
    world_half_width = (width * 0.5) / max(scale, 1e-6)
    world_half_height = (height * 0.5) / max(scale, 1e-6)
    min_tile_x = int(math.floor((center_x - world_half_width) / TILE_SIZE)) - 1
    max_tile_x = int(math.floor((center_x + world_half_width) / TILE_SIZE)) + 1
    min_tile_y = int(math.floor((center_y - world_half_height) / TILE_SIZE)) - 1
    max_tile_y = int(math.floor((center_y + world_half_height) / TILE_SIZE)) + 1

    tile_count = 2 ** z
    visible = []
    for tile_y in range(max(0, min_tile_y), min(tile_count - 1, max_tile_y) + 1):
      for tile_x in range(min_tile_x, max_tile_x + 1):
        visible.append((z, tile_x % tile_count, tile_y))
    return z, scale, center_x, center_y, visible

  @staticmethod
  def _image_ext(payload: bytes) -> str:
    if payload.startswith(b"\xff\xd8\xff"):
      return ".jpg"
    if payload.startswith(b"RIFF") and b"WEBP" in payload[:16]:
      return ".webp"
    return ".png"

  def _prune_cache(self, keep_tiles: set[tuple[int, int, int]]) -> None:
    if len(self._textures) <= CACHE_LIMIT:
      return

    for tile_key in list(self._textures):
      if tile_key in keep_tiles:
        continue
      rl.unload_texture(self._textures.pop(tile_key))
      if len(self._textures) <= CACHE_LIMIT:
        break

  def update(self, latitude: float, longitude: float, zoom: float, width: float, height: float):
    if self._provider_disabled:
      self._status = "disabled"
      return

    self._consume_pending()

    z, scale, center_x, center_y, visible_tiles = self._visible_tile_keys(latitude, longitude, zoom, width, height)
    center_tile_x = center_x / TILE_SIZE
    center_tile_y = center_y / TILE_SIZE
    token = self._token()

    for tile_key in visible_tiles:
      self._queue_cached_tile(tile_key)

    missing_tiles = [
      tile_key for tile_key in visible_tiles
      if tile_key not in self._textures and tile_key not in self._inflight
    ]
    missing_tiles.sort(key=lambda tile_key: abs(tile_key[1] - center_tile_x) + abs(tile_key[2] - center_tile_y))
    if token:
      launch_count = max(0, MAX_INFLIGHT_TILES - len(self._inflight))
      for tile_key in missing_tiles[:launch_count]:
        self._inflight.add(tile_key)
        self._status = "loading"
        thread = threading.Thread(target=self._fetch_worker, args=(tile_key, token), daemon=True)
        thread.start()
    elif not self._textures:
      self._status = "token_missing"

    visible_set = set(visible_tiles)
    if all(tile_key in self._textures for tile_key in visible_set) and visible_set:
      self._status = "ready" if token else "offline_cache"
    elif self._inflight:
      self._status = "loading"
    elif self._textures:
      self._status = "offline_cache"

    tile_count = 2 ** z
    keep_tiles = set()
    for tile_key in visible_tiles:
      _, tile_x, tile_y = tile_key
      for dx in range(-CACHE_MARGIN_TILES, CACHE_MARGIN_TILES + 1):
        for dy in range(-CACHE_MARGIN_TILES, CACHE_MARGIN_TILES + 1):
          keep_y = tile_y + dy
          if 0 <= keep_y < tile_count:
            keep_tiles.add((z, (tile_x + dx) % tile_count, keep_y))
    self._prune_cache(keep_tiles)

  def draw(self, rect: rl.Rectangle, latitude: float, longitude: float, zoom: float) -> bool:
    if self._provider_disabled:
      return False
    z, scale, center_x, center_y, visible_tiles = self._visible_tile_keys(latitude, longitude, zoom, rect.width, rect.height)
    drew_any = False
    half_width = rect.width * 0.5
    half_height = rect.height * 0.5

    for tile_key in visible_tiles:
      texture = self._textures.get(tile_key)
      if texture is None:
        continue
      _, tile_x, tile_y = tile_key
      tile_left = rect.x + half_width + ((tile_x * TILE_SIZE) - center_x) * scale
      tile_top = rect.y + half_height + ((tile_y * TILE_SIZE) - center_y) * scale
      dst = rl.Rectangle(tile_left, tile_top, TILE_SIZE * scale, TILE_SIZE * scale)
      src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
      rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
      drew_any = True

    return drew_any

  def status(self) -> str:
    return self._status

  def has_content(self) -> bool:
    return bool(self._textures)


class OsmOfflineProvider:
  def __init__(self):
    self._conn: Any | None = None
    self._mbtiles_path: Path | None = None
    self._xyz_root: Path | None = None
    self._textures: dict[tuple[int, int, int], rl.Texture] = {}
    self._status = "offline_missing"
    self._min_zoom: int | None = None
    self._max_zoom: int | None = None

  def _close_conn(self) -> None:
    if self._conn is not None:
      self._conn.close()
      self._conn = None

  def _refresh_source(self, latitude: float, longitude: float) -> None:
    mbtiles_path = find_offline_mbtiles_path(latitude, longitude)
    xyz_root = find_offline_xyz_root(latitude, longitude)

    if self._mbtiles_path == mbtiles_path and self._xyz_root == xyz_root:
      return

    self._close_conn()
    self._mbtiles_path = mbtiles_path
    self._xyz_root = xyz_root
    self._min_zoom = None
    self._max_zoom = None

    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures.clear()

    if self._mbtiles_path is not None:
      try:
        self._conn = open_mbtiles(self._mbtiles_path)
        if mbtiles_is_raster(self._conn):
          self._min_zoom, self._max_zoom = mbtiles_zoom_bounds(self._conn)
          self._status = "offline_ready"
        else:
          self._status = "offline_invalid"
      except SQLITE_ERRORS:
        self._conn = None
        self._status = "offline_invalid"
    elif self._xyz_root is not None:
      self._min_zoom, self._max_zoom = xyz_zoom_bounds(self._xyz_root)
      self._status = "offline_ready"
    else:
      self._status = "offline_missing"

  def _source_tile_for_request(self, tile_key: tuple[int, int, int]) -> tuple[tuple[int, int, int], int]:
    z, x, y = tile_key
    source_z = z
    if self._max_zoom is not None and z > self._max_zoom:
      source_z = self._max_zoom
    elif self._min_zoom is not None and z < self._min_zoom:
      source_z = self._min_zoom

    delta = z - source_z
    if delta <= 0:
      return (source_z, x, y), 0

    return (source_z, x >> delta, y >> delta), delta

  def _consume_blob(self, tile_key: tuple[int, int, int], payload: bytes) -> None:
    image = rl.load_image_from_memory(MapboxTileProvider._image_ext(payload), payload, len(payload))
    texture = rl.load_texture_from_image(image)
    rl.unload_image(image)
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
    old_texture = self._textures.get(tile_key)
    if old_texture is not None:
      rl.unload_texture(old_texture)
    self._textures[tile_key] = texture

  def _visible_tile_keys(self, latitude: float, longitude: float, zoom: float, width: float, height: float) -> tuple[int, float, float, float, list[tuple[int, int, int]]]:
    z = max(0, min(22, int(round(zoom))))
    scale = 2.0 ** (zoom - z)
    center_x, center_y = mercator_world_px_at_zoom(latitude, longitude, z, tile_size=TILE_SIZE)
    world_half_width = (width * 0.5) / max(scale, 1e-6)
    world_half_height = (height * 0.5) / max(scale, 1e-6)
    min_tile_x = int(math.floor((center_x - world_half_width) / TILE_SIZE)) - 1
    max_tile_x = int(math.floor((center_x + world_half_width) / TILE_SIZE)) + 1
    min_tile_y = int(math.floor((center_y - world_half_height) / TILE_SIZE)) - 1
    max_tile_y = int(math.floor((center_y + world_half_height) / TILE_SIZE)) + 1

    tile_count = 2 ** z
    visible = []
    for tile_y in range(max(0, min_tile_y), min(tile_count - 1, max_tile_y) + 1):
      for tile_x in range(min_tile_x, max_tile_x + 1):
        visible.append((z, tile_x % tile_count, tile_y))
    return z, scale, center_x, center_y, visible

  def _load_blob(self, tile_key: tuple[int, int, int]) -> bytes | None:
    z, x, y = tile_key
    if self._conn is not None and self._status == "offline_ready":
      try:
        return load_raster_tile_blob(self._conn, z, x, y)
      except SQLITE_ERRORS:
        self._status = "offline_invalid"
        return None
    if self._xyz_root is not None:
      return load_raster_xyz_tile_blob(self._xyz_root, z, x, y)
    return None

  def update(self, latitude: float, longitude: float, zoom: float, width: float, height: float) -> None:
    self._refresh_source(latitude, longitude)
    if self._status != "offline_ready":
      return

    _, _, _, _, visible_tiles = self._visible_tile_keys(latitude, longitude, zoom, width, height)
    visible_source_keys = set()
    for requested_tile in visible_tiles:
      source_tile, _ = self._source_tile_for_request(requested_tile)
      visible_source_keys.add(source_tile)
      if source_tile in self._textures:
        continue
      payload = self._load_blob(source_tile)
      if payload is not None:
        try:
          self._consume_blob(source_tile, payload)
        except RuntimeError:
          self._status = "offline_invalid"
          return

    for tile_key in list(self._textures):
      if tile_key not in visible_source_keys:
        rl.unload_texture(self._textures.pop(tile_key))

  def draw(self, rect: rl.Rectangle, latitude: float, longitude: float, zoom: float) -> bool:
    if self._status != "offline_ready":
      return False

    z, scale, center_x, center_y, visible_tiles = self._visible_tile_keys(latitude, longitude, zoom, rect.width, rect.height)
    drew_any = False
    half_width = rect.width * 0.5
    half_height = rect.height * 0.5

    for requested_tile in visible_tiles:
      source_tile, delta = self._source_tile_for_request(requested_tile)
      texture = self._textures.get(source_tile)
      if texture is None:
        continue
      _, tile_x, tile_y = requested_tile
      tile_left = rect.x + half_width + ((tile_x * TILE_SIZE) - center_x) * scale
      tile_top = rect.y + half_height + ((tile_y * TILE_SIZE) - center_y) * scale
      dst = rl.Rectangle(tile_left, tile_top, TILE_SIZE * scale, TILE_SIZE * scale)
      if delta == 0:
        src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
      else:
        subdivisions = 2 ** delta
        src_width = float(texture.width) / subdivisions
        src_height = float(texture.height) / subdivisions
        src_x = float(tile_x % subdivisions) * src_width
        src_y = float(tile_y % subdivisions) * src_height
        src = rl.Rectangle(src_x, src_y, src_width, src_height)
      rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
      drew_any = True

    return drew_any

  def status(self) -> str:
    return self._status

  def has_content(self) -> bool:
    return bool(self._textures)


class NavMapPanel(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self.active = False
    self._maps_enabled = False
    self.current_latitude = 0.0
    self.current_longitude = 0.0
    self.bearing_deg = 0.0
    self.zoom_hint = 16.0
    self.destination_latitude = 0.0
    self.destination_longitude = 0.0
    self.render_center_latitude = 0.0
    self.render_center_longitude = 0.0
    self.render_zoom = 16.0
    self.display_center_latitude = 0.0
    self.display_center_longitude = 0.0
    self.display_zoom = 16.0
    self.route_points = []
    self.next_distance = 0.0
    self.next_description = ""
    self.next_direction = 0
    self.next_type = 0
    self.next_valid = False
    self.nav_active = False
    self.destination_name = ""
    self.time_remaining = 0.0
    self.distance_remaining = 0.0
    self.road_name = ""
    self._has_render_fix = False
    self._route_ahead_index = 0
    self._projected_route_points: list[tuple[float, float]] = []
    self._projected_route_key: tuple | None = None
    self._mapbox = MapboxTileProvider()
    self._offline = OsmOfflineProvider()
    self._title_font = gui_app.font(FontWeight.BOLD)
    self._body_font = gui_app.font(FontWeight.MEDIUM)
    self._micro_font = gui_app.font(FontWeight.SEMI_BOLD)
    self._icon_textures: dict[str, rl.Texture] = {}
    self._last_params_refresh = 0.0
    self._last_mapbox_update = 0.0
    self._last_offline_update = 0.0
    self._last_projection_update = 0.0

  @staticmethod
  def _enum_value(value) -> int:
    return int(getattr(value, "raw", value))

  def _route_ahead_points(self):
    if len(self.route_points) < 2:
      self._route_ahead_index = 0
      return self.route_points

    best_idx = 0
    best_score = None
    for idx, point in enumerate(self.route_points):
      dlat = float(point.latitude) - self.current_latitude
      dlon = float(point.longitude) - self.current_longitude
      score = dlat * dlat + dlon * dlon
      if best_score is None or score < best_score:
        best_score = score
        best_idx = idx

    self._route_ahead_index = best_idx
    return self.route_points[best_idx:]

  def _refresh_route_projection(self, force: bool = False) -> None:
    route_points = self.route_points[self._route_ahead_index:]
    if len(route_points) < 2:
      self._projected_route_points = []
      self._projected_route_key = None
      return

    projection_key = (
      self._route_ahead_index,
      len(self.route_points),
      round(self.display_center_latitude, 5),
      round(self.display_center_longitude, 5),
      round(self.display_zoom, 2),
    )
    if not force and projection_key == self._projected_route_key:
      return

    started = time.monotonic()
    self._projected_route_points = project_nav_polyline(
      route_points,
      self.display_center_latitude,
      self.display_center_longitude,
      self.display_zoom,
      0.0,
      PANEL_WIDTH - 24,
      MAP_HEIGHT,
    )
    self._projected_route_key = projection_key

    project_ms = (time.monotonic() - started) * 1000
    if project_ms > 3.0:
      log_issue_limited(
        "nav_map_projection_slow",
        "ui",
        f"nav map projection slow project_ms={project_ms:.2f} points={len(route_points)} active={self.active}",
        interval_sec=1.0,
      )

  def _icon_asset_name(self) -> str | None:
    if not self._display_next_valid():
      return None
    dir_left = self._display_direction_is_left()
    if self.next_type == 1:
      return "direction_turn_left.png" if dir_left else "direction_turn_right.png"
    if self.next_type == 2:
      return "direction_off_ramp_left.png" if dir_left else "direction_off_ramp_right.png"
    if self.next_type == 3:
      return "direction_merge_left.png" if dir_left else "direction_merge_right.png"
    if self.next_type == 4:
      return "direction_fork_left.png" if dir_left else "direction_fork_right.png"
    if self.next_type == 6:
      return "direction_arrive.png"
    return "direction_continue_left.png" if dir_left else "direction_continue_right.png"

  def _display_next_valid(self) -> bool:
    return bool(
      self.next_valid and (
        self.next_distance > 1.0
        or bool(self.next_description)
        or self.next_type == 6
      )
    )

  def _display_direction_is_left(self) -> bool:
    description = f" {self.next_description.lower()} "
    if " left " in description and " right " not in description:
      return True
    if " right " in description and " left " not in description:
      return False
    return self.next_direction == 1

  def _display_route_active(self) -> bool:
    return bool(
      self.nav_active and (
        self.distance_remaining > 1.0
        or self.time_remaining > 1.0
        or bool(self.destination_name)
        or self._display_next_valid()
        or len(self.route_points) >= 2
      )
    )

  def _icon_texture(self):
    name = self._icon_asset_name()
    if name is None:
      return None
    if name in self._icon_textures:
      return self._icon_textures[name]

    path = ICON_ASSET_DIR / name
    if not path.exists():
      return None

    texture = rl.load_texture(path.as_posix())
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
    self._icon_textures[name] = texture
    return texture

  def _destination_texture(self):
    name = "direction_flag.png"
    if name in self._icon_textures:
      return self._icon_textures[name]

    path = ICON_ASSET_DIR / name
    if not path.exists():
      return None

    texture = rl.load_texture(path.as_posix())
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
    self._icon_textures[name] = texture
    return texture

  def _fit_text_size(self, font: rl.Font, text: str, max_width: float, max_size: int, min_size: int) -> int:
    for size in range(max_size, min_size - 1, -1):
      if measure_text_cached(font, text, size).x <= max_width:
        return size
    return min_size

  @staticmethod
  def _lerp(start: float, end: float, alpha: float) -> float:
    return start + (end - start) * alpha

  def update(self):
    now = time.monotonic()
    if now - self._last_params_refresh >= PARAMS_REFRESH_S:
      try:
        self._maps_enabled = self._params.get_bool("OnScreenNavigation")
      except UnknownKeyName:
        # If the param doesn't exist in this build, default to disabled.
        self._maps_enabled = False
      self._last_params_refresh = now

    if not gui_app.big_ui():
      self.active = False
      return
    if not self._maps_enabled:
      self.active = False
      return

    sm = ui_state.sm
    if sm.updated["iqNavRenderState"]:
      rs = sm["iqNavRenderState"]
      rs_lat = float(rs.currentLatitude)
      rs_lon = float(rs.currentLongitude)
      has_fix = abs(rs_lat) > 0.001 and abs(rs_lon) > 0.001
      if has_fix:
        self.current_latitude = rs_lat
        self.current_longitude = rs_lon
        self.bearing_deg = float(rs.bearingDeg)
        self.zoom_hint = float(rs.zoomHint) if float(rs.zoomHint) > 0.0 else 16.0
        self._has_render_fix = True
      route_points = list(rs.routePolylineSimplified) if len(rs.routePolylineSimplified) > 0 else list(rs.routePolyline)
      if route_points:
        self.route_points = route_points
        self._projected_route_key = None
      self.next_distance = float(rs.nextManeuverDistance)
      self.next_direction = self._enum_value(rs.nextManeuverDirection)
      self.next_type = self._enum_value(rs.nextManeuverType)
      if self._has_render_fix:
        self.render_center_latitude, self.render_center_longitude, self.render_zoom = choose_nav_camera(
          self.current_latitude,
          self.current_longitude,
          self.bearing_deg,
          self._route_ahead_points(),
          PANEL_WIDTH - 24,
          MAP_HEIGHT,
          self.zoom_hint,
        )
      self.destination_latitude = float(rs.destinationLatitude)
      self.destination_longitude = float(rs.destinationLongitude)
      if self.display_center_latitude == 0.0 and self.display_center_longitude == 0.0:
        self.display_center_latitude = self.render_center_latitude
        self.display_center_longitude = self.render_center_longitude
        self.display_zoom = self.render_zoom
      self.active = bool(rs.active) or self._has_render_fix or bool(self.route_points)

    if sm.updated["iqNavState"]:
      nav = sm["iqNavState"]
      self.nav_active = bool(nav.active)
      self.next_valid = bool(nav.nextManeuverValid)
      self.destination_name = str(nav.destinationName or "")
      self.next_description = nav.nextManeuverDescription if nav.nextManeuverValid else ""
      self.time_remaining = float(nav.timeRemaining)
      self.distance_remaining = float(nav.distanceRemaining)
      self.next_direction = self._enum_value(nav.nextManeuverDirection) if nav.nextManeuverValid else self.next_direction
      self.next_type = self._enum_value(nav.nextManeuverType) if nav.nextManeuverValid else self.next_type

    if sm.updated["iqLiveData"]:
      self.road_name = sm["iqLiveData"].roadName

    if self.active:
      self.display_center_latitude = self._lerp(self.display_center_latitude, self.render_center_latitude, CAMERA_SMOOTHING)
      self.display_center_longitude = self._lerp(self.display_center_longitude, self.render_center_longitude, CAMERA_SMOOTHING)
      self.display_zoom = self._lerp(self.display_zoom, self.render_zoom, CAMERA_SMOOTHING)
      if now - self._last_projection_update >= ROUTE_PROJECTION_UPDATE_S:
        self._refresh_route_projection()
        self._last_projection_update = now

      if now - self._last_mapbox_update >= MAP_PROVIDER_UPDATE_S:
        self._mapbox.update(
          self.display_center_latitude,
          self.display_center_longitude,
          self.display_zoom,
          PANEL_WIDTH - 24,
          MAP_HEIGHT,
        )
        self._last_mapbox_update = now

      mapbox_status = self._mapbox.status()
      should_update_offline = mapbox_status in {"disabled", "token_missing", "error"} or not self._mapbox.has_content()
      if should_update_offline and now - self._last_offline_update >= OFFLINE_PROVIDER_UPDATE_S:
        self._offline.update(
          self.display_center_latitude,
          self.display_center_longitude,
          self.display_zoom,
          PANEL_WIDTH - 24,
          MAP_HEIGHT,
        )
        self._last_offline_update = now

  def maps_enabled(self) -> bool:
    now = time.monotonic()
    if now - self._last_params_refresh >= PARAMS_REFRESH_S:
      try:
        self._maps_enabled = self._params.get_bool("OnScreenNavigation")
      except UnknownKeyName:
        self._maps_enabled = False
      self._last_params_refresh = now
    return bool(self._maps_enabled)

  @staticmethod
  def _draw_card(rect: rl.Rectangle):
    shadow = rl.Rectangle(rect.x + 8, rect.y + 12, rect.width, rect.height)
    rl.draw_rectangle_rounded(shadow, CARD_RADIUS, 18, rl.Color(4, 8, 14, 110))
    rl.draw_rectangle_rounded(rect, CARD_RADIUS, 18, rl.Color(9, 18, 28, 246))
    rl.draw_rectangle_rounded_lines(rect, CARD_RADIUS, 18, rl.Color(255, 255, 255, 35))

  @staticmethod
  def _draw_fallback_background(rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.04, 14, rl.Color(20, 27, 37, 255))
    spacing = 44
    line_color = rl.Color(90, 104, 123, 86)
    x = rect.x
    while x < rect.x + rect.width:
      rl.draw_line(int(x), int(rect.y), int(x), int(rect.y + rect.height), line_color)
      x += spacing
    y = rect.y
    while y < rect.y + rect.height:
      rl.draw_line(int(rect.x), int(y), int(rect.x + rect.width), int(y), line_color)
      y += spacing

  @staticmethod
  def _draw_ego_arrow(center_x: float, center_y: float, bearing_deg: float):
    rl.draw_circle_v(rl.Vector2(center_x, center_y + 6), 15.0, rl.Color(0, 0, 0, 120))
    heading = math.radians(bearing_deg)

    def rotate(px: float, py: float) -> rl.Vector2:
      rx = (px * math.cos(heading)) - (py * math.sin(heading))
      ry = (px * math.sin(heading)) + (py * math.cos(heading))
      return rl.Vector2(center_x + rx, center_y + ry)

    nose = rotate(0.0, -18.0)
    left = rotate(-11.5, 14.0)
    right = rotate(11.5, 14.0)
    rl.draw_triangle(nose, left, right, rl.Color(255, 255, 255, 245))

  def _draw_provider_badge(self, map_rect: rl.Rectangle):
    status = self._mapbox.status()
    offline_status = self._offline.status()
    if status == "offline_cache":
      label = f"{self.road_name or 'Navigation'} (Mapbox cached)"
    elif status == "ready" or self._mapbox.has_content():
      label = self.road_name or "Navigation"
    elif offline_status == "offline_ready" and self._offline.has_content():
      label = f"{self.road_name or 'Navigation'} (offline local)"
    else:
      label = {
        "disabled": "Mapbox disabled",
        "token_missing": "Mapbox token missing",
        "loading": "Loading live map",
        "error": "Mapbox unavailable",
        "offline_cache": "Mapbox cached",
      }.get(status, self.road_name or "Navigation")
      if offline_status == "offline_missing" and status in {"token_missing", "error"}:
        label = "Offline maps missing"
      elif offline_status == "offline_invalid" and status in {"token_missing", "error"}:
        label = "Offline maps invalid"

    badge = rl.Rectangle(map_rect.x + 16, map_rect.y + 16, min(280.0, map_rect.width - 32), 38)
    rl.draw_rectangle_rounded(badge, 0.28, 10, rl.Color(7, 12, 18, 175))
    rl.draw_text_ex(self._micro_font, label, rl.Vector2(badge.x + 14, badge.y + 9), 20, 0, rl.Color(238, 243, 247, 240))

  @staticmethod
  def _draw_panel_shell(rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.03, 12, rl.Color(9, 18, 28, 248))
    rl.draw_rectangle_rounded_lines(rect, 0.03, 12, rl.Color(255, 255, 255, 26))

  @staticmethod
  def _draw_glass_band(rect: rl.Rectangle, alpha: int = 220):
    rl.draw_rectangle_rounded(rect, 0.02, 10, rl.Color(7, 12, 18, alpha))

  def _format_next_distance(self) -> str:
    if not self._display_next_valid() or self.next_distance <= 0.0:
      return "--"
    if ui_state.is_metric:
      if self.next_distance >= 1000.0:
        return f"{self.next_distance / 1000.0:.1f} km"
      return f"{self.next_distance:.0f} m"

    feet = self.next_distance * 3.28084
    if feet >= 900.0:
      return f"{self.next_distance * 0.000621371:.1f} mi"
    if feet < 500.0:
      return f"{int(round(feet / 50) * 50)} ft"
    return f"{int(round(feet / 100) * 100)} ft"

  def _format_remaining_distance(self) -> str:
    if not self._display_route_active() or self.distance_remaining <= 0.0:
      return "--"
    if ui_state.is_metric:
      return f"{self.distance_remaining / 1000.0:.1f} km"
    return f"{self.distance_remaining * 0.000621371:.1f} mi"

  def _format_eta_clock(self) -> str:
    if not self._display_route_active() or self.time_remaining <= 0.0:
      return "--"
    eta_epoch = time.time() + self.time_remaining
    if ui_state.is_metric:
      return time.strftime("%H:%M", time.localtime(eta_epoch))
    return time.strftime("%-I:%M %p", time.localtime(eta_epoch)).lower()

  def _draw_map_surface(self, map_rect: rl.Rectangle, draw_fade: bool = True) -> None:
    rl.begin_scissor_mode(int(map_rect.x), int(map_rect.y), int(map_rect.width), int(map_rect.height))
    self._draw_fallback_background(map_rect)
    if not self._mapbox.draw(map_rect, self.display_center_latitude, self.display_center_longitude, self.display_zoom):
      self._offline.draw(map_rect, self.display_center_latitude, self.display_center_longitude, self.display_zoom)
    if draw_fade:
      fade = rl.Rectangle(map_rect.x, map_rect.y + map_rect.height - 128, map_rect.width, 128)
      rl.draw_rectangle_gradient_v(int(fade.x), int(fade.y), int(fade.width), int(fade.height), rl.Color(0, 0, 0, 0), rl.Color(4, 10, 16, 170))
    self._draw_route_overlay(map_rect)
    rl.end_scissor_mode()

  def _draw_route_overlay(self, map_rect: rl.Rectangle):
    if len(self._projected_route_points) >= 2:
      for idx in range(len(self._projected_route_points) - 1):
        x1, y1 = self._projected_route_points[idx]
        x2, y2 = self._projected_route_points[idx + 1]
        p1 = rl.Vector2(map_rect.x + x1, map_rect.y + y1)
        p2 = rl.Vector2(map_rect.x + x2, map_rect.y + y2)
        rl.draw_line_ex(p1, p2, 16.0, rl.Color(8, 18, 30, 220))
        rl.draw_line_ex(p1, p2, 10.0, rl.Color(255, 255, 255, 210))
        rl.draw_line_ex(p1, p2, 6.0, rl.Color(58, 164, 255, 255))

    if abs(self.destination_latitude) > 0.001 and abs(self.destination_longitude) > 0.001:
      dest_x, dest_y = project_nav_point(
        self.destination_latitude,
        self.destination_longitude,
        self.display_center_latitude,
        self.display_center_longitude,
        self.display_zoom,
        0.0,
        map_rect.width,
        map_rect.height,
      )
      center = rl.Vector2(map_rect.x + dest_x, map_rect.y + dest_y)
      rl.draw_circle_v(center, 12.0, rl.Color(7, 18, 26, 235))
      rl.draw_circle_lines(int(center.x), int(center.y), 12.0, rl.Color(255, 255, 255, 150))
      texture = self._destination_texture()
      if texture is not None:
        src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
        dst = rl.Rectangle(center.x - 9, center.y - 11, 18, 22)
        rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)

    ego_x, ego_y = project_nav_point(
      self.current_latitude,
      self.current_longitude,
      self.display_center_latitude,
      self.display_center_longitude,
      self.display_zoom,
      0.0,
      map_rect.width,
      map_rect.height,
    )
    self._draw_ego_arrow(map_rect.x + ego_x, map_rect.y + ego_y, self.bearing_deg)

  def _draw_maneuver_icon(self, tile: rl.Rectangle):
    display_next_valid = self._display_next_valid()
    bg_color = rl.Color(34, 188, 90, 255) if display_next_valid else rl.Color(32, 48, 62, 255)
    rl.draw_rectangle_rounded(tile, 0.22, 10, bg_color)
    texture = self._icon_texture()
    if texture is not None and display_next_valid:
      src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
      padding = 18
      dst = rl.Rectangle(tile.x + padding, tile.y + 12, tile.width - padding * 2, tile.height - 44)
      rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)

    distance_text = f"{self.next_distance:.0f} m" if display_next_valid and self.next_distance > 0 else "--"
    distance_size = self._fit_text_size(self._micro_font, distance_text, tile.width - 22, 22, 16)
    dist_width = measure_text_cached(self._micro_font, distance_text, distance_size).x
    rl.draw_text_ex(self._micro_font, distance_text, rl.Vector2(tile.x + (tile.width - dist_width) * 0.5, tile.y + tile.height - 34), distance_size, 0, rl.WHITE)

  def _draw_split_header(self, rect: rl.Rectangle):
    header_rect = rl.Rectangle(rect.x + 14, rect.y + 14, rect.width - 28, SPLIT_HEADER_HEIGHT - 20)
    self._draw_glass_band(header_rect, 214)

    icon_tile = rl.Rectangle(header_rect.x + 18, header_rect.y + 18, 112, 112)
    self._draw_maneuver_icon(icon_tile)

    display_next_valid = self._display_next_valid()
    display_route_active = self._display_route_active()
    distance_text = self._format_next_distance()
    if display_next_valid and self.next_description:
      title = self.next_description
    elif display_route_active and self.destination_name:
      title = self.destination_name
    elif display_route_active:
      title = "Route guidance"
    else:
      title = self.road_name or "Navigation"

    if display_next_valid and self.road_name:
      sublabel = self.road_name
    elif display_route_active:
      sublabel = "Route active"
    else:
      sublabel = self.road_name or "Navigation standby"

    text_x = icon_tile.x + icon_tile.width + 22
    right_x = header_rect.x + header_rect.width - 22
    distance_size = self._fit_text_size(self._title_font, distance_text, 140, 42, 22)
    distance_width = measure_text_cached(self._title_font, distance_text, distance_size).x
    rl.draw_text_ex(self._title_font, distance_text, rl.Vector2(right_x - distance_width, header_rect.y + 22), distance_size, 0, rl.WHITE)

    title_max_width = max(160.0, right_x - text_x - 10)
    title_size = self._fit_text_size(self._title_font, title, title_max_width, 34, 22)
    title_lines = wrap_text(self._title_font, title, title_size, int(title_max_width))[:2]
    for idx, line in enumerate(title_lines):
      rl.draw_text_ex(self._title_font, line, rl.Vector2(text_x, header_rect.y + 24 + idx * (title_size + 2)), title_size, 0, rl.WHITE)

    sub_size = self._fit_text_size(self._micro_font, sublabel, title_max_width, 22, 18)
    sub_y = header_rect.y + 30 + len(title_lines) * (title_size + 2)
    rl.draw_text_ex(self._micro_font, sublabel, rl.Vector2(text_x, sub_y), sub_size, 0, rl.Color(179, 188, 201, 240))

  def _draw_split_footer(self, rect: rl.Rectangle):
    footer_rect = rl.Rectangle(rect.x + 14, rect.y + rect.height - SPLIT_FOOTER_HEIGHT - 14, rect.width - 28, SPLIT_FOOTER_HEIGHT)
    self._draw_glass_band(footer_rect, 222)

    chips_y = footer_rect.y + 20
    chips_x = footer_rect.x + 20
    chips_gap = 12
    chip_width = (footer_rect.width - 40 - chips_gap * 2) / 3.0
    self._draw_stat_chip(rl.Rectangle(chips_x, chips_y, chip_width, 54), self._format_eta_clock(), "eta")
    minutes_text = f"{self.time_remaining / 60.0:.1f} min" if self._display_route_active() and self.time_remaining > 0.0 else "--"
    self._draw_stat_chip(rl.Rectangle(chips_x + chip_width + chips_gap, chips_y, chip_width, 54), minutes_text, "time")
    self._draw_stat_chip(rl.Rectangle(chips_x + (chip_width + chips_gap) * 2, chips_y, chip_width, 54), self._format_remaining_distance(), "left")

  def _draw_info_panel(self, panel_rect: rl.Rectangle):
    info_rect = rl.Rectangle(panel_rect.x + 14, panel_rect.y + MAP_HEIGHT + 26, panel_rect.width - 28, panel_rect.height - MAP_HEIGHT - 40)
    rl.draw_rectangle_rounded(info_rect, 0.08, 12, rl.Color(8, 14, 20, 225))

    icon_tile = rl.Rectangle(info_rect.x + 16, info_rect.y + 16, 124, 124)
    self._draw_maneuver_icon(icon_tile)

    display_next_valid = self._display_next_valid()
    display_route_active = self._display_route_active()

    if display_next_valid and self.next_description:
      title = self.next_description
    elif display_route_active and self.destination_name:
      title = self.destination_name
    elif display_route_active:
      title = "Route guidance"
    else:
      title = self.road_name or "Navigation"
    title_x = info_rect.x + 162
    title_max_width = info_rect.width - 178
    title_size = self._fit_text_size(self._title_font, title, title_max_width, 34, 24)
    title_lines = wrap_text(self._title_font, title, title_size, int(title_max_width))[:2]
    for idx, line in enumerate(title_lines):
      rl.draw_text_ex(self._title_font, line, rl.Vector2(title_x, info_rect.y + 18 + idx * (title_size + 2)), title_size, 0, rl.WHITE)

    if display_next_valid and self.road_name:
      road_label = self.road_name
    elif display_route_active:
      road_label = "Route active"
    else:
      road_label = self.road_name or "No active route"
    road_size = self._fit_text_size(self._micro_font, road_label, title_max_width, 22, 18)
    road_y = info_rect.y + 18 + len(title_lines) * (title_size + 2) + 8
    rl.draw_text_ex(self._micro_font, road_label, rl.Vector2(title_x, road_y), road_size, 0, rl.Color(171, 184, 196, 240))

    eta_text = f"{(self.time_remaining / 60.0):.1f} min" if display_route_active and self.time_remaining > 0 else "--"
    remaining_text = f"{(self.distance_remaining / 1000.0):.1f} km" if display_route_active and self.distance_remaining > 0 else "--"
    next_text = f"{self.next_distance:.0f} m" if display_next_valid and self.next_distance > 0 else "--"

    stat_y = info_rect.y + info_rect.height - 58
    available_width = info_rect.width - 178
    chip_width = (available_width - STAT_GAP * 2) / 3.0
    self._draw_stat_chip(rl.Rectangle(title_x, stat_y, chip_width, 50), next_text, "next")
    self._draw_stat_chip(rl.Rectangle(title_x + chip_width + STAT_GAP, stat_y, chip_width, 50), eta_text, "eta")
    self._draw_stat_chip(rl.Rectangle(title_x + (chip_width + STAT_GAP) * 2, stat_y, chip_width, 50), remaining_text, "left")

  def _draw_stat_chip(self, rect: rl.Rectangle, value: str, label: str):
    rl.draw_rectangle_rounded(rect, 0.24, 10, rl.Color(18, 30, 42, 255))
    value_size = self._fit_text_size(self._body_font, value, rect.width - 16, 20, 15)
    label_size = self._fit_text_size(self._micro_font, label.upper(), rect.width - 16, 11, 9)
    value_width = measure_text_cached(self._body_font, value, value_size).x
    label_width = measure_text_cached(self._micro_font, label.upper(), label_size).x
    rl.draw_text_ex(self._body_font, value, rl.Vector2(rect.x + (rect.width - value_width) * 0.5, rect.y + 5), value_size, 0, rl.WHITE)
    rl.draw_text_ex(self._micro_font, label.upper(), rl.Vector2(rect.x + (rect.width - label_width) * 0.5, rect.y + 31), label_size, 0, rl.Color(122, 205, 161, 255))

  def _render(self, rect: rl.Rectangle):
    if not self.active or not gui_app.big_ui():
      return

    panel_rect = rl.Rectangle(rect.x + rect.width - PANEL_WIDTH - PANEL_MARGIN_RIGHT, rect.y + PANEL_MARGIN_TOP, PANEL_WIDTH, PANEL_HEIGHT)
    self._draw_card(panel_rect)

    map_rect = rl.Rectangle(panel_rect.x + 12, panel_rect.y + 12, panel_rect.width - 24, MAP_HEIGHT)
    self._draw_map_surface(map_rect)

    self._draw_provider_badge(map_rect)
    self._draw_info_panel(panel_rect)

  def render_split_direct(self, rect: rl.Rectangle) -> None:
    local_rect = rl.Rectangle(rect.x, rect.y, rect.width, rect.height)
    map_rect = rl.Rectangle(rect.x + 8, rect.y + 8, rect.width - 16, rect.height - 16)
    self._draw_panel_shell(local_rect)
    self._draw_map_surface(map_rect, draw_fade=False)
    self._draw_provider_badge(map_rect)
    self._draw_split_header(local_rect)
    self._draw_split_footer(local_rect)

  def render_split(self, rect: rl.Rectangle) -> None:
    self.render_split_direct(rect)
