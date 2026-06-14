import pyray as rl
from collections.abc import Callable
from cereal import log

from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigParamToggle, NeonBigMultiToggle
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
STOCK_ACC_OPTION = "Stock ACC"
IQ_STANDARD_OPTION = "IQ.Standard"
IQ_DYNAMIC_OPTION = "IQ.Dynamic"
IQ_PILOT_OPTION = "IQ.Pilot"
PERSONALITY_RELAXED = "Relaxed"
PERSONALITY_STANDARD = "Standard"
PERSONALITY_AGGRESSIVE = "Aggressive"
PERSONALITY_OPTIONS = [PERSONALITY_RELAXED, PERSONALITY_STANDARD, PERSONALITY_AGGRESSIVE]
PERSONALITY_OPTION_TO_PARAM = {
  PERSONALITY_RELAXED: PERSONALITY_TO_INT["relaxed"],
  PERSONALITY_STANDARD: PERSONALITY_TO_INT["standard"],
  PERSONALITY_AGGRESSIVE: PERSONALITY_TO_INT["aggressive"],
}
PERSONALITY_PARAM_TO_OPTION = {v: k for k, v in PERSONALITY_OPTION_TO_PARAM.items()}


class TogglesLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)
    # Keep IQ.Pilot enabled by default; the UI no longer exposes this toggle.
    ui_state.params.put_bool("OpenpilotEnabledToggle", True)

    self._personality_toggle = NeonBigMultiToggle("driving personality", PERSONALITY_OPTIONS, select_callback=self._on_personality_selection)
    self._longitudinal_control_selector = NeonBigMultiToggle(
      "longitudinal control",
      [STOCK_ACC_OPTION, IQ_STANDARD_OPTION, IQ_DYNAMIC_OPTION, IQ_PILOT_OPTION],
      select_callback=self._on_longitudinal_control_selection,
    )
    is_metric_toggle = NeonBigParamToggle("use metric units", "IsMetric")
    ldw_toggle = NeonBigParamToggle("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = NeonBigParamToggle("always-on driver monitor", "AlwaysOnDM")
    record_front = NeonBigParamToggle("record & upload driver camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_audio_toggle = NeonBigParamToggle("record audio (mic)", "RecordAudio", toggle_callback=restart_needed_callback)
    self._scroller = Scroller([
      self._longitudinal_control_selector,
      self._personality_toggle,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
      record_audio_toggle,
    ], snap_items=False)

    # Toggle lists
    self._refresh_toggles = (
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_audio_toggle),
    )

    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(PERSONALITY_PARAM_TO_OPTION.get(personality, PERSONALITY_STANDARD))
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    mode_value = self._get_longitudinal_control_option()
    alpha_available = bool(ui_state.CP is not None and ui_state.CP.alphaLongitudinalAvailable)
    alpha_requested = ui_state.params.get_bool("AlphaLongitudinalEnabled")
    toyota_stock_long_forced = bool(
      ui_state.CP is not None and
      ui_state.CP.brand == "toyota" and
      ui_state.params.get_bool("ToyotaEnforceStockLongitudinal")
    )
    iq_modes_selectable = alpha_available or alpha_requested or toyota_stock_long_forced

    self._longitudinal_control_selector.set_visible(True)
    self._personality_toggle.set_visible(True)

    selector_enabled = iq_modes_selectable and not ui_state.engaged
    self._longitudinal_control_selector.set_enabled(selector_enabled)
    personality_enabled = iq_modes_selectable and mode_value in (IQ_PILOT_OPTION, IQ_DYNAMIC_OPTION)
    self._personality_toggle.set_enabled(personality_enabled)

    self._longitudinal_control_selector.set_value(mode_value)
    self._personality_toggle.set_value(
      PERSONALITY_PARAM_TO_OPTION.get(ui_state.params.get("LongitudinalPersonality", return_default=True), PERSONALITY_STANDARD)
    )

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.refresh()


  def _on_longitudinal_control_selection(self, value: str):
    alpha_available = bool(ui_state.CP is not None and ui_state.CP.alphaLongitudinalAvailable)
    alpha_requested = ui_state.params.get_bool("AlphaLongitudinalEnabled")
    toyota_stock_long_forced = bool(
      ui_state.CP is not None and
      ui_state.CP.brand == "toyota" and
      ui_state.params.get_bool("ToyotaEnforceStockLongitudinal")
    )
    if not (alpha_available or alpha_requested or toyota_stock_long_forced) and value != STOCK_ACC_OPTION:
      self._longitudinal_control_selector.set_value(STOCK_ACC_OPTION)
      return

    if value == self._get_longitudinal_control_option():
      return

    previous_alpha = ui_state.params.get_bool("AlphaLongitudinalEnabled")
    previous_toyota_stock_long = ui_state.params.get_bool("ToyotaEnforceStockLongitudinal")
    self._apply_longitudinal_control_selection(value)
    if previous_alpha != ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      restart_needed_callback(ui_state.params.get_bool("AlphaLongitudinalEnabled"))
      ui_state.params.put_bool("OnroadCycleRequested", True)
    elif previous_toyota_stock_long != ui_state.params.get_bool("ToyotaEnforceStockLongitudinal"):
      ui_state.params.put_bool("OnroadCycleRequested", True)
    self._update_toggles()

  def _on_personality_selection(self, value: str):
    ui_state.params.put("LongitudinalPersonality", PERSONALITY_OPTION_TO_PARAM[value])

  def _get_longitudinal_control_option(self) -> str:
    if not ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      return STOCK_ACC_OPTION
    if not ui_state.params.get_bool("ExperimentalMode"):
      return IQ_STANDARD_OPTION
    return IQ_DYNAMIC_OPTION if ui_state.params.get_bool("IQDynamicMode") else IQ_PILOT_OPTION

  def _apply_longitudinal_control_selection(self, value: str) -> None:
    previous_toyota_stock_long = ui_state.params.get_bool("ToyotaEnforceStockLongitudinal")

    if value == IQ_PILOT_OPTION:
      ui_state.params.put_bool("AlphaLongitudinalEnabled", True)
      ui_state.params.put_bool("ExperimentalMode", True)
      ui_state.params.put_bool("IQDynamicMode", False)
    elif value == IQ_DYNAMIC_OPTION:
      ui_state.params.put_bool("AlphaLongitudinalEnabled", True)
      ui_state.params.put_bool("ExperimentalMode", True)
      ui_state.params.put_bool("IQDynamicMode", True)
    elif value == IQ_STANDARD_OPTION:
      ui_state.params.put_bool("AlphaLongitudinalEnabled", True)
      ui_state.params.put_bool("ExperimentalMode", False)
      ui_state.params.put_bool("IQDynamicMode", False)
      ui_state.params.put("LongitudinalPersonality", PERSONALITY_TO_INT["relaxed"])
    else:
      ui_state.params.put_bool("AlphaLongitudinalEnabled", False)
      ui_state.params.put_bool("ExperimentalMode", False)
      ui_state.params.put_bool("IQDynamicMode", False)

    if value != STOCK_ACC_OPTION and previous_toyota_stock_long:
      ui_state.params.put_bool("ToyotaEnforceStockLongitudinal", False)

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
