"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from cereal import car
from openpilot.common.params import Params
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import AutoLaneChangeMode
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigParamControl
from openpilot.selfdrive.ui.mici.layouts.settings.iq_widgets import MappedParamToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


class SabBrakeToggle(BigParamControl):
  """Driver-intervention toggle backed by AolSteeringMode == 2."""
  def __init__(self):
    super().__init__("Driver Intervention Handling", "AolEnabled")

  def refresh(self):
    self.set_checked(int(self.params.get("AolSteeringMode", return_default=True)) == 2)

  def _handle_mouse_release(self, mouse_pos):
    super(BigParamControl, self)._handle_mouse_release(mouse_pos)
    enabled = self._checked
    current_mode = int(self.params.get("AolSteeringMode", return_default=True))
    if enabled:
      self.params.put("AolSteeringMode", 2)
    elif current_mode == 2:
      self.params.put("AolSteeringMode", 1)


def _has_limited_sab_options() -> bool:
  brand = ""
  if ui_state.is_offroad():
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      brand = bundle.get("brand", "")
  if not brand:
    brand = ui_state.CP.brand if ui_state.CP else ""
  return brand == "rivian"


class SabSettingsPanel(NavScroller):
  def __init__(self):
    super().__init__()
    self._main_cruise = BigParamControl("Availability While Cruise Changes", "AolMainCruiseAllowed")
    self._brake = SabBrakeToggle()
    self._mode = MappedParamToggle("Brake Response Mode", "AolSteeringMode",
                                   ["remain active", "standby", "disengage"], [0, 1, 2])
    self._scroller.add_widgets([self._main_cruise, self._brake, self._mode])

  def show_event(self):
    super().show_event()
    limited = _has_limited_sab_options()
    if limited:
      ui_state.params.remove("AolMainCruiseAllowed")
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)
      ui_state.params.put("AolSteeringMode", 2)
    offroad = ui_state.is_offroad()
    for w in (self._main_cruise, self._brake, self._mode):
      w.refresh()
      w.set_enabled(offroad and not limited)


class LaneChangePanel(NavScroller):
  def __init__(self):
    super().__init__()
    self._timer = MappedParamToggle("Auto Lane Change", "AutoLaneChangeTimer",
                                    ["off", "nudge", "nudgeless", "0.5 s", "1 s", "2 s", "3 s"],
                                    [-1, 0, 1, 2, 3, 4, 5])
    self._bsm_delay = BigParamControl("Delay with Blind Spot", "AutoLaneChangeBsmDelay")
    self._continuous = BigParamControl("Continuous Changes", "LaneChangeContinuous")
    self._scroller.add_widgets([self._timer, self._bsm_delay, self._continuous])

  def show_event(self):
    super().show_event()
    self._timer.refresh()
    enable_bsm = bool(ui_state.CP and ui_state.CP.enableBsm)
    if not enable_bsm and ui_state.params.get_bool("AutoLaneChangeBsmDelay"):
      ui_state.params.remove("AutoLaneChangeBsmDelay")
    self._bsm_delay.refresh()
    self._bsm_delay.set_enabled(
      enable_bsm and int(ui_state.params.get("AutoLaneChangeTimer", return_default=True)) > AutoLaneChangeMode.NUDGE
    )
    self._continuous.refresh()


class SteeringLayoutMici(NavScroller):
  _AOL_MODES = ["remain active", "standby", "disengage"]

  def __init__(self):
    super().__init__()

    self._sab_panel = SabSettingsPanel()
    self._lc_panel = LaneChangePanel()

    self._aol = BigParamControl("AOL", "AolEnabled", toggle_callback=self._on_aol_toggled)
    self._sab_settings_button = BigButton("steering assistance behavior")
    self._sab_settings_button.set_click_callback(lambda: gui_app.push_widget(self._sab_panel))
    self._lane_change = BigButton("lane change")
    self._lane_change.set_click_callback(lambda: gui_app.push_widget(self._lc_panel))
    self._nnff = BigParamControl("Neural Net FF", "NeuralNetworkFeedForward", toggle_callback=self._on_nnff_toggled)

    self._scroller.add_widgets([
      self._aol, self._sab_settings_button, self._lane_change,
      self._nnff,
    ])

  def _aol_mode_str(self) -> str:
    try:
      return self._AOL_MODES[int(ui_state.params.get("AolSteeringMode", return_default=True))]
    except (TypeError, ValueError, IndexError):
      return self._AOL_MODES[0]

  def _on_aol_toggled(self, checked: bool):
    if checked:
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)

  def _on_nnff_toggled(self, checked: bool):
    return None

  def _refresh(self):
    offroad = ui_state.is_offroad()
    self._aol.refresh()
    self._aol.set_value(self._aol_mode_str())
    self._nnff.refresh()

    steering_supported = (ui_state.CP is not None and
                          ui_state.CP.steerControlType != car.CarParams.SteerControlType.angle)
    if not steering_supported:
      ui_state.params.remove("NeuralNetworkFeedForward")
      self._nnff.refresh()

    self._aol.set_enabled(offroad)
    self._sab_settings_button.set_enabled(offroad and self._aol._checked)
    self._nnff.set_enabled(offroad and steering_supported)

  def _update_state(self):
    super()._update_state()
    self._refresh()

  def show_event(self):
    super().show_event()
    self._refresh()
