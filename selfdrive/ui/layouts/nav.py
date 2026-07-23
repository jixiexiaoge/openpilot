import threading
import time
import pyray as rl
from collections.abc import Callable

import requests

from openpilot.common.params import Params
from openpilot.selfdrive.ui.lib.nav_helpers import (has_mapbox_token, resolve_mapbox_token,
                                                    current_or_last_gps_position)
from openpilot.iqpilot.ui.onroad.nav_map_panel import NavMapPanel
from openpilot.iqpilot.ui.onroad.nav_map_utils import build_mapbox_static_url
from openpilot.selfdrive.ui.widgets.screen_header import ScreenHeader, HEADER_HEIGHT
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, GL_VERSION
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.selfdrive.ui.lib import nav_search
from openpilot.selfdrive.ui.lib.nav_search import NavSearch, SearchResult
from openpilot.selfdrive.ui.widgets.interactive_map import InteractiveNavMap

MARGIN = 40
SPACING = 25
SEARCH_HEIGHT = 120
PILL_HEIGHT = 120
MAP_ZOOM = 15.0
MAP_RETRY_INTERVAL = 5.0

PANEL_BG = rl.Color(38, 40, 46, 255)
PANEL_BORDER = rl.Color(255, 255, 255, 38)
MUTED = rl.Color(165, 165, 170, 255)

ROUNDED_TEXTURE_VERTEX_SHADER = GL_VERSION + """
in vec3 vertexPosition;
in vec2 vertexTexCoord;
uniform mat4 mvp;
out vec2 fragTexCoord;

void main() {
  fragTexCoord = vertexTexCoord;
  gl_Position = mvp * vec4(vertexPosition, 1.0);
}
"""

ROUNDED_TEXTURE_FRAGMENT_SHADER = GL_VERSION + """
in vec2 fragTexCoord;
uniform sampler2D texture0;
uniform vec4 clipRect;
uniform float cornerRadius;
uniform float viewportHeight;
out vec4 fragColor;

float roundedRectDistance(vec2 p, vec2 center, vec2 halfSize, float radius) {
  vec2 d = abs(p - center) - (halfSize - vec2(radius));
  return length(max(d, vec2(0.0))) + min(max(d.x, d.y), 0.0) - radius;
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, viewportHeight - gl_FragCoord.y);
  vec2 center = clipRect.xy + clipRect.zw * 0.5;
  vec2 halfSize = clipRect.zw * 0.5;
  float radius = min(cornerRadius, min(halfSize.x, halfSize.y));
  float dist = roundedRectDistance(p, center, halfSize, radius);
  float alpha = 1.0 - smoothstep(0.0, 1.25, dist);
  vec4 sampled = texture(texture0, fragTexCoord);
  fragColor = vec4(sampled.rgb, sampled.a * alpha);
}
"""


class _MapPreview:
  """Fetches a Mapbox static map (background thread) and caches it as a texture."""

  def __init__(self):
    self._params = Params()
    self._session = requests.Session()
    self._texture: rl.Texture | None = None
    self._pending: tuple[tuple, bytes] | None = None
    self._fetching = False
    self._key: tuple | None = None
    self._status = "idle"
    self._last_attempt = 0.0
    self._rounded_shader = None
    self._rounded_shader_locs: dict[str, int] = {}
    self._clip_rect = rl.ffi.new("float[]", [0.0, 0.0, 0.0, 0.0])
    self._corner_radius = rl.ffi.new("float[]", [0.0])
    self._viewport_height = rl.ffi.new("float[]", [0.0])

  def has_token(self) -> bool:
    return has_mapbox_token(self._params)

  def _fetch(self, url: str, token: str, key: tuple):
    try:
      r = self._session.get(url, params={"access_token": token}, timeout=4.0)
      if r.status_code == 200 and r.content:
        self._pending = (key, r.content)
        self._status = "ready"
      else:
        self._key = None
        self._status = "error"
    except requests.RequestException:
      self._key = None
      self._status = "error"
    finally:
      self._fetching = False

  def request(self, lat: float, lon: float, bearing: float, w: float, h: float):
    token = resolve_mapbox_token(self._params)
    if not token or w < 20 or h < 20:
      self._status = "token_missing" if not token else "idle"
      return
    key = (round(lat, 4), round(lon, 4))
    if self._fetching or key == self._key:
      return
    now = time.monotonic()
    if self._status == "error" and now - self._last_attempt < MAP_RETRY_INTERVAL:
      return
    self._last_attempt = now
    self._key = key
    self._fetching = True
    self._status = "loading"
    scale = min(1.0, 1000.0 / max(w, h))
    url = build_mapbox_static_url(lat, lon, MAP_ZOOM, bearing, max(1, int(w * scale)), max(1, int(h * scale)))
    threading.Thread(target=self._fetch, args=(url, token, key), daemon=True).start()

  def _consume(self):
    if self._pending is None:
      return
    _key, data = self._pending
    self._pending = None
    try:
      ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
      img = rl.load_image_from_memory(ext, data, len(data))
      tex = rl.load_texture_from_image(img)
      rl.unload_image(img)
      rl.set_texture_filter(tex, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      if self._texture is not None:
        rl.unload_texture(self._texture)
      self._texture = tex
    except Exception:
      pass

  def _ensure_rounded_shader(self):
    if self._rounded_shader is not None:
      return
    self._rounded_shader = rl.load_shader_from_memory(ROUNDED_TEXTURE_VERTEX_SHADER, ROUNDED_TEXTURE_FRAGMENT_SHADER)
    self._rounded_shader_locs = {
      "clipRect": rl.get_shader_location(self._rounded_shader, "clipRect"),
      "cornerRadius": rl.get_shader_location(self._rounded_shader, "cornerRadius"),
      "viewportHeight": rl.get_shader_location(self._rounded_shader, "viewportHeight"),
    }

  def _draw_texture(self, src: rl.Rectangle, rect: rl.Rectangle, roundness: float):
    if roundness <= 0:
      rl.draw_texture_pro(self._texture, src, rect, rl.Vector2(0, 0), 0, rl.WHITE)
      return

    self._ensure_rounded_shader()
    self._clip_rect[0:4] = [rect.x, rect.y, rect.width, rect.height]
    self._corner_radius[0] = max(0.0, min(rect.width, rect.height) * roundness * 0.5)
    self._viewport_height[0] = gui_app.height
    rl.set_shader_value(
      self._rounded_shader,
      self._rounded_shader_locs["clipRect"],
      self._clip_rect,
      rl.ShaderUniformDataType.SHADER_UNIFORM_VEC4,
    )
    rl.set_shader_value(
      self._rounded_shader,
      self._rounded_shader_locs["cornerRadius"],
      self._corner_radius,
      rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT,
    )
    rl.set_shader_value(
      self._rounded_shader,
      self._rounded_shader_locs["viewportHeight"],
      self._viewport_height,
      rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT,
    )

    rl.begin_shader_mode(self._rounded_shader)
    rl.draw_texture_pro(self._texture, src, rect, rl.Vector2(0, 0), 0, rl.WHITE)
    rl.end_shader_mode()

  def draw(self, rect: rl.Rectangle, roundness: float = 0.0) -> bool:
    self._consume()
    if self._texture is None or self._texture.id == 0:
      return False
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    src = rl.Rectangle(0, 0, self._texture.width, self._texture.height)
    self._draw_texture(src, rect, roundness)
    rl.end_scissor_mode()
    return True

  def status(self) -> str:
    if self._fetching:
      return "loading"
    return self._status


class _Pill(Widget):
  """A rounded destination shortcut: icon + label (Home / Work / Recent)."""

  BG = rl.Color(38, 40, 46, 255)
  BG_PRESSED = rl.Color(54, 57, 65, 255)

  def __init__(self, icon_path: str, label: str, on_click: Callable[[], None] | None = None):
    super().__init__()
    self._label = label
    self._icon = gui_app.texture(icon_path, 56, 56, keep_aspect_ratio=True)
    if on_click is not None:
      self.set_click_callback(on_click)

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.5, 20, self.BG_PRESSED if self.is_pressed else self.BG)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.5, 20, 2, PANEL_BORDER)
    cy = rect.y + rect.height / 2
    x = rect.x + 32
    rl.draw_texture(self._icon, int(x), int(cy - self._icon.height / 2), rl.WHITE)
    x += self._icon.width + 20
    font = gui_app.font(FontWeight.MEDIUM)
    ts = measure_text_cached(font, self._label, 40)
    rl.draw_text_ex(font, self._label, rl.Vector2(int(x), int(cy - ts.y / 2)), 40, 0, rl.WHITE)


ROW_HEIGHT = 116
ROW_GAP = 16
RESULT_NAME = rl.Color(240, 240, 244, 255)
SEARCH_DEBOUNCE = 0.25


class NavLayout(Widget):
  """Offroad Navigate screen: destination search with live Mapbox autocomplete, Home/Work/Recent
  shortcuts, and a location map preview. Picking a place writes NavigationDestination (navd routes)."""

  def __init__(self):
    super().__init__()
    self._header = self._child(ScreenHeader(tr("Navigation")))
    self._search_icon = gui_app.texture("icons/iq/search.png", 52, 52, keep_aspect_ratio=True)
    self._pin_icon = gui_app.texture("icons/iq/pin.png", 90, 90, keep_aspect_ratio=True)
    self._home_icon = gui_app.texture("icons/iq/home.png", 52, 52, keep_aspect_ratio=True)
    self._work_icon = gui_app.texture("icons/iq/work.png", 52, 52, keep_aspect_ratio=True)
    self._recent_icon = gui_app.texture("icons/iq/recent.png", 52, 52, keep_aspect_ratio=True)

    self._keyboard = Keyboard(max_text_size=128, min_text_size=0)
    self._map = _MapPreview()
    self._imap = self._child(InteractiveNavMap())
    self._search = NavSearch()

    self._on_back_cb: Callable[[], None] | None = None
    self._mode = "browse"          # "browse" | "results"
    self._purpose = "navigate"     # "navigate" | "set_home" | "set_work"
    self._query = ""
    self._selecting = False
    self._status_ts = 0.0
    self._pending_exit = False
    self._status_msg = ""

    self._home: SearchResult | None = None
    self._work: SearchResult | None = None
    self._recents: list[SearchResult] = []

    self._tap_targets: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self._reload_favorites()

  def _reload_favorites(self):
    self._home = nav_search.get_home()
    self._work = nav_search.get_work()
    self._recents = nav_search.get_recents()

  def set_on_back(self, cb: Callable[[], None]) -> None:
    self._on_back_cb = cb
    self._header.set_on_back(self._handle_back)

  def show_event(self):
    super().show_event()
    self._mode = "browse"
    self._status_msg = ""
    self._reload_favorites()

  def hide_event(self):
    super().hide_event()
    # Free the tile cache's GPU memory while the screen is away.
    self._imap.release()

  def _handle_back(self):
    if self._mode == "results":
      self._exit_search()
    elif self._on_back_cb is not None:
      self._on_back_cb()

  # --- search lifecycle -------------------------------------------------------
  def _open_search(self, purpose: str = "navigate"):
    # Full-screen modal keyboard (same as before) — search runs when you hit Done.
    self._purpose = purpose
    self._search.new_session()
    self._keyboard.reset(min_text_size=1)
    title = {"set_home": tr("Set Home"), "set_work": tr("Set Work")}.get(purpose, tr("Search"))
    self._keyboard.set_title(title, tr("Enter an address or place"))
    self._keyboard.set_text(self._query if purpose == "navigate" else "")
    gui_app.set_modal_overlay(self._keyboard, callback=self._on_search_done)

  def _on_search_done(self, result: int):
    if result != 1:
      return
    self._query = self._keyboard.text.strip()
    if not self._query:
      return
    self._search.search(self._query)
    self._mode = "results"
    self._status_msg = ""
    self._selecting = False

  def _exit_search(self):
    self._mode = "browse"
    self._selecting = False
    self._status_msg = ""
    self._reload_favorites()

  # --- selection (threaded: retrieve coords, then persist) --------------------
  def _select_result(self, r: SearchResult):
    if self._selecting:
      return
    self._selecting = True
    self._status_msg = tr("Locating...")
    threading.Thread(target=self._finish_select, args=(r, self._purpose), daemon=True).start()

  def _finish_select(self, r: SearchResult, purpose: str):
    full = self._search.retrieve(r)
    if full is None or not full.has_coords:
      self._status_msg = tr("Couldn't locate that place")
      self._selecting = False
      return
    if purpose == "set_home":
      nav_search.save_home(full)
    elif purpose == "set_work":
      nav_search.save_work(full)
    else:
      nav_search.set_destination(full.lat, full.lon, full.name)
      nav_search.add_recent(full)
    self._selecting = False
    self._pending_exit = True

  def _navigate_place(self, place: SearchResult):
    if place is not None and place.has_coords:
      nav_search.set_destination(place.lat, place.lon, place.name)
      nav_search.add_recent(place)
      self._reload_favorites()
      self._dest_check_time = 0.0
      self._set_status(tr("Destination set"))

  def _set_status(self, msg: str):
    self._status_msg = msg
    self._status_ts = time.monotonic()

  def _cancel_nav(self):
    nav_search.cancel_navigation()
    self._dest_check_time = 0.0
    self._set_status(tr("Navigation canceled"))

  def _remove_home(self):
    nav_search.remove_home()
    self._reload_favorites()

  def _remove_work(self):
    nav_search.remove_work()
    self._reload_favorites()

  def _remove_recent(self, r: SearchResult):
    nav_search.remove_recent(r)
    self._reload_favorites()

  def _on_home(self):
    self._navigate_place(self._home) if self._home is not None else self._open_search("set_home")

  def _on_work(self):
    self._navigate_place(self._work) if self._work is not None else self._open_search("set_work")

  # --- render -----------------------------------------------------------------
  def _render(self, rect: rl.Rectangle):
    self._tap_targets = []
    if self._pending_exit:
      self._pending_exit = False
      self._exit_search()
    header_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, HEADER_HEIGHT)
    self._header.render(header_rect)
    body = rl.Rectangle(rect.x + MARGIN, header_rect.y + HEADER_HEIGHT + SPACING,
                        rect.width - 2 * MARGIN, rect.y + rect.height - (header_rect.y + HEADER_HEIGHT + SPACING) - MARGIN)
    if self._mode == "results":
      self._render_results(body)
    else:
      self._render_browse(body)

  def _row(self, rect: rl.Rectangle, icon, title: str, subtitle: str, on_tap, on_delete=None, pressed_hint=True):
    hit = rl.check_collision_point_rec(rl.get_mouse_position(), rect)
    bg = rl.Color(54, 57, 65, 255) if (hit and pressed_hint and rl.is_mouse_button_down(0)) else PANEL_BG
    rl.draw_rectangle_rounded(rect, 0.35, 20, bg)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.35, 20, 2, PANEL_BORDER)
    x = rect.x + 32
    if icon is not None:
      rl.draw_texture(icon, int(x), int(rect.y + rect.height / 2 - icon.height / 2), rl.WHITE)
      x += icon.width + 24
    text_w = rect.width - (x - rect.x) - (110 if on_delete is not None else 32)
    font = gui_app.font(FontWeight.MEDIUM)
    if subtitle:
      rl.draw_text_ex(font, title, rl.Vector2(int(x), int(rect.y + 22)), 40, 0, RESULT_NAME)
      sub = self._ellipsize(font, subtitle, 30, text_w)
      rl.draw_text_ex(font, sub, rl.Vector2(int(x), int(rect.y + 66)), 30, 0, MUTED)
    else:
      ts = measure_text_cached(font, title, 42)
      rl.draw_text_ex(font, title, rl.Vector2(int(x), int(rect.y + rect.height / 2 - ts.y / 2)), 42, 0, RESULT_NAME)
    # Delete (×) button — appended first so a tap on it wins over the row's navigate tap.
    if on_delete is not None:
      cx, cy = rect.x + rect.width - 60, rect.y + rect.height / 2
      del_r = rl.Rectangle(cx - 34, cy - 34, 68, 68)
      dhit = rl.check_collision_point_rec(rl.get_mouse_position(), del_r)
      rl.draw_circle(int(cx), int(cy), 30, rl.Color(90, 62, 66, 255) if dhit else rl.Color(60, 62, 70, 255))
      rl.draw_line_ex(rl.Vector2(cx - 13, cy - 13), rl.Vector2(cx + 13, cy + 13), 4, rl.Color(230, 120, 120, 255))
      rl.draw_line_ex(rl.Vector2(cx - 13, cy + 13), rl.Vector2(cx + 13, cy - 13), 4, rl.Color(230, 120, 120, 255))
      self._tap_targets.append((del_r, on_delete))
    if on_tap is not None:
      self._tap_targets.append((rect, on_tap))

  @staticmethod
  def _ellipsize(font, text: str, size: int, max_w: float) -> str:
    if measure_text_cached(font, text, size).x <= max_w:
      return text
    while text and measure_text_cached(font, text + "…", size).x > max_w:
      text = text[:-1]
    return text + "…"

  def _render_browse(self, rect: rl.Rectangle):
    font = gui_app.font(FontWeight.MEDIUM)
    x, w = rect.x, rect.width
    y = rect.y
    # Search bar
    bar = rl.Rectangle(x, y, w, SEARCH_HEIGHT)
    rl.draw_rectangle_rounded(bar, 0.4, 20, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(bar, 0.4, 20, 2, PANEL_BORDER)
    cy = bar.y + bar.height / 2
    rl.draw_texture(self._search_icon, int(bar.x + 36), int(cy - self._search_icon.height / 2), MUTED)
    ph = tr("Search address or place")
    rl.draw_text_ex(font, ph, rl.Vector2(int(bar.x + 36 + self._search_icon.width + 24),
                    int(cy - 22)), 44, 0, MUTED)
    self._tap_targets.append((bar, lambda: self._open_search("navigate")))
    y += SEARCH_HEIGHT + SPACING

    # Cancel active route (param read throttled)
    now = time.monotonic()
    if now - getattr(self, "_dest_check_time", 0.0) > 1.0:
      self._has_dest = nav_search.has_active_destination()
      self._dest_check_time = now
    if getattr(self, "_has_dest", False):
      cr = rl.Rectangle(x, y, w, ROW_HEIGHT)
      chit = rl.check_collision_point_rec(rl.get_mouse_position(), cr)
      rl.draw_rectangle_rounded(cr, 0.35, 20, rl.Color(96, 46, 48, 255) if chit else rl.Color(74, 40, 42, 255))
      rl.draw_rectangle_rounded_lines_ex(cr, 0.35, 20, 2, rl.Color(210, 90, 90, 120))
      label = tr("Cancel navigation")
      ls = measure_text_cached(font, label, 42)
      rl.draw_text_ex(font, label, rl.Vector2(int(x + 32), int(cr.y + cr.height / 2 - ls.y / 2)), 42, 0,
                      rl.Color(240, 180, 180, 255))
      self._tap_targets.append((cr, self._cancel_nav))
      y += ROW_HEIGHT + SPACING

    # Home / Work
    hw_gap = ROW_GAP
    hw_w = (w - hw_gap) / 2
    self._row(rl.Rectangle(x, y, hw_w, ROW_HEIGHT), self._home_icon, tr("Home"),
              self._home.address if self._home else tr("Set home address"), self._on_home,
              on_delete=(self._remove_home if self._home else None))
    self._row(rl.Rectangle(x + hw_w + hw_gap, y, hw_w, ROW_HEIGHT), self._work_icon, tr("Work"),
              self._work.address if self._work else tr("Set work address"), self._on_work,
              on_delete=(self._remove_work if self._work else None))
    y += ROW_HEIGHT + SPACING

    # Recents (fit as many as room allows, leaving space for the map)
    map_min = 300
    for r in self._recents:
      if y + ROW_HEIGHT > rect.y + rect.height - map_min - SPACING:
        break
      self._row(rl.Rectangle(x, y, w, ROW_HEIGHT), self._recent_icon, r.name, r.address,
                (lambda r=r: self._navigate_place(r)), on_delete=(lambda r=r: self._remove_recent(r)))
      y += ROW_HEIGHT + ROW_GAP

    # Map preview of current location
    map_rect = rl.Rectangle(x, y, w, rect.y + rect.height - y)
    if map_rect.height > 120:
      self._imap.render(map_rect)
    if self._status_msg and time.monotonic() - self._status_ts < 2.5:
      self._draw_toast(map_rect, self._status_msg)

  def _draw_toast(self, area: rl.Rectangle, text: str):
    font = gui_app.font(FontWeight.MEDIUM)
    ts = measure_text_cached(font, text, 36)
    pad = 32
    pw = ts.x + pad * 2
    pill = rl.Rectangle(area.x + (area.width - pw) / 2, area.y + 24, pw, 66)
    rl.draw_rectangle_rounded(pill, 0.5, 20, rl.Color(20, 22, 26, 235))
    rl.draw_rectangle_rounded_lines_ex(pill, 0.5, 20, 2, PANEL_BORDER)
    rl.draw_text_ex(font, text, rl.Vector2(int(pill.x + pad), int(pill.y + 33 - ts.y / 2)), 36, 0, rl.WHITE)

  def _render_map(self, rect: rl.Rectangle):
    lat, lon, bearing, fix = current_or_last_gps_position()
    if fix and self._map.has_token:
      self._map.request(lat, lon, 0.0, rect.width, rect.height)
      if self._map.draw(rect, roundness=0.03):
        # The static map is centered on the fix, so the current location is the panel center.
        cx, cy = int(rect.x + rect.width / 2), int(rect.y + rect.height / 2)
        rl.draw_circle(cx, cy, 26, rl.Color(255, 255, 255, 235))
        rl.draw_circle(cx, cy, 18, rl.Color(23, 134, 246, 255))   # blue location dot
        return
    rl.draw_rectangle_rounded(rect, 0.03, 20, rl.Color(18, 18, 20, 255))
    rl.draw_rectangle_rounded_lines_ex(rect, 0.03, 20, 2, PANEL_BORDER)
    pin_x = int(rect.x + (rect.width - self._pin_icon.width) / 2)
    rl.draw_texture(self._pin_icon, pin_x, int(rect.y + rect.height / 2 - self._pin_icon.height), MUTED)
    self._draw_center_note(rect, tr("Waiting for GPS fix..."), dy=16)

  def _draw_center_note(self, rect: rl.Rectangle, text: str, dy: float = 0):
    font = gui_app.font(FontWeight.MEDIUM)
    ns = measure_text_cached(font, text, 40)
    rl.draw_text_ex(font, text, rl.Vector2(int(rect.x + (rect.width - ns.x) / 2),
                    int(rect.y + rect.height / 2 + dy)), 40, 0, MUTED)

  def _render_results(self, rect: rl.Rectangle):
    font = gui_app.font(FontWeight.MEDIUM)
    x, w = rect.x, rect.width
    y = rect.y
    # Query bar — tap to reopen the keyboard and refine the search.
    bar = rl.Rectangle(x, y, w, SEARCH_HEIGHT)
    rl.draw_rectangle_rounded(bar, 0.4, 20, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(bar, 0.4, 20, 2, PANEL_BORDER)
    cy = bar.y + bar.height / 2
    rl.draw_texture(self._search_icon, int(bar.x + 36), int(cy - self._search_icon.height / 2), MUTED)
    rl.draw_text_ex(font, self._query or tr("Search"),
                    rl.Vector2(int(bar.x + 36 + self._search_icon.width + 24), int(cy - 22)), 44, 0, rl.WHITE)
    self._tap_targets.append((bar, lambda: self._open_search(self._purpose)))
    y += SEARCH_HEIGHT + SPACING

    list_rect = rl.Rectangle(x, y, w, rect.y + rect.height - y)
    results = self._search.results()
    if self._selecting:
      self._draw_center_note(list_rect, self._status_msg or tr("Locating..."))
      return
    if not results:
      note = tr("Searching...") if self._search.searching else (self._status_msg or tr("No results"))
      self._draw_center_note(list_rect, note)
      return
    for r in results:
      if y + ROW_HEIGHT > list_rect.y + list_rect.height:
        break
      dist = f"{r.distance_m / 1609.34:.1f} mi" if r.distance_m else ""
      sub = f"{r.address}   ·   {dist}" if dist else r.address
      self._row(rl.Rectangle(x, y, w, ROW_HEIGHT), self._pin_icon, r.name, sub,
                (lambda r=r: self._select_result(r)))
      y += ROW_HEIGHT + ROW_GAP

  def _handle_mouse_release(self, mouse_pos: MousePos):
    for rect, cb in self._tap_targets:
      if rl.check_collision_point_rec(mouse_pos, rect):
        cb()
        return
