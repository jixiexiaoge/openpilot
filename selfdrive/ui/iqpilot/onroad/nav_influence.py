"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl

from openpilot.selfdrive.ui.onroad.hud_renderer import COLORS
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


class NavInfluenceRenderer(Widget):
  _PROVIDER_LABELS = {
    0: "",
    1: "NAV",
    2: "MBX",
    3: "VIS",
    4: "OSM",
  }

  def __init__(self):
    super().__init__()
    self.engaged = False
    self.valid = False
    self.provider = 0
    self.long_override = False
    self._active_frame = 0

    self.font = gui_app.font(FontWeight.BOLD)
    self._tex = rl.load_render_texture(256, 128)

  def update(self):
    sm = ui_state.sm
    if sm.updated["iqPlan"]:
      nav = sm["iqPlan"].iqNavState.nav
      self.engaged = nav.engaged
      self.valid = nav.valid
      self.provider = getattr(nav.provider, "raw", nav.provider)

    if sm.updated["carControl"]:
      self.long_override = sm["carControl"].cruiseControl.override

    if self.engaged and self.valid:
      self._active_frame += 1
    else:
      self._active_frame = 0

  @staticmethod
  def _pulse_element(frame):
    return not (frame % gui_app.target_fps < (gui_app.target_fps / 2.5))

  def _draw_icon(self, rect_center_x, rect_height, x_offset, y_offset, label):
    font_size = 36
    padding_v = 5
    box_width = 160
    sz = measure_text_cached(self.font, label, font_size)
    box_height = int(sz.y + padding_v * 2)

    texture_width = 256
    texture_height = 128

    rl.begin_texture_mode(self._tex)
    rl.clear_background(rl.Color(0, 0, 0, 0))

    box_color = COLORS.OVERRIDE if self.long_override else rl.Color(0, 255, 0, 255)

    box_x = (texture_width - box_width) // 2
    box_y = (texture_height - box_height) // 2
    rl.draw_rectangle_rounded(rl.Rectangle(box_x, box_y, box_width, box_height), 0.2, 10, box_color)

    rl.rl_set_blend_factors(rl.RL_ZERO, rl.RL_ONE_MINUS_SRC_ALPHA, 0x8006)
    rl.rl_set_blend_mode(rl.BLEND_CUSTOM)

    text_pos_x = box_x + (box_width - sz.x) / 2
    text_pos_y = box_y + (box_height - sz.y) / 2
    rl.draw_text_ex(self.font, label, rl.Vector2(text_pos_x, text_pos_y), font_size, 0, rl.WHITE)

    rl.rl_set_blend_mode(rl.BLEND_ALPHA)
    rl.end_texture_mode()

    screen_y = rect_height / 4 - 40 + y_offset
    dest_x = rect_center_x + x_offset - texture_width / 2
    dest_y = screen_y - texture_height / 2

    src_rect = rl.Rectangle(0, 0, texture_width, -texture_height)
    dst_rect = rl.Rectangle(dest_x, dest_y, texture_width, texture_height)
    rl.draw_texture_pro(self._tex.texture, src_rect, dst_rect, rl.Vector2(0, 0), 0, rl.WHITE)

  def _render(self, rect: rl.Rectangle):
    if not self.valid:
      return

    pulse = self._pulse_element(self._active_frame)
    if self.engaged and not pulse:
      return

    label = self._PROVIDER_LABELS.get(int(self.provider), "NAV")
    if label:
      self._draw_icon(rect.x + rect.width / 2, rect.height, -260, 0, label)
