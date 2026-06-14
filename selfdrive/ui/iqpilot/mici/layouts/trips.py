"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Trips / drive statistics for MICI (comma 4). All-time stats only.
"""
import threading
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import Scroller

try:
  from openpilot.selfdrive.ui.iqpilot.layouts.settings.trips import fetch_drive_stats
except ImportError:
  fetch_drive_stats = None


class _NeonStatCard(NeonBigButton):
  def __init__(self, label: str):
    super().__init__("—", chips=[label])
  def set_value(self, value: str):
    self._title_text = value
    self._label.set_text(value)
class TripsLayoutMici(NavWidget):
  PAD = 20

  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params  = Params()
    self._loading = False
    self._stats: dict | None = None
    self._drives_card   = _NeonStatCard("drives")
    self._distance_card = _NeonStatCard("distance")
    self._hours_card    = _NeonStatCard("hours")
    self._refresh_btn = NeonBigButton("refresh")
    self._refresh_btn.set_click_callback(self._start_fetch)
    self._status_label = UnifiedLabel(
      "loading...", 36, FontWeight.ROMAN,
      rl.Color(255, 255, 255, int(255 * 0.35)),
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE,
    )
    self._scroller = Scroller(
      [self._drives_card, self._distance_card, self._hours_card, self._refresh_btn],
      snap_items=False,
    )
    if back_callback:
      self.set_back_callback(back_callback)
  def _start_fetch(self):
    if self._loading or fetch_drive_stats is None:
      return
    self._loading = True
    self._stats = None
    self._status_label.set_text("loading...")

    def _fetch():
      try:
        self._stats = fetch_drive_stats()
      except Exception:
        self._stats = {}
      finally:
        self._loading = False
        self._update_display()

    threading.Thread(target=_fetch, daemon=True).start()

  def _is_metric(self) -> bool:
    return self._params.get_bool("IsMetric", False)

  def _update_display(self):
    if not self._stats:
      self._status_label.set_text("no data")
      return
    drives = self._stats.get("routes", 0)
    if self._is_metric():
      dist_str = f"{self._stats.get('distance_km', 0.0):,.0f} km"
    else:
      dist_str = f"{self._stats.get('distance_mi', 0.0):,.0f} mi"
    hours = self._stats.get("hours", 0.0)
    self._drives_card.set_value(f"{drives:,}")
    self._distance_card.set_value(dist_str)
    self._hours_card.set_value(f"{hours:.1f}h")
    self._status_label.set_text("")

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._start_fetch()

  def _render(self, rect: rl.Rectangle):
    if self._loading or not self._stats:
      # Centred status text + refresh button pinned to bottom-right
      self._status_label.render(rect)
      btn_w = self._refresh_btn._rect.width
      btn_h = self._refresh_btn._rect.height
      self._refresh_btn.render(rl.Rectangle(
        rect.x + (rect.width - btn_w) / 2,
        rect.y + rect.height - btn_h - self.PAD,
        btn_w, btn_h,
      ))
      return

    self._scroller.render(rect)
