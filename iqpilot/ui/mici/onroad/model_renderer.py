"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from openpilot.selfdrive.ui.ui_state import UIStatus

IQ_LANE_LINE_COLORS = {
  UIStatus.LAT_ONLY: rl.Color(0x0C, 0x94, 0x96, 0xFF),
  UIStatus.LONG_ONLY: rl.Color(0x0C, 0x94, 0x96, 0xFF),
}
