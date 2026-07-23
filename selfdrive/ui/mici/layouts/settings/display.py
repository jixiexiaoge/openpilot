"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from openpilot.selfdrive.ui.mici.layouts.settings.iq_widgets import MappedParamToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.widgets.scroller import NavScroller

_DISPLAY_BRIGHT_OPTIONS = ["default"] + [f"{p}%" for p in range(5, 101, 5)]
_DISPLAY_BRIGHT_VALUES = [0] + list(range(5, 101, 5))

_ONROAD_BRIGHT_OPTIONS = ["auto", "auto dark"] + [f"{p}%" for p in range(5, 101, 5)]
_ONROAD_BRIGHT_VALUES = list(range(len(_ONROAD_BRIGHT_OPTIONS)))

_DELAY_OPTIONS = ["15s", "30s", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "10m"]
_DELAY_VALUES = [15, 30, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600]

_INTERACT_OPTIONS = ["default", "10s", "20s", "30s", "40s", "50s", "1m", "70s", "80s", "90s", "100s", "110s", "2m"]
_INTERACT_VALUES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]


class DisplayLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._force_mici = BigParamControl("force mici UI", "ForceSmallUI")
    self._display_bright = MappedParamToggle("display brightness", "Brightness",
                                             _DISPLAY_BRIGHT_OPTIONS, _DISPLAY_BRIGHT_VALUES)
    self._onroad_bright = MappedParamToggle("onroad brightness", "OnroadScreenOffBrightness",
                                            _ONROAD_BRIGHT_OPTIONS, _ONROAD_BRIGHT_VALUES)
    self._delay = MappedParamToggle("brightness delay", "OnroadScreenOffTimer",
                                    _DELAY_OPTIONS, _DELAY_VALUES)
    self._interact = MappedParamToggle("interactivity", "InteractivityTimeout",
                                       _INTERACT_OPTIONS, _INTERACT_VALUES)

    self._items = [self._display_bright, self._onroad_bright, self._delay, self._interact]
    if HARDWARE.get_device_type() != "mici":
      self._items.insert(0, self._force_mici)
    self._scroller.add_widgets(self._items)

  def _refresh(self):
    for w in self._items:
      w.refresh()
    bval = int(float(ui_state.params.get("OnroadScreenOffBrightness", return_default=True) or 0))
    self._delay.set_enabled(bval not in (0, 1))

  def _update_state(self):
    super()._update_state()
    bval = int(float(ui_state.params.get("OnroadScreenOffBrightness", return_default=True) or 0))
    self._delay.set_enabled(bval not in (0, 1))

  def show_event(self):
    super().show_event()
    self._refresh()
