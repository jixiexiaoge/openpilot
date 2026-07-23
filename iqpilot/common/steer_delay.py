"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Chooses which steer-actuator delay the lateral controllers run with: the value the
live estimator learned, or the driver's fixed software delay — gated by the
"LagdToggle" param. The pick is mirrored into "LagdValueCache" so consumers that do
not subscribe to liveDelay can still read the current value.
"""
from openpilot.common.params import Params

_ENABLE_KEY = "LagdToggle"
_FIXED_KEY = "LagdToggleDelay"
_CACHE_KEY = "LagdValueCache"


def resolve_steer_delay(params, stock_delay):
  """Learned lateral delay while live-learning is enabled, otherwise the stock delay."""
  if not params.get_bool(_ENABLE_KEY):
    return stock_delay
  return float(params.get(_CACHE_KEY, return_default=True))


def cached_steer_delay():
  """Last value SteerDelayPublisher mirrored into the param — usable without a
  liveDelay subscription (e.g. at process startup)."""
  return Params().get(_CACHE_KEY, return_default=True)


class SteerDelayPublisher:
  """Refreshes LagdValueCache every lag message: the learned live delay when the
  toggle is on, else the actuator delay plus the driver's fixed software offset."""

  def __init__(self, car_params):
    self._params = Params()
    self._actuator_delay = car_params.steerActuatorDelay

  def _fixed_delay(self):
    return self._actuator_delay + self._params.get(_FIXED_KEY, return_default=True)

  def update(self, lag_msg):
    live = self._params.get_bool(_ENABLE_KEY)
    value = lag_msg.liveDelay.lateralDelay if live else self._fixed_delay()
    self._params.put_nonblocking(_CACHE_KEY, value)
