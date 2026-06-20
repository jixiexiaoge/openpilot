"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import StrEnum

from opendbc.car import Bus,structs

from opendbc.iqpilot.aol_base import AolCarStateBase
from opendbc.can.parser import CANParser


class AolCarState(AolCarStateBase):
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    super().__init__(CP, CP_IQ)

  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp = can_parsers[Bus.pt]

    self.prev_lkas_button = self.lkas_button
    self.lkas_button = cp.vl["Steering_Data_FD1"]["TjaButtnOnOffPress"]
