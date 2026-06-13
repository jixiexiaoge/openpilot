"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import car

from openpilot.common.constants import CV
from openpilot.common.params import Params


class SignalPauseEngine:
  _KEY_ON = "BlinkerPauseLateralControl"
  _KEY_UNIT = "IsMetric"
  _KEY_GATE = "BlinkerMinLateralControlSpeed"

  def __init__(self):
    self._kv = Params()
    self._state = {"on": False, "metric": False, "gate": 0.0}
    self.reload_setup()

  @staticmethod
  def _one_signal(cs: car.CarState) -> bool:
    return bool(cs.leftBlinker) ^ bool(cs.rightBlinker)

  @staticmethod
  def _as_float(raw) -> float:
    try:
      return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
      return 0.0

  def _pull_setup(self) -> None:
    self._state["on"] = self._kv.get_bool(self._KEY_ON)
    self._state["metric"] = self._kv.get_bool(self._KEY_UNIT)
    self._state["gate"] = self._as_float(self._kv.get(self._KEY_GATE))

  def _gate_mps(self) -> float:
    factor = CV.KPH_TO_MS if self._state["metric"] else CV.MPH_TO_MS
    return self._state["gate"] * factor

  def reload_setup(self) -> None:
    self._pull_setup()

  def heartbeat(self) -> None:
    self._pull_setup()

  def is_paused(self, cs: car.CarState) -> bool:
    return bool(self._state["on"] and self._one_signal(cs) and cs.vEgo < self._gate_mps())

  @property
  def enabled(self):
    return self._state["on"]

  @enabled.setter
  def enabled(self, value):
    self._state["on"] = bool(value)

  @property
  def is_metric(self):
    return self._state["metric"]

  @is_metric.setter
  def is_metric(self, value):
    self._state["metric"] = bool(value)

  @property
  def min_speed(self):
    return self._state["gate"]

  @min_speed.setter
  def min_speed(self, value):
    self._state["gate"] = float(value)


class BlinkerPauseLateral(SignalPauseEngine):
  def __init__(self):
    super().__init__()

  def get_params(self) -> None:
    self.reload_setup()

  def update(self, cs: car.CarState) -> bool:
    return self.is_paused(cs)
