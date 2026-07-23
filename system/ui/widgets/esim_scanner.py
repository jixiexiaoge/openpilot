import numpy as np
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, NavWidget
from openpilot.system.ui.widgets.label import gui_label
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.system.hardware.tici.qr_decode import decode_qr, stable_code_key, validate_lpa_activation_code

if gui_app.big_ui():
  from openpilot.selfdrive.ui.onroad.driver_camera_dialog import DriverCameraDialog
else:
  from openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog import DriverCameraDialog


class EsimQrScannerDialog(NavWidget):
  REQUIRED_MATCH_FRAMES = 3
  DECODE_EVERY_N_FRAMES = 3
  NO_CAMERA_MESSAGE_DELAY_SEC = 3.0

  def __init__(self):
    super().__init__()
    self._is_big_ui = gui_app.big_ui()
    self._camera = DriverCameraDialog() if self._is_big_ui else DriverCameraDialog(no_escape=True)
    self._candidate_key = ""
    self._candidate_count = 0
    self.code: str | None = None
    self._status = tr("Point the driver camera at a carrier eSIM QR code (LPA:...)")
    self._frame_count = 0
    self._no_camera_elapsed_sec = 0.0
    self._result = DialogResult.NO_ACTION

    self.set_back_callback(lambda: setattr(self, "_result", DialogResult.CANCEL))

  def _get_frame(self):
    return self._camera.frame if self._is_big_ui else self._camera._camera_view.frame

  def show_event(self):
    super().show_event()
    self._camera.show_event()
    ui_state.params.put_bool_nonblocking("IsDriverViewEnabled", True)
    device.set_override_interactive_timeout(300)
    self._no_camera_elapsed_sec = 0.0

  def hide_event(self):
    super().hide_event()
    ui_state.params.put_bool("IsDriverViewEnabled", False)
    device.set_override_interactive_timeout(None)
    self._camera.hide_event()

  def _update_state(self):
    super()._update_state()
    if device.awake and not ui_state.params.get_bool("IsDriverViewEnabled"):
      ui_state.params.put_bool_nonblocking("IsDriverViewEnabled", True)
    self._frame_count += 1

    frame = self._get_frame()
    if frame is None:
      self._no_camera_elapsed_sec += 1.0 / gui_app.target_fps
      if self._no_camera_elapsed_sec >= self.NO_CAMERA_MESSAGE_DELAY_SEC:
        self._status = tr("Waiting for driver camera. Use the carrier eSIM QR code or enter the LPA code manually.")
      return

    self._no_camera_elapsed_sec = 0.0
    if frame is None or (self._frame_count % self.DECODE_EVERY_N_FRAMES != 0):
      return

    try:
      y = np.frombuffer(frame.data[:frame.uv_offset], dtype=np.uint8).reshape((-1, frame.stride))[:frame.height, :frame.width]
    except Exception:
      return

    codes = decode_qr(y)
    if not codes:
      self._candidate_key = ""
      self._candidate_count = 0
      self._status = tr("No QR detected")
      return

    valid_payload = ""
    validation_error = ""
    for payload in codes:
      valid, err = validate_lpa_activation_code(payload)
      if valid:
        valid_payload = payload
        break
      validation_error = err

    if not valid_payload:
      self._candidate_key = ""
      self._candidate_count = 0
      self._status = validation_error or tr("Invalid QR code")
      return

    key = stable_code_key(valid_payload)
    if key == self._candidate_key:
      self._candidate_count += 1
    else:
      self._candidate_key = key
      self._candidate_count = 1

    if self._candidate_count >= self.REQUIRED_MATCH_FRAMES:
      self.code = valid_payload
      self._status = tr("QR accepted")
      self._result = DialogResult.CONFIRM
    else:
      self._status = tr("Hold steady...")

  def _render(self, rect: rl.Rectangle):
    self._camera.render(rect)

    if self._get_frame() is None:
      gui_label(
        rect,
        tr("camera starting"),
        font_size=72 if gui_app.big_ui() else 44,
        font_weight=FontWeight.BOLD,
        alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
      )
    else:
      text_rect = rl.Rectangle(rect.x + 40, rect.y + 40, rect.width - 80, 90)
      gui_label(
        text_rect,
        self._status,
        font_size=50 if gui_app.big_ui() else 30,
        font_weight=FontWeight.MEDIUM,
        alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
      )

    return self._result
