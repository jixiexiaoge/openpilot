"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Rivian longitudinal-harness-upgrade carState reader: with the upgrade harness the
right steering-wheel controls and the drive stalk drive the openpilot set speed,
and the harness exposes blind-spot indicators. Only active behind the upgrade flag.
"""
import math
from enum import StrEnum

from iqdbc.car import Bus, structs
from iqdbc.can.parser import CANParser
from iqdbc.car.common.conversions import Conversions as CV
from iqdbc.car.rivian.values import DBC
from iqdbc.lvbs.car.rivian.values import RivianFlagsIQ

ButtonType = structs.CarState.ButtonEvent.Type

_SET_SPEED_MAX = 85 * CV.MPH_TO_MS
_SET_SPEED_MIN = 20 * CV.MPH_TO_MS
_LONG_PRESS_FRAMES = 66
_STALK_HOLD_FRAMES = 50


class IQCarState:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.set_speed = 10
    self.increase_button = False
    self.decrease_button = False
    self.distance_button = 0
    self.increase_counter = 0
    self.decrease_counter = 0
    self.stalk_down_counter = 0

  def _apply_set_speed_buttons(self, ret: structs.CarState, cp_park, cp_adas) -> None:
    was_increasing = self.increase_button
    was_decreasing = self.decrease_button

    self.increase_button = cp_park.vl["WheelButtons"]["RightButton_RightClick"] == 2
    self.decrease_button = cp_park.vl["WheelButtons"]["RightButton_LeftClick"] == 2
    self.increase_counter = self.increase_counter + 1 if self.increase_button else 0
    self.decrease_counter = self.decrease_counter + 1 if self.decrease_button else 0

    metric = cp_adas.vl["Cluster"]["Cluster_Unit"] == 0
    conversion = CV.KPH_TO_MS if metric else CV.MPH_TO_MS
    step = 10.0 if metric else 5.0
    shown = self.set_speed * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)

    # A held button steps to the next round multiple; a tap nudges by one unit.
    if self.increase_button:
      if self.increase_counter % _LONG_PRESS_FRAMES == 0:
        self.set_speed = math.ceil((shown + 1) / step) * step * conversion
      elif not was_increasing:
        self.set_speed += conversion
    if self.decrease_button:
      if self.decrease_counter % _LONG_PRESS_FRAMES == 0:
        self.set_speed = math.floor((shown - 1) / step) * step * conversion
      elif not was_decreasing:
        self.set_speed -= conversion

  def update_longitudinal_upgrade(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp_park = can_parsers[Bus.alt]
    cp_adas = can_parsers[Bus.adas]
    cp = can_parsers[Bus.pt]

    if self.CP.openpilotLongitudinalControl:
      right_scroll = cp_park.vl["WheelButtons"]["RightButton_Scroll"]
      if right_scroll != 255:
        if self.distance_button != right_scroll:
          ret.buttonEvents = [structs.CarState.ButtonEvent(pressed=False, type=ButtonType.gapAdjustCruise)]
        self.distance_button = right_scroll

      self._apply_set_speed_buttons(ret, cp_park, cp_adas)

      if not ret.cruiseState.enabled:
        self.set_speed = ret.vEgoCluster

      # Drive stalk held down (VDM_UserAdasRequest 3/4) for ~0.5s snaps set speed
      # up to the current speed, matching stock Rivian ACC (it never lowers it).
      stalk_down = int(cp.vl["VDM_AdasSts"]["VDM_UserAdasRequest"]) in (3, 4)
      self.stalk_down_counter = self.stalk_down_counter + 1 if stalk_down else 0
      if self.stalk_down_counter == _STALK_HOLD_FRAMES:
        self.set_speed = max(self.set_speed, ret.vEgoCluster)

      self.set_speed = max(_SET_SPEED_MIN, min(self.set_speed, _SET_SPEED_MAX))
      ret.cruiseState.speed = self.set_speed

    if self.CP.enableBsm:
      ret.leftBlindspot = cp_park.vl["BSM_BlindSpotIndicator"]["BSM_BlindSpotIndicator_Left"] != 0
      ret.rightBlindspot = cp_park.vl["BSM_BlindSpotIndicator"]["BSM_BlindSpotIndicator_Right"] != 0

  def update(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    if self.CP_IQ.flags & RivianFlagsIQ.LONGITUDINAL_HARNESS_UPGRADE:
      self.update_longitudinal_upgrade(ret, can_parsers)

  @staticmethod
  def get_parser(CP, CP_IQ) -> dict[StrEnum, CANParser]:
    messages: dict[StrEnum, CANParser] = {}
    if CP_IQ.flags & RivianFlagsIQ.LONGITUDINAL_HARNESS_UPGRADE:
      messages[Bus.alt] = CANParser(DBC[CP.carFingerprint][Bus.alt], [], 5)
    return messages
