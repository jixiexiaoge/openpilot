"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot Subaru extension flags. Selected in apply_iq_car_config() from the user's
stop-and-go params and consumed by the stop-and-go controller and panda safety.
"""
from enum import IntFlag


class SubaruFlagsIQ(IntFlag):
  STOP_AND_GO = 1
  STOP_AND_GO_MANUAL_PARKING_BRAKE = 2


class SubaruSafetyFlagsIQ:
  STOP_AND_GO = 1
