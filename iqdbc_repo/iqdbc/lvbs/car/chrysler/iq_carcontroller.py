"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Chrysler low-speed steering gate: overrides the stock LKAS control bit when the
no-min-steering-speed option is set, and holds the RAM DT engagement window.
"""
from iqdbc.car import structs
from iqdbc.car.interfaces import CarStateBase
from iqdbc.car.chrysler.values import RAM_DT
from iqdbc.lvbs.car.chrysler.iq_values import ChryslerFlagsIQ

GearShifter = structs.CarState.GearShifter


class IQCarController:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

  def get_lkas_control_bit(self, CS: CarStateBase, CC: structs.CarControl, lkas_control_bit: bool) -> bool:
    if self.CP_IQ.flags & ChryslerFlagsIQ.NO_MIN_STEERING_SPEED:
      return CC.latActive

    if self.CP.carFingerprint in RAM_DT:
      if self.CP.minEnableSpeed <= CS.out.vEgo <= self.CP.minEnableSpeed + 0.5:
        lkas_control_bit = True
      if self.CP.minEnableSpeed >= 14.5 and CS.out.gearShifter != GearShifter.drive:
        lkas_control_bit = False

    return lkas_control_bit
