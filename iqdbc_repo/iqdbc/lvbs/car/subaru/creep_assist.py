"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot Subaru stop-and-go: nudges the ACC out of a standstill it would
otherwise hold. Two variants gated by user flags — an electronic-parking-brake
resume pulse (distance/lead triggered) and a manual-parking-brake hold-timer
resume. Both work by spoofing the camera-bus throttle/brake frames.
"""
import copy
from enum import StrEnum

from iqdbc.car import Bus, structs, DT_CTRL
from iqdbc.car.can_definitions import CanData
from iqdbc.car.interfaces import CarStateBase
from iqdbc.car.subaru.values import SubaruFlags

from iqdbc.lvbs.car.subaru import iq_subarucan
from iqdbc.lvbs.car.subaru.iq_values import SubaruFlagsIQ
from iqdbc.can.parser import CANParser

# EPB resume fires only while the lead is pulling away within this gap band (m).
_RESUME_GAP_MIN = 3.0
_RESUME_GAP_MAX = 4.5
_EPB_PULSE_FRAMES = 15


class IQStopAndGoController:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ
    self.enabled = bool(CP_IQ.flags & (SubaruFlagsIQ.STOP_AND_GO | SubaruFlagsIQ.STOP_AND_GO_MANUAL_PARKING_BRAKE))
    self.manual_parking_brake = bool(CP_IQ.flags & SubaruFlagsIQ.STOP_AND_GO_MANUAL_PARKING_BRAKE)

    self.standstill_since = 0
    self._pulse_left = 0
    self.prev_gap = 0.0

  def _epb_pulse(self, trigger: bool) -> bool:
    # A trigger arms a fixed-length resume pulse; the pulse then plays out frame by frame.
    if self.manual_parking_brake:
      return False
    if trigger:
      self._pulse_left = _EPB_PULSE_FRAMES
    if self._pulse_left > 0:
      self._pulse_left -= 1
      return True
    return False

  def _want_resume(self, CC: structs.CarControl, CS: CarStateBase, frame: int) -> bool:
    if not CC.enabled or not CC.hudControl.leadVisible:
      return False

    gap = CS.es_distance_msg["Close_Distance"]
    standing = CS.out.standstill
    if not standing:
      self.standstill_since = frame

    hold_arm, hold_reset = (0.75, 0.8) if self.CP.flags & SubaruFlags.PREGLOBAL else (0.5, 0.55)
    held_for = (frame - self.standstill_since) * DT_CTRL
    held_long_enough = held_for > hold_arm
    if held_for >= hold_reset:
      self.standstill_since = frame

    lead_pulling_away = _RESUME_GAP_MIN < gap < _RESUME_GAP_MAX and gap > self.prev_gap
    self.prev_gap = gap

    if self.manual_parking_brake:
      return held_long_enough
    return self._epb_pulse(standing and lead_pulling_away)

  def create_creep_assist(self, packer, CC: structs.CarControl, CS: CarStateBase, frame: int) -> list[CanData]:
    if not self.enabled:
      return []

    resume = self._want_resume(CC, CS, frame)
    can_sends = [iq_subarucan.create_throttle(packer, self.CP, CS.throttle_msg, resume and not self.manual_parking_brake)]
    if frame % 2 == 0:
      can_sends.append(iq_subarucan.create_brake_pedal(packer, self.CP, CS.brake_pedal_msg, resume and self.manual_parking_brake))
    return can_sends


class IQStopAndGoState:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ
    self.brake_pedal_msg: dict[str, float] = {}
    self.throttle_msg: dict[str, float] = {}

  def update(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp = can_parsers[Bus.pt]
    self.brake_pedal_msg = copy.copy(cp.vl["Brake_Pedal"])
    if not self.CP.flags & SubaruFlags.HYBRID:
      self.throttle_msg = copy.copy(cp.vl["Throttle"])
