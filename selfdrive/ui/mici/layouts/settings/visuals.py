"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from openpilot.system.ui.widgets.scroller import NavScroller


class VisualsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._blind_spot = BigParamControl("Blind Spot Warnings", "IQBlindSpotAlerts")
    self._steering_arc = BigParamControl("Steering Effort Arc", "IQSteerEffortArc")
    self._road_name = BigParamControl("Road Name", "IQRoadNameOverlay")
    self._turn_signals = BigParamControl("Turn Signals", "IQBlinkerIndicators")
    self._accel_bar = BigParamControl("Acceleration Bar", "IQAccelMeter")

    self._toggles = [self._blind_spot, self._steering_arc, self._road_name,
                     self._turn_signals, self._accel_bar]
    self._scroller.add_widgets(self._toggles)

  def show_event(self):
    super().show_event()
    for w in self._toggles:
      w.refresh()
