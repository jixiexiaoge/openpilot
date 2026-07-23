import time
import pyray as rl
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget


class ExpButton(Widget):
  def __init__(self, button_size: int, icon_size: int):
    super().__init__()
    self._params = Params()
    self._experimental_mode: bool = False
    self._iq_dynamic_mode: bool = False
    self._engageable: bool = False

    # State hold mechanism
    self._hold_duration = 2.0  # seconds
    self._held_mode: tuple | None = None  # (experimental, iq_dynamic) or None
    self._hold_end_time: float | None = None

    self._white_color: rl.Color = rl.Color(255, 255, 255, 255)
    self._black_bg: rl.Color = rl.Color(0, 0, 0, 166)
    self._txt_wheel: rl.Texture = gui_app.texture('icons/chffr_wheel.png', icon_size, icon_size)
    self._txt_standard: rl.Texture = gui_app.texture('icons_mici/iqstandard_mode_tizi.png', icon_size, icon_size)
    self._txt_pilot: rl.Texture = gui_app.texture('icons_mici/experimental_mode_tizi.png', icon_size, icon_size)
    self._txt_dyn: rl.Texture = gui_app.texture('icons_mici/iqdynamic_mode_tizi.png', icon_size, icon_size)
    self._rect = rl.Rectangle(0, 0, button_size, button_size)

  def set_rect(self, rect: rl.Rectangle) -> None:
    self._rect.x, self._rect.y = rect.x, rect.y

  def _update_state(self) -> None:
    selfdrive_state = ui_state.sm["selfdriveState"]
    self._experimental_mode = selfdrive_state.experimentalMode
    self._iq_dynamic_mode = self._params.get_bool("IQDynamicMode")
    self._engageable = selfdrive_state.engageable or selfdrive_state.enabled

  def _handle_mouse_release(self, _):
    super()._handle_mouse_release(_)
    if not self._is_toggle_allowed():
      return

    exp, dyn = self._current_mode()
    # Cycle: IQ.Standard → IQ.Dynamic → IQ.Pilot → IQ.Standard
    if not exp:
      new_exp, new_dyn = True, True
    elif dyn:
      new_exp, new_dyn = True, False
    else:
      new_exp, new_dyn = False, False

    self._params.put_bool("ExperimentalMode", new_exp)
    self._params.put_bool("IQDynamicMode", new_dyn)
    self._held_mode = (new_exp, new_dyn)
    self._hold_end_time = time.monotonic() + self._hold_duration

  def _render(self, rect: rl.Rectangle) -> None:
    center_x = int(self._rect.x + self._rect.width // 2)
    center_y = int(self._rect.y + self._rect.height // 2)

    self._white_color.a = 180 if self.is_pressed or not self._engageable else 255

    exp, dyn = self._current_mode()
    if not ui_state.has_longitudinal_control:
      texture = self._txt_wheel
    elif exp and dyn:
      texture = self._txt_dyn
    elif exp:
      texture = self._txt_pilot
    else:
      texture = self._txt_standard
    rl.draw_circle(center_x, center_y, self._rect.width / 2, self._black_bg)
    rl.draw_texture(texture, center_x - texture.width // 2, center_y - texture.height // 2, self._white_color)

  def _current_mode(self) -> tuple:
    now = time.monotonic()
    if self._hold_end_time and now < self._hold_end_time:
      return self._held_mode
    if self._hold_end_time and now >= self._hold_end_time:
      self._hold_end_time = self._held_mode = None
    return (self._experimental_mode, self._iq_dynamic_mode)

  def _is_toggle_allowed(self):
    if not self._params.get_bool("ExperimentalModeConfirmed"):
      return False
    return ui_state.has_longitudinal_control
