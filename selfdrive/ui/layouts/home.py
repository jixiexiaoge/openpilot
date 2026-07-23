import time
import os
import pyray as rl
from collections.abc import Callable
from enum import IntEnum
from cereal import log
from openpilot.common.params import Params
from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.widgets.offroad_alerts import UpdateAlert, OffroadAlert
from openpilot.selfdrive.ui.widgets.setup import SetupWidget
from openpilot.selfdrive.ui.widgets.inspire_widget import InspireWidget
from openpilot.selfdrive.ui.widgets.map_panel_widget import MapPanelWidget
from openpilot.iqpilot.ui.layouts.settings.trips import TripsLayout
from openpilot.selfdrive.ui.layouts.sidebar import NETWORK_TYPES
from openpilot.selfdrive.ui.lib.wifi_ssid import current_ssid
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight, MouseEvent, MousePos
from openpilot.system.ui.lib.multilang import tr, trn
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets.label import gui_label, UnifiedLabel
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle

STATUS_BAR_HEIGHT = 120
HEAD_BUTTON_FONT_SIZE = 40
CONTENT_MARGIN = 40
SPACING = 25
TILE_GAP = 24
STATS_PANEL_VERTICAL_INSET = TILE_GAP
REFRESH_INTERVAL = 10.0
CHANGELOG_REFRESH_INTERVAL = 15.0
HOLD_THRESHOLD = 0.6  # seconds to trigger the panel picker

PANEL_KEY = "HomePanelWidget"
PANEL_CHANGELOG = "changelog"
PANEL_STATS = "stats"
PANEL_MAP = "map"
PANEL_INSPIRE = "inspire"

PICKER_BG = rl.Color(20, 21, 26, 230)
PICKER_CARD = rl.Color(34, 36, 44, 255)
PICKER_CARD_HOVER = rl.Color(48, 51, 60, 255)
PICKER_BORDER = rl.Color(255, 255, 255, 30)
PICKER_TEAL = rl.Color(16, 185, 169, 255)
PICKER_SEL_BORDER = rl.Color(16, 185, 169, 200)

ThermalStatus = log.DeviceState.ThermalStatus
NetworkType = log.DeviceState.NetworkType

# Status-light severity colors
STATUS_GOOD = rl.Color(16, 185, 169, 255)    # teal
STATUS_WARN = rl.Color(245, 166, 35, 255)    # orange
STATUS_DANGER = rl.Color(226, 72, 58, 255)   # red


class ChangelogWidget(Widget):
  PANEL_BG_COLOR = rl.Color(34, 36, 42, 255)
  PANEL_BORDER = rl.Color(255, 255, 255, 26)
  BODY_COLOR = rl.Color(235, 235, 235, 255)
  HEADING_COLOR = rl.Color(255, 255, 255, 255)

  def __init__(self):
    super().__init__()
    self._show_all = False
    self._latest_text = ""
    self._all_text = ""
    self._render_latest: list[dict] = []
    self._render_all: list[dict] = []
    self._wrap_width = 0
    self._last_load = 0.0
    self._scroll_px = 0.0
    self._max_scroll = 0.0
    self._is_dragging = False
    self._drag_last_y = 0.0
    self._text_rect = rl.Rectangle(0, 0, 0, 0)
    self._btn_rect = rl.Rectangle(0, 0, 0, 0)
    self._latest_btn = Button("Latest", self._show_latest, button_style=ButtonStyle.PRIMARY, font_size=28)
    self._all_btn = Button("All", self._show_all_logs, button_style=ButtonStyle.NORMAL, font_size=28)
    self._load_changelog(force=True)

  def show_event(self):
    self._load_changelog(force=True)

  def _show_latest(self) -> None:
    self._show_all = False
    self._scroll_px = 0.0
    self._is_dragging = False

  def _show_all_logs(self) -> None:
    self._show_all = True
    self._scroll_px = 0.0
    self._is_dragging = False

  def _load_changelog(self, force: bool = False) -> None:
    now = time.monotonic()
    if not force and (now - self._last_load) < CHANGELOG_REFRESH_INTERVAL:
      return
    self._last_load = now

    paths = [os.path.join(BASEDIR, "CHANGELOG.md"), os.path.join(BASEDIR, "changelog.md")]
    content = ""
    for p in paths:
      try:
        with open(p, encoding="utf-8") as f:
          content = f.read().strip()
          if content:
            break
      except OSError:
        pass

    if not content:
      content = "No changelog found.\n\nAdd CHANGELOG.md to the project root."

    ordered = self._reorder_sections_newest_first(content)
    self._latest_text = self._build_latest_text(ordered)
    self._all_text = ordered
    self._render_latest = []
    self._render_all = []
    self._wrap_width = 0

  def _reorder_sections_newest_first(self, content: str) -> str:
    lines = content.splitlines()
    intro: list[str] = []
    sections: list[list[str]] = []
    current: list[str] | None = None

    for line in lines:
      if line.startswith("## "):
        if current is not None:
          sections.append(current)
        current = [line]
      else:
        if current is None:
          intro.append(line)
        else:
          current.append(line)

    if current is not None:
      sections.append(current)

    out: list[str] = []
    if intro:
      out.extend(intro)
      out.append("")

    for i, section in enumerate(reversed(sections)):
      out.extend(section)
      if i != len(sections) - 1:
        out.append("")

    return "\n".join(out).strip()

  def _build_latest_text(self, content: str) -> str:
    lines = content.splitlines()
    if not lines:
      return "No updates available."

    out: list[str] = []
    section_count = 0
    for line in lines:
      if line.startswith("## "):
        section_count += 1
        if section_count > 2:
          break
      out.append(line)
    return "\n".join(out).strip() or content

  @staticmethod
  def _clean_inline_markdown(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()

  def _build_render_lines(self, text: str, width: int) -> list[dict]:
    lines: list[dict] = []
    for raw in text.splitlines():
      stripped = raw.strip()
      if not stripped:
        lines.append({"text": "", "font_size": 16, "font_weight": FontWeight.NORMAL, "indent": 0, "color": self.BODY_COLOR, "height": 18})
        continue

      font_size = 34
      font_weight = FontWeight.NORMAL
      indent = 0
      color = self.BODY_COLOR
      text_line = stripped
      extra_spacing = 0

      if stripped.startswith("### "):
        text_line = self._clean_inline_markdown(stripped[4:])
        font_size = 34
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 8
      elif stripped.startswith("## "):
        text_line = self._clean_inline_markdown(stripped[3:])
        font_size = 38
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 10
      elif stripped.startswith("# "):
        text_line = self._clean_inline_markdown(stripped[2:])
        font_size = 42
        font_weight = FontWeight.BOLD
        color = self.HEADING_COLOR
        extra_spacing = 12
      elif stripped.startswith(("- ", "* ")):
        text_line = "• " + self._clean_inline_markdown(stripped[2:])
        font_size = 34
        indent = 8
      else:
        text_line = self._clean_inline_markdown(stripped)

      font = gui_app.font(font_weight)
      wrapped = wrap_text(font, text_line, font_size, max(50, width - indent))
      if not wrapped:
        wrapped = [text_line]

      for i, w in enumerate(wrapped):
        line_indent = indent if i == 0 else indent + 18
        line_h = int(font_size * 1.15)
        lines.append({
          "text": w,
          "font_size": font_size,
          "font_weight": font_weight,
          "indent": line_indent,
          "color": color,
          "height": line_h,
        })

      if extra_spacing > 0:
        lines.append({"text": "", "font_size": extra_spacing, "font_weight": FontWeight.NORMAL, "indent": 0, "color": self.BODY_COLOR, "height": extra_spacing})

    return lines

  def _ensure_wrapped(self, text_w: int):
    if text_w <= 0:
      return
    if self._wrap_width == text_w and self._render_latest and self._render_all:
      return
    self._wrap_width = text_w
    self._render_latest = self._build_render_lines(self._latest_text, text_w)
    self._render_all = self._build_render_lines(self._all_text, text_w)

  @staticmethod
  def _total_height(lines: list[dict]) -> int:
    return sum(line["height"] for line in lines)

  def _clamp_scroll(self):
    self._scroll_px = max(0.0, min(self._max_scroll, self._scroll_px))

  def _handle_mouse_press(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, self._text_rect):
      self._is_dragging = True
      self._drag_last_y = mouse_pos.y

  def _handle_mouse_event(self, mouse_event):
    if not self._is_dragging or not mouse_event.left_down:
      return
    dy = mouse_event.pos.y - self._drag_last_y
    self._drag_last_y = mouse_event.pos.y
    self._scroll_px -= dy
    self._clamp_scroll()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    self._is_dragging = False

  def _render(self, rect: rl.Rectangle):
    self._load_changelog()
    rl.draw_rectangle_rounded(rect, 0.06, 24, self.PANEL_BG_COLOR)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.06, 24, 2, self.PANEL_BORDER)

    title_rect = rl.Rectangle(rect.x + 36, rect.y + 24, rect.width - 72, 50)
    gui_label(title_rect, "Latest Updates", 44, rl.WHITE, font_weight=FontWeight.BOLD, alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT)

    btn_w = 150
    btn_h = 54
    btn_gap = 12
    self._btn_rect = rl.Rectangle(rect.x + rect.width - (btn_w * 2) - btn_gap - 36, rect.y + 84, (btn_w * 2) + btn_gap, btn_h)
    latest_rect = rl.Rectangle(self._btn_rect.x, self._btn_rect.y, btn_w, btn_h)
    all_rect = rl.Rectangle(self._btn_rect.x + btn_w + btn_gap, self._btn_rect.y, btn_w, btn_h)

    self._latest_btn.set_button_style(ButtonStyle.PRIMARY if not self._show_all else ButtonStyle.NORMAL)
    self._all_btn.set_button_style(ButtonStyle.PRIMARY if self._show_all else ButtonStyle.NORMAL)
    self._latest_btn.render(latest_rect)
    self._all_btn.render(all_rect)

    self._text_rect = rl.Rectangle(rect.x + 36, rect.y + 154, rect.width - 72, rect.height - 182)
    self._ensure_wrapped(int(self._text_rect.width))

    lines = self._render_all if self._show_all else self._render_latest
    total_h = self._total_height(lines)
    self._max_scroll = max(0.0, total_h - self._text_rect.height)
    self._clamp_scroll()

    # Clip content region and draw formatted lines
    rl.begin_scissor_mode(int(self._text_rect.x), int(self._text_rect.y), int(self._text_rect.width), int(self._text_rect.height))
    y = self._text_rect.y - self._scroll_px
    for line in lines:
      line_h = line["height"]
      if line["text"] and (y + line_h) >= self._text_rect.y and y <= (self._text_rect.y + self._text_rect.height):
        font = gui_app.font(line["font_weight"])
        x = self._text_rect.x + line["indent"]
        rl.draw_text_ex(font, line["text"], rl.Vector2(x, y), line["font_size"], 0, line["color"])
      y += line_h
    rl.end_scissor_mode()

    if self._max_scroll > 0.0:
      hint = "Drag to scroll"
      hint_size = measure_text_cached(gui_app.font(FontWeight.NORMAL), hint, 24)
      hint_x = self._text_rect.x + self._text_rect.width - hint_size.x
      hint_y = rect.y + rect.height - 12 - hint_size.y
      rl.draw_text_ex(gui_app.font(FontWeight.NORMAL), hint, rl.Vector2(hint_x, hint_y), 24, 0, rl.Color(180, 180, 180, 220))


def _format_updater_description(description: str | None) -> str:
  brand = "IQ.Pilot"
  if not description:
    return brand

  cleaned = description.strip()
  lower = cleaned.lower()
  if lower.startswith("iqpilot"):
    cleaned = cleaned[len("iqpilot"):].lstrip(" -:/")

  if cleaned.lower().startswith(brand.lower()):
    return cleaned
  return f"{brand} {cleaned}" if cleaned else brand


class LauncherTile(Widget):
  """A large offroad launcher tile: teal-gradient icon over a dark rounded card, label beneath."""

  BG = rl.Color(34, 36, 42, 255)
  BG_PRESSED = rl.Color(50, 53, 61, 255)
  BORDER = rl.Color(255, 255, 255, 26)

  def __init__(self, icon_path: str, label: str, on_click: Callable[[], None] | None = None):
    super().__init__()
    self._label = label
    self._icon_path = icon_path
    self._icon = gui_app.texture(icon_path, 256, 256, keep_aspect_ratio=True)
    if on_click is not None:
      self.set_click_callback(on_click)

  def set_label(self, label: str) -> None:
    self._label = label

  def set_icon_path(self, icon_path: str) -> None:
    if icon_path != self._icon_path:
      self._icon_path = icon_path
      self._icon = gui_app.texture(icon_path, 256, 256, keep_aspect_ratio=True)

  def _render(self, rect: rl.Rectangle):
    pressed = self.is_pressed
    rl.draw_rectangle_rounded(rect, 0.16, 24, self.BG_PRESSED if pressed else self.BG)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.16, 24, 2, self.BORDER)

    # Icon centered in the upper portion of the tile
    icon_size = min(rect.width, rect.height) * 0.44
    cx = rect.x + rect.width / 2
    cy = rect.y + rect.height * 0.40
    icon_dst = rl.Rectangle(cx - icon_size / 2, cy - icon_size / 2, icon_size, icon_size)
    src = rl.Rectangle(0, 0, self._icon.width, self._icon.height)
    rl.draw_texture_pro(self._icon, src, icon_dst, rl.Vector2(0, 0), 0, rl.WHITE)

    # Label, centered beneath the icon
    font = gui_app.font(FontWeight.MEDIUM)
    label_size = 48
    ts = measure_text_cached(font, self._label, label_size)
    label_x = rect.x + (rect.width - ts.x) / 2
    label_y = rect.y + rect.height * 0.75
    rl.draw_text_ex(font, self._label, rl.Vector2(int(label_x), int(label_y)), label_size, 0, rl.WHITE)


class HomeLayoutState(IntEnum):
  HOME = 0
  UPDATE = 1
  ALERTS = 2


class HomeLayout(Widget):
  def __init__(self):
    super().__init__()
    self.params = Params()

    self.update_alert = UpdateAlert()
    self.offroad_alert = OffroadAlert()

    self._layout_widgets = {HomeLayoutState.UPDATE: self.update_alert, HomeLayoutState.ALERTS: self.offroad_alert}

    self.current_state = HomeLayoutState.HOME
    self.last_refresh = 0
    self.settings_callback: Callable[[], None] | None = None
    self.stats_callback: Callable[[], None] | None = None
    self.nav_callback: Callable[[], None] | None = None
    self.routes_callback: Callable[[], None] | None = None

    self.update_available = False
    self.alert_count = 0
    self._version_text = ""
    self._version_commit_text = ""
    self._status_version_label = UnifiedLabel("", font_size=44, font_weight=FontWeight.MEDIUM,
                                              text_color=rl.Color(185, 185, 190, 255),
                                              alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE,
                                              wrap_text=False, scroll=True)
    self._prev_update_available = False
    self._prev_alerts_present = False

    # Status-bar state
    self._status_color = STATUS_GOOD
    self._status_word = tr("READY")
    self._expanded = False
    self._expanded_metrics: list[tuple[str, str, rl.Color]] = []
    self._net_type = NETWORK_TYPES.get(NetworkType.none)
    self._on_wifi = False
    self._battery_pct: int | None = None
    self._battery_charging = False

    self.status_bar_rect = rl.Rectangle(0, 0, 0, 0)
    self.content_rect = rl.Rectangle(0, 0, 0, 0)
    self.left_column_rect = rl.Rectangle(0, 0, 0, 0)
    self.right_column_rect = rl.Rectangle(0, 0, 0, 0)
    self._tile_rects: list[rl.Rectangle] = []

    self.update_notif_rect = rl.Rectangle(0, 0, 200, 60)
    self.alert_notif_rect = rl.Rectangle(0, 0, 220, 60)

    self._setup_widget = SetupWidget()
    self._changelog_widget = ChangelogWidget()
    self._inspire_widget = InspireWidget()
    self._map_panel_widget = MapPanelWidget()
    self._stats_panel_widget = TripsLayout()

    # Right-panel widget selection
    saved = self.params.get(PANEL_KEY) or ""
    self._panel_widget = saved if saved in (PANEL_CHANGELOG, PANEL_STATS, PANEL_MAP, PANEL_INSPIRE) else PANEL_CHANGELOG

    # Hold-to-pick
    self._press_start: float | None = None
    self._press_origin: tuple[float, float] = (0.0, 0.0)
    self._press_scrolled = False   # True once the current press moved — don't restart timer
    self._show_picker = False
    self._picker_hover: str | None = None
    self._picker_ignore_release = False  # swallow the release that opened the picker

    # Status-bar icons (white, tinted at draw time)
    self._icon_wifi = gui_app.texture("icons/iq/wifi.png", 64, 64, keep_aspect_ratio=True)
    self._icon_battery = gui_app.texture("icons/iq/battery.png", 72, 72, keep_aspect_ratio=True)

    _net_base = "icons_mici/settings/network/"
    self._cell_strength_icons = [
      gui_app.texture(f"{_net_base}cell_strength_none.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_medium.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_high.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_full.png", 64, 64, keep_aspect_ratio=True),
    ]
    # wifi has no "high" variant: none/low/medium/full only
    self._wifi_strength_icons = [
      gui_app.texture(f"{_net_base}wifi_strength_none.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_medium.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_full.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_full.png", 64, 64, keep_aspect_ratio=True),
    ]
    self._net_strength = 0

    # Launcher tiles
    self._tiles = [
      LauncherTile("icons/iq/tile_settings.png", tr("Settings"), self._on_settings_tile),
      LauncherTile("icons/iq/tile_stats.png", tr("Stats"), self._on_stats_tile),
      LauncherTile("icons/iq/tile_nav.png", tr("Navigation"), self._on_nav_tile),
      LauncherTile("icons/iq/tile_routes.png", tr("Routes"), self._on_routes_tile),
    ]

    self._setup_callbacks()

  def show_event(self):
    self._changelog_widget.show_event()
    self.last_refresh = time.monotonic()
    self._refresh()

  def _setup_callbacks(self):
    self.update_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))
    self.offroad_alert.set_dismiss_callback(lambda: self._set_state(HomeLayoutState.HOME))

  def set_settings_callback(self, callback: Callable):
    self.settings_callback = callback

  def set_stats_callback(self, callback: Callable):
    self.stats_callback = callback

  def set_nav_callback(self, callback: Callable):
    self.nav_callback = callback

  def set_routes_callback(self, callback: Callable):
    self.routes_callback = callback

  # Tile actions
  def _on_settings_tile(self):
    if self.settings_callback:
      self.settings_callback()

  def _on_stats_tile(self):
    if self.stats_callback:
      self.stats_callback()

  def _on_nav_tile(self):
    if self.nav_callback:
      self.nav_callback()

  def _on_routes_tile(self):
    if self.routes_callback:
      self.routes_callback()

  def _set_state(self, state: HomeLayoutState):
    # propagate show/hide events
    if state != self.current_state:
      if state in self._layout_widgets:
        self._layout_widgets[state].show_event()
      if self.current_state in self._layout_widgets:
        self._layout_widgets[self.current_state].hide_event()

    self.current_state = state

  def _render(self, rect: rl.Rectangle):
    current_time = time.monotonic()
    if current_time - self.last_refresh >= REFRESH_INTERVAL:
      self._refresh()
      self.last_refresh = current_time

    self._render_status_bar()

    if self.current_state == HomeLayoutState.HOME:
      self._render_home_content()
    elif self.current_state == HomeLayoutState.UPDATE:
      self.update_alert.render(self.content_rect)
    elif self.current_state == HomeLayoutState.ALERTS:
      self.offroad_alert.render(self.content_rect)

  def _update_state(self):
    self.status_bar_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, self._rect.y + CONTENT_MARGIN,
      self._rect.width - 2 * CONTENT_MARGIN, STATUS_BAR_HEIGHT
    )

    content_y = self._rect.y + CONTENT_MARGIN + STATUS_BAR_HEIGHT + SPACING
    content_height = self._rect.height - CONTENT_MARGIN - STATUS_BAR_HEIGHT - SPACING - CONTENT_MARGIN
    self.content_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, content_y, self._rect.width - 2 * CONTENT_MARGIN, content_height
    )

    right_width = min(820, self.content_rect.width * 0.46)
    left_width = self.content_rect.width - right_width - SPACING
    self.left_column_rect = rl.Rectangle(self.content_rect.x, self.content_rect.y, left_width, self.content_rect.height)
    self.right_column_rect = rl.Rectangle(
      self.content_rect.x + left_width + SPACING, self.content_rect.y, right_width, self.content_rect.height
    )

    # 2x2 tile grid
    tile_w = (self.left_column_rect.width - TILE_GAP) / 2
    tile_h = (self.left_column_rect.height - TILE_GAP) / 2
    self._tile_rects = []
    for i in range(4):
      col = i % 2
      row = i // 2
      tx = self.left_column_rect.x + col * (tile_w + TILE_GAP)
      ty = self.left_column_rect.y + row * (tile_h + TILE_GAP)
      self._tile_rects.append(rl.Rectangle(tx, ty, tile_w, tile_h))

    self._update_status_info()
    self._update_hold()

  def _clear_panel_hold(self):
    self._press_start = None
    self._press_scrolled = False

  def _update_hold(self):
    if not ui_state.prime_state.is_paired() or self._show_picker:
      self._clear_panel_hold()
      return
    if self._press_start is None or self._press_scrolled:
      return
    if time.monotonic() - self._press_start >= HOLD_THRESHOLD:
      self._show_picker = True
      self._press_start = None
      self._picker_ignore_release = True

  def _update_status_info(self):
    # Read the expanded-status toggle every frame (not gated by deviceState updates)
    self._expanded = self.params.get_bool("IQExpandedStatus")

    sm = ui_state.sm
    # Network + battery — updated from cached state every frame so values are never stale
    _ds_cached = sm['deviceState']
    self._net_type = NETWORK_TYPES.get(_ds_cached.networkType.raw, self._net_type)
    self._on_wifi = _ds_cached.networkType.raw in (NetworkType.wifi, NetworkType.ethernet)
    _strength = _ds_cached.networkStrength
    self._net_strength = max(0, min(5, _strength.raw + 1)) if _strength.raw > 0 else 0
    if sm.updated['deviceState']:
      ds = sm['deviceState']
      # Battery (not present on all hardware/messages)
      try:
        self._battery_pct = int(ds.batteryPercent)
        self._battery_charging = bool(ds.batteryStatus == "Charging")
      except (AttributeError, ValueError):
        self._battery_pct = None

    # Status pill — computed every frame from cached state so it's always current.
    # severity: 1 = warning (orange), 2 = error (red). No issues -> READY (teal).
    _ds = sm['deviceState']
    issues: list[tuple[int, str]] = []

    _ts = _ds.thermalStatus
    if _ts == ThermalStatus.red:
      issues.append((2, tr("TEMP HIGH")))
    elif _ts == ThermalStatus.yellow:
      issues.append((1, tr("TEMP OK")))

    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      issues.append((2, tr("UNAVAILABLE")))

    _last_ping = _ds.lastAthenaPingTime
    if _last_ping == 0:
      issues.append((1, tr("KONN3KT OFFLINE")))
    elif time.monotonic_ns() - _last_ping >= 80_000_000_000:
      issues.append((2, tr("KONN3KT ERROR")))

    if issues:
      severity, word = max(issues, key=lambda i: i[0])
    else:
      severity, word = 0, tr("READY")

    self._status_color = (STATUS_GOOD, STATUS_WARN, STATUS_DANGER)[severity]
    self._status_word = word

    # Expanded status (classic-UI style) — rebuilt every frame from cached state
    if self._expanded:
      ds = sm['deviceState']
      ts = ds.thermalStatus
      if ts == ThermalStatus.green:
        temp = (tr("TEMP"), tr("GOOD"), STATUS_GOOD)
      elif ts == ThermalStatus.yellow:
        temp = (tr("TEMP"), tr("OK"), STATUS_WARN)
      else:
        temp = (tr("TEMP"), tr("HIGH"), STATUS_DANGER)
      if ui_state.panda_type == log.PandaState.PandaType.unknown:
        veh = (tr("VEHICLE"), tr("NO PANDA"), STATUS_DANGER)
      else:
        veh = (tr("VEHICLE"), tr("ONLINE"), STATUS_GOOD)
      last_ping = ds.lastAthenaPingTime
      if last_ping == 0:
        kon = (tr("KONN3KT"), tr("OFFLINE"), STATUS_WARN)
      elif time.monotonic_ns() - last_ping < 80_000_000_000:
        kon = (tr("KONN3KT"), tr("ONLINE"), STATUS_GOOD)
      else:
        kon = (tr("KONN3KT"), tr("ERROR"), STATUS_DANGER)
      self._expanded_metrics = [temp, veh, kon]
    else:
      self._expanded_metrics = []

  def _handle_mouse_press(self, mouse_pos: MousePos):
    if (self.current_state == HomeLayoutState.HOME and ui_state.prime_state.is_paired()
        and not self._show_picker and rl.check_collision_point_rec(mouse_pos, self.right_column_rect)):
      self._press_start = time.monotonic()
      self._press_origin = (mouse_pos.x, mouse_pos.y)
      self._press_scrolled = False

  def _handle_mouse_event(self, mouse_event: MouseEvent):
    if self._press_start is None or self._press_scrolled or not mouse_event.left_down:
      return

    dx = mouse_event.pos.x - self._press_origin[0]
    dy = mouse_event.pos.y - self._press_origin[1]
    if dx * dx + dy * dy > 18 * 18:
      self._press_start = None
      self._press_scrolled = True

  def _handle_mouse_release(self, mouse_pos: MousePos):
    self._clear_panel_hold()

    if self._show_picker:
      if self._picker_ignore_release:
        self._picker_ignore_release = False
        return
      if self._picker_hover is not None:
        self._panel_widget = self._picker_hover
        self.params.put(PANEL_KEY, self._panel_widget)
        if self._panel_widget == PANEL_INSPIRE:
          self._inspire_widget.show_event()
        elif self._panel_widget == PANEL_CHANGELOG:
          self._changelog_widget.show_event()
      self._show_picker = False
      self._picker_hover = None
      return

    super()._handle_mouse_release(mouse_pos)

    if self.update_available and rl.check_collision_point_rec(mouse_pos, self.update_notif_rect):
      self._set_state(HomeLayoutState.UPDATE)
    elif self.alert_count > 0 and rl.check_collision_point_rec(mouse_pos, self.alert_notif_rect):
      self._set_state(HomeLayoutState.ALERTS)

  def _render_status_bar(self):
    rect = self.status_bar_rect
    cy = rect.y + rect.height / 2
    font_bold = gui_app.font(FontWeight.BOLD)
    font = gui_app.font(FontWeight.MEDIUM)

    word_fs = 50
    text_fs = 44
    pad = 36
    gap = 26
    light_d = 54  # status light region width

    # --- measure the left cluster so we can wrap it in a rounded pill ---
    # The summary word (READY / KONN3KT ERROR / ...) duplicates the expanded TEMP/VEHICLE/KONN3KT
    # chips, so drop it when expanded — the color-coded status dot still conveys severity.
    show_word = not (self._expanded and self._expanded_metrics)
    word_w = measure_text_cached(font_bold, self._status_word, word_fs).x if show_word else 0
    net_text = current_ssid(self._on_wifi) or tr(self._net_type)
    net_w = measure_text_cached(font, net_text, text_fs).x
    _sig_icons = self._wifi_strength_icons if self._on_wifi else self._cell_strength_icons
    _icon_signal = _sig_icons[min(self._net_strength, len(_sig_icons) - 1)]
    cluster_w = pad + light_d + gap + (word_w + gap if show_word else 0) + _icon_signal.width + 14 + net_w
    batt_text = None
    if self._battery_pct is not None:
      batt_text = f"{self._battery_pct}%"
      cluster_w += gap + self._icon_battery.width + 10 + measure_text_cached(font, batt_text, text_fs).x
    cluster_w += pad

    pill = rl.Rectangle(rect.x, rect.y, cluster_w, rect.height)
    rl.draw_rectangle_rounded(pill, 0.5, 20, rl.Color(28, 30, 36, 255))
    rl.draw_rectangle_rounded_lines_ex(pill, 0.5, 20, 2, rl.Color(255, 255, 255, 28))

    # status light dot with a faint halo
    x = rect.x + pad
    halo = rl.Color(self._status_color.r, self._status_color.g, self._status_color.b, 70)
    rl.draw_circle(int(x + light_d / 2), int(cy), 32, halo)
    rl.draw_circle(int(x + light_d / 2), int(cy), 22, self._status_color)
    x += light_d + gap

    # status word (summary) — hidden when the expanded chips already show the breakdown
    if show_word:
      word_size = measure_text_cached(font_bold, self._status_word, word_fs)
      rl.draw_text_ex(font_bold, self._status_word, rl.Vector2(int(x), int(cy - word_size.y / 2)), word_fs, 0, rl.WHITE)
      x += word_w + gap

    # network: signal icon (strength-aware) + type
    rl.draw_texture(_icon_signal, int(x), int(cy - _icon_signal.height / 2), rl.WHITE)
    x += _icon_signal.width + 14
    net_size = measure_text_cached(font, net_text, text_fs)
    rl.draw_text_ex(font, net_text, rl.Vector2(int(x), int(cy - net_size.y / 2)), text_fs, 0, rl.Color(215, 215, 215, 255))
    x += net_w + gap

    # battery, if available
    if batt_text is not None:
      rl.draw_texture(self._icon_battery, int(x), int(cy - self._icon_battery.height / 2), rl.WHITE)
      x += self._icon_battery.width + 10
      batt_size = measure_text_cached(font, batt_text, text_fs)
      rl.draw_text_ex(font, batt_text, rl.Vector2(int(x), int(cy - batt_size.y / 2)), text_fs, 0, rl.Color(215, 215, 215, 255))

    right_x = rect.x + rect.width
    version_fs = 44
    version_text = self._version_commit_text if self._expanded else self._version_text
    version_size = measure_text_cached(font, version_text, version_fs)
    version_available = max(1.0, right_x - x - gap)
    version_w = min(version_size.x, version_available)
    version_rect = rl.Rectangle(right_x - version_w, rect.y, version_w, rect.height)

    # --- expanded status chips (classic-UI style), gated by the Visuals toggle ---
    if self._expanded and self._expanded_metrics:
      chip_x = rect.x + cluster_w + gap
      chip_h = rect.height - 16
      chip_pad = 22
      dot_r = 11
      label_fs = 30
      max_x = version_rect.x - 30
      for label, value, color in self._expanded_metrics:
        ctext = f"{label} {value}"
        tw = measure_text_cached(font, ctext, label_fs).x
        chip_w = chip_pad + dot_r * 2 + 14 + tw + chip_pad
        if chip_x + chip_w > max_x:
          break
        chip = rl.Rectangle(chip_x, rect.y + 8, chip_w, chip_h)
        rl.draw_rectangle_rounded(chip, 0.5, 16, rl.Color(28, 30, 36, 255))
        rl.draw_rectangle_rounded_lines_ex(chip, 0.5, 16, 2, rl.Color(255, 255, 255, 22))
        ccx = chip.x + chip_pad + dot_r
        rl.draw_circle(int(ccx), int(cy), dot_r, color)
        rl.draw_text_ex(font, ctext, rl.Vector2(int(ccx + dot_r + 14), int(cy - label_fs / 2 - 3)), label_fs, 0, rl.WHITE)
        chip_x += chip_w + 16

    # --- right cluster: version (small), then notification chips to its left ---
    if version_size.x <= version_rect.width:
      rl.draw_text_ex(font, version_text, rl.Vector2(int(right_x - version_size.x), int(cy - version_size.y / 2)),
                      version_fs, 0, rl.Color(185, 185, 190, 255))
    else:
      self._status_version_label.set_text(version_text)
      self._status_version_label.render(version_rect)
    chip_x = version_rect.x - 30

    if self.alert_count > 0:
      self.alert_notif_rect = rl.Rectangle(chip_x - self.alert_notif_rect.width, cy - 30, self.alert_notif_rect.width, 60)
      self._draw_chip(self.alert_notif_rect, trn("{} ALERT", "{} ALERTS", self.alert_count).format(self.alert_count),
                      rl.Color(226, 72, 58, 255) if self.current_state != HomeLayoutState.ALERTS else rl.Color(245, 92, 78, 255))
      chip_x = self.alert_notif_rect.x - 16

    if self.update_available:
      self.update_notif_rect = rl.Rectangle(chip_x - self.update_notif_rect.width, cy - 30, self.update_notif_rect.width, 60)
      self._draw_chip(self.update_notif_rect, tr("UPDATE"),
                      rl.Color(54, 77, 239, 255) if self.current_state != HomeLayoutState.UPDATE else rl.Color(75, 95, 255, 255))

  def _draw_chip(self, chip_rect: rl.Rectangle, text: str, color: rl.Color):
    rl.draw_rectangle_rounded(chip_rect, 0.4, 10, color)
    font = gui_app.font(FontWeight.MEDIUM)
    text_size = measure_text_cached(font, text, HEAD_BUTTON_FONT_SIZE)
    text_x = chip_rect.x + (chip_rect.width - text_size.x) / 2
    text_y = chip_rect.y + (chip_rect.height - text_size.y) / 2
    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

  def _render_home_content(self):
    # left: 2x2 launcher tiles
    for tile, tile_rect in zip(self._tiles, self._tile_rects, strict=False):
      tile.render(tile_rect)

    # right: setup until paired, then the user-chosen widget
    if not ui_state.prime_state.is_paired():
      self._setup_widget.render(self.right_column_rect)
      return

    self._render_right_panel()

    if self._show_picker:
      self._render_picker()

  def _render_right_panel(self):
    rect = self.right_column_rect
    if self._panel_widget == PANEL_STATS:
      stats_rect = rl.Rectangle(
        rect.x,
        rect.y + STATS_PANEL_VERTICAL_INSET,
        rect.width,
        max(1, rect.height - STATS_PANEL_VERTICAL_INSET * 2),
      )
      self._stats_panel_widget.render(stats_rect)
    elif self._panel_widget == PANEL_MAP:
      self._map_panel_widget.render(rect)
    elif self._panel_widget == PANEL_INSPIRE:
      self._inspire_widget.render(rect)
    else:
      self._changelog_widget.render(rect)

    # Hold-progress ring drawn over the panel while user is holding
    if self._press_start is not None and not self._show_picker:
      held = time.monotonic() - self._press_start
      progress = min(1.0, held / HOLD_THRESHOLD)
      cx = int(rect.x + rect.width / 2)
      cy = int(rect.y + rect.height / 2)
      rl.draw_ring(rl.Vector2(cx, cy), 34, 42, -90, -90 + 360 * progress, 40, rl.Color(16, 185, 169, 180))

  def _render_picker(self):
    rect = self.right_column_rect
    rl.draw_rectangle_rounded(rect, 0.06, 24, PICKER_BG)

    options = [
      (PANEL_CHANGELOG, "Changelog",   "Latest updates"),
      (PANEL_STATS,     "Stats",       "Your drive history"),
      (PANEL_MAP,       "Map",         "Last known location"),
      (PANEL_INSPIRE,   "Inspiration", "Daily message"),
    ]

    TITLE_FS = 58
    SUB_FS = 38
    CARD_PAD_V = 36
    CARD_PAD_H = 32
    DOT_MARGIN = 24
    card_h = TITLE_FS + 12 + SUB_FS + CARD_PAD_V * 2
    outer_pad = 20
    gap = 12
    n = len(options)
    total_cards_h = n * card_h + (n - 1) * gap
    start_y = rect.y + (rect.height - total_cards_h) / 2

    mp = rl.get_mouse_position()
    self._picker_hover = None

    font_title = gui_app.font(FontWeight.BOLD)
    font_sub = gui_app.font(FontWeight.MEDIUM)

    for i, (key, title, sub) in enumerate(options):
      cy_card = start_y + i * (card_h + gap)
      card = rl.Rectangle(rect.x + outer_pad, cy_card, rect.width - outer_pad * 2, card_h)
      hovered = rl.check_collision_point_rec(mp, card)
      if hovered:
        self._picker_hover = key
      is_sel = key == self._panel_widget

      bg = PICKER_CARD_HOVER if hovered else PICKER_CARD
      rl.draw_rectangle_rounded(card, 0.14, 16, bg)
      border = PICKER_SEL_BORDER if is_sel else PICKER_BORDER
      rl.draw_rectangle_rounded_lines_ex(card, 0.14, 16, 2 if is_sel else 1, border)

      dot_cx = int(card.x + CARD_PAD_H)
      dot_cy = int(card.y + card_h / 2)
      if is_sel:
        rl.draw_circle(dot_cx, dot_cy, 8, PICKER_TEAL)
      else:
        rl.draw_circle(dot_cx, dot_cy, 8, rl.Color(255, 255, 255, 35))
        rl.draw_ring(rl.Vector2(dot_cx, dot_cy), 5.5, 8, 0, 360, 24, rl.Color(255, 255, 255, 55))

      tx = int(card.x + CARD_PAD_H + DOT_MARGIN + 6)
      title_y = int(card.y + CARD_PAD_V)
      sub_y = int(title_y + TITLE_FS + 8)
      title_col = rl.WHITE if is_sel else rl.Color(210, 210, 215, 255)
      sub_col = PICKER_TEAL if is_sel else rl.Color(130, 130, 138, 255)
      rl.draw_text_ex(font_title, title, rl.Vector2(tx, title_y), TITLE_FS, 0, title_col)
      rl.draw_text_ex(font_sub, sub, rl.Vector2(tx, sub_y), SUB_FS, 0, sub_col)

    # Hint centered below the cards
    hint = "Tap a widget to switch  •  tap outside to dismiss"
    font_hint = gui_app.font(FontWeight.MEDIUM)
    hw = measure_text_cached(font_hint, hint, 24).x
    hint_y = int(start_y + total_cards_h + 18)
    rl.draw_text_ex(font_hint, hint,
                    rl.Vector2(int(rect.x + (rect.width - hw) / 2), hint_y),
                    24, 0, rl.Color(110, 110, 118, 220))

  def _refresh(self):
    self._version_text, self._version_commit_text = self._get_version_texts()
    update_available = self.update_alert.refresh()
    alert_count = self.offroad_alert.refresh()
    alerts_present = alert_count > 0

    # Show panels on transition from no alert/update to any alerts/update
    if not update_available and not alerts_present:
      self._set_state(HomeLayoutState.HOME)
    elif update_available and ((not self._prev_update_available) or (not alerts_present and self.current_state == HomeLayoutState.ALERTS)):
      self._set_state(HomeLayoutState.UPDATE)
    elif alerts_present and ((not self._prev_alerts_present) or (not update_available and self.current_state == HomeLayoutState.UPDATE)):
      self._set_state(HomeLayoutState.ALERTS)

    self.update_available = update_available
    self.alert_count = alert_count
    self._prev_update_available = update_available
    self._prev_alerts_present = alerts_present

  def _get_version_texts(self) -> tuple[str, str]:
    description = self.params.get("UpdaterCurrentDescription")
    version_text = _format_updater_description(description)
    if description:
      parts = [part.strip() for part in description.split(" / ")]
      if len(parts) >= 3 and parts[2]:
        return version_text, parts[2]
    return version_text, version_text
