"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import numpy as np

from opendbc.car import structs
from opendbc.car.can_definitions import CanData
from opendbc.iqpilot.car import create_gas_interceptor_command


class GasInterceptorCarController:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.gas = 0.
    self.interceptor_gas_cmd = 0.

  def update(self, CC: structs.CarControl, CS: structs.CarState, gas: float, brake: float, wind_brake: float,
             packer, frame: int) -> list[CanData]:
    can_sends = []

    if self.CP_IQ.enableGasInterceptor:
      gas_pedal = np.interp(CS.out.vEgo, [0., 10.], [0.4, 1.0])
      if CC.longActive:
        self.gas = float(np.clip(gas_pedal * (gas - brake + wind_brake * 3 / 4), 0., 1.))
      else:
        self.gas = 0.0
      can_sends.append(create_gas_interceptor_command(packer, self.gas, frame // 2))

    return can_sends
