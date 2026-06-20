import time
import numpy as np
import pyray as rl
from cereal import log, messaging
from msgq.visionipc import VisionStreamType
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
from openpilot.selfdrive.ui.onroad.driver_state import DriverStateRenderer as BaseDriverStateRenderer, BTN_SIZE
from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer as BaseHudRenderer
from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.system.ui.lib.application import gui_app
from openpilot.common.issue_debug import log_issue_limited
from openpilot.common.transformations.camera import DEVICE_CAMERAS, DeviceCameraConfig, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.selfdrive.locationd.calibration_helpers import get_calibrated_rpy

from openpilot.selfdrive.ui.iqpilot.onroad.augmented_road_view import BORDER_COLORS_IQ, AugmentedRoadViewIQ
from openpilot.selfdrive.ui.iqpilot.onroad.driver_state import DriverStateRendererIQ
from openpilot.selfdrive.ui.iqpilot.onroad.hud_renderer import IQHudRenderer
from openpilot.selfdrive.ui.iqpilot.ui_state import OnroadTimerStatus

OpState = log.SelfdriveState.OpenpilotState
CALIBRATED = log.LiveCalibrationData.Status.calibrated
ROAD_CAM = VisionStreamType.VISION_STREAM_ROAD
WIDE_CAM = VisionStreamType.VISION_STREAM_WIDE_ROAD
DEFAULT_DEVICE_CAMERA = DEVICE_CAMERAS["tici", "ar0231"]

BORDER_COLORS = {
  UIStatus.DISENGAGED: rl.Color(0x12, 0x28, 0x39, 0xFF),  # Blue for disengaged state
  UIStatus.OVERRIDE: rl.Color(0x89, 0x92, 0x8D, 0xFF),  # Gray for override state
  UIStatus.ENGAGED: rl.Color(0x0C, 0x94, 0x96, 0xFF),
  **BORDER_COLORS_IQ,
}

WIDE_CAM_MAX_SPEED = 10.0  # m/s (22 mph)
ROAD_CAM_MIN_SPEED = 15.0  # m/s (34 mph)
INF_POINT = np.array([1000.0, 0.0, 0.0])


class AugmentedRoadView(CameraView, AugmentedRoadViewIQ):
  def __init__(self, stream_type: VisionStreamType = VisionStreamType.VISION_STREAM_ROAD):
    CameraView.__init__(self, "camerad", stream_type)
    AugmentedRoadViewIQ.__init__(self)
    self._set_placeholder_color(BORDER_COLORS[UIStatus.DISENGAGED])

    self.device_camera: DeviceCameraConfig | None = None
    self.view_from_calib = view_frame_from_device_frame.copy()
    self.view_from_wide_calib = view_frame_from_device_frame.copy()

    self._matrix_cache_key = (0, 0.0, 0.0, stream_type)
    self._cached_matrix: np.ndarray | None = None
    self._content_rect = rl.Rectangle()
    self._split_nav_available = False

    self.model_renderer = ModelRenderer()
    self.alert_renderer = AlertRenderer()
    self._hud_renderer = IQHudRenderer()
    self.driver_state_renderer = DriverStateRendererIQ()
    self._split_nav_available = hasattr(self._hud_renderer, "render_split_nav")

    # debug
    self._pm = messaging.PubMaster(['uiDebug'])

  def _render(self, rect):
    # Only render when system is started to avoid invalid data access
    start_draw = time.monotonic()
    if not ui_state.started:
      return

    self._switch_stream_if_needed(ui_state.sm)

    # Update calibration before rendering
    self._update_calibration()

    # Create inner content area with border padding
    full_content_rect = rl.Rectangle(
      rect.x + UI_BORDER_SIZE,
      rect.y + UI_BORDER_SIZE,
      rect.width - 2 * UI_BORDER_SIZE,
      rect.height - 2 * UI_BORDER_SIZE,
    )
    split_nav_enabled = bool(getattr(self._hud_renderer, "split_nav_enabled", lambda: False)())
    if split_nav_enabled:
      split_width = full_content_rect.width * 0.5
      camera_rect = rl.Rectangle(full_content_rect.x, full_content_rect.y, split_width, full_content_rect.height)
      map_rect = rl.Rectangle(full_content_rect.x + split_width, full_content_rect.y, full_content_rect.width - split_width, full_content_rect.height)
    else:
      camera_rect = full_content_rect
      map_rect = None
    self._content_rect = camera_rect

    if map_rect is not None:
      self._hud_renderer.render_split_nav(map_rect)
      rl.draw_line_ex(
        rl.Vector2(map_rect.x, map_rect.y + 20),
        rl.Vector2(map_rect.x, map_rect.y + map_rect.height - 20),
        2.0,
        rl.Color(255, 255, 255, 20),
      )

    # Enable scissor mode to clip all rendering within content rectangle boundaries
    # This creates a rendering viewport that prevents graphics from drawing outside the border
    rl.begin_scissor_mode(
      int(camera_rect.x),
      int(camera_rect.y),
      int(camera_rect.width),
      int(camera_rect.height)
    )

    # Render the base camera view
    super()._render(camera_rect)

    # Draw all UI overlays
    self.model_renderer.render(camera_rect)
    AugmentedRoadViewIQ.update_fade_out_bottom_overlay(self, camera_rect)
    self._hud_renderer.render(camera_rect)

    # Custom UI extension point - add custom overlays here
    # Use self._content_rect for positioning within camera bounds

    # End clipping region
    rl.end_scissor_mode()

    if hasattr(self._hud_renderer, "render_full_width_overlays"):
      self._hud_renderer.render_full_width_overlays(full_content_rect)

    self.alert_renderer.render(full_content_rect)
    self.driver_state_renderer.render(full_content_rect)

    # Draw colored border based on driving state
    self._draw_border(rect)

    # publish uiDebug
    draw_time_ms = (time.monotonic() - start_draw) * 1000
    if draw_time_ms > 40.0:
      log_issue_limited(
        "ui_draw_slow",
        "ui",
        f"onroad draw slow drawTimeMillis={draw_time_ms:.2f} navActive={getattr(ui_state.sm['iqNavState'], 'active', False)}",
        interval_sec=1.0,
      )
    msg = messaging.new_message('uiDebug')
    msg.uiDebug.drawTimeMillis = draw_time_ms
    self._pm.send('uiDebug', msg)

  def _handle_mouse_press(self, mouse_pos):
    dm = self.driver_state_renderer
    if ui_state.has_longitudinal_control and dm.is_visible:
      dx = mouse_pos.x - dm.position_x
      dy = mouse_pos.y - dm.position_y
      if dx * dx + dy * dy <= (BTN_SIZE / 2) ** 2:
        dm.cycle_personality()
        return

    if not self._hud_renderer.user_interacting() and self._click_callback is not None:
      self._click_callback()

  def _handle_mouse_release(self, _):
    # We only call click callback on press if not interacting with HUD
    pass

  def _draw_border(self, rect: rl.Rectangle):
    rl.draw_rectangle_lines_ex(rect, UI_BORDER_SIZE, rl.BLACK)
    border_roundness = 0.12
    border_color = BORDER_COLORS.get(ui_state.status, BORDER_COLORS[UIStatus.DISENGAGED])
    border_rect = rl.Rectangle(rect.x + UI_BORDER_SIZE, rect.y + UI_BORDER_SIZE,
                               rect.width - 2 * UI_BORDER_SIZE, rect.height - 2 * UI_BORDER_SIZE)
    aol = ui_state.sm["iqState"].aol
    if aol.active and not ui_state.sm["selfdriveState"].enabled:
      bottom_only_height = max(int(UI_BORDER_SIZE * 4), 60)
      clip_y = int(rect.y + rect.height - bottom_only_height)
      rl.begin_scissor_mode(int(rect.x), clip_y, int(rect.width), bottom_only_height)
      rl.draw_rectangle_rounded_lines_ex(border_rect, border_roundness, 10, UI_BORDER_SIZE, border_color)
      rl.end_scissor_mode()
    else:
      rl.draw_rectangle_rounded_lines_ex(border_rect, border_roundness, 10, UI_BORDER_SIZE, border_color)

  def _switch_stream_if_needed(self, sm):
    if sm['selfdriveState'].experimentalMode and WIDE_CAM in self.available_streams:
      v_ego = sm['carState'].vEgo
      if v_ego < WIDE_CAM_MAX_SPEED:
        target = WIDE_CAM
      elif v_ego > ROAD_CAM_MIN_SPEED:
        target = ROAD_CAM
      else:
        # Hysteresis zone - keep current stream
        target = self.stream_type
    else:
      target = ROAD_CAM

    if self.stream_type != target:
      self.switch_stream(target)

  def _update_calibration(self):
    # Update device camera if not already set
    sm = ui_state.sm
    if not self.device_camera and sm.seen['roadCameraState'] and sm.seen['deviceState']:
      self.device_camera = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['roadCameraState'].sensor))]

    # Check if live calibration data is available and valid
    if not (sm.updated["liveCalibration"] and sm.valid['liveCalibration']):
      return

    calib = sm['liveCalibration']
    calib_rpy = get_calibrated_rpy(calib)
    if calib_rpy is None:
      return

    # Update view_from_calib matrix
    device_from_calib = rot_from_euler(calib_rpy)
    self.view_from_calib = view_frame_from_device_frame @ device_from_calib

    # Update wide calibration if available
    if hasattr(calib, 'wideFromDeviceEuler') and len(calib.wideFromDeviceEuler) == 3:
      wide_from_device = rot_from_euler(calib.wideFromDeviceEuler)
      self.view_from_wide_calib = view_frame_from_device_frame @ wide_from_device @ device_from_calib

  def _calc_frame_matrix(self, rect: rl.Rectangle) -> np.ndarray:
    # Check if we can use cached matrix
    cache_key = (
      ui_state.sm.recv_frame['liveCalibration'],
      self._content_rect.width,
      self._content_rect.height,
      self.stream_type
    )
    if cache_key == self._matrix_cache_key and self._cached_matrix is not None:
      return self._cached_matrix

    # Get camera configuration
    device_camera = self.device_camera or DEFAULT_DEVICE_CAMERA
    is_wide_camera = self.stream_type == WIDE_CAM
    intrinsic = device_camera.ecam.intrinsics if is_wide_camera else device_camera.fcam.intrinsics
    calibration = self.view_from_wide_calib if is_wide_camera else self.view_from_calib
    zoom = 2.0 if is_wide_camera else 1.1

    # Calculate transforms for vanishing point
    calib_transform = intrinsic @ calibration
    kep = calib_transform @ INF_POINT

    # Calculate center points and dimensions
    x, y = self._content_rect.x, self._content_rect.y
    w, h = self._content_rect.width, self._content_rect.height
    cx, cy = intrinsic[0, 2], intrinsic[1, 2]

    # Calculate max allowed offsets with margins
    margin = 5
    max_x_offset = cx * zoom - w / 2 - margin
    max_y_offset = cy * zoom - h / 2 - margin

    # Calculate and clamp offsets to prevent out-of-bounds issues
    try:
      if abs(kep[2]) > 1e-6:
        x_offset = np.clip((kep[0] / kep[2] - cx) * zoom, -max_x_offset, max_x_offset)
        y_offset = np.clip((kep[1] / kep[2] - cy) * zoom, -max_y_offset, max_y_offset)
      else:
        x_offset, y_offset = 0, 0
    except (ZeroDivisionError, OverflowError):
      x_offset, y_offset = 0, 0

    # Cache the computed transformation matrix to avoid recalculations
    self._matrix_cache_key = cache_key
    self._cached_matrix = np.array([
      [zoom * 2 * cx / w, 0, -x_offset / w * 2],
      [0, zoom * 2 * cy / h, -y_offset / h * 2],
      [0, 0, 1.0]
    ])

    video_transform = np.array([
      [zoom, 0.0, (w / 2 + x - x_offset) - (cx * zoom)],
      [0.0, zoom, (h / 2 + y - y_offset) - (cy * zoom)],
      [0.0, 0.0, 1.0]
    ])
    self.model_renderer.set_transform(video_transform @ calib_transform)

    return self._cached_matrix

  def show_event(self):
    if gui_app.iqpilot_ui():
      ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)

  def hide_event(self):
    if gui_app.iqpilot_ui():
      ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)


if __name__ == "__main__":
  gui_app.init_window("OnRoad Camera View")
  road_camera_view = AugmentedRoadView(ROAD_CAM)
  print("***press space to switch camera view***")
  try:
    for _ in gui_app.render():
      ui_state.update()
      if rl.is_key_released(rl.KeyboardKey.KEY_SPACE):
        if WIDE_CAM in road_camera_view.available_streams:
          stream = ROAD_CAM if road_camera_view.stream_type == WIDE_CAM else WIDE_CAM
          road_camera_view.switch_stream(stream)
      road_camera_view.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
  finally:
    road_camera_view.close()
