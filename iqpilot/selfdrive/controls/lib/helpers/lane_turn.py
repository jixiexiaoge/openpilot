"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import custom

from openpilot.common.constants import CV
from openpilot.common.params import Params

TurnDirection = custom.IQModelDataV2.TurnDirection

TURN_TRIGGER_MPS = 20 * CV.MPH_TO_MS
TURN_SPEED_GATE_MPS = TURN_TRIGGER_MPS
LANE_CHANGE_SPEED_MIN = TURN_SPEED_GATE_MPS


class TurnSignalPlanner:
  _STEP = 50

  def __init__(self, desire_hub):
    self._hub = desire_hub
    self._kv = Params()
    self._cache = {
      "on": False,
      "mps": TURN_TRIGGER_MPS,
      "choice": TurnDirection.none,
      "frame": 0,
    }
    self.reload_setup()

  @staticmethod
  def _as_float(raw) -> float:
    try:
      return float(raw) * CV.MPH_TO_MS
    except (TypeError, ValueError):
      return TURN_TRIGGER_MPS

  def _pull_setup(self) -> None:
    self._cache["on"] = self._kv.get_bool("LaneTurnDesire")
    raw = self._kv.get("LaneTurnValue", return_default=True)
    self._cache["mps"] = min(float(TURN_TRIGGER_MPS), self._as_float(raw))

  def _pick(self, blocked_l: bool, blocked_r: bool, blink_l: bool, blink_r: bool, speed_mps: float):
    if speed_mps >= self._cache["mps"]:
      return TurnDirection.none
    if blink_l and not blink_r and not blocked_l:
      return TurnDirection.turnLeft
    if blink_r and not blink_l and not blocked_r:
      return TurnDirection.turnRight
    return TurnDirection.none

  def reload_setup(self):
    self._pull_setup()

  def heartbeat(self) -> None:
    if (self._cache["frame"] % self._STEP) == 0:
      self._pull_setup()
    self._cache["frame"] += 1

  def sample(self,
             blocked_l: bool = False,
             blocked_r: bool = False,
             blink_l: bool = False,
             blink_r: bool = False,
             speed_mps: float = 0.0,
             **legacy) -> None:
    blocked_l = bool(legacy.get("blindspot_left", blocked_l))
    blocked_r = bool(legacy.get("blindspot_right", blocked_r))
    blink_l = bool(legacy.get("left_blinker", blink_l))
    blink_r = bool(legacy.get("right_blinker", blink_r))
    speed_mps = float(legacy.get("v_ego", speed_mps))
    self._cache["choice"] = self._pick(blocked_l, blocked_r, blink_l, blink_r, speed_mps)

  def output(self):
    return self._cache["choice"] if self._cache["on"] else TurnDirection.none

  @property
  def enabled(self):
    return self._cache["on"]

  @enabled.setter
  def enabled(self, value):
    self._cache["on"] = bool(value)

  @property
  def speed_gate(self):
    return self._cache["mps"]

  @speed_gate.setter
  def speed_gate(self, value):
    self._cache["mps"] = float(value)

  @property
  def turn_direction(self):
    return self._cache["choice"]

  @turn_direction.setter
  def turn_direction(self, value):
    self._cache["choice"] = value


class LaneTurnController(TurnSignalPlanner):
  def __init__(self, desire_helper):
    super().__init__(desire_helper)

  def read_params(self):
    self.reload_setup()

  def update_params(self) -> None:
    self.heartbeat()

  def update_lane_turn(self,
                       blindspot_left: bool,
                       blindspot_right: bool,
                       left_blinker: bool,
                       right_blinker: bool,
                       v_ego: float) -> None:
    self.sample(blocked_l=blindspot_left,
                blocked_r=blindspot_right,
                blink_l=left_blinker,
                blink_r=right_blinker,
                speed_mps=v_ego)

  def get_turn_direction(self):
    return self.output()

  @property
  def lane_turn_value(self):
    return self.speed_gate

  @lane_turn_value.setter
  def lane_turn_value(self, value):
    self.speed_gate = value
