"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import time
import numpy as np
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.driver_state import DriverStateRenderer, BTN_SIZE, ARC_LENGTH
from openpilot.iqpilot.ui.onroad.hud_overlays import DeveloperUiRenderer
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached

# LongitudinalPersonality ordinals (matches cereal enum: relaxed=0, standard=1, aggressive=2)
_PERSONALITY_RELAXED = 0
_PERSONALITY_STANDARD = 1
_PERSONALITY_AGGRESSIVE = 2

PERSONALITY_COLORS = {
  _PERSONALITY_RELAXED:    rl.Color(0x17, 0xC9, 0x64, 0xFF),  # green
  _PERSONALITY_STANDARD:   rl.Color(0x0C, 0x94, 0x96, 0xFF),  # teal
  _PERSONALITY_AGGRESSIVE: rl.Color(0xE8, 0x2C, 0x2C, 0xFF),  # red
}

PERSONALITY_NAMES = {
  _PERSONALITY_RELAXED:    "Relaxed",
  _PERSONALITY_STANDARD:   "Standard",
  _PERSONALITY_AGGRESSIVE: "Aggressive",
}

_TOAST_DURATION = 2.0     # seconds
_TOAST_FONT_SIZE = 52
_TOAST_PAD_X = 52
_TOAST_PAD_Y = 22
_TOAST_BOTTOM_MARGIN = UI_BORDER_SIZE + 36
_TOAST_RADIUS = 0.45
_TOAST_FADE = 0.25        # fade-in / fade-out window


class DriverStateRendererIQ(DriverStateRenderer):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._personality: int = _PERSONALITY_STANDARD
    self._personality_color: rl.Color = PERSONALITY_COLORS[_PERSONALITY_STANDARD]

    self._toast_end_time: float = 0.0
    self._toast_text: str = ""
    self._toast_color: rl.Color = rl.WHITE
    self._font = gui_app.font(FontWeight.SEMI_BOLD)

    self.dev_ui_offset = DeveloperUiRenderer.get_bottom_dev_ui_offset()
    self._dm_background = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_background.png", BTN_SIZE, BTN_SIZE)
    self._dm_person = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_person.png", 118, 118)
    self._dm_cone = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_cone.png", 118, 118)

  def _update_state(self):
    super()._update_state()
    personality = self._params.get("LongitudinalPersonality", return_default=True)
    if personality is not None:
      self._personality = int(personality)
    self._personality_color = PERSONALITY_COLORS.get(self._personality, PERSONALITY_COLORS[_PERSONALITY_STANDARD])

  def cycle_personality(self):
    next_p = (self._personality + 1) % 3
    self._params.put_nonblocking("LongitudinalPersonality", next_p)
    self._personality = next_p
    self._personality_color = PERSONALITY_COLORS[next_p]
    self._toast_text = PERSONALITY_NAMES[next_p]
    self._toast_color = PERSONALITY_COLORS[next_p]
    self._toast_end_time = time.monotonic() + _TOAST_DURATION

  def _render(self, _):
    fade = max(0.35, 1.0 - self.dm_fade_state)
    alpha = int(255 * fade)
    pc = self._personality_color

    rl.draw_texture(
      self._dm_background,
      int(self.position_x - self._dm_background.width / 2),
      int(self.position_y - self._dm_background.height / 2),
      rl.Color(pc.r, pc.g, pc.b, alpha),
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
        rl.Color(pc.r, pc.g, pc.b, alpha),
      )
    else:
      rl.draw_circle(int(self.position_x), int(self.position_y), 14, rl.Color(255, 255, 255, alpha))

    self._draw_personality_toast()

  def _draw_personality_toast(self):
    now = time.monotonic()
    remaining = self._toast_end_time - now
    if remaining <= 0 or not self._toast_text:
      return

    elapsed = _TOAST_DURATION - remaining
    fade_in = min(1.0, elapsed / _TOAST_FADE)
    fade_out = min(1.0, remaining / _TOAST_FADE)
    a = int(255 * fade_in * fade_out)

    text_size = measure_text_cached(self._font, self._toast_text, _TOAST_FONT_SIZE)
    toast_w = text_size.x + _TOAST_PAD_X * 2
    toast_h = text_size.y + _TOAST_PAD_Y * 2

    cx = self._rect.x + self._rect.width / 2
    toast_x = cx - toast_w / 2
    toast_y = self._rect.y + self._rect.height - _TOAST_BOTTOM_MARGIN - toast_h

    tc = self._toast_color
    toast_rect = rl.Rectangle(toast_x, toast_y, toast_w, toast_h)
    rl.draw_rectangle_rounded(toast_rect, _TOAST_RADIUS, 10, rl.Color(tc.r, tc.g, tc.b, a))
    rl.draw_text_ex(
      self._font, self._toast_text,
      rl.Vector2(toast_x + _TOAST_PAD_X, toast_y + _TOAST_PAD_Y),
      _TOAST_FONT_SIZE, 0,
      rl.Color(255, 255, 255, a),
    )

  def _pre_calculate_drawing_elements(self):
    """Pre-calculate all drawing elements based on the current rectangle"""
    width, height = self._rect.width, self._rect.height
    offset = UI_BORDER_SIZE + BTN_SIZE // 2
    self.position_x = self._rect.x + (width - offset if self.is_rhd else offset)
    self.position_y = self._rect.y + height - offset - self.dev_ui_offset

    positioned_keypoints = self.face_keypoints_transformed + np.array([self.position_x, self.position_y])
    for i in range(len(positioned_keypoints)):
      self.face_lines[i].x = positioned_keypoints[i][0]
      self.face_lines[i].y = positioned_keypoints[i][1]

    delta_x = -self.driver_pose_sins[1] * ARC_LENGTH / 2.0
    delta_y = -self.driver_pose_sins[0] * ARC_LENGTH / 2.0

    h_width = abs(delta_x)
    self.h_arc_data = self._calculate_arc_data(
      delta_x, h_width, self.position_x, self.position_y - ARC_LENGTH / 2,
      self.driver_pose_sins[1], self.driver_pose_diff[1], is_horizontal=True
    )

    v_height = abs(delta_y)
    self.v_arc_data = self._calculate_arc_data(
      delta_y, v_height, self.position_x - ARC_LENGTH / 2, self.position_y,
      self.driver_pose_sins[0], self.driver_pose_diff[0], is_horizontal=False
    )
