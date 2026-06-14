"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from enum import IntFlag


class SubaruSafetyFlagsIQ:
  STOP_AND_GO = 1


class SubaruFlagsIQ(IntFlag):
  STOP_AND_GO = 1
  STOP_AND_GO_MANUAL_PARKING_BRAKE = 2
