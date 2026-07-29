import pyray as rl
import time
from dataclasses import dataclass
from collections.abc import Callable
from cereal import log
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.lib.wifi_ssid import current_ssid
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

SIDEBAR_WIDTH = 300
METRIC_HEIGHT = 120
METRIC_WIDTH = 252
METRIC_MARGIN = 24

CARD_GAP = 16
STATUS_DOT_CENTER_X = 36
STATUS_TEXT_X = 66
STATUS_TEXT_RIGHT_MARGIN = 20
STATUS_LABEL_SIZE = 26
STATUS_VALUE_SIZE = 36
STATUS_LINE_GAP = 2
NETWORK_RECT = rl.Rectangle(24, 18, 252, 76)
SETTINGS_BTN = rl.Rectangle(24, 112, 252, 112)
HOME_BTN = rl.Rectangle(60, 860, 180, 180)

ThermalStatus = log.DeviceState.ThermalStatus
NetworkType = log.DeviceState.NetworkType


# Color scheme
class Colors:
  WHITE = rl.WHITE
  WHITE_DIM = rl.Color(255, 255, 255, 85)
  GRAY = rl.Color(84, 84, 84, 255)

  # Keep these in parity with the offroad home status indicators.
  GOOD = rl.Color(16, 185, 169, 255)
  WARNING = rl.Color(245, 166, 35, 255)
  DANGER = rl.Color(226, 72, 58, 255)

  # UI elements
  CARD_BG = rl.Color(28, 30, 36, 255)
  CARD_BG_PRESSED = rl.Color(50, 53, 61, 255)
  METRIC_BORDER = rl.Color(255, 255, 255, 22)
  BOOKMARK_BG = CARD_BG
  BOOKMARK_BG_PRESSED = CARD_BG_PRESSED
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(255, 255, 255, 166)


NETWORK_TYPES = {
  NetworkType.none: tr_noop("--"),
  NetworkType.wifi: tr_noop("Wi-Fi"),
  NetworkType.ethernet: tr_noop("ETH"),
  NetworkType.cell2G: tr_noop("2G"),
  NetworkType.cell3G: tr_noop("3G"),
  NetworkType.cell4G: tr_noop("LTE"),
  NetworkType.cell5G: tr_noop("5G"),
}


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class Sidebar(Widget):
  def __init__(self):
    Widget.__init__(self)
    self._net_type = NETWORK_TYPES.get(NetworkType.none)
    self._net_strength = 0

    self._temp_status = MetricData(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    self._panda_status = MetricData(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)
    self._connect_status = MetricData(tr_noop("KONN3KT"), tr_noop("OFFLINE"), Colors.WARNING)
    self._recording_audio = False

    self._home_img = gui_app.texture("images/button_home.png", HOME_BTN.width, HOME_BTN.height)
    self._konn3kt_home_logo = gui_app.texture("icons_mici/settings/konn3kt_icon.png", 104, 104)
    self._settings_img = gui_app.texture("icons/iq/tile_settings.png", 92, 92, keep_aspect_ratio=True)
    self._mic_img = gui_app.texture("icons_mici/microphone.png", 26, 30, keep_aspect_ratio=True)
    self._live_view_img = gui_app.texture("icons/live_view.png", 38, 32, keep_aspect_ratio=True)
    self._live_streaming = False
    _net_base = "icons_mici/settings/network/"
    self._cell_strength_icons = [
      gui_app.texture(f"{_net_base}cell_strength_none.png", 56, 56, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_low.png", 56, 56, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_low.png", 56, 56, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_medium.png", 56, 56, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_high.png", 56, 56, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}cell_strength_full.png", 56, 56, keep_aspect_ratio=True),
    ]
    self._wifi_strength_icons = [
      gui_app.texture(f"{_net_base}wifi_strength_none.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_low.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_medium.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_full.png", 64, 64, keep_aspect_ratio=True),
      gui_app.texture(f"{_net_base}wifi_strength_full.png", 64, 64, keep_aspect_ratio=True),
    ]
    self._mic_indicator_rect = rl.Rectangle(0, 0, 0, 0)
    self._font_regular = gui_app.font(FontWeight.MEDIUM)
    self._font_bold = gui_app.font(FontWeight.BOLD)

    # Callbacks
    self._on_settings_click: Callable | None = None
    self._on_flag_click: Callable | None = None
    self._open_settings_callback: Callable | None = None

  def set_callbacks(self, on_settings: Callable | None = None, on_flag: Callable | None = None,
                    open_settings: Callable | None = None):
    self._on_settings_click = on_settings
    self._on_flag_click = on_flag
    self._open_settings_callback = open_settings

  def _render(self, rect: rl.Rectangle):
    # Background
    rl.draw_rectangle_rec(rect, rl.BLACK)

    self._draw_buttons(rect)
    self._draw_network_indicator(rect)
    self._draw_metrics(rect)

  def _update_state(self):
    sm = ui_state.sm
    device_state = sm['deviceState']

    self._recording_audio = ui_state.recording_audio
    # Konn3kt Live View is streaming to a viewer (hephaestusd sets this while a session is live)
    self._live_streaming = ui_state.params.get_bool("IsLiveStreaming")
    self._update_network_status(device_state)
    self._update_temperature_status(device_state)
    self._update_connection_status(device_state)
    self._update_panda_status()

  def _update_network_status(self, device_state):
    self._net_type = NETWORK_TYPES.get(device_state.networkType.raw, tr_noop("Unknown"))
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _update_temperature_status(self, device_state):
    thermal_status = device_state.thermalStatus

    if thermal_status == ThermalStatus.green:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    elif thermal_status == ThermalStatus.yellow:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("OK"), Colors.WARNING)
    else:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("HIGH"), Colors.DANGER)

  def _update_connection_status(self, device_state):
    last_ping = device_state.lastAthenaPingTime
    if last_ping == 0:
      self._connect_status.update(tr_noop("KONN3KT"), tr_noop("OFFLINE"), Colors.WARNING)
    elif time.monotonic_ns() - last_ping < 80_000_000_000:  # 80 seconds in nanoseconds
      self._connect_status.update(tr_noop("KONN3KT"), tr_noop("ONLINE"), Colors.GOOD)
    else:
      self._connect_status.update(tr_noop("KONN3KT"), tr_noop("ERROR"), Colors.DANGER)

  def _update_panda_status(self):
    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("NO PANDA"), Colors.DANGER)
    else:
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN):
      if self._on_settings_click:
        self._on_settings_click()
    elif rl.check_collision_point_rec(mouse_pos, HOME_BTN) and ui_state.started:
      if self._on_flag_click:
        self._on_flag_click()
    elif self._recording_audio and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect):
      if self._open_settings_callback:
        self._open_settings_callback()

  def _draw_buttons(self, rect: rl.Rectangle):
    mouse_pos = rl.get_mouse_position()
    mouse_down = self.is_pressed and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # Settings button
    settings_down = mouse_down and rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN)
    rl.draw_rectangle_rounded(SETTINGS_BTN, 0.28, 18, Colors.CARD_BG_PRESSED if settings_down else Colors.CARD_BG)
    rl.draw_rectangle_rounded_lines_ex(SETTINGS_BTN, 0.28, 18, 2, rl.Color(255, 255, 255, 28))
    tint = Colors.BUTTON_PRESSED if settings_down else Colors.BUTTON_NORMAL
    rl.draw_texture(self._settings_img,
                    int(SETTINGS_BTN.x + (SETTINGS_BTN.width - self._settings_img.width) / 2),
                    int(SETTINGS_BTN.y + (SETTINGS_BTN.height - self._settings_img.height) / 2),
                    tint)

    # Home/Flag button
    flag_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, HOME_BTN)
    if ui_state.started:
      center_x = HOME_BTN.x + HOME_BTN.width / 2
      center_y = HOME_BTN.y + HOME_BTN.height / 2
      radius = min(HOME_BTN.width, HOME_BTN.height) * 0.5
      fill = Colors.BOOKMARK_BG_PRESSED if flag_pressed else Colors.BOOKMARK_BG
      tint = Colors.BUTTON_PRESSED if flag_pressed else Colors.BUTTON_NORMAL
      rl.draw_circle(int(center_x), int(center_y), radius, fill)
      self._draw_bookmark_icon(center_x, center_y, tint, fill)
    else:
      center_x = HOME_BTN.x + HOME_BTN.width / 2
      center_y = HOME_BTN.y + HOME_BTN.height / 2
      radius = min(HOME_BTN.width, HOME_BTN.height) * 0.47
      circle_color = Colors.BUTTON_PRESSED if mouse_down and rl.check_collision_point_rec(mouse_pos, HOME_BTN) else Colors.BUTTON_NORMAL
      rl.draw_circle(int(center_x), int(center_y), radius, circle_color)

      logo_x = center_x - self._konn3kt_home_logo.width / 2
      logo_y = center_y - self._konn3kt_home_logo.height / 2
      rl.draw_texture(self._konn3kt_home_logo, int(logo_x), int(logo_y), rl.WHITE)

    # Status indicators (right-anchored row): Live View (when streaming to konn3kt) sits to the LEFT
    # of the Microphone (when recording audio). Each shows independently. Mic keeps its tap target.
    slot_w, slot_h, gap = 70, 38, 12
    slot_y = rect.y + 240
    row_right = rect.x + rect.width - 36  # right edge of the rightmost slot
    indicators = []
    if self._live_streaming:
      indicators.append(("live", self._live_view_img))
    if self._recording_audio:
      indicators.append(("mic", self._mic_img))

    total_w = len(indicators) * slot_w + max(0, len(indicators) - 1) * gap
    slot_x = row_right - total_w
    for kind, img in indicators:
      slot = rl.Rectangle(slot_x, slot_y, slot_w, slot_h)
      icon_x = int(slot.x + (slot_w - img.width) / 2)
      icon_y = int(slot.y + (slot_h - img.height) / 2)
      if kind == "mic":
        self._mic_indicator_rect = slot
        mic_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, slot)
        tint = rl.Color(255, 255, 255, 150) if mic_pressed else rl.WHITE
        rl.draw_texture(img, icon_x, icon_y, tint)
      else:
        rl.draw_texture(img, icon_x, icon_y, rl.WHITE)
      slot_x += slot_w + gap

  def _draw_network_indicator(self, rect: rl.Rectangle):
    on_wifi = self._net_type == NETWORK_TYPES[NetworkType.wifi]
    net_text = current_ssid(on_wifi) or tr(self._net_type)
    icon_list = self._wifi_strength_icons if self._net_type in (NETWORK_TYPES[NetworkType.wifi], NETWORK_TYPES[NetworkType.ethernet]) else self._cell_strength_icons
    signal_icon = icon_list[min(self._net_strength, len(icon_list) - 1)]
    text_size = measure_text_cached(self._font_regular, net_text, 44)
    content_w = signal_icon.width + 14 + text_size.x

    icon_x = NETWORK_RECT.x + (NETWORK_RECT.width - content_w) / 2
    icon_y = NETWORK_RECT.y + (NETWORK_RECT.height - signal_icon.height) / 2
    rl.draw_texture(signal_icon, int(icon_x), int(icon_y), Colors.WHITE)

    text_x = icon_x + signal_icon.width + 14
    text_y = NETWORK_RECT.y + (NETWORK_RECT.height - text_size.y) / 2
    rl.draw_text_ex(self._font_regular, net_text, rl.Vector2(int(text_x), int(text_y)), 44, 0, rl.Color(215, 215, 215, 255))

  def _draw_metrics(self, rect: rl.Rectangle):
    metric_count = 3
    metrics_height = metric_count * METRIC_HEIGHT + (metric_count - 1) * CARD_GAP
    available_top = SETTINGS_BTN.y + SETTINGS_BTN.height
    available_height = HOME_BTN.y - available_top
    first_metric_y = available_top + max(0, (available_height - metrics_height) / 2)
    metrics = [
      (self._temp_status, first_metric_y),
      (self._panda_status, first_metric_y + METRIC_HEIGHT + CARD_GAP),
      (self._connect_status, first_metric_y + 2 * (METRIC_HEIGHT + CARD_GAP)),
    ]

    for metric, y_offset in metrics:
      self._draw_metric(rect, metric, rect.y + y_offset)

  def _draw_metric(self, rect: rl.Rectangle, metric: MetricData, y: float):
    metric_rect = rl.Rectangle(rect.x + METRIC_MARGIN, y, METRIC_WIDTH, METRIC_HEIGHT)
    rl.draw_rectangle_rounded(metric_rect, 0.28, 16, Colors.CARD_BG)
    rl.draw_rectangle_rounded_lines_ex(metric_rect, 0.28, 16, 2, Colors.METRIC_BORDER)

    dot_r = 11
    label = tr(metric.label)
    value = tr(metric.value)
    dot_x = metric_rect.x + STATUS_DOT_CENTER_X
    text_x = metric_rect.x + STATUS_TEXT_X
    text_col_w = metric_rect.width - STATUS_TEXT_X - STATUS_TEXT_RIGHT_MARGIN

    label_size = STATUS_LABEL_SIZE
    value_size = STATUS_VALUE_SIZE
    label_text_size = measure_text_cached(self._font_regular, label, label_size)
    value_text_size = measure_text_cached(self._font_bold, value, value_size)
    while value_text_size.x > text_col_w and value_size > 30:
      value_size -= 2
      value_text_size = measure_text_cached(self._font_bold, value, value_size)

    text_h = label_text_size.y + value_text_size.y + STATUS_LINE_GAP
    label_y = metric_rect.y + (metric_rect.height - text_h) / 2
    value_y = label_y + label_text_size.y + STATUS_LINE_GAP
    dot_y = label_y + text_h / 2
    rl.draw_circle(int(dot_x), int(dot_y), dot_r, metric.color)

    rl.begin_scissor_mode(int(text_x), int(metric_rect.y), int(text_col_w), int(metric_rect.height))
    rl.draw_text_ex(self._font_regular, label, rl.Vector2(int(text_x), int(label_y)), label_size, 0, rl.Color(185, 185, 190, 255))
    rl.draw_text_ex(self._font_bold, value, rl.Vector2(int(text_x), int(value_y)), value_size, 0, Colors.WHITE)
    rl.end_scissor_mode()

  def _draw_bookmark_icon(self, center_x: float, center_y: float, tint: rl.Color, cutout_color: rl.Color):
    icon_w = 78
    icon_h = 96
    icon_rect = rl.Rectangle(center_x - icon_w / 2, center_y - icon_h / 2, icon_w, icon_h)
    rl.draw_rectangle_rounded(icon_rect, 0.18, 14, tint)

    notch_top = icon_rect.y + icon_rect.height - 31
    notch_left = icon_rect.x + 10
    notch_right = icon_rect.x + icon_rect.width - 10
    notch_bottom = icon_rect.y + icon_rect.height
    rl.draw_triangle(
      rl.Vector2(center_x, notch_top),
      rl.Vector2(notch_left, notch_bottom),
      rl.Vector2(notch_right, notch_bottom),
      cutout_color,
    )
