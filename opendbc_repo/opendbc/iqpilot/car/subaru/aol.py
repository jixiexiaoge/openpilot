"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import StrEnum
from opendbc.car import Bus, structs

from opendbc.car.subaru.values import SubaruFlags
from opendbc.iqpilot.aol_base import AolCarStateBase
from opendbc.can.parser import CANParser

ButtonType = structs.CarState.ButtonEvent.Type


class AolCarState(AolCarStateBase):
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    super().__init__(CP, CP_IQ)

  @staticmethod
  def create_lkas_button_events(cur_btn: int, prev_btn: int,
                                buttons_dict: dict[int, structs.CarState.ButtonEvent.Type]) -> list[structs.CarState.ButtonEvent]:
    events: list[structs.CarState.ButtonEvent] = []

    if cur_btn == prev_btn:
      return events

    state_changes = [
      {"pressed": prev_btn != cur_btn and cur_btn != 2 and not (prev_btn == 2 and cur_btn == 1)},
      {"pressed": prev_btn != cur_btn and cur_btn == 2 and cur_btn != 1},
    ]

    for change in state_changes:
      if change["pressed"]:
        events.append(structs.CarState.ButtonEvent(pressed=change["pressed"],
                                                   type=buttons_dict.get(cur_btn, ButtonType.unknown)))
    return events

  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp_cam = can_parsers[Bus.cam]

    self.prev_lkas_button = self.lkas_button
    if not self.CP.flags & SubaruFlags.PREGLOBAL:
      self.lkas_button = cp_cam.vl["ES_LKAS_State"]["LKAS_Dash_State"]

    ret.buttonEvents = self.create_lkas_button_events(self.lkas_button, self.prev_lkas_button, {1: ButtonType.lkas})
