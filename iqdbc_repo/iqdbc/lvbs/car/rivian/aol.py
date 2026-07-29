"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Always-on-Lateral output adapter for Rivian: derives the per-frame lateral-active
and lane-keep icon state the LKAS command needs from the shared AOL state.
"""
from collections import namedtuple

from iqdbc.car import structs
from iqdbc.car.interfaces import CarStateBase

# Rivian EPAS rejects large-angle torque, so lateral is dropped past this bound.
_MAX_STEERING_ANGLE = 90.0

AolDataIQ = namedtuple("AolDataIQ", ["lka_icon_states", "lat_active"])


class AolCarController:
  def __init__(self):
    self.aol = AolDataIQ(False, False)

  def update(self, CC: structs.CarControl, CC_IQ: structs.IQCarControl, CS: CarStateBase) -> None:
    prev_active = self.aol.lat_active
    if CC_IQ.aol.available:
      lat_active = CC.latActive and abs(CS.out.steeringAngleDeg) < _MAX_STEERING_ANGLE
      lka_icon = prev_active
    else:
      lat_active = CC.latActive
      lka_icon = CC.enabled
    self.aol = AolDataIQ(lka_icon, lat_active)
