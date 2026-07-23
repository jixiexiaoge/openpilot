"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigParamControl
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state


class DashcamLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._dashcam = BigParamControl("enable dashcam", "DashcamEnabled", toggle_callback=restart_needed_callback)
    self._record_front = BigParamControl("record driver camera", "RecordFront", toggle_callback=restart_needed_callback)
    self._record_audio = BigParamControl("record microphone audio", "RecordAudio", toggle_callback=restart_needed_callback)

    self._scroller.add_widgets([self._dashcam, self._record_front, self._record_audio])

    self._refresh_toggles = (
      ("DashcamEnabled", self._dashcam),
      ("RecordFront", self._record_front),
      ("RecordAudio", self._record_audio),
    )

    self._record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    self._record_audio.set_enabled(lambda: not ui_state.engaged)
    ui_state.add_engaged_transition_callback(self._update_toggles)

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
