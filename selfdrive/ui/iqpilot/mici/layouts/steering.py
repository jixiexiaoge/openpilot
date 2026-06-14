"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections.abc import Callable

import pyray as rl
from cereal import car

from openpilot.common.params import Params
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import AutoLaneChangeMode
from openpilot.selfdrive.ui.mici.widgets.button import (
  DrumMappedParamButton, NeonBigButton, NeonBigParamToggle,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.scroller import Scroller


class AolBrakeToggle(NeonBigParamToggle):
  """Disengage-on-Brake toggle backed by AolSteeringMode == 2."""

  def __init__(self):
    super().__init__("Disengage on Brake", "AolEnabled")

  def refresh(self):
    self._checked = int(self._params.get("AolSteeringMode", return_default=True)) == 2
    self._rebuild_chips()

  def _handle_mouse_release(self, mouse_pos):
    # Skip NeonBigParamToggle's param write; handle manually
    super(NeonBigParamToggle, self)._handle_mouse_release(mouse_pos)  # type: ignore[arg-type]
    enabled = not self._checked
    self._checked = enabled
    current_mode = int(self._params.get("AolSteeringMode", return_default=True))
    if enabled:
      self._params.put("AolSteeringMode", 2)
    elif current_mode == 2:
      self._params.put("AolSteeringMode", 1)


class SteeringLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()
    self._original_back_callback = back_callback

    # ── Main controls ────────────────────────────────────────────────────────
    self._aol_btn = NeonBigParamToggle(
      "AOL",
      "AolEnabled",
      sub_chips=self._get_aol_sub_chips(),
      toggle_callback=self._on_aol_toggled,
    )

    self._aol_settings_btn = NeonBigButton("aol settings")
    self._aol_settings_btn.set_click_callback(self._show_aol_settings)

    self._lane_change_btn = NeonBigButton("lane change")
    self._lane_change_btn.set_click_callback(self._show_lane_change_settings)

    self._torque_ctrl = NeonBigParamToggle(
      "Torque Auto Tune", "EnforceTorqueControl",
      toggle_callback=self._on_torque_toggled,
    )

    self._torque_settings_btn = NeonBigButton("torque settings")
    self._torque_settings_btn.set_click_callback(self._show_torque_settings)

    self._nnff_ctrl = NeonBigParamToggle(
      "Neural Net FF", "NeuralNetworkFeedForward",
      toggle_callback=self._on_nnff_toggled,
    )

    self._main_items = [
      self._aol_btn,
      self._aol_settings_btn,
      self._lane_change_btn,
      self._torque_ctrl,
      self._torque_settings_btn,
      self._nnff_ctrl,
    ]

    # ── AOL settings sub-panel ───────────────────────────────────────────────
    self._aol_main_cruise       = NeonBigParamToggle("Toggle with Main Cruise", "AolMainCruiseAllowed")
    self._aol_disengage_on_brake = AolBrakeToggle()
    self._aol_steering_mode     = DrumMappedParamButton(
      "Steering Mode",
      "AolSteeringMode",
      ["remain active", "pause", "disengage"],
      [0, 1, 2],
    )
    self._aol_items = [
      self._aol_main_cruise,
      self._aol_disengage_on_brake,
      self._aol_steering_mode,
    ]

    # ── Lane change sub-panel ────────────────────────────────────────────────
    self._lc_timer = DrumMappedParamButton(
      "Auto Lane Change",
      "AutoLaneChangeTimer",
      ["off", "nudge", "nudgeless", "0.5 s", "1 s", "2 s", "3 s"],
      [-1, 0, 1, 2, 3, 4, 5],
    )
    self._lc_bsm_delay = NeonBigParamToggle("Delay with Blind Spot", "AutoLaneChangeBsmDelay")
    self._lc_items = [
      self._lc_timer,
      self._lc_bsm_delay,
    ]

    # ── Torque settings sub-panel ────────────────────────────────────────────
    self._torque_self_tune    = NeonBigParamToggle("Self Tune",               "LiveTorqueParamsToggle")
    self._torque_relaxed_tune = NeonBigParamToggle("Relaxed Self Tune",       "LiveTorqueParamsRelaxedToggle")
    self._torque_custom_tune  = NeonBigParamToggle("Enable Custom Tuning",    "CustomTorqueParams")
    self._torque_manual_rt    = NeonBigParamToggle("Manual Real-Time Tuning", "TorqueParamsOverrideEnabled")
    self._torque_items = [
      self._torque_self_tune,
      self._torque_relaxed_tune,
      self._torque_custom_tune,
      self._torque_manual_rt,
    ]

    # ── Scroller (shared, items swapped per sub-panel) ───────────────────────
    self._scroller = Scroller(self._main_items, snap_items=False)

    if back_callback:
      self.set_back_callback(back_callback)

  # ── Sub-chip helpers ────────────────────────────────────────────────────────

  def _get_aol_sub_chips(self) -> list[str]:
    modes = ["remain active", "pause", "disengage"]
    try:
      mode = int(self._params.get("AolSteeringMode", return_default=True))
      return [modes[mode]]
    except (TypeError, ValueError, IndexError):
      return [modes[0]]

  # ── Toggle callbacks ────────────────────────────────────────────────────────

  def _on_aol_toggled(self, checked: bool):
    if checked:
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)
    self._aol_btn.set_sub_chips(self._get_aol_sub_chips())

  def _on_torque_toggled(self, checked: bool):
    if checked:
      ui_state.params.put_bool("NeuralNetworkFeedForward", False)
    self._refresh_main_controls()

  def _on_nnff_toggled(self, checked: bool):
    if checked:
      ui_state.params.put_bool("EnforceTorqueControl", False)
    self._refresh_main_controls()

  # ── Sub-panel navigation ────────────────────────────────────────────────────

  def _show_sub_panel(self, items: list, back_fn: Callable):
    self._scroller._items = items
    self._scroller.scroll_panel.set_offset(0)
    self.set_back_callback(back_fn)

  def _show_main(self):
    self._scroller._items = self._main_items
    self._scroller.scroll_panel.set_offset(0)
    self.set_back_callback(self._original_back_callback)
    self._refresh_main_controls()

  def _show_aol_settings(self):
    limited = self._aol_limited_settings()
    if limited:
      ui_state.params.remove("AolMainCruiseAllowed")
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)
      ui_state.params.put("AolSteeringMode", 2)

    self._aol_main_cruise.refresh()
    self._aol_main_cruise.set_enabled(ui_state.is_offroad() and not limited)

    self._aol_disengage_on_brake.refresh()
    self._aol_disengage_on_brake.set_enabled(ui_state.is_offroad() and not limited)

    self._aol_steering_mode.refresh()
    self._aol_steering_mode.set_enabled(ui_state.is_offroad() and not limited)

    self._show_sub_panel(self._aol_items, self._show_main)

  def _show_lane_change_settings(self):
    self._lc_timer.refresh()

    enable_bsm = bool(ui_state.CP and ui_state.CP.enableBsm)
    if not enable_bsm and ui_state.params.get_bool("AutoLaneChangeBsmDelay"):
      ui_state.params.remove("AutoLaneChangeBsmDelay")

    self._lc_bsm_delay.refresh()
    self._lc_bsm_delay.set_enabled(
      enable_bsm and
      int(ui_state.params.get("AutoLaneChangeTimer", return_default=True)) > AutoLaneChangeMode.NUDGE
    )

    self._show_sub_panel(self._lc_items, self._show_main)

  def _show_torque_settings(self):
    if not ui_state.params.get_bool("LiveTorqueParamsToggle"):
      ui_state.params.remove("LiveTorqueParamsRelaxedToggle")

    custom_tune_enabled = ui_state.params.get_bool("CustomTorqueParams")

    self._torque_self_tune.refresh()
    self._torque_self_tune.set_enabled(ui_state.is_offroad())

    self._torque_relaxed_tune.refresh()
    self._torque_relaxed_tune.set_enabled(ui_state.is_offroad() and self._torque_self_tune._checked)

    self._torque_custom_tune.refresh()
    self._torque_custom_tune.set_enabled(ui_state.is_offroad())

    self._torque_manual_rt.refresh()
    self._torque_manual_rt.set_visible(custom_tune_enabled)
    self._torque_manual_rt.set_enabled(ui_state.is_offroad())

    self._show_sub_panel(self._torque_items, self._show_main)

  # ── State helpers ───────────────────────────────────────────────────────────

  @staticmethod
  def _aol_limited_settings() -> bool:
    brand = ""
    if ui_state.is_offroad():
      bundle = ui_state.params.get("CarPlatformBundle")
      if bundle:
        brand = bundle.get("brand", "")
    if not brand:
      brand = ui_state.CP.brand if ui_state.CP else ""
    return brand == "rivian"

  def _refresh_main_controls(self):
    self._aol_btn.refresh()
    self._aol_btn.set_sub_chips(self._get_aol_sub_chips())

    self._torque_ctrl.refresh()
    self._nnff_ctrl.refresh()

    torque_allowed = (
      ui_state.CP is not None and
      ui_state.CP.steerControlType != car.CarParams.SteerControlType.angle
    )
    if not torque_allowed:
      ui_state.params.remove("EnforceTorqueControl")
      ui_state.params.remove("NeuralNetworkFeedForward")
      self._torque_ctrl.refresh()
      self._nnff_ctrl.refresh()

    self._aol_btn.set_enabled(ui_state.is_offroad())
    self._aol_settings_btn.set_enabled(ui_state.is_offroad() and self._aol_btn._checked)

    self._torque_ctrl.set_enabled(
      ui_state.is_offroad() and torque_allowed and not self._nnff_ctrl._checked
    )
    self._nnff_ctrl.set_enabled(
      ui_state.is_offroad() and torque_allowed and not self._torque_ctrl._checked
    )
    self._torque_settings_btn.set_enabled(self._torque_ctrl._checked)

  def _update_state(self):
    super()._update_state()
    if self._scroller._items is self._main_items:
      self._refresh_main_controls()

  # ── Lifecycle ───────────────────────────────────────────────────────────────

  def show_event(self):
    super().show_event()
    # Always return to main panel on show
    self._scroller._items = self._main_items
    self.set_back_callback(self._original_back_callback)
    self._refresh_main_controls()
    self._scroller.show_event()

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
