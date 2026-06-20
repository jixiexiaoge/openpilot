"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Visuals settings for MICI (comma 4).
"""
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import DrumParamButton, NeonBigParamToggle
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.scroller import Scroller

CHEVRON_OPTIONS = ["off", "distance", "speed", "time", "all"]
DEV_UI_OPTIONS  = ["off", "bottom", "right", "right+bottom"]


class VisualsLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()

    # Bool toggles
    self._blind_spot   = NeonBigParamToggle("Blind Spot Warnings", "BlindSpot")
    self._steering_arc = NeonBigParamToggle("Steering Arc",        "TorqueBar")
    self._road_name    = NeonBigParamToggle("Road Name",           "RoadNameToggle")
    self._turn_signals = NeonBigParamToggle("Turn Signals",        "ShowTurnSignals")
    self._accel_bar    = NeonBigParamToggle("Acceleration Bar",    "RocketFuel")

    # Multi-option selectors — drum picker
    self._chevron_info = DrumParamButton("Chevron Info", "ChevronInfo", CHEVRON_OPTIONS)
    self._dev_ui       = DrumParamButton("Dev UI",       "DevUIInfo",   DEV_UI_OPTIONS)

    self._scroller = Scroller([
      self._blind_spot,
      self._steering_arc,
      self._road_name,
      self._turn_signals,
      self._accel_bar,
      self._chevron_info,
      self._dev_ui,
    ], snap_items=False)

    if back_callback:
      self.set_back_callback(back_callback)

  def show_event(self):
    super().show_event()
    self._blind_spot.refresh()
    self._steering_arc.refresh()
    self._road_name.refresh()
    self._turn_signals.refresh()
    self._accel_bar.refresh()
    self._chevron_info.refresh()
    self._dev_ui.refresh()
    self._scroller.show_event()

  def _update_state(self):
    super()._update_state()
    # ChevronInfo is only meaningful when longitudinal control is active.
    # We use AlphaLongitudinalEnabled (a real openpilot param) rather than
    # the non-existent "LongitudinalControl" key that caused crashes on device.
    long_active = self._params.get_bool("AlphaLongitudinalEnabled")
    self._chevron_info.set_enabled(long_active)

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
