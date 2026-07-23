"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot.ui.onroad.hud_overlays import ChevronMetrics
from openpilot.iqpilot.ui.onroad.rainbow_path import RainbowPath


class IQModelRenderer:
  def __init__(self):
    self.rainbow_path = RainbowPath()
