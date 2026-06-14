"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import numpy as np
import pyray as rl

from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.driver_state import DriverStateRenderer, BTN_SIZE, ARC_LENGTH
from openpilot.selfdrive.ui.iqpilot.onroad.developer_ui import DeveloperUiRenderer
from openpilot.system.ui.lib.application import gui_app

ACTIVE_ACCENT = rl.Color(0x0C, 0x94, 0x96, 0xFF)


class DriverStateRendererIQ(DriverStateRenderer):
  def __init__(self):
    super().__init__()
    self.dev_ui_offset = DeveloperUiRenderer.get_bottom_dev_ui_offset()
    self._dm_background = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_background.png", BTN_SIZE, BTN_SIZE)
    self._dm_person = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_person.png", 118, 118)
    self._dm_cone = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_cone.png", 118, 118)
    self._dm_center = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_center.png", 82, 82)

  def _render(self, _):
    fade = max(0.35, 1.0 - self.dm_fade_state)
    alpha = int(255 * fade)

    rl.draw_texture(
      self._dm_background,
      int(self.position_x - self._dm_background.width / 2),
      int(self.position_y - self._dm_background.height / 2),
      rl.Color(255, 255, 255, alpha),
    )

    rl.draw_texture(
      self._dm_person,
      int(self.position_x - self._dm_person.width / 2),
      int(self.position_y - self._dm_person.height / 2),
      rl.Color(255, 255, 255, int(alpha * 0.9)),
    )

    if self.is_active:
      dest_rect = rl.Rectangle(self.position_x, self.position_y, self._dm_cone.width, self._dm_cone.height)
      rl.draw_texture_pro(
        self._dm_cone,
        rl.Rectangle(0, 0, self._dm_cone.width, self._dm_cone.height),
        dest_rect,
        rl.Vector2(dest_rect.width / 2, dest_rect.height / 2),
        180.0,
        rl.Color(ACTIVE_ACCENT.r, ACTIVE_ACCENT.g, ACTIVE_ACCENT.b, alpha),
      )
    else:
      rl.draw_texture(
        self._dm_center,
        int(self.position_x - self._dm_center.width / 2),
        int(self.position_y - self._dm_center.height / 2),
        rl.Color(255, 255, 255, alpha),
      )

  def _pre_calculate_drawing_elements(self):
    """Pre-calculate all drawing elements based on the current rectangle"""
    # Calculate icon position (bottom-left or bottom-right)
    width, height = self._rect.width, self._rect.height
    offset = UI_BORDER_SIZE + BTN_SIZE // 2
    self.position_x = self._rect.x + (width - offset if self.is_rhd else offset)
    self.position_y = self._rect.y + height - offset - self.dev_ui_offset

    # Pre-calculate the face lines positions
    positioned_keypoints = self.face_keypoints_transformed + np.array([self.position_x, self.position_y])
    for i in range(len(positioned_keypoints)):
      self.face_lines[i].x = positioned_keypoints[i][0]
      self.face_lines[i].y = positioned_keypoints[i][1]

    # Calculate arc dimensions based on head rotation
    delta_x = -self.driver_pose_sins[1] * ARC_LENGTH / 2.0  # Horizontal movement
    delta_y = -self.driver_pose_sins[0] * ARC_LENGTH / 2.0  # Vertical movement

    # Horizontal arc
    h_width = abs(delta_x)
    self.h_arc_data = self._calculate_arc_data(
      delta_x, h_width, self.position_x, self.position_y - ARC_LENGTH / 2,
      self.driver_pose_sins[1], self.driver_pose_diff[1], is_horizontal=True
    )

    # Vertical arc
    v_height = abs(delta_y)
    self.v_arc_data = self._calculate_arc_data(
      delta_y, v_height, self.position_x - ARC_LENGTH / 2, self.position_y,
      self.driver_pose_sins[0], self.driver_pose_diff[0], is_horizontal=False
    )
