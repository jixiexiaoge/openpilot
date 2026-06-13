
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import StrEnum

from opendbc.car import Bus, structs
from opendbc.can.parser import CANParser
from opendbc.car.chrysler.values import RAM_HD
from opendbc.iqpilot.car.chrysler.values_ext import BUTTONS


class CarStateExt:
  def __init__(self, CP, CP_IQ):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.button_events = []
    self.button_states = {button.event_type: False for button in BUTTONS}

  def update(self, ret: structs.CarState, ret_iq: structs.IQCarState, can_parsers: dict[StrEnum, CANParser]):
    cp = can_parsers[Bus.pt]

    button_events = []
    for button in BUTTONS:
      state = (cp.vl[button.can_addr][button.can_msg] in button.values)
      if self.button_states[button.event_type] != state:
        event = structs.CarState.ButtonEvent.new_message()
        event.type = button.event_type
        event.pressed = state
        button_events.append(event)
      self.button_states[button.event_type] = state
    self.button_events = button_events

    if self.CP.carFingerprint in RAM_HD:
      ret.steeringAngleDeg = cp.vl["STEERING"]["STEERING_ANGLE"]
