"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Non-ACC GM carState: these cars have no adaptive cruise, so cruise engage/set
speed come from the stock (non-adaptive) ECM cruise message.
"""
from enum import StrEnum

from iqdbc.car import Bus, structs
from iqdbc.car.common.conversions import Conversions as CV
from iqdbc.can.parser import CANParser
from iqdbc.lvbs.car.gm.iq_values import GMFlagsIQ


class IQCarState:
  def __init__(self, CP, CP_IQ):
    self.CP = CP
    self.CP_IQ = CP_IQ

  def update(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    if not self.CP_IQ.flags & GMFlagsIQ.NON_ACC:
      return
    pt_cp = can_parsers[Bus.pt]
    ret.cruiseState.enabled = pt_cp.vl["ECMCruiseControl"]["CruiseActive"] != 0
    ret.cruiseState.speed = pt_cp.vl["ECMCruiseControl"]["CruiseSetSpeed"] * CV.KPH_TO_MS
    ret.accFaulted = False
