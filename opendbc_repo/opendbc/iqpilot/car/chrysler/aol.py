"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import StrEnum
from collections import namedtuple

from opendbc.car import Bus, structs
from opendbc.car.chrysler.values import RAM_CARS

from opendbc.iqpilot.aol_base import AolCarStateBase
from opendbc.can.parser import CANParser

AolDataIQ = namedtuple("AolDataIQ",
                        ["enable_aol", "paused", "lkas_disabled"])

ButtonType = structs.CarState.ButtonEvent.Type


class AolCarController:
  def __init__(self):
    self.aol = AolDataIQ(False, False, False)

  @staticmethod
  def create_lkas_heartbit(packer, lkas_heartbit, aol):
    # LKAS_HEARTBIT (0x2D9) LKAS heartbeat
    values = {s: lkas_heartbit[s] for s in [
      "LKAS_DISABLED",
      "AUTO_HIGH_BEAM",
      "FORWARD_1",
      "FORWARD_2",
      "FORWARD_3",
    ]}

    if aol.enable_aol:
      values["LKAS_DISABLED"] = 1 if aol.lkas_disabled else 0

    return packer.make_can_msg("LKAS_HEARTBIT", 0, values)

  @staticmethod
  def aol_status_update(CC: structs.CarControl, CC_IQ: structs.IQCarControl, CS) -> AolDataIQ:
    enable_aol = CC_IQ.aol.available
    paused = CC_IQ.aol.enabled and not CC.latActive

    if any(be.type == ButtonType.lkas and be.pressed for be in CS.out.buttonEvents):
      CS.lkas_disabled = not CS.lkas_disabled

    return AolDataIQ(enable_aol, paused, CS.lkas_disabled)

  def update(self, CC: structs.CarControl, CC_IQ: structs.IQCarControl, CS) -> None:
    self.aol = self.aol_status_update(CC, CC_IQ, CS)


class AolCarState(AolCarStateBase):
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    super().__init__(CP, CP_IQ)
    self.lkas_heartbit = 0

    self.init_lkas_disabled = False
    self.lkas_disabled = False

  @staticmethod
  def get_parser(CP, pt_messages, cam_messages) -> None:
    if CP.carFingerprint in RAM_CARS:
      pt_messages += [
        ("Center_Stack_2", 1),
      ]
    else:
      pt_messages.append(("TRACTION_BUTTON", 1))
      cam_messages.append(("LKAS_HEARTBIT", 1))

  def get_lkas_button(self, cp, cp_cam):
    if self.CP.carFingerprint in RAM_CARS:
      lkas_button = cp.vl["Center_Stack_2"]["LKAS_Button"]
    else:
      lkas_button = cp.vl["TRACTION_BUTTON"]["TOGGLE_LKAS"]
      self.lkas_heartbit = cp_cam.vl["LKAS_HEARTBIT"]
      if not self.init_lkas_disabled:
        self.lkas_disabled = cp_cam.vl["LKAS_HEARTBIT"]["LKAS_DISABLED"]
        self.init_lkas_disabled = True

    return lkas_button

  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    self.prev_lkas_button = self.lkas_button
    self.lkas_button = self.get_lkas_button(cp, cp_cam)
