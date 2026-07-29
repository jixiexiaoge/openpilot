"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from openpilot.selfdrive.ui.ui_state import UIStatus

BORDER_COLORS_IQ = {
  UIStatus.LAT_ONLY: rl.Color(0x0C, 0x94, 0x96, 0xFF),
  UIStatus.LONG_ONLY: rl.Color(0x96, 0x1C, 0xA8, 0xFF),  # Purple for longitudinal-only state
}


class AugmentedRoadViewIQ:
  def __init__(self):
    pass

  def update_fade_out_bottom_overlay(self, _content_rect):
    pass
