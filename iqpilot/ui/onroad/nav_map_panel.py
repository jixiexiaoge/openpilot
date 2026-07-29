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

from openpilot.common.basedir import BASEDIR
from openpilot.common.iq_perf import PerfSample, PerfTraceEmitter
from openpilot.common.params import Params, UnknownKeyName
from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position, resolve_mapbox_token
from openpilot.selfdrive.ui.lib.local_routes import utc_offset_hours
from openpilot.iqpilot.ui.onroad.offline_tiles import (
  find_offline_mbtiles_path,
  find_offline_xyz_root,
  load_raster_tile_blob,
  load_raster_xyz_tile_blob,
  mbtiles_is_raster,
  mbtiles_zoom_bounds,
  open_mbtiles,
  xyz_zoom_bounds,
)
from openpilot.iqpilot.ui.onroad.nav_map_utils import (
  build_mapbox_tile_url,
  choose_nav_camera,
  mercator_world_px_at_zoom,
  project_nav_point,
  project_nav_polyline,
  solar_elevation_deg,
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
# parents[4] pointed one level above the repo (stock selfdrive/assets has no nav icons),
# so the maneuver arrow never loaded anywhere — anchor to BASEDIR instead
ICON_ASSET_DIR = Path(BASEDIR) / "iqpilot" / "selfdrive" / "assets" / "navigation"
STAT_GAP = 10
TILE_SIZE = 256
# env-overridable GPU-texture footprint levers; CACHE_LIMIT must stay >= the keep-set (~(visible + 2*margin)^2)
TILE_SCALE = int(os.getenv("IQPILOT_NAV_TILE_SCALE", "2"))
# Downscale each decoded tile before uploading to the GPU. Mapbox only serves integer-retina
# tiles (@2x = 512px), which cost ~1MB of dmabuf each; the resident cache of these is the bulk
# of the map's memory floor. Resizing the crisp @2x source down to TILE_SIZE*this (1.75 -> 448px,
# ~768KB) reclaims GPU memory while staying sharper than a native @1x (256px) fetch would be.
# Only ever downsamples — sources already at/under the target (e.g. native 256px offline tiles)
# are left untouched. Set to TILE_SCALE to keep full @2x resolution.
TILE_TEXTURE_SCALE = float(os.getenv("IQPILOT_NAV_TILE_TEXTURE_SCALE", "1.75"))
MAX_INFLIGHT_TILES = 8
CAMERA_SMOOTHING = 0.18
# The onroad corner panel is immediate-mode redrawn (rounded rects + every glyph + tile blits)
# every UI frame at 20Hz, which measured at ~52% of a CPU core on a comma 3x and starved radard.
# Cache the whole panel in a persistent RenderTexture and only re-render it a few times a second;
# every frame just blits the cached texture. A corner map panning at 12Hz is visually seamless.
PANEL_RENDER_FPS = max(1, int(os.getenv("IQPILOT_NAV_PANEL_FPS", "12")))
PANEL_RENDER_INTERVAL = 1.0 / PANEL_RENDER_FPS
# The drop-shadow is drawn a few px past the panel bounds; pad the render target so it isn't clipped.
PANEL_SHADOW_PAD = 16
# Chrome (badge + info-panel text/chips) only changes when nav values change, so it's cached in its
# own texture regenerated on a content-key change. This cap forces a refresh at least every 0.5s so a
# missed key field can never freeze the readout.
CHROME_MAX_INTERVAL = 0.5
CACHE_MARGIN_TILES = int(os.getenv("IQPILOT_NAV_CACHE_MARGIN", "2"))
CACHE_LIMIT = int(os.getenv("IQPILOT_NAV_CACHE_LIMIT", "96"))
# The corner panel's viewport (560x392) keeps ~(3+2*margin)x(2+2*margin) = 42 tiles on
# screen+margin; 96 was sized for the full-screen interactive map and doubles the panel's
# resident GPU footprint for tiles that can never be drawn.
PANEL_CACHE_LIMIT = int(os.getenv("IQPILOT_NAV_PANEL_CACHE_LIMIT", "48"))
# How long mapbox must stay healthy before the offline fallback's tile cache is freed.
OFFLINE_RELEASE_AFTER_S = 60.0
PARAMS_REFRESH_S = 0.5
MAP_PROVIDER_UPDATE_S = 0.25
# Offline decode now runs off the render thread (worker pattern, same as mapbox), so when
# offline is the engaged provider it updates at the same cadence as the online one.
OFFLINE_PROVIDER_UPDATE_S = MAP_PROVIDER_UPDATE_S
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
NAV_TEXTURE_WARN_US = 20_000
NAV_TILE_OP_WARN_US = 10_000
NAV_PRUNE_WARN_US = 10_000
NAV_BURST_WARN_TILES = 4
NAV_PERF = PerfTraceEmitter("ui.nav")


def _downscale_tile_image(image) -> None:
  """Shrink a decoded tile image in place to the configured texture footprint.

  Downsample-only: leaves images already at/under the target size alone so native low-DPI
  (e.g. 256px offline) tiles are never upscaled. The resize is a CPU (stb) bicubic pass, so
  it must run OFF the render thread (in the fetch worker) — doing it inline in _consume_pending
  stalled the UI loop for several ms per tile and caused visible map lag on tile bursts."""
  target = int(round(TILE_SIZE * TILE_TEXTURE_SCALE))
  if target > 0 and image.width > target:
    rl.image_resize(image, target, target)


def _decode_tile_image(payload: bytes):
  """Decode a raw tile payload to an rl.Image and downscale it, on the calling thread.

  Pure CPU (stb) work — no GL context needed — so it is safe to run from a fetch worker
  thread. The returned Image is uploaded to a GPU texture later on the render thread.

  Raises ValueError on undecodable payloads: stb returns a 0x0 image instead of failing
  (e.g. webp, which stb can't read), and uploading that produces an invisible texture the
  cache then counts as content — the map draws blank while the badge claims tiles."""
  image = rl.load_image_from_memory(MapboxTileProvider._image_ext(payload), payload, len(payload))
  if image.width <= 0 or image.height <= 0:
    rl.unload_image(image)
    raise ValueError("undecodable tile payload")
  _downscale_tile_image(image)
  # pooled textures are refilled in place; contents must be RGBA8 regardless of source format
  rl.image_format(image, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
  return image


def _emit_nav_perf(event_class: str, *, frame_id: int = 0, total_time_us: int = 0,
                   batch_size: int = 0, severity: str = "warning", detail: str = "",
                   sample: PerfSample | None = None, min_interval_s: float = 0.5) -> None:
  NAV_PERF.emit(
    event_class,
    severity=severity,
    frame_id=frame_id,
    total_time_us=total_time_us,
    batch_size=batch_size,
    samples=[sample] if sample is not None else None,
    detail=detail,
    min_interval_s=min_interval_s,
  )


class TexturePool:
  """Recycles GL texture objects between tiles of identical size/format.

  Creating/destroying thousands of texture objects per drive ratchets the GL
  driver's CPU-side pools (measured: hundreds of MB of driver-owned anon memory
  on both Adreno and Mac). Refilling an existing texture via rl.update_texture
  allocates nothing at steady state. Render thread only."""

  def __init__(self, max_free: int):
    self._max_free = max_free
    self._free: dict[tuple[int, int], list[Any]] = {}

  def acquire(self, image) -> Any:
    bucket = self._free.get((image.width, image.height))
    if bucket:
      texture = bucket.pop()
      rl.update_texture(texture, image.data)
      return texture
    texture = rl.load_texture_from_image(image)
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
    return texture

  def release(self, texture) -> None:
    bucket = self._free.setdefault((texture.width, texture.height), [])
    if len(bucket) < self._max_free:
      bucket.append(texture)
    else:
      rl.unload_texture(texture)

  def drain(self) -> None:
    for bucket in self._free.values():
      for texture in bucket:
        rl.unload_texture(texture)
    self._free.clear()


class MapboxTileProvider:
  def __init__(self, cache_limit: int = CACHE_LIMIT):
    self._cache_limit = cache_limit
    self._pool = TexturePool(cache_limit)
    self._params = Params()
    self._session = requests.Session()
    # Decoded, downscaled rl.Images ready for GPU upload. Decoding + resizing happens off the
    # render thread (fetch worker) and is drained by _consume_pending, which only uploads.
    self._pending_tiles: dict[tuple[int, int, int], Any] = {}
    self._inflight: set[tuple[int, int, int]] = set()
    self._textures: dict[tuple[int, int, int], rl.Texture] = {}
    self._lock = threading.Lock()
    self._status = "idle"
    self._viewport_complete = False
    self._cache_root = TILE_CACHE_ROOT
    self._cache_root.mkdir(parents=True, exist_ok=True)
    self._provider_disabled = MAPBOX_PROVIDER_DISABLED
    self._cache_disabled = MAPBOX_CACHE_DISABLED
    self._day_mode = False
    self._style = "navigation-night-v1"
    self._rotated = False
    self._keep_margin = CACHE_MARGIN_TILES

  def set_day_mode(self, day: bool) -> None:
    """Switch between the day/night Mapbox styles. Frees the tile cache on a change —
    the resident textures are the wrong palette. Render-thread only (release touches GL)."""
    if day == self._day_mode:
      return
    self._day_mode = day
    self._style = "navigation-day-v1" if day else "navigation-night-v1"
    self.release()

  def _token(self) -> str:
    return resolve_mapbox_token(self._params)

  def _fetch_worker(self, tile_key: tuple[int, int, int], token: str) -> None:
    z, x, y = tile_key
    url = build_mapbox_tile_url(z, x, y, tile_size=TILE_SIZE, scale=TILE_SCALE, style=self._style)
    try:
      response = self._session.get(url, params={"access_token": token}, timeout=1.5)
      fallback_style = "light-v11" if self._day_mode else "dark-v11"
      if response.status_code == 401 and self._style != fallback_style:
        # some tokens can't access the navigation styles ("Direct access not allowed")
        self._style = fallback_style
        url = build_mapbox_tile_url(z, x, y, tile_size=TILE_SIZE, scale=TILE_SCALE, style=self._style)
        response = self._session.get(url, params={"access_token": token}, timeout=3.0)
      response.raise_for_status()
      if not self._cache_disabled:
        cache_path = self._cache_path(tile_key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
      # Decode + downscale here on the worker thread (pure CPU/stb, no GL), so the render
      # thread only pays the cheap GPU upload in _consume_pending.
      self._stash_pending(tile_key, _decode_tile_image(response.content))
      self._status = "ready"
    except (requests.RequestException, ValueError):
      if not self._queue_cached_tile(tile_key, inline=True):
        self._status = "error"
    finally:
      self._inflight.discard(tile_key)

  def _cache_path(self, tile_key: tuple[int, int, int]) -> Path:
    z, x, y = tile_key
    # style-keyed: day and night tiles must never mix in the disk cache
    return self._cache_root / self._style / str(z) / str(x) / f"{y}@{TILE_SCALE}x.png"

  def _queue_cached_tile(self, tile_key: tuple[int, int, int], inline: bool = False) -> bool:
    if self._cache_disabled:
      return False
    if tile_key in self._textures or tile_key in self._pending_tiles:
      return True
    # The render-thread path defers when the tile is already being fetched/decoded; the inline
    # (network-error fallback) path owns its own _inflight entry, so it must not short-circuit here.
    if not inline and tile_key in self._inflight:
      return True

    cache_path = self._cache_path(tile_key)
    if not cache_path.exists():
      return False

    if inline:
      # Already on a worker thread (network-error fallback) — decode here directly.
      try:
        payload = cache_path.read_bytes()
        self._stash_pending(tile_key, _decode_tile_image(payload))
      except (OSError, ValueError):
        return False
      self._status = "offline_cache"
      return True

    # Called from the render thread: offload the disk read + decode + resize to a worker so the
    # UI loop never stalls, even when a whole screen of tiles is served from cache. Bounded by
    # MAX_INFLIGHT (shared with network fetches); over the cap we defer to a later frame.
    if len(self._inflight) >= MAX_INFLIGHT_TILES:
      return True
    self._inflight.add(tile_key)
    self._status = "offline_cache"
    threading.Thread(target=self._cache_decode_worker, args=(tile_key, cache_path), daemon=True).start()
    return True

  def _cache_decode_worker(self, tile_key: tuple[int, int, int], cache_path: Path) -> None:
    try:
      payload = cache_path.read_bytes()
      self._stash_pending(tile_key, _decode_tile_image(payload))
    except (OSError, ValueError):
      pass
    finally:
      self._inflight.discard(tile_key)

  def _stash_pending(self, tile_key: tuple[int, int, int], image) -> None:
    """Store a decoded tile Image for upload, unloading any Image it displaces.

    Safe to call from a fetch worker thread; only the render thread uploads/unloads textures."""
    with self._lock:
      displaced = self._pending_tiles.get(tile_key)
      self._pending_tiles[tile_key] = image
    if displaced is not None:
      rl.unload_image(displaced)

  def _consume_pending(self) -> None:
    with self._lock:
      pending = list(self._pending_tiles.items())
      self._pending_tiles.clear()

    decode_us = 0
    upload_us = 0
    unload_us = 0
    unload_count = 0
    payload_bytes = 0
    cache_before = len(self._textures)
    for tile_key, image in pending:
      # Images arrive already decoded + downscaled from the fetch worker; the render thread
      # only uploads to a GPU texture here (decode cost is off-thread, so decode_us stays ~0).
      started_ns = time.monotonic_ns()
      texture = self._pool.acquire(image)
      upload_us += (time.monotonic_ns() - started_ns) // 1000
      rl.unload_image(image)
      old_texture = self._textures.get(tile_key)
      if old_texture is not None:
        started_ns = time.monotonic_ns()
        self._pool.release(old_texture)
        unload_us += (time.monotonic_ns() - started_ns) // 1000
        unload_count += 1
      self._textures[tile_key] = texture

    total_us = decode_us + upload_us + unload_us
    if pending and (
      total_us >= NAV_TEXTURE_WARN_US
      or decode_us >= NAV_TILE_OP_WARN_US
      or upload_us >= NAV_TILE_OP_WARN_US
      or len(pending) >= NAV_BURST_WARN_TILES
    ):
      sample = PerfSample(
        texture_decode_us=int(decode_us),
        texture_upload_us=int(upload_us),
        texture_unload_us=int(unload_us),
        texture_consume_us=int(total_us),
        texture_batch_size=len(pending),
        texture_bytes=payload_bytes,
        texture_cache_before=cache_before,
        texture_cache_after=len(self._textures),
        texture_unloaded=unload_count,
      )
      _emit_nav_perf(
        "nav_texture_burst",
        total_time_us=int(total_us),
        batch_size=len(pending),
        detail=(
          f"provider=mapbox decode_us={decode_us} upload_us={upload_us} unload_us={unload_us} "
          + f"tiles={len(pending)} bytes={payload_bytes} cache_before={cache_before} cache_after={len(self._textures)}"
        ),
        sample=sample,
      )

  def _visible_tile_keys(
    self, latitude: float, longitude: float, zoom: float, width: float, height: float
  ) -> tuple[int, float, float, float, list[tuple[int, int, int]]]:
    if self._rotated:
      # rotation coverage = bounding circle; keep_margin=1 keeps resident set under cache_limit
      width = height = math.hypot(width, height)
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

  def set_rotated(self, rotated: bool) -> None:
    self._rotated = rotated
    self._keep_margin = 1 if rotated else CACHE_MARGIN_TILES

  @staticmethod
  def _image_ext(payload: bytes) -> str:
    if payload.startswith(b"\xff\xd8\xff"):
      return ".jpg"
    if payload.startswith(b"RIFF") and b"WEBP" in payload[:16]:
      return ".webp"
    return ".png"

  def _prune_cache(self, keep_tiles: set[tuple[int, int, int]]) -> None:
    if len(self._textures) <= self._cache_limit:
      return

    cache_before = len(self._textures)
    unload_count = 0
    started_ns = time.monotonic_ns()
    for tile_key in list(self._textures):
      if tile_key in keep_tiles:
        continue
      self._pool.release(self._textures.pop(tile_key))
      unload_count += 1
      if len(self._textures) <= self._cache_limit:
        break
    prune_us = (time.monotonic_ns() - started_ns) // 1000
    if prune_us >= NAV_PRUNE_WARN_US or unload_count >= NAV_BURST_WARN_TILES:
      sample = PerfSample(
        texture_prune_us=int(prune_us),
        texture_cache_before=cache_before,
        texture_cache_after=len(self._textures),
        texture_unloaded=unload_count,
      )
      _emit_nav_perf(
        "nav_texture_prune",
        total_time_us=int(prune_us),
        batch_size=unload_count,
        detail=f"provider=mapbox prune_us={prune_us} cache_before={cache_before} cache_after={len(self._textures)} unload_count={unload_count}",
        sample=sample,
      )

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
    self._viewport_complete = bool(visible_set) and all(tile_key in self._textures for tile_key in visible_set)
    if self._viewport_complete:
      self._status = "ready" if token else "offline_cache"
    elif self._inflight:
      self._status = "loading"
    elif self._textures:
      self._status = "offline_cache"

    tile_count = 2 ** z
    keep_tiles = set()
    for tile_key in visible_tiles:
      _, tile_x, tile_y = tile_key
      for dx in range(-self._keep_margin, self._keep_margin + 1):
        for dy in range(-self._keep_margin, self._keep_margin + 1):
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

  def viewport_complete(self) -> bool:
    """True when every tile of the last update() viewport has a resident texture."""
    return self._viewport_complete

  def release(self) -> None:
    """Free all GPU tile textures and drop pending decodes.

    Called when the map panel goes inactive (offroad / maps disabled) so the tile
    cache — up to CACHE_LIMIT textures of dmabuf-backed GPU memory — isn't held
    resident while nothing is drawing it. Safe to call from the UI thread only
    (raylib GL context); update()/_consume_pending() already run here."""
    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures.clear()
    self._pool.drain()
    with self._lock:
      pending_images = list(self._pending_tiles.values())
      self._pending_tiles.clear()
    for image in pending_images:
      rl.unload_image(image)
    self._status = "idle"
    self._viewport_complete = False


class OsmOfflineProvider:
  def __init__(self, cache_limit: int = CACHE_LIMIT):
    self._cache_limit = cache_limit
    self._pool = TexturePool(cache_limit)
    self._conn: Any | None = None
    # Serializes sqlite access + source swaps: blob reads run on fetch worker threads against a
    # single shared read-only connection, and _refresh_source may close/reopen it under them.
    self._db_lock = threading.Lock()
    self._mbtiles_path: Path | None = None
    self._xyz_root: Path | None = None
    # Decoded, downscaled rl.Images ready for GPU upload — same off-render-thread pattern as
    # MapboxTileProvider: workers read the blob + decode + resize, _consume_pending only uploads.
    self._pending_tiles: dict[tuple[int, int, int], Any] = {}
    self._inflight: set[tuple[int, int, int]] = set()
    self._lock = threading.Lock()
    self._textures: dict[tuple[int, int, int], rl.Texture] = {}
    self._status = "offline_missing"
    self._min_zoom: int | None = None
    self._max_zoom: int | None = None
    self._day_mode = False
    self._rotated = False
    self._keep_margin = CACHE_MARGIN_TILES

  def set_day_mode(self, day: bool) -> None:
    self._day_mode = day

  def set_rotated(self, rotated: bool) -> None:
    self._rotated = rotated
    self._keep_margin = 1 if rotated else CACHE_MARGIN_TILES

  def _close_conn_locked(self) -> None:
    if self._conn is not None:
      self._conn.close()
      self._conn = None

  def _drop_pending(self) -> None:
    with self._lock:
      pending_images = list(self._pending_tiles.values())
      self._pending_tiles.clear()
    for image in pending_images:
      rl.unload_image(image)

  def _refresh_source(self, latitude: float, longitude: float) -> None:
    mbtiles_path = find_offline_mbtiles_path(latitude, longitude, day=self._day_mode)
    xyz_root = find_offline_xyz_root(latitude, longitude)

    if self._mbtiles_path == mbtiles_path and self._xyz_root == xyz_root:
      return

    self._mbtiles_path = mbtiles_path
    self._xyz_root = xyz_root
    self._min_zoom = None
    self._max_zoom = None

    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures.clear()
    self._drop_pending()

    with self._db_lock:
      self._close_conn_locked()
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

  def _stash_pending(self, tile_key: tuple[int, int, int], image) -> None:
    """Store a decoded tile Image for upload, unloading any Image it displaces.

    Safe to call from a fetch worker thread; only the render thread uploads/unloads textures."""
    with self._lock:
      displaced = self._pending_tiles.get(tile_key)
      self._pending_tiles[tile_key] = image
    if displaced is not None:
      rl.unload_image(displaced)

  def _load_decode_worker(self, tile_key: tuple[int, int, int]) -> None:
    """Read a tile blob from disk and decode + downscale it, entirely off the render thread.

    Mirrors MapboxTileProvider._fetch_worker: the render loop must never pay the sqlite/file
    read or the stb decode — with offline as the primary provider, an inline decode of a
    screenful of tiles was a visible render-loop hitch."""
    try:
      payload = self._load_blob(tile_key)
      if payload is not None:
        self._stash_pending(tile_key, _decode_tile_image(payload))
    except Exception:
      pass
    finally:
      self._inflight.discard(tile_key)

  def _consume_pending(self) -> None:
    with self._lock:
      pending = list(self._pending_tiles.items())
      self._pending_tiles.clear()

    upload_us = 0
    unload_us = 0
    unload_count = 0
    cache_before = len(self._textures)
    for tile_key, image in pending:
      # Images arrive already decoded + downscaled from the worker; only the GPU upload runs here.
      started_ns = time.monotonic_ns()
      texture = self._pool.acquire(image)
      upload_us += (time.monotonic_ns() - started_ns) // 1000
      rl.unload_image(image)
      old_texture = self._textures.get(tile_key)
      if old_texture is not None:
        started_ns = time.monotonic_ns()
        self._pool.release(old_texture)
        unload_us += (time.monotonic_ns() - started_ns) // 1000
        unload_count += 1
      self._textures[tile_key] = texture

    total_us = upload_us + unload_us
    if pending and (
      total_us >= NAV_TEXTURE_WARN_US
      or upload_us >= NAV_TILE_OP_WARN_US
      or len(pending) >= NAV_BURST_WARN_TILES
    ):
      sample = PerfSample(
        texture_upload_us=int(upload_us),
        texture_unload_us=int(unload_us),
        texture_consume_us=int(total_us),
        texture_batch_size=len(pending),
        texture_cache_before=cache_before,
        texture_cache_after=len(self._textures),
        texture_unloaded=unload_count,
      )
      _emit_nav_perf(
        "nav_texture_burst",
        total_time_us=int(total_us),
        batch_size=len(pending),
        detail=(
          f"provider=offline upload_us={upload_us} unload_us={unload_us} "
          + f"tiles={len(pending)} cache_before={cache_before} cache_after={len(self._textures)}"
        ),
        sample=sample,
      )

  def _prune_cache(self, keep_tiles: set[tuple[int, int, int]]) -> None:
    if len(self._textures) <= self._cache_limit:
      return

    cache_before = len(self._textures)
    unload_count = 0
    started_ns = time.monotonic_ns()
    for tile_key in list(self._textures):
      if tile_key in keep_tiles:
        continue
      self._pool.release(self._textures.pop(tile_key))
      unload_count += 1
      if len(self._textures) <= self._cache_limit:
        break
    prune_us = (time.monotonic_ns() - started_ns) // 1000
    if prune_us >= NAV_PRUNE_WARN_US or unload_count >= NAV_BURST_WARN_TILES:
      sample = PerfSample(
        texture_prune_us=int(prune_us),
        texture_cache_before=cache_before,
        texture_cache_after=len(self._textures),
        texture_unloaded=unload_count,
      )
      _emit_nav_perf(
        "nav_texture_prune",
        total_time_us=int(prune_us),
        batch_size=unload_count,
        detail=f"provider=offline prune_us={prune_us} cache_before={cache_before} cache_after={len(self._textures)} unload_count={unload_count}",
        sample=sample,
      )

  def _visible_tile_keys(
    self, latitude: float, longitude: float, zoom: float, width: float, height: float
  ) -> tuple[int, float, float, float, list[tuple[int, int, int]]]:
    if self._rotated:
      width = height = math.hypot(width, height)
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
    # Runs on worker threads: the shared read-only sqlite connection is not safe for
    # concurrent queries, and _refresh_source may swap it — serialize via _db_lock.
    with self._db_lock:
      if self._conn is not None and self._status == "offline_ready":
        try:
          return load_raster_tile_blob(self._conn, z, x, y)
        except SQLITE_ERRORS:
          self._status = "offline_invalid"
          return None
      xyz_root = self._xyz_root
    if xyz_root is not None:
      return load_raster_xyz_tile_blob(xyz_root, z, x, y)
    return None

  def update(self, latitude: float, longitude: float, zoom: float, width: float, height: float) -> None:
    self._refresh_source(latitude, longitude)
    if self._status != "offline_ready":
      return

    self._consume_pending()

    z, _, center_x, center_y, visible_tiles = self._visible_tile_keys(latitude, longitude, zoom, width, height)
    # Map requested tiles to their on-disk source tiles (overzoom clamps to the stored range).
    visible_source: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for requested_tile in visible_tiles:
      source_tile, _ = self._source_tile_for_request(requested_tile)
      if source_tile not in seen:
        seen.add(source_tile)
        visible_source.append(source_tile)

    missing_tiles = [
      tile_key for tile_key in visible_source
      if tile_key not in self._textures and tile_key not in self._inflight
    ]

    def _center_distance(tile_key: tuple[int, int, int]) -> float:
      source_z, tile_x, tile_y = tile_key
      zoom_scale = 2.0 ** (z - source_z)
      return (
        abs(tile_x + 0.5 - (center_x / TILE_SIZE) / zoom_scale)
        + abs(tile_y + 0.5 - (center_y / TILE_SIZE) / zoom_scale)
      )

    missing_tiles.sort(key=_center_distance)
    launch_count = max(0, MAX_INFLIGHT_TILES - len(self._inflight))
    for tile_key in missing_tiles[:launch_count]:
      self._inflight.add(tile_key)
      threading.Thread(target=self._load_decode_worker, args=(tile_key,), daemon=True).start()

    # Keep a margin ring around the visible source tiles so panning doesn't churn re-decodes;
    # the cache limit bounds the resident GPU footprint exactly like the mapbox provider.
    keep_tiles: set[tuple[int, int, int]] = set()
    for source_z, tile_x, tile_y in visible_source:
      tile_count = 2 ** source_z
      for dx in range(-self._keep_margin, self._keep_margin + 1):
        for dy in range(-self._keep_margin, self._keep_margin + 1):
          keep_y = tile_y + dy
          if 0 <= keep_y < tile_count:
            keep_tiles.add((source_z, (tile_x + dx) % tile_count, keep_y))
    self._prune_cache(keep_tiles)

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

  def release(self) -> None:
    """Free all GPU tile textures and drop pending decodes. See MapboxTileProvider.release()."""
    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures.clear()
    self._pool.drain()
    self._drop_pending()


class NavMapPanel(Widget):
  def __init__(self, force_visible: bool = False):
    super().__init__()
    self._params = Params()
    self._force_visible = force_visible
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
    self._map_viewport_width: float = PANEL_WIDTH - 24
    self._map_viewport_height: float = MAP_HEIGHT
    self._mapbox = MapboxTileProvider(cache_limit=PANEL_CACHE_LIMIT)
    self._offline = OsmOfflineProvider(cache_limit=PANEL_CACHE_LIMIT)
    self._offline_idle_since = 0.0
    # OnlineOSMaps/OfflineOSMaps pick the tile sources: both on = online primary with offline
    # filling in whenever mapbox is unhealthy; online only = mapbox alone (stock behavior);
    # offline only = local tiles alone, mapbox never fetched (no network threads at all).
    self._online_maps_enabled = True
    self._offline_maps_enabled = False
    self._mapbox_mode_released = False
    # Day/night map styling, Apple/Google-style: solar elevation drives it once a GPS fix
    # exists (hysteresis: day above 0 deg, night below -6 deg / civil dusk); the local clock
    # seeds the first frame. OSMapsStyleMode param forces day(1)/night(2), 0 = auto.
    self._day_mode = 6 <= time.localtime().tm_hour < 20
    self._style_mode = 0
    self._last_daynight_check = 0.0
    self._heading_up = True
    self.display_bearing = 0.0
    self._title_font = gui_app.font(FontWeight.BOLD)
    self._body_font = gui_app.font(FontWeight.MEDIUM)
    self._micro_font = gui_app.font(FontWeight.SEMI_BOLD)
    self._icon_textures: dict[str, rl.Texture] = {}
    self._last_params_refresh = 0.0
    self._last_mapbox_update = 0.0
    self._last_offline_update = 0.0
    self._released = False
    self._last_projection_update = 0.0
    # Memoizes _fit_text_size: the fit loop measures the same (font, text, width) tuples every
    # frame at 20Hz across ~a dozen text elements. The result only depends on those inputs, so
    # cache it and skip the descending measure loop entirely on repeats.
    self._fit_size_cache: dict[tuple, int] = {}
    # Split RenderTexture caches for the onroad panel (lazily created on the render thread, which
    # owns the GL context). The map layer (tiles/route/ego) pans, so it refreshes at
    # PANEL_RENDER_FPS; the chrome layer (badge + info text) only refreshes on a value change.
    self._map_rt: Any = None
    self._chrome_rt: Any = None
    self._last_map_render = 0.0
    self._last_chrome_render = 0.0
    self._chrome_key: Any = None

  @staticmethod
  def _enum_value(value) -> int:
    return int(getattr(value, "raw", value))

  def _release_providers(self) -> None:
    """Free tile textures once when the panel transitions to inactive.

    Latched so it runs on the offroad/maps-off transition rather than every idle
    frame. force_visible (offroad NAV screen) keeps its own panel active, so this
    only fires for the onroad panel when it stops drawing."""
    if self._released:
      return
    self._mapbox.release()
    self._offline.release()
    for attr in ("_map_rt", "_chrome_rt"):
      rt = getattr(self, attr)
      if rt is not None:
        rl.unload_render_texture(rt)
        setattr(self, attr, None)
    self._last_map_render = 0.0
    self._last_chrome_render = 0.0
    self._chrome_key = None
    self._released = True

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
      round(self._map_viewport_width, 0),
      round(self._map_viewport_height, 0),
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
      self._map_viewport_width,
      self._map_viewport_height,
    )
    self._projected_route_key = projection_key

    project_us = int((time.monotonic() - started) * 1_000_000)
    if project_us > 3_000:
      sample = PerfSample(texture_consume_us=project_us, texture_batch_size=len(route_points))
      _emit_nav_perf(
        "nav_map_projection_slow",
        total_time_us=project_us,
        batch_size=len(route_points),
        detail=f"project_us={project_us} points={len(route_points)} active={int(self.active)}",
        sample=sample,
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
    key = (id(font), text, round(max_width), max_size, min_size)
    cached = self._fit_size_cache.get(key)
    if cached is not None:
      return cached
    fitted = min_size
    for size in range(max_size, min_size - 1, -1):
      if measure_text_cached(font, text, size).x <= max_width:
        fitted = size
        break
    # Bound the cache: distances/ETA strings churn, but the working set per frame is tiny.
    if len(self._fit_size_cache) > 512:
      self._fit_size_cache.clear()
    self._fit_size_cache[key] = fitted
    return fitted

  @staticmethod
  def _lerp(start: float, end: float, alpha: float) -> float:
    return start + (end - start) * alpha

  @staticmethod
  def _lerp_angle(current: float, target: float, alpha: float) -> float:
    delta = ((target - current + 180.0) % 360.0) - 180.0
    return (current + delta * alpha) % 360.0

  def _refresh_position_from_fallback(self) -> bool:
    lat, lon, bearing, have_fix = current_or_last_gps_position()
    if not have_fix:
      return False

    self.current_latitude = lat
    self.current_longitude = lon
    self.bearing_deg = bearing
    self.zoom_hint = self.zoom_hint if self.zoom_hint > 0.0 else 16.0
    self.render_center_latitude, self.render_center_longitude, self.render_zoom = choose_nav_camera(
      self.current_latitude,
      self.current_longitude,
      self.bearing_deg,
      self._route_ahead_points(),
      self._map_viewport_width,
      self._map_viewport_height,
      self.zoom_hint,
    )
    if self.display_center_latitude == 0.0 and self.display_center_longitude == 0.0:
      self.display_center_latitude = self.render_center_latitude
      self.display_center_longitude = self.render_center_longitude
      self.display_zoom = self.render_zoom
    self._has_render_fix = True
    self.active = True
    return True

  def _refresh_params(self, now: float) -> None:
    if now - self._last_params_refresh < PARAMS_REFRESH_S:
      return
    try:
      self._maps_enabled = self._force_visible or self._params.get_bool("OnScreenNavigation")
    except UnknownKeyName:
      # If the param doesn't exist in this build, default to disabled unless explicitly embedded.
      self._maps_enabled = self._force_visible
    try:
      self._online_maps_enabled = self._params.get_bool("OnlineOSMaps")
      self._offline_maps_enabled = self._params.get_bool("OfflineOSMaps")
    except UnknownKeyName:
      # Builds whose compiled params predate the toggles keep the legacy behavior:
      # online primary with the offline fallback armed.
      self._online_maps_enabled = True
      self._offline_maps_enabled = True
    try:
      self._style_mode = int(self._params.get("OSMapsStyleMode") or 0)
    except (UnknownKeyName, ValueError):
      self._style_mode = 0
    try:
      self._heading_up = self._params.get_bool("OSMapsHeadingUp")
    except UnknownKeyName:
      self._heading_up = True
    self._last_params_refresh = now

  def _refresh_day_mode(self, now: float) -> None:
    if self._style_mode in (1, 2):
      self._day_mode = self._style_mode == 1
      return
    if now - self._last_daynight_check < 60.0:
      return
    self._last_daynight_check = now
    if abs(self.current_latitude) > 0.01 or abs(self.current_longitude) > 0.01:
      elevation = solar_elevation_deg(self.current_latitude, self.current_longitude, time.time())  # noqa: TID251
      if elevation > 0.0:
        self._day_mode = True
      elif elevation < -6.0:
        self._day_mode = False
      # between 0 and -6 deg (twilight): keep the current style, no flapping

  def update(self):
    now = time.monotonic()
    self._refresh_params(now)

    if not gui_app.big_ui() and not self._force_visible:
      self.active = False
      self._release_providers()
      return
    if not self._maps_enabled:
      self.active = False
      self._release_providers()
      return

    # We're onroad with maps enabled — tiles may load again, so re-arm the release latch.
    self._released = False

    sm = ui_state.sm
    render_updated = False
    if sm.updated["iqNavRenderState"]:
      render_updated = True
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
          self._map_viewport_width,
          self._map_viewport_height,
          self.zoom_hint,
        )
      self.destination_latitude = float(rs.destinationLatitude)
      self.destination_longitude = float(rs.destinationLongitude)
      if self.display_center_latitude == 0.0 and self.display_center_longitude == 0.0:
        self.display_center_latitude = self.render_center_latitude
        self.display_center_longitude = self.render_center_longitude
        self.display_zoom = self.render_zoom
      self.active = bool(rs.active) or self._has_render_fix or bool(self.route_points)

    if self._force_visible and (not render_updated or not self.active):
      self._refresh_position_from_fallback()

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

      self._refresh_day_mode(now)
      self._mapbox.set_day_mode(self._day_mode)
      self._offline.set_day_mode(self._day_mode)

      rotate = self._heading_up and self._has_render_fix
      self._mapbox.set_rotated(rotate)
      self._offline.set_rotated(rotate)
      target_bearing = self.bearing_deg if rotate else 0.0
      self.display_bearing = self._lerp_angle(self.display_bearing, target_bearing, 0.15)

      if self._online_maps_enabled:
        self._mapbox_mode_released = False
        if now - self._last_mapbox_update >= MAP_PROVIDER_UPDATE_S:
          self._mapbox.update(
            self.display_center_latitude,
            self.display_center_longitude,
            self.display_zoom,
            self._map_viewport_width,
            self._map_viewport_height,
          )
          self._last_mapbox_update = now
      elif not self._mapbox_mode_released:
        # Online maps toggled off: free the mapbox tile cache once. No update() means no fetch
        # threads and no network traffic while offline-only mode is selected.
        self._mapbox.release()
        self._mapbox_mode_released = True

      if self._offline_maps_enabled:
        if self._online_maps_enabled:
          # Both sources on: offline engages only while mapbox can't cover the screen.
          mapbox_status = self._mapbox.status()
          offline_engaged = mapbox_status in {"disabled", "token_missing", "error"} or not self._mapbox.has_content()
        else:
          offline_engaged = True
      else:
        offline_engaged = False

      if offline_engaged:
        if now - self._last_offline_update >= OFFLINE_PROVIDER_UPDATE_S:
          self._offline.update(
            self.display_center_latitude,
            self.display_center_longitude,
            self.display_zoom,
            self._map_viewport_width,
            self._map_viewport_height,
          )
          self._last_offline_update = now
        self._offline_idle_since = 0.0
      elif self._offline.has_content():
        if not self._offline_maps_enabled:
          # Offline maps toggled off mid-drive: free its tile cache immediately.
          self._offline.release()
          self._offline_idle_since = 0.0
        # Mapbox recovered: the offline fill-in cache (up to CACHE_LIMIT tiles of GPU
        # memory) would otherwise stay resident until the panel deactivates — one LTE
        # dropout per drive made it a permanent +tile-cache floor. It refills from the
        # on-disk cache in a few frames when needed, so free it after a healthy minute.
        elif self._offline_idle_since == 0.0:
          self._offline_idle_since = now
        elif now - self._offline_idle_since >= OFFLINE_RELEASE_AFTER_S:
          self._offline.release()
          self._offline_idle_since = 0.0

  def maps_enabled(self) -> bool:
    if self._force_visible:
      return True
    self._refresh_params(time.monotonic())
    return bool(self._maps_enabled)

  def warm_up_tiles(self, timeout_s: float = 30.0) -> bool:
    """Block until the online provider covers the current viewport. For offline rendering
    (tools/clip), where frames aren't wall-clock paced and async tile fetches would lag the
    output. Pumps update() with the provider throttle bypassed; needs the panel active (a nav
    fix already fed through sm) and a resolvable Mapbox token. Render thread only."""
    if not (self._maps_enabled and self.active and self._online_maps_enabled):
      return False
    if not resolve_mapbox_token(self._params):
      return False
    deadline = time.monotonic() + timeout_s
    while True:
      self._last_mapbox_update = 0.0
      self.update()
      if self._mapbox.viewport_complete():
        return True
      if time.monotonic() >= deadline:
        return False
      time.sleep(0.05)

  @staticmethod
  def _draw_card(rect: rl.Rectangle):
    shadow = rl.Rectangle(rect.x + 8, rect.y + 12, rect.width, rect.height)
    rl.draw_rectangle_rounded(shadow, CARD_RADIUS, 18, rl.Color(4, 8, 14, 110))
    rl.draw_rectangle_rounded(rect, CARD_RADIUS, 18, rl.Color(9, 18, 28, 246))
    rl.draw_rectangle_rounded_lines(rect, CARD_RADIUS, 18, rl.Color(255, 255, 255, 35))

  @staticmethod
  def _draw_fallback_background(rect: rl.Rectangle, draw_grid: bool = True):
    rl.draw_rectangle_rounded(rect, 0.04, 14, rl.Color(20, 27, 37, 255))
    # The decorative grid is only visible in the no-map placeholder state; once tiles are drawn
    # they paint over it opaquely, so the ~20 draw_line calls/frame are pure wasted overdraw.
    if not draw_grid:
      return
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
    rl.draw_circle_v(rl.Vector2(center_x, center_y + 8), 21.0, rl.Color(0, 0, 0, 120))
    heading = math.radians(bearing_deg)

    def rotate(px: float, py: float) -> rl.Vector2:
      rx = (px * math.cos(heading)) - (py * math.sin(heading))
      ry = (px * math.sin(heading)) + (py * math.cos(heading))
      return rl.Vector2(center_x + rx, center_y + ry)

    nose = rotate(0.0, -25.0)
    left = rotate(-16.0, 19.0)
    right = rotate(16.0, 19.0)
    rl.draw_triangle(nose, left, right, rl.Color(255, 255, 255, 245))

  def _draw_provider_badge(self, map_rect: rl.Rectangle):
    status = self._mapbox.status()
    offline_status = self._offline.status()
    base = self.road_name or "Navigation"
    if not self._online_maps_enabled and not self._offline_maps_enabled:
      label = "Map sources disabled"
    elif not self._online_maps_enabled:
      # Offline-only mode: local tiles are the primary (and only) source.
      if offline_status == "offline_ready" and self._offline.has_content():
        label = f"{base} (offline)"
      else:
        label = {
          "offline_missing": "Offline maps missing",
          "offline_invalid": "Offline maps invalid",
        }.get(offline_status, "Loading offline map")
    elif status == "offline_cache":
      label = f"{base} (Mapbox cached)"
    elif status == "ready" or self._mapbox.has_content():
      label = base
    elif self._offline_maps_enabled and offline_status == "offline_ready" and self._offline.has_content():
      label = f"{base} (offline)"
    else:
      label = {
        "disabled": "Mapbox disabled",
        "token_missing": "Mapbox token missing",
        "loading": "Loading live map",
        "error": "Mapbox unavailable",
        "offline_cache": "Mapbox cached",
      }.get(status, base)
      if self._offline_maps_enabled and status in {"token_missing", "error"}:
        if offline_status == "offline_missing":
          label = "Offline maps missing"
        elif offline_status == "offline_invalid":
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
    eta_epoch = time.time() + self.time_remaining + utc_offset_hours() * 3600
    eta_time = time.gmtime(eta_epoch)
    if ui_state.is_metric:
      return time.strftime("%H:%M", eta_time)
    return time.strftime("%-I:%M %p", eta_time).lower()

  def _draw_map_surface(self, map_rect: rl.Rectangle, draw_fade: bool = True) -> None:
    rl.begin_scissor_mode(int(map_rect.x), int(map_rect.y), int(map_rect.width), int(map_rect.height))
    # Skip the placeholder grid whenever a provider has tiles to paint over it.
    has_tiles = self._mapbox.has_content() or self._offline.has_content()
    self._draw_fallback_background(map_rect, draw_grid=not has_tiles)
    # heading-up: one modelview rotation about the map center covers tiles + route + pin
    rotation = self.display_bearing % 360.0
    rotated = min(rotation, 360.0 - rotation) > 0.2
    if rotated:
      rl.rl_push_matrix()
      rl.rl_translatef(map_rect.x + map_rect.width * 0.5, map_rect.y + map_rect.height * 0.5, 0.0)
      rl.rl_rotatef(-self.display_bearing, 0.0, 0.0, 1.0)
      rl.rl_translatef(-(map_rect.x + map_rect.width * 0.5), -(map_rect.y + map_rect.height * 0.5), 0.0)
    if self._online_maps_enabled:
      if self._offline_maps_enabled and self._offline.has_content():
        # Offline underlay fills any tiles mapbox is missing; it only holds content while
        # mapbox is degraded (released ~60s after recovery), so this is a no-op when healthy.
        self._offline.draw(map_rect, self.display_center_latitude, self.display_center_longitude, self.display_zoom)
      self._mapbox.draw(map_rect, self.display_center_latitude, self.display_center_longitude, self.display_zoom)
    elif self._offline_maps_enabled:
      self._offline.draw(map_rect, self.display_center_latitude, self.display_center_longitude, self.display_zoom)
    self._draw_route_overlay(map_rect)
    if rotated:
      rl.rl_pop_matrix()
    if draw_fade:
      fade = rl.Rectangle(map_rect.x, map_rect.y + map_rect.height - 128, map_rect.width, 128)
      rl.draw_rectangle_gradient_v(int(fade.x), int(fade.y), int(fade.width), int(fade.height), rl.Color(0, 0, 0, 0), rl.Color(4, 10, 16, 170))
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
        # counter-rotate about its own center so the flag stays upright in heading-up
        dst = rl.Rectangle(center.x, center.y, 18, 22)
        rl.draw_texture_pro(texture, src, dst, rl.Vector2(9, 11), self.display_bearing, rl.WHITE)

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
    texture = self._icon_texture()
    if texture is not None and display_next_valid:
      src = rl.Rectangle(0, 0, float(texture.width), float(texture.height))
      icon_side = min(tile.width, tile.height - 32)
      dst = rl.Rectangle(tile.x + (tile.width - icon_side) * 0.5, tile.y, icon_side, icon_side)
      rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)

    distance_text = f"{self.next_distance:.0f} m" if display_next_valid and self.next_distance > 0 else "--"
    distance_size = self._fit_text_size(self._micro_font, distance_text, tile.width - 22, 22, 16)
    dist_width = measure_text_cached(self._micro_font, distance_text, distance_size).x
    distance_color = rl.WHITE if display_next_valid else rl.Color(150, 163, 176, 200)
    rl.draw_text_ex(
      self._micro_font,
      distance_text,
      rl.Vector2(tile.x + (tile.width - dist_width) * 0.5, tile.y + tile.height - 30),
      distance_size,
      0,
      distance_color,
    )

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
    value_size = self._fit_text_size(self._body_font, value, rect.width - 16, 25, 17)
    label_size = self._fit_text_size(self._micro_font, label.upper(), rect.width - 16, 12, 9)
    value_width = measure_text_cached(self._body_font, value, value_size).x
    label_width = measure_text_cached(self._micro_font, label.upper(), label_size).x
    rl.draw_text_ex(
      self._body_font,
      value,
      rl.Vector2(rect.x + (rect.width - value_width) * 0.5, rect.y + 3),
      value_size,
      0,
      rl.WHITE,
    )
    rl.draw_text_ex(
      self._micro_font,
      label.upper(),
      rl.Vector2(rect.x + (rect.width - label_width) * 0.5, rect.y + 33),
      label_size,
      0,
      rl.Color(122, 205, 161, 255),
    )

  def _draw_panel_contents(self, panel_rect: rl.Rectangle) -> None:
    """Draw the full onroad panel into the given rect. Rect origin is (0,0) when rendering into
    the cache texture, or the real screen position on the direct-draw fallback."""
    self._draw_card(panel_rect)

    map_rect = rl.Rectangle(panel_rect.x + 12, panel_rect.y + 12, panel_rect.width - 24, MAP_HEIGHT)
    self._map_viewport_width = map_rect.width
    self._map_viewport_height = map_rect.height
    self._draw_map_surface(map_rect)

    self._draw_provider_badge(map_rect)
    self._draw_info_panel(panel_rect)

  def _ensure_rt(self, attr: str, width: int, height: int):
    rt = getattr(self, attr)
    if rt is None:
      try:
        rt = rl.load_render_texture(width, height)
        rl.set_texture_filter(rt.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        setattr(self, attr, rt)
      except Exception:
        setattr(self, attr, None)
        return None
    return rt

  def _chrome_content_key(self):
    # Every piece of state that _draw_provider_badge + _draw_info_panel turn into pixels.
    return (
      round(self.next_distance), self.next_direction, self.next_type, bool(self.next_valid),
      self.next_description, self.destination_name,
      round(self.time_remaining), round(self.distance_remaining),
      bool(self.nav_active), self.road_name, len(self.route_points),
      self._mapbox.status(), self._offline.status(),
      self._mapbox.has_content(), self._offline.has_content(),
      self._online_maps_enabled, self._offline_maps_enabled, self._day_mode,
      bool(ui_state.is_metric),
    )

  @staticmethod
  def _blit_rt(rt, x: float, y: float) -> None:
    # RenderTexture color buffers are stored bottom-up, so flip vertically via negative src height.
    tex = rt.texture
    src = rl.Rectangle(0, 0, float(tex.width), -float(tex.height))
    dst = rl.Rectangle(float(x), float(y), float(tex.width), float(tex.height))
    rl.draw_texture_pro(tex, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)

  def _render(self, rect: rl.Rectangle):
    if not self.active or not gui_app.big_ui():
      return

    panel_x = rect.x + rect.width - PANEL_WIDTH - PANEL_MARGIN_RIGHT
    panel_y = rect.y + PANEL_MARGIN_TOP
    map_w = float(PANEL_WIDTH - 24)
    map_h = float(MAP_HEIGHT)

    map_rt = self._ensure_rt("_map_rt", int(map_w), int(map_h))
    chrome_rt = self._ensure_rt("_chrome_rt", int(PANEL_WIDTH + PANEL_SHADOW_PAD), int(PANEL_HEIGHT + PANEL_SHADOW_PAD))
    if map_rt is None or chrome_rt is None:
      # RenderTexture unavailable — fall back to direct per-frame draw (previous behavior).
      self._draw_panel_contents(rl.Rectangle(panel_x, panel_y, PANEL_WIDTH, PANEL_HEIGHT))
      return

    now = time.monotonic()
    self._map_viewport_width = map_w
    self._map_viewport_height = map_h

    # LIVE map layer: tiles/route/ego pan continuously -> refresh at PANEL_RENDER_FPS.
    if now - self._last_map_render >= PANEL_RENDER_INTERVAL:
      self._last_map_render = now
      rl.begin_texture_mode(map_rt)
      rl.clear_background(rl.Color(0, 0, 0, 0))
      self._draw_map_surface(rl.Rectangle(0.0, 0.0, map_w, map_h))
      rl.end_texture_mode()

    # CHROME layer: badge + info text only change on value updates. Regenerate on a content-key
    # change, with a safety cap so a missed key field can't freeze the readout.
    key = self._chrome_content_key()
    if key != self._chrome_key or now - self._last_chrome_render >= CHROME_MAX_INTERVAL:
      self._chrome_key = key
      self._last_chrome_render = now
      rl.begin_texture_mode(chrome_rt)
      rl.clear_background(rl.Color(0, 0, 0, 0))
      self._draw_provider_badge(rl.Rectangle(12.0, 12.0, map_w, map_h))
      self._draw_info_panel(rl.Rectangle(0.0, 0.0, PANEL_WIDTH, PANEL_HEIGHT))
      rl.end_texture_mode()

    # Composite: static card backdrop -> live map -> chrome text overlay.
    self._draw_card(rl.Rectangle(panel_x, panel_y, PANEL_WIDTH, PANEL_HEIGHT))
    self._blit_rt(map_rt, panel_x + 12, panel_y + 12)
    self._blit_rt(chrome_rt, panel_x, panel_y)

  def render_split_direct(self, rect: rl.Rectangle) -> None:
    local_rect = rl.Rectangle(rect.x, rect.y, rect.width, rect.height)
    map_rect = rl.Rectangle(rect.x + 8, rect.y + 8, rect.width - 16, rect.height - 16)
    self._map_viewport_width = map_rect.width
    self._map_viewport_height = map_rect.height
    self._draw_panel_shell(local_rect)
    self._draw_map_surface(map_rect, draw_fade=False)
    self._draw_provider_badge(map_rect)
    self._draw_split_header(local_rect)
    self._draw_split_footer(local_rect)

  def render_split(self, rect: rl.Rectangle) -> None:
    self.render_split_direct(rect)
