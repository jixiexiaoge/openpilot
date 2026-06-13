"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from enum import StrEnum

from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.can.parser import CANParser
from opendbc.iqpilot.car.gm.values_ext import GMFlagsIQ


class CarStateExt:
  def __init__(self, CP, CP_IQ):
    self.CP = CP
    self.CP_IQ = CP_IQ

  def update(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    pt_cp = can_parsers[Bus.pt]

    if self.CP_IQ.flags & GMFlagsIQ.NON_ACC:
      ret.cruiseState.enabled = pt_cp.vl["ECMCruiseControl"]["CruiseActive"] != 0
      ret.cruiseState.speed = pt_cp.vl["ECMCruiseControl"]["CruiseSetSpeed"] * CV.KPH_TO_MS
      ret.accFaulted = False
