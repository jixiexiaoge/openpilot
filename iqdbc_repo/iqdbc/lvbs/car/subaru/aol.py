"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Always-on-Lateral input adapter for Subaru: turns the dashboard LKAS button into
a carState lkas ButtonEvent so the shared AOL state machine can toggle lateral.
"""
from enum import StrEnum

from iqdbc.car import Bus, structs
from iqdbc.car.subaru.values import SubaruFlags
from iqdbc.lvbs.aol_base import AolCarStateBase
from iqdbc.can.parser import CANParser

_LKAS = structs.CarState.ButtonEvent.Type.lkas

# ES_LKAS_State/LKAS_Dash_State: 0 = neutral, 1 = LKAS shown on, 2 = LKAS shown off
_DASH_ON = 1
_DASH_OFF = 2


class AolCarState(AolCarStateBase):
  def update_aol(self, ret: structs.CarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    if self.CP.flags & SubaruFlags.PREGLOBAL:
      return

    self.prev_lkas_button = self.lkas_button
    self.lkas_button = can_parsers[Bus.cam].vl["ES_LKAS_State"]["LKAS_Dash_State"]

    if self._is_toggle_edge():
      ret.buttonEvents = [*ret.buttonEvents, structs.CarState.ButtonEvent(type=_LKAS, pressed=True)]

  def _is_toggle_edge(self) -> bool:
    # every dash-state change is a deliberate press except the off->on rebound (2 -> 1)
    if self.lkas_button == self.prev_lkas_button:
      return False
    return not (self.prev_lkas_button == _DASH_OFF and self.lkas_button == _DASH_ON)
