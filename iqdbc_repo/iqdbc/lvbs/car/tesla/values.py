"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from enum import IntFlag


class TeslaFlagsIQ(IntFlag):
  HAS_VEHICLE_BUS = 1  # 3-finger infotainment press signal is present on the VEHICLE bus with the deprecated Tesla harness installed
  COOP_STEERING = 2  # virtual torque blending


class TeslaSafetyFlagsIQ:
  HAS_VEHICLE_BUS = 1


