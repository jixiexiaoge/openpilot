#!/usr/bin/env python3
import numpy as np


class FanController:
  def __init__(self) -> None:
    self.last_ignition = False

  def update(self, cur_temp: float, ignition: bool) -> int:
    if cur_temp < 70.0:
      fan_pwr_out = 0
    elif cur_temp > 85.0:
      fan_pwr_out = 100
    else:
      # 70°C → 0%, 85°C → 80%, target 75°C
      fan_pwr_out = int(np.interp(cur_temp, [70.0, 85.0], [0, 80]))

    if not ignition:
      fan_pwr_out = min(fan_pwr_out, 30)

    self.last_ignition = ignition
    return fan_pwr_out
