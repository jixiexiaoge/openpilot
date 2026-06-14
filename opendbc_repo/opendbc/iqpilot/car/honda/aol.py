"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from opendbc.car import structs
from opendbc.car.honda.values import HONDA_BOSCH_RADARLESS


class AolCarController:
  def __init__(self):
    self.dashed_lanes = False

  def update(self, CP: structs.CarParams, CC: structs.CarControl, CC_IQ: structs.IQCarControl) -> None:
    enable_aol = CC_IQ.aol.available

    if enable_aol:
      self.dashed_lanes = CC_IQ.aol.enabled and not CC.latActive
    else:
      self.dashed_lanes = CC.hudControl.lanesVisible if CP.carFingerprint in HONDA_BOSCH_RADARLESS else False
