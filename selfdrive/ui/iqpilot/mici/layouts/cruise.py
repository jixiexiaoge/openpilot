"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Cruise control settings for MICI (comma 4).
Matches BIG UI CruiseLayout feature parity.
"""
import time
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import (
  DrumFloatMappedParamButton, DrumMappedParamButton, DrumParamButton,
  NeonBigButton, NeonBigParamToggle,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import NavWidget, Widget
from openpilot.system.ui.widgets.scroller import Scroller

FOLLOW_DISTANCE_OPTIONS = ["aggressive", "standard", "relaxed", "stock"]
FOLLOW_DISTANCE_VALUES  = [0, 1, 2, 3]

MS_TO_MPH = 2.23694
_SPEED_MPH = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
_SPEED_OPTIONS = [f"{s} mph" for s in _SPEED_MPH]
_SPEED_VALUES = [round(s / MS_TO_MPH, 2) for s in _SPEED_MPH]

_LEAD_SPEED_MPH = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85]
_LEAD_SPEED_OPTIONS = [f"{s} mph" for s in _LEAD_SPEED_MPH]
_LEAD_SPEED_VALUES = [round(s / MS_TO_MPH, 2) for s in _LEAD_SPEED_MPH]

_STOP_TIME_OPTIONS = ["1.0s", "1.5s", "2.0s", "2.5s", "3.0s", "3.5s", "4.0s", "4.5s", "5.0s", "5.5s", "6.0s"]
_STOP_TIME_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]

_LOOKAHEAD_OPTIONS = ["1.0s", "2.0s", "3.0s", "4.0s", "5.0s", "6.0s", "7.0s", "8.0s", "9.0s", "10.0s"]
_LOOKAHEAD_VALUES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]

DOUBLE_TAP_THRESHOLD = 0.4


class DoubleTapToggle(NeonBigParamToggle):
  """NeonBigParamToggle that defers the single-tap toggle to distinguish from double-tap."""

  def __init__(self, title, param, double_tap_callback=None, **kwargs):
    super().__init__(title, param, **kwargs)
    self._double_tap_callback = double_tap_callback
    self._pending_tap_time = 0.0
    self._pending_mouse_pos = None

  def _handle_mouse_release(self, mouse_pos):
    now = time.monotonic()
    if self._pending_mouse_pos is not None and now - self._pending_tap_time < DOUBLE_TAP_THRESHOLD:
      self._pending_mouse_pos = None
      self._pending_tap_time = 0.0
      if self._double_tap_callback:
        self._double_tap_callback()
      return
    self._pending_tap_time = now
    self._pending_mouse_pos = mouse_pos

  def _update_state(self):
    super()._update_state()
    if self._pending_mouse_pos is not None and time.monotonic() - self._pending_tap_time >= DOUBLE_TAP_THRESHOLD:
      super()._handle_mouse_release(self._pending_mouse_pos)
      self._pending_mouse_pos = None


class CruiseLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()
    self._original_back_callback = back_callback

    # ── Main controls ────────────────────────────────────────────────────────
    self._experimental = NeonBigParamToggle(
      "Experimental Mode", "ExperimentalMode",
      toggle_callback=self._on_experimental_toggled,
    )

    self._dynamic = DoubleTapToggle(
      "IQ Dynamic Mode", "IQDynamicMode",
      double_tap_callback=self._show_dynamic_settings,
    )

    self._follow_dist = DrumMappedParamButton(
      "Follow Distance", "LongitudinalPersonality",
      FOLLOW_DISTANCE_OPTIONS, FOLLOW_DISTANCE_VALUES,
    )

    self._speed_limit = DrumParamButton(
      "Speed Limit Mode", "SpeedLimitMode",
      ["off", "info", "warning", "control"],
    )

    self._slc_settings_btn = NeonBigButton("speed limit settings")
    self._slc_settings_btn.set_click_callback(self._show_slc_settings)

    self._main_items: list[Widget] = [
      self._experimental,
      self._dynamic,
      self._follow_dist,
      self._speed_limit,
      self._slc_settings_btn,
    ]

    # ── IQ Dynamic sub-panel ─────────────────────────────────────────────────
    self._dyn_curves       = NeonBigParamToggle("IQ.Dynamic Curves",       "IQDynamicConditionalCurves")
    self._dyn_slower_lead  = NeonBigParamToggle("IQ.Dynamic Slower Lead",  "IQDynamicConditionalSlowerLead")
    self._dyn_stopped_lead = NeonBigParamToggle("IQ.Dynamic Stopped Lead", "IQDynamicConditionalStoppedLead")
    self._dyn_model_stops  = NeonBigParamToggle("IQ.Dynamic Model Stops",  "IQDynamicConditionalModelStops")
    self._dyn_slc_fallback = NeonBigParamToggle("IQ.Dynamic SLC Fallback", "IQDynamicConditionalSLCFallback")
    self._force_stops      = NeonBigParamToggle("IQ Force Stops",          "IQForceStops")

    self._dyn_low_speed = DrumFloatMappedParamButton(
      "IQ.Dynamic Low Speed", "IQDynamicConditionalSpeed",
      _SPEED_OPTIONS, _SPEED_VALUES,
    )
    self._dyn_lead_speed = DrumFloatMappedParamButton(
      "IQ.Dynamic Lead Speed", "IQDynamicConditionalLeadSpeed",
      _LEAD_SPEED_OPTIONS, _LEAD_SPEED_VALUES,
    )
    self._dyn_stop_time = DrumFloatMappedParamButton(
      "Model Stop Time", "IQDynamicModelStopTime",
      _STOP_TIME_OPTIONS, _STOP_TIME_VALUES,
    )

    self._dynamic_items: list[Widget] = [
      self._dyn_curves,
      self._dyn_slower_lead,
      self._dyn_stopped_lead,
      self._dyn_model_stops,
      self._dyn_slc_fallback,
      self._dyn_low_speed,
      self._dyn_lead_speed,
      self._dyn_stop_time,
      self._force_stops,
    ]

    # ── Speed Limit sub-panel ────────────────────────────────────────────────
    self._slc_policy = DrumMappedParamButton(
      "SLC Policy", "SLCPolicy",
      ["map only", "map priority", "combined"], [0, 1, 2],
    )
    self._slc_override = DrumMappedParamButton(
      "SLC Override", "SLCOverrideMethod",
      ["manual", "set speed"], [0, 1],
    )
    self._slc_confirm_higher  = NeonBigParamToggle("SLC Confirm Higher",  "SpeedLimitConfirmationHigher")
    self._slc_confirm_lower   = NeonBigParamToggle("SLC Confirm Lower",   "SpeedLimitConfirmationLower")
    self._slc_auto_confirm    = NeonBigParamToggle("SLC Auto Confirm",    "SLCAutoConfirm")
    self._slc_fb_set_speed    = NeonBigParamToggle("SLC Fallback Set Speed",    "SLCFallbackSetSpeed")
    self._slc_fb_previous     = NeonBigParamToggle("SLC Fallback Previous",     "SLCFallbackPreviousSpeedLimit")
    self._slc_fb_experimental = NeonBigParamToggle("SLC Fallback Experimental", "SLCFallbackExperimentalMode")
    self._slc_mapbox          = NeonBigParamToggle("SLC Mapbox Filler",         "SLCMapboxFiller")
    self._slc_lookahead_higher = DrumFloatMappedParamButton(
      "Map Lookahead Higher", "MapSpeedLookaheadHigher",
      _LOOKAHEAD_OPTIONS, _LOOKAHEAD_VALUES,
    )
    self._slc_lookahead_lower = DrumFloatMappedParamButton(
      "Map Lookahead Lower", "MapSpeedLookaheadLower",
      _LOOKAHEAD_OPTIONS, _LOOKAHEAD_VALUES,
    )

    self._slc_items: list[Widget] = [
      self._slc_policy,
      self._slc_override,
      self._slc_confirm_higher,
      self._slc_confirm_lower,
      self._slc_auto_confirm,
      self._slc_fb_set_speed,
      self._slc_fb_previous,
      self._slc_fb_experimental,
      self._slc_mapbox,
      self._slc_lookahead_higher,
      self._slc_lookahead_lower,
    ]

    # ── Scroller (shared, items swapped per sub-panel) ───────────────────────
    self._scroller = Scroller(self._main_items, snap_items=False)

    if back_callback:
      self.set_back_callback(back_callback)

  # ── Toggle callbacks ────────────────────────────────────────────────────────

  def _on_experimental_toggled(self, checked: bool):
    if checked:
      self._params.put_bool("IQDynamicMode", False)
      self._dynamic.refresh()

  # ── Sub-panel navigation ────────────────────────────────────────────────────

  def _show_sub_panel(self, items: list, back_fn: Callable):
    self._scroller._items = items
    self._scroller.scroll_panel.set_offset(0)
    self.set_back_callback(back_fn)

  def _show_main(self):
    self._scroller._items = self._main_items
    self._scroller.scroll_panel.set_offset(0)
    self.set_back_callback(self._original_back_callback)
    self._refresh_main()

  def _show_dynamic_settings(self):
    for item in self._dynamic_items:
      if hasattr(item, 'refresh'):
        item.refresh()
    self._show_sub_panel(self._dynamic_items, self._show_main)

  def _show_slc_settings(self):
    for item in self._slc_items:
      if hasattr(item, 'refresh'):
        item.refresh()
    self._show_sub_panel(self._slc_items, self._show_main)

  # ── State ──────────────────────────────────────────────────────────────────

  def _refresh_main(self):
    self._experimental.refresh()
    self._dynamic.refresh()
    self._follow_dist.refresh()
    self._speed_limit.refresh()

  def show_event(self):
    super().show_event()
    self._scroller._items = self._main_items
    self.set_back_callback(self._original_back_callback)
    self._refresh_main()
    self._scroller.show_event()

  def _update_state(self):
    super()._update_state()

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
