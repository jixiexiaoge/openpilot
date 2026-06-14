"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import StrEnum
from collections import namedtuple

from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.hyundai.values import CAR

from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.iqpilot.car.hyundai.values import HyundaiFlagsIQ
from opendbc.iqpilot.aol_base import AolCarStateBase
from opendbc.can.parser import CANParser

ButtonType = structs.CarState.ButtonEvent.Type

AolDataIQ = namedtuple("AolDataIQ",
                        ["enable_aol", "lat_active", "disengaging", "paused"])


class AolCarController:
  def __init__(self):
    self.aol = AolDataIQ(False, False, False, False)

    self.lat_disengage_blink = 0
    self.lat_disengage_init = False
    self.prev_lat_active = False

    self.lkas_icon = 0
    self.lfa_icon = 0

  # display LFA "white_wheel" and LKAS "White car + lanes" when not CC.latActive
  def aol_status_update(self, CC: structs.CarControl, CC_IQ: structs.IQCarControl, frame: int) -> AolDataIQ:
    enable_aol = CC_IQ.aol.available

    if CC.latActive:
      self.lat_disengage_init = False
    elif self.prev_lat_active:
      self.lat_disengage_init = True

    if not self.lat_disengage_init:
      self.lat_disengage_blink = frame

    paused = CC_IQ.aol.enabled and not CC.latActive
    disengaging = (frame - self.lat_disengage_blink) * DT_CTRL < 1.0 if self.lat_disengage_init else False

    self.prev_lat_active = CC.latActive

    return AolDataIQ(enable_aol, CC.latActive, disengaging, paused)

  def create_lkas_icon(self, CP: structs.CarParams, enabled: bool) -> int:
    if self.aol.enable_aol:
      lkas_icon = 2 if self.aol.lat_active else 3 if self.aol.disengaging else 1
    else:
      lkas_icon = 2 if enabled else 1

    # Override common signals for KIA_OPTIMA_G4 and KIA_OPTIMA_G4_FL
    if CP.carFingerprint in (CAR.KIA_OPTIMA_G4, CAR.KIA_OPTIMA_G4_FL, CAR.HYUNDAI_KONA_NON_SCC):
      lkas_icon = 3 if (self.aol.lat_active if self.aol.enable_aol else enabled) else 1

    return lkas_icon

  def create_lfa_icon(self, enabled: bool) -> int:
    if self.aol.enable_aol:
      lfa_icon = 2 if self.aol.lat_active else 3 if self.aol.disengaging else 1 if self.aol.paused else 0
    else:
      lfa_icon = 2 if enabled else 0

    return lfa_icon

  def update(self, CP: structs.CarParams, CC: structs.CarControl, CC_IQ: structs.IQCarControl, frame: int) -> None:
    self.aol = self.aol_status_update(CC, CC_IQ, frame)
    self.lkas_icon = self.create_lkas_icon(CP, CC.enabled)
    self.lfa_icon = self.create_lfa_icon(CC.enabled)


class AolCarState(AolCarStateBase):
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.CarParams):
    super().__init__(CP, CP_IQ)
    self.main_cruise_enabled: bool = False

  @staticmethod
  def get_parser(CP, CP_IQ, pt_messages) -> None:
    pass

  def get_main_cruise(self, ret: structs.CarState) -> bool:
    if self.CP_IQ.flags & HyundaiFlagsIQ.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE:
      if any(be.type == ButtonType.mainCruise and be.pressed for be in ret.buttonEvents):
        self.main_cruise_enabled = not self.main_cruise_enabled
    else:
      self.main_cruise_enabled = True

    return self.main_cruise_enabled if ret.cruiseState.available else False

  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    pass

  def update_aol_canfd(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    if not self.CP.openpilotLongitudinalControl:
      cp_cruise_info = cp_cam if self.CP.flags & HyundaiFlags.CANFD_CAMERA_SCC else cp
      ret.cruiseState.available = cp_cruise_info.vl["SCC_CONTROL"]["MainMode_ACC"] == 1
