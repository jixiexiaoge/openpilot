"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Chrysler cruise-button reader: emits edge ButtonEvents for the ACC steering-wheel
buttons so IQ.Pilot can react to accel/decel/cancel/resume.
"""
from enum import StrEnum

from iqdbc.car import Bus, structs
from iqdbc.can.parser import CANParser
from iqdbc.lvbs.car.chrysler.iq_values import BUTTONS


class IQCarState:
  def __init__(self, CP, CP_IQ):
    self.CP = CP
    self.CP_IQ = CP_IQ
    self.button_events: list = []
    self.button_states = {button.event_type: False for button in BUTTONS}

  def update(self, ret: structs.CarState, ret_iq: structs.IQCarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    cp = can_parsers[Bus.pt]
    events = []
    for button in BUTTONS:
      pressed = cp.vl[button.can_addr][button.can_msg] in button.values
      if pressed != self.button_states[button.event_type]:
        event = structs.CarState.ButtonEvent.new_message()
        event.type = button.event_type
        event.pressed = pressed
        events.append(event)
      self.button_states[button.event_type] = pressed
    self.button_events = events
