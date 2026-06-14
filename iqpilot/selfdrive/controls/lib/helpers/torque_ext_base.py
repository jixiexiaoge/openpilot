"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import math

import numpy as np

from openpilot.common.pid import PIDController
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.selfdrive.modeld.constants import ModelConstants

PLAN_SAMPLE_START = 5
LAG_EXTRA_S = 0.0

BASE_P = 0.8
BASE_I = 0.15
PID_SPEED_BP = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]
PID_P_GAIN = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, BASE_P]


def jerk_trace(accel_trace, dt_trace):
  accel_delta = np.diff(accel_trace)
  span = min(len(accel_delta), len(dt_trace))
  if span <= 0:
    return []
  return (accel_delta[:span] / np.array(dt_trace)[:span]).tolist()


def polarity(value):
  return 1.0 if value > 0.0 else (-1.0 if value < 0.0 else 0.0)


def sign(value):
  return polarity(value)


def sign_locked_min(future_vals, seed_val):
  if len(future_vals) == 0:
    return seed_val
  same = [v for v in future_vals if polarity(v) == polarity(seed_val)]
  if len(same) < len(future_vals):
    return 0.0
  return min(same + [seed_val], key=lambda v: abs(v))


class LatControlTorqueExtBase:
  def __init__(self, torque_ctrl, cp, cp_iq, car_if):
    del cp_iq
    self.model_v2 = None
    self.model_valid = False
    self.lac_torque = torque_ctrl
    self.torque_from_lateral_accel_in_torque_space = car_if.torque_from_lateral_accel_in_torque_space()

    self.actual_lateral_jerk = 0.0
    self.lateral_jerk_setpoint = 0.0
    self.lateral_jerk_measurement = 0.0
    self.lookahead_lateral_jerk = 0.0

    self._ff = 0.0
    self._pid = PIDController([PID_SPEED_BP, PID_P_GAIN], BASE_I)
    self._pid_log = None
    self._setpoint = 0.0
    self._measurement = 0.0
    self._roll_compensation = 0.0
    self._lateral_accel_deadzone = 0.0
    self._desired_lateral_accel = 0.0
    self._actual_lateral_accel = 0.0
    self._desired_curvature = 0.0
    self._actual_curvature = 0.0
    self._gravity_adjusted_lateral_accel = 0.0
    self._steer_limited_by_safety = False
    self._output_torque = 0.0

    self.friction_look_ahead_v = [1.4, 2.0]
    self.friction_look_ahead_bp = [9.0, 30.0]
    self.lat_jerk_friction_factor = 0.4
    self.lat_accel_friction_factor = 0.7

    self.t_diffs = np.diff(ModelConstants.T_IDXS)
    self.desired_lat_jerk_time = cp.steerActuatorDelay + LAG_EXTRA_S

  def update_model_v2(self, model_packet):
    self.model_v2 = model_packet
    self.model_valid = self.model_v2 is not None and len(self.model_v2.orientation.x) >= CONTROL_N

  def update_lateral_lag(self, lag):
    self.desired_lat_jerk_time = max(0.01, lag) + LAG_EXTRA_S

  def update_friction_input(self, target_val, measured_val):
    error = target_val - measured_val
    return self.lat_accel_friction_factor * error + self.lat_jerk_friction_factor * self.lookahead_lateral_jerk

  @staticmethod
  def _instant_jerk(car_state, vehicle_model) -> float:
    curv_rate = -vehicle_model.calc_curvature(math.radians(car_state.steeringRateDeg), car_state.vEgo, 0.0)
    return curv_rate * car_state.vEgo ** 2

  def _peek_upper_idx(self, speed_mps: float) -> int:
    lookahead = np.interp(speed_mps, self.friction_look_ahead_bp, self.friction_look_ahead_v)
    return next((i for i, t in enumerate(ModelConstants.T_IDXS) if t > lookahead), 16)

  def update_calculations(self, car_state, vehicle_model, desired_lat_accel):
    self.actual_lateral_jerk = self._instant_jerk(car_state, vehicle_model)
    self.lateral_jerk_setpoint = 0.0
    self.lateral_jerk_measurement = 0.0
    self.lookahead_lateral_jerk = 0.0

    if not self.model_valid:
      return

    horizon_accel = np.interp(self.desired_lat_jerk_time, ModelConstants.T_IDXS, self.model_v2.acceleration.y)
    desired_jerk = (horizon_accel - desired_lat_accel) / self.desired_lat_jerk_time
    forecast = jerk_trace(self.model_v2.acceleration.y, self.t_diffs)
    upper_idx = self._peek_upper_idx(car_state.vEgo)
    sampled_jerk = sign_locked_min(forecast[PLAN_SAMPLE_START:upper_idx], desired_jerk)

    self.lookahead_lateral_jerk = sampled_jerk
    if self.lookahead_lateral_jerk == 0.0:
      self.actual_lateral_jerk = 0.0
      self.lat_accel_friction_factor = 1.0
    self.lateral_jerk_setpoint = self.lat_jerk_friction_factor * self.lookahead_lateral_jerk
    self.lateral_jerk_measurement = self.lat_jerk_friction_factor * self.actual_lateral_jerk


TorqueBrainCore = LatControlTorqueExtBase
