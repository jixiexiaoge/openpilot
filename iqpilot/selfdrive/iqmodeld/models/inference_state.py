"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Common base for the per-process inference/runtime states. It seeds the lateral
steer delay from the cached learned value so every subclass starts with a usable
number before its first liveDelay message arrives.
"""
from openpilot.iqpilot.common.steer_delay import cached_steer_delay


class InferenceStateBase:
  def __init__(self):
    self.lat_delay = cached_steer_delay()
