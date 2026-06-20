"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import DrumMappedParamButton, DrumParamButton
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.scroller import Scroller

# ── Brightness options ─────────────────────────────────────────────────────────
# Index 0 = auto, 1 = auto dark, 2–21 = 5%..100% manual steps
ONROAD_BRIGHTNESS_OPTIONS = [
  "auto",
  "auto dark",
  "5%", "10%", "15%", "20%", "25%", "30%", "35%", "40%",
  "45%", "50%", "55%", "60%", "65%", "70%", "75%", "80%",
  "85%", "90%", "95%", "100%",
]

BRIGHTNESS_DELAY_OPTIONS  = ["15s", "30s", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "10m"]
BRIGHTNESS_DELAY_VALUES   = [15, 30, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600]

INTERACTIVITY_OPTIONS = ["default", "10s", "20s", "30s", "40s", "50s", "1m", "70s", "80s", "90s", "100s", "110s", "2m"]
INTERACTIVITY_VALUES  = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]


class DisplayLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()

    self._brightness_mode = DrumParamButton(
      "Onroad Brightness", "OnroadScreenOffBrightness", ONROAD_BRIGHTNESS_OPTIONS,
    )

    self._brightness_delay = DrumMappedParamButton(
      "Brightness Delay", "OnroadScreenOffTimer", BRIGHTNESS_DELAY_OPTIONS, BRIGHTNESS_DELAY_VALUES,
    )

    self._interactivity_timeout = DrumMappedParamButton(
      "Interactivity", "InteractivityTimeout", INTERACTIVITY_OPTIONS, INTERACTIVITY_VALUES,
    )

    self._scroller = Scroller([
      self._brightness_mode,
      self._brightness_delay,
      self._interactivity_timeout,
    ], snap_items=False)

    if back_callback:
      self.set_back_callback(back_callback)

  def _refresh_enabled(self):
    brightness_val = int(self._params.get("OnroadScreenOffBrightness", return_default=True) or 0)
    self._brightness_delay.set_enabled(brightness_val not in (0, 1))

  def show_event(self):
    super().show_event()
    self._brightness_mode.refresh()
    self._brightness_delay.refresh()
    self._interactivity_timeout.refresh()
    self._refresh_enabled()
    self._scroller.show_event()

  def _update_state(self):
    super()._update_state()
    self._refresh_enabled()

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
