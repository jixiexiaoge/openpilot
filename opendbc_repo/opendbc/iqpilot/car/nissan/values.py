"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from collections import namedtuple
from opendbc.car import structs


class NissanSafetyFlagsIQ:
  DEFAULT = 0
  LEAF = 1




ButtonType = structs.CarState.ButtonEvent.Type
Button = namedtuple('Button', ['event_type', 'can_addr', 'can_msg', 'values'])


BUTTONS = [
  Button(ButtonType.accelCruise, "CRUISE_THROTTLE", "RES_BUTTON", [1]),
  Button(ButtonType.decelCruise, "CRUISE_THROTTLE", "SET_BUTTON", [1]),
]
