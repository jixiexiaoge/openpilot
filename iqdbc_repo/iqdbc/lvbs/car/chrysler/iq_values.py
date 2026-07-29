"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot Chrysler extension flags + the cruise-button table read by the AOL
cruise-button reader.
"""
from collections import namedtuple
from enum import IntFlag

from iqdbc.car import structs

ButtonType = structs.CarState.ButtonEvent.Type
Button = namedtuple('Button', ['event_type', 'can_addr', 'can_msg', 'values'])

BUTTONS = [
  Button(ButtonType.accelCruise, "CRUISE_BUTTONS", "ACC_Accel", [1]),
  Button(ButtonType.decelCruise, "CRUISE_BUTTONS", "ACC_Decel", [1]),
  Button(ButtonType.cancel, "CRUISE_BUTTONS", "ACC_Cancel", [1]),
  Button(ButtonType.resumeCruise, "CRUISE_BUTTONS", "ACC_Resume", [1]),
]


class ChryslerFlagsIQ(IntFlag):
  NO_MIN_STEERING_SPEED = 1
