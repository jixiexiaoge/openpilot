"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.ui_state import ui_state


class TogglesLayoutMici(NavScroller):
  """Equivalent to the BIG UI toggles page, minus cruise items (personality / speed limit /
  longitudinal control live in Cruise) and dashcam items (dashcam / driver-cam / mic live in Dashcam)."""
  def __init__(self):
    super().__init__()
    ui_state.params.put_bool("OpenpilotEnabledToggle", True)

    disengage = BigParamControl("disengage on accelerator", "DisengageOnAccelerator")
    ldw = BigParamControl("lane departure warnings", "IsLdwEnabled")
    is_metric = BigParamControl("use metric units", "IsMetric")

    self._scroller.add_widgets([disengage, ldw, is_metric])

    self._refresh_toggles = (
      ("DisengageOnAccelerator", disengage),
      ("IsLdwEnabled", ldw),
      ("IsMetric", is_metric),
    )

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
