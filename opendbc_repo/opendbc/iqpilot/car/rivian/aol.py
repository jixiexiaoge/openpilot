"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections import namedtuple

from opendbc.car import structs
from opendbc.car.interfaces import CarStateBase

MAX_STEERING_ANGLE = 90.0

AolDataIQ = namedtuple("AolDataIQ",
                        ["lka_icon_states", "lat_active"])


class AolCarController:
  def __init__(self):
    self.aol = AolDataIQ(False, False)

    self.lka_icon_states = False
    self.lat_active = False

  def aol_status_update(self, CC: structs.CarControl, CC_IQ: structs.IQCarControl, CS: CarStateBase) -> AolDataIQ:
    if CC_IQ.aol.available:
      self.lka_icon_states = self.lat_active
      self.lat_active = CC.latActive and abs(CS.out.steeringAngleDeg) < MAX_STEERING_ANGLE
    else:
      self.lka_icon_states = CC.enabled
      self.lat_active = CC.latActive

    return AolDataIQ(self.lka_icon_states, self.lat_active)

  def update(self, CC: structs.CarControl, CC_IQ: structs.IQCarControl, CS: CarStateBase) -> None:
    self.aol = self.aol_status_update(CC, CC_IQ, CS)
