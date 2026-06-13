"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import log

from opendbc.car import structs
from openpilot.common.params import Params


class LagdToggle:
  def __init__(self, CP: structs.CarParams):
    self.CP = CP
    self.params = Params()
    self.lag = 0.0

    self.lagd_toggle = self.params.get_bool("LagdToggle")
    self.software_delay = self.params.get("LagdToggleDelay", return_default=True)

  def read_params(self) -> None:
    self.lagd_toggle = self.params.get_bool("LagdToggle")
    self.software_delay = self.params.get("LagdToggleDelay", return_default=True)

  def update(self, lag_msg: log.LiveDelayData) -> None:
    self.read_params()

    if not self.lagd_toggle:
      steer_actuator_delay = self.CP.steerActuatorDelay
      delay = self.software_delay
      self.lag = (steer_actuator_delay + delay)
      self.params.put_nonblocking("LagdValueCache", self.lag)
      return

    lateral_delay = lag_msg.liveDelay.lateralDelay
    self.lag = lateral_delay
    self.params.put_nonblocking("LagdValueCache", self.lag)
