"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from openpilot.system.ui.widgets.scroller import NavScroller


class VisualsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._blind_spot = BigParamControl("Blind Spot Warnings", "BlindSpot")
    self._steering_arc = BigParamControl("Steering Arc", "TorqueBar")
    self._road_name = BigParamControl("Road Name", "RoadNameToggle")
    self._turn_signals = BigParamControl("Turn Signals", "ShowTurnSignals")
    self._accel_bar = BigParamControl("Acceleration Bar", "RocketFuel")

    self._toggles = [self._blind_spot, self._steering_arc, self._road_name,
                     self._turn_signals, self._accel_bar]
    self._scroller.add_widgets(self._toggles)

  def show_event(self):
    super().show_event()
    for w in self._toggles:
      w.refresh()
