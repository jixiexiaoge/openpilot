"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from abc import abstractmethod, ABC
from enum import StrEnum

from opendbc.car import structs
from opendbc.can.parser import CANParser


class AolCarStateBase(ABC):
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.lkas_button = 0
    self.prev_lkas_button = 0

  @abstractmethod
  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    pass
