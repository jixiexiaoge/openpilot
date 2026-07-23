"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Original concept and implementation by SpysyWeeb (github.com/SpysyWeeb)
"""
from iqdbc.car.interfaces import ACCEL_MIN
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL

STANDSTILL_SPEED = 0.05
STANDSTILL_HOLD_SPEED = 0.15
SETTLE_DECEL = 0.80
TAPER_SPEED = 1.0
STOP_KISS_DECEL = 0.25
STOP_GAP_MARGIN = 3.0
MIN_GAP_BUDGET = 0.5
PROGRESS_EPS = 0.02
ANTI_CREEP_RATE = 0.50
SETTLE_JERK = 2.5
EMERGENCY_DECEL = 3.0


def read_smooth_stops_enabled(params: Params) -> bool:
  return params.get_bool("IQForceStops")


class SmoothStopController:
  def __init__(self):
    self.params = Params()
    self.frame = 0
    self.enabled = False
    self._v_min = float("inf")
    self._stall_s = 0.0
    self.read_params()

  def read_params(self) -> None:
    self.enabled = read_smooth_stops_enabled(self.params)

  def update(self) -> None:
    if self.frame % int(3 / DT_CTRL) == 0:
      self.read_params()
    self.frame += 1

  def reset(self) -> None:
    self._v_min = float("inf")
    self._stall_s = 0.0

  def want_hold(self, should_stop: bool, v_ego: float, standstill: bool) -> bool:
    return bool(should_stop and (v_ego <= STANDSTILL_SPEED or (standstill and v_ego <= STANDSTILL_HOLD_SPEED)))

  def settle(self, a_target: float, v_ego: float, lead_distance: float, has_lead: bool, last_output: float) -> float:
    landing = STOP_KISS_DECEL + (SETTLE_DECEL - STOP_KISS_DECEL) * min(v_ego / TAPER_SPEED, 1.0)
    a_settle = -landing

    if has_lead and lead_distance > 0.0:
      gap = max(lead_distance - STOP_GAP_MARGIN, MIN_GAP_BUDGET)
      a_settle = min(a_settle, -(v_ego * v_ego) / (2.0 * gap))

    if v_ego < self._v_min - PROGRESS_EPS:
      self._v_min = v_ego
      self._stall_s = 0.0
    else:
      self._stall_s += DT_CTRL
    a_settle -= ANTI_CREEP_RATE * self._stall_s

    a_settle = max(a_settle, ACCEL_MIN)
    target = min(a_settle, a_target)

    if target <= -EMERGENCY_DECEL:
      return target

    step = SETTLE_JERK * DT_CTRL
    return min(max(target, last_output - step), last_output + step)
