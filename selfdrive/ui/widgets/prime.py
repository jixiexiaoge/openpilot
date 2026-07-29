import pyray as rl
import time
import json

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label


class PrimeWidget(Widget):
  """Widget for displaying Konn3kt pairing status"""

  PRIME_BG_COLOR = rl.Color(51, 51, 51, 255)
  KONN3KT_ONLINE_NS = 80_000_000_000  # 80 seconds in nanoseconds
  TRIPS_PARAM_KEY = "ApiCache_DriveStats"

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._icon_distance = gui_app.texture("icons/road.png", 58, 58, keep_aspect_ratio=True)
    self._icon_drives = gui_app.texture("icons_mici/wheel.png", 52, 52, keep_aspect_ratio=True)
    self._icon_hours = gui_app.texture("../../iqpilot/selfdrive/assets/icons/clock.png", 52, 52, keep_aspect_ratio=True)

  def _render(self, rect):
    if ui_state.prime_state.is_paired():
      self._render_for_paired_user(rect)
    else:
      self._render_for_unpaired_users(rect)

  def _is_konn3kt_online(self) -> bool:
    last_ping = ui_state.sm['deviceState'].lastAthenaPingTime
    return last_ping != 0 and (time.monotonic_ns() - last_ping) < self.KONN3KT_ONLINE_NS

  def _render_for_unpaired_users(self, rect: rl.Rectangle):
    """Renders the pairing prompt for unpaired users."""

    rl.draw_rectangle_rounded(rect, 0.025, 10, self.PRIME_BG_COLOR)

    # Layout
    x, y = rect.x + 80, rect.y + 90
    w = rect.width - 160

    # Title
    gui_label(rl.Rectangle(x, y, w, 90), tr("Pair Your Device"), 75, font_weight=FontWeight.BOLD)

    # Description with wrapping
    desc_y = y + 140
    font = gui_app.font(FontWeight.NORMAL)
    wrapped_text = "\n".join(wrap_text(font, tr("Pair your device in the Konn3kt app"), 56, int(w)))
    text_size = measure_text_cached(font, wrapped_text, 56)
    rl.draw_text_ex(font, wrapped_text, rl.Vector2(x, desc_y), 56, 0, rl.WHITE)

    # Features section
    features_y = desc_y + text_size.y + 50
    gui_label(rl.Rectangle(x, features_y, w, 50), tr("Konn3kt Features:"), 41, font_weight=FontWeight.BOLD)

    # Feature list
    features = [tr("Remote access"), tr("Live streaming"), tr("Unlimited route storage"), tr("And so much more")]
    for i, feature in enumerate(features):
      item_y = features_y + 80 + i * 65
      gui_label(rl.Rectangle(x, item_y, 100, 60), "✓", 50, color=rl.Color(70, 91, 234, 255))
      gui_label(rl.Rectangle(x + 60, item_y, w - 60, 60), feature, 50)

  def _render_for_paired_user(self, rect: rl.Rectangle):
    """Renders the paired status widget."""

    status_card_height = 188
    trips_spacing = 12
    trips_y = rect.y + status_card_height + trips_spacing
    trips_height = max(0, rect.height - status_card_height - trips_spacing)

    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, status_card_height), 0.1, 10, self.PRIME_BG_COLOR)

    x = rect.x + 56
    y = rect.y + 26

    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, tr("Konn3kt"), rl.Vector2(x, y), 72, 0, rl.WHITE)

    status_label = tr("Konn3kt Status:")
    status_font = gui_app.font(FontWeight.NORMAL)
    status_font_size = 46
    status_pos = rl.Vector2(x, y + 84)
    rl.draw_text_ex(status_font, status_label, status_pos, status_font_size, 0, rl.WHITE)

    status_size = measure_text_cached(status_font, status_label, status_font_size)
    is_online = self._is_konn3kt_online()
    status_color = rl.Color(134, 255, 78, 255) if is_online else rl.Color(201, 34, 49, 255)

    dot_x = int(status_pos.x + status_size.x + 26)
    dot_y = int(status_pos.y + status_size.y / 2)
    rl.draw_circle(dot_x, dot_y, 14, status_color)
    if trips_height > 0:
      self._render_all_time_stats(rl.Rectangle(rect.x, trips_y, rect.width, trips_height))

  def _get_all_time_stats(self) -> dict:
    raw_stats = self._params.get(self.TRIPS_PARAM_KEY)
    if not raw_stats:
      return {}

    if isinstance(raw_stats, dict):
      stats = raw_stats
    elif isinstance(raw_stats, (bytes, bytearray)):
      try:
        stats = json.loads(raw_stats.decode("utf-8"))
      except Exception:
        return {}
    elif isinstance(raw_stats, str):
      try:
        stats = json.loads(raw_stats)
      except Exception:
        return {}
    else:
      return {}

    return stats.get("all", {}) if isinstance(stats.get("all", {}), dict) else {}

  def _render_all_time_stats(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.05, 10, rl.Color(30, 30, 30, 255))

    stats = self._get_all_time_stats()
    is_metric = self._params.get_bool("IsMetric")

    routes = int(stats.get("routes", 0))
    distance = float(stats.get("distance", 0))
    distance_val = int(distance * CV.MPH_TO_KPH) if is_metric else int(distance)
    hours = int(float(stats.get("minutes", 0)) / 60.0)

    title_font = gui_app.font(FontWeight.BOLD)
    title_size = 52
    title_y = rect.y + 20
    rl.draw_text_ex(title_font, tr("ALL TIME"), rl.Vector2(rect.x + 36, title_y), title_size, 0, rl.Color(228, 228, 228, 255))

    header_line_y = rect.y + 82
    rl.draw_line_ex(
      rl.Vector2(rect.x + 28, header_line_y),
      rl.Vector2(rect.x + rect.width - 28, header_line_y),
      2,
      rl.Color(95, 95, 95, 150),
    )

    inner_rect = rl.Rectangle(rect.x + 22, rect.y + 94, rect.width - 44, rect.height - 116)
    rl.draw_rectangle_rounded(inner_rect, 0.04, 10, rl.Color(26, 26, 31, 255))

    # Center a compact stats block within the inner area.
    group_height = min(220, max(180, inner_rect.height - 16))
    base_y = inner_rect.y + max(0.0, (inner_rect.height - group_height) / 2.0)

    col_width = inner_rect.width / 3
    number_font = gui_app.font(FontWeight.BOLD)
    number_size = 74
    unit_font = gui_app.font(FontWeight.LIGHT)
    unit_size = 48
    unit_color = rl.Color(170, 170, 170, 255)

    for i in (1, 2):
      line_x = inner_rect.x + (col_width * i)
      rl.draw_line_ex(rl.Vector2(line_x, base_y + 8), rl.Vector2(line_x, base_y + group_height - 10), 2, rl.Color(82, 82, 86, 160))

    def draw_col(col_idx: int, icon, value: str, unit: str):
      col_x = inner_rect.x + (col_width * col_idx)
      center_x = col_x + (col_width / 2)

      icon_x = int(center_x - (icon.width / 2))
      rl.draw_texture(icon, icon_x, int(base_y + 12), rl.WHITE)

      val_size = measure_text_cached(number_font, value, number_size)
      val_x = center_x - (val_size.x / 2)
      rl.draw_text_ex(number_font, value, rl.Vector2(val_x, base_y + 86), number_size, 0, rl.WHITE)

      unit_size_vec = measure_text_cached(unit_font, unit, unit_size)
      unit_x = center_x - (unit_size_vec.x / 2)
      rl.draw_text_ex(unit_font, unit, rl.Vector2(unit_x, base_y + 168), unit_size, 0, unit_color)

    draw_col(0, self._icon_drives, str(routes), tr("Drives"))
    draw_col(1, self._icon_distance, str(distance_val), tr("KM") if is_metric else tr("Miles"))
    draw_col(2, self._icon_hours, str(hours), tr("Hours"))
