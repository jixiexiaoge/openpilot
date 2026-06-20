"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.selfdrive.ui.iqpilot.onroad.chevron_metrics import ChevronMetrics
from openpilot.selfdrive.ui.iqpilot.onroad.rainbow_path import RainbowPath


class IQModelRenderer:
  def __init__(self):
    self.rainbow_path = RainbowPath()
    self.chevron_metrics = ChevronMetrics()

