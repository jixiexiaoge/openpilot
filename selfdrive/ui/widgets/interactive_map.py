"""Touch-interactive tile map for the offroad Navigate screen.

Drag to pan, +/- to zoom, recenter snaps back to GPS. Tiles come from the onroad
MapboxTileProvider (async fetch, disk+GPU cache). Tiles are drawn directly every frame (~20
texture blits); the fetch/prune pipeline is throttled so panning doesn't churn the cache.
"""
from __future__ import annotations

import math
import time

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position
from openpilot.iqpilot.ui.onroad.nav_map_panel import MapboxTileProvider
from openpilot.iqpilot.ui.onroad.nav_map_utils import TILE_SIZE
from openpilot.system.ui.lib.application import gui_app, FontWeight, MouseEvent, MousePos
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

DEFAULT_ZOOM = 15.0
MIN_ZOOM = 4.0
MAX_ZOOM = 18.0
ZOOM_STEP = 1.0
TILE_UPDATE_S = 0.20          # fetch/prune cadence; drawing runs every frame
GPS_POLL_S = 0.5
DEST_POLL_S = 1.0
BTN = 92
PUCK_BLUE = rl.Color(23, 134, 246, 255)
MAP_BG = rl.Color(18, 18, 20, 255)
BTN_BG = rl.Color(28, 30, 36, 235)
BTN_BORDER = rl.Color(255, 255, 255, 45)


def _norm(lat: float, lon: float) -> tuple[float, float]:
  lat = max(-85.05, min(85.05, lat))
  x = (lon + 180.0) / 360.0
  s = math.sin(math.radians(lat))
  y = 0.5 - math.log((1.0 + s) / (1.0 - s)) / (4.0 * math.pi)
  return x, y


def _denorm(x: float, y: float) -> tuple[float, float]:
  lon = x * 360.0 - 180.0
  lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))
  return lat, lon


class InteractiveNavMap(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._tiles = MapboxTileProvider()
    self._lat = 0.0
    self._lon = 0.0
    self._zoom = DEFAULT_ZOOM
    self._follow = True
    self._have_center = False

    self._drag_start: MousePos | None = None
    self._drag_center: tuple[float, float] | None = None
    self._dragging = False

    self._tiles_time = 0.0
    self._gps_cache: tuple[float, float, bool] = (0.0, 0.0, False)
    self._gps_time = 0.0
    self._dest_cache = None
    self._dest_time = 0.0

    self._pin_icon = gui_app.texture("icons/iq/pin.png", 64, 64, keep_aspect_ratio=True)

  def _world_size(self) -> float:
    return TILE_SIZE * (2.0 ** self._zoom)

  def _poll_gps(self):
    now = time.monotonic()
    if now - self._gps_time > GPS_POLL_S:
      lat, lon, _, fix = current_or_last_gps_position(self._params)
      self._gps_cache = (lat, lon, fix)
      self._gps_time = now
    lat, lon, fix = self._gps_cache
    if fix and self._follow and not self._dragging:
      self._lat, self._lon = lat, lon
      self._have_center = True
    elif fix and not self._have_center:
      self._lat, self._lon = lat, lon
      self._have_center = True
    return lat, lon, fix

  def recenter(self):
    self._follow = True
    self._gps_time = 0.0

  # --- gestures ---------------------------------------------------------------
  def _handle_mouse_event(self, mouse_event: MouseEvent) -> None:
    super()._handle_mouse_event(mouse_event)
    if mouse_event.slot != 0 or not self._have_center:
      return
    if mouse_event.left_pressed:
      if rl.check_collision_point_rec(mouse_event.pos, self._rect) and self._control_hit(mouse_event.pos) is None:
        self._drag_start = mouse_event.pos
        self._drag_center = _norm(self._lat, self._lon)
        self._dragging = False
      else:
        self._drag_start = None
    elif mouse_event.left_down and self._drag_start is not None:
      dx = mouse_event.pos.x - self._drag_start.x
      dy = mouse_event.pos.y - self._drag_start.y
      if not self._dragging and (abs(dx) > 10 or abs(dy) > 10):
        self._dragging = True
        self._follow = False
      if self._dragging:
        ws = self._world_size()
        nx = (self._drag_center[0] - dx / ws) % 1.0
        ny = max(0.001, min(0.999, self._drag_center[1] - dy / ws))
        self._lat, self._lon = _denorm(nx, ny)
    elif mouse_event.left_released:
      self._drag_start = None
      self._drag_center = None
      self._dragging = False

  def _controls(self) -> list[tuple[str, rl.Rectangle]]:
    r = self._rect
    x = r.x + r.width - BTN - 20
    ctrls = [("+", rl.Rectangle(x, r.y + 20, BTN, BTN)),
             ("-", rl.Rectangle(x, r.y + 20 + BTN + 14, BTN, BTN))]
    if not self._follow:
      ctrls.append(("recenter", rl.Rectangle(x, r.y + r.height - BTN - 20, BTN, BTN)))
    return ctrls

  def _control_hit(self, pos: MousePos) -> str | None:
    for name, rect in self._controls():
      if rl.check_collision_point_rec(pos, rect):
        return name
    return None

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    hit = self._control_hit(mouse_pos)
    if hit == "+":
      self._zoom = min(MAX_ZOOM, self._zoom + ZOOM_STEP)
      self._tiles_time = 0.0
    elif hit == "-":
      self._zoom = max(MIN_ZOOM, self._zoom - ZOOM_STEP)
      self._tiles_time = 0.0
    elif hit == "recenter":
      self.recenter()

  # --- rendering --------------------------------------------------------------
  def _render(self, rect: rl.Rectangle):
    gps_lat, gps_lon, fix = self._poll_gps()

    if not self._have_center:
      rl.draw_rectangle_rounded(rect, 0.03, 20, MAP_BG)
      self._center_note(rect, "Waiting for GPS fix...")
      return

    now = time.monotonic()
    if now - self._tiles_time > TILE_UPDATE_S:
      self._tiles.update(self._lat, self._lon, self._zoom, rect.width, rect.height)
      self._tiles_time = now

    rl.draw_rectangle_rec(rect, MAP_BG)
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    self._tiles.draw(rect, self._lat, self._lon, self._zoom)
    if fix:
      self._draw_puck(rect, gps_lat, gps_lon)
    self._draw_destination(rect)
    rl.end_scissor_mode()
    rl.draw_rectangle_rounded_lines_ex(rect, 0.03, 20, 2, rl.Color(255, 255, 255, 38))
    self._draw_controls()

  def _center_note(self, rect: rl.Rectangle, text: str):
    font = gui_app.font(FontWeight.MEDIUM)
    ns = measure_text_cached(font, text, 40)
    rl.draw_text_ex(font, text, rl.Vector2(int(rect.x + (rect.width - ns.x) / 2),
                    int(rect.y + rect.height / 2 - ns.y / 2)), 40, 0, rl.Color(165, 165, 170, 255))

  def _project(self, rect: rl.Rectangle, lat: float, lon: float) -> tuple[float, float]:
    ws = self._world_size()
    cx, cy = _norm(self._lat, self._lon)
    px, py = _norm(lat, lon)
    return (rect.x + rect.width / 2 + (px - cx) * ws,
            rect.y + rect.height / 2 + (py - cy) * ws)

  def _draw_puck(self, rect: rl.Rectangle, lat: float, lon: float):
    x, y = self._project(rect, lat, lon)
    if rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height:
      rl.draw_circle(int(x), int(y), 24, rl.Color(255, 255, 255, 235))
      rl.draw_circle(int(x), int(y), 16, PUCK_BLUE)

  def _draw_destination(self, rect: rl.Rectangle):
    now = time.monotonic()
    if now - self._dest_time > DEST_POLL_S:
      try:
        self._dest_cache = self._params.get("NavigationDestination")
      except Exception:
        self._dest_cache = None
      self._dest_time = now
    dest = self._dest_cache
    if not dest:
      return
    try:
      lat, lon = float(dest["latitude"]), float(dest["longitude"])
    except Exception:
      return
    x, y = self._project(rect, lat, lon)
    if rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height:
      rl.draw_texture(self._pin_icon, int(x - self._pin_icon.width / 2), int(y - self._pin_icon.height), rl.WHITE)

  def _draw_controls(self):
    font = gui_app.font(FontWeight.MEDIUM)
    for name, r in self._controls():
      rl.draw_rectangle_rounded(r, 0.35, 16, BTN_BG)
      rl.draw_rectangle_rounded_lines_ex(r, 0.35, 16, 2, BTN_BORDER)
      cx, cy = r.x + r.width / 2, r.y + r.height / 2
      if name == "recenter":
        rl.draw_circle_lines(int(cx), int(cy), 20, rl.WHITE)
        rl.draw_circle(int(cx), int(cy), 6, PUCK_BLUE)
        for ang in (0, 90, 180, 270):
          a = math.radians(ang)
          rl.draw_line_ex(rl.Vector2(cx + 20 * math.cos(a), cy + 20 * math.sin(a)),
                          rl.Vector2(cx + 30 * math.cos(a), cy + 30 * math.sin(a)), 3, rl.WHITE)
      else:
        ts = measure_text_cached(font, name, 56)
        rl.draw_text_ex(font, name, rl.Vector2(int(cx - ts.x / 2), int(cy - ts.y / 2)), 56, 0, rl.WHITE)

  def release(self):
    self._tiles.release()
