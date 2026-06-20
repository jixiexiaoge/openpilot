"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
#!/usr/bin/env python3
import math
import time
import numpy as np

from cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.drive_helpers import MIN_SPEED
from openpilot.selfdrive.controls.lib.lateral_mpc_lib.lat_mpc import LateralMpc
from openpilot.selfdrive.controls.lib.lateral_mpc_lib.lat_mpc import N as LAT_MPC_N


TRAJECTORY_SIZE = 33
CAMERA_OFFSET = 0.0

PATH_COST = 1.0
LATERAL_MOTION_COST = 0.11
LATERAL_ACCEL_COST = 0.0
LATERAL_JERK_COST = 0.04
STEERING_RATE_COST = 700.0


def _clamp(num: float, min_value: float, max_value: float) -> float:
  if min_value > num > max_value:
    return (min_value + max_value) * 0.5
  if num < min_value:
    return min_value
  if num > max_value:
    return max_value
  return num


def _smooth_moving_avg(arr: np.ndarray, window: int = 5) -> np.ndarray:
  if window < 2:
    return arr
  if window % 2 == 0:
    window += 1
  pad = window // 2
  arr_pad = np.pad(arr, (pad, pad), mode='edge')
  kernel = np.ones(window) / window
  return np.convolve(arr_pad, kernel, mode='same')[pad:-pad]


def _yaw_from_path(path_xyz: np.ndarray, v_plan: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
  v0 = float(np.asarray(v_plan)[0]) if len(v_plan) else 0.0
  smooth_window = 9 if v0 <= 6.0 else 5

  n = path_xyz.shape[0]
  x = path_xyz[:, 0].astype(float)
  y = path_xyz[:, 1].astype(float)

  if n < 5:
    return np.zeros(n, np.float32), np.zeros(n, np.float32)

  dx = np.diff(x)
  dy = np.diff(y)
  ds_seg = np.sqrt(dx * dx + dy * dy)
  ds_seg[ds_seg < 0.05] = 0.05
  s = np.zeros(n, float)
  s[1:] = np.cumsum(ds_seg)
  if s[-1] < 0.5:
    return np.zeros(n, np.float32), np.zeros(n, np.float32)

  x_smooth = _smooth_moving_avg(x, smooth_window)
  y_smooth = _smooth_moving_avg(y, smooth_window)

  dx_ds = np.gradient(x_smooth, s)
  dy_ds = np.gradient(y_smooth, s)
  d2x_ds2 = np.gradient(dx_ds, s)
  d2y_ds2 = np.gradient(dy_ds, s)

  yaw = np.unwrap(np.arctan2(dy_ds, dx_ds))

  denom = (dx_ds * dx_ds + dy_ds * dy_ds) ** 1.5
  denom[denom < 1e-9] = 1e-9
  kappa = (dx_ds * d2y_ds2 - dy_ds * d2x_ds2) / denom

  yaw_rate = kappa * np.asarray(v_plan, float)
  if v0 <= 6.0:
    yaw_rate = _smooth_moving_avg(yaw_rate, window=7)

  return yaw.astype(np.float32), yaw_rate.astype(np.float32)


class IQLanePlanner:
  def __init__(self, params: Params):
    self.params = params
    self.ll_t = np.zeros((TRAJECTORY_SIZE,))
    self.ll_x = np.zeros((TRAJECTORY_SIZE,))
    self.lll_y = np.zeros((TRAJECTORY_SIZE,))
    self.rll_y = np.zeros((TRAJECTORY_SIZE,))
    self.le_y = np.zeros((TRAJECTORY_SIZE,))
    self.re_y = np.zeros((TRAJECTORY_SIZE,))
    self.lane_width_estimate = FirstOrderFilter(3.2, 3.0, DT_MDL)
    self.lane_width = 3.2
    self.lane_width_last = self.lane_width
    self.lane_change_multiplier = 1.0

    self.lll_prob = 0.0
    self.rll_prob = 0.0
    self.d_prob = 0.0
    self.lll_std = 0.0
    self.rll_std = 0.0

    self.l_lane_change_prob = 0.0
    self.r_lane_change_prob = 0.0

    self.lane_width_left = 0.0
    self.lane_width_right = 0.0
    self.lane_width_left_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_width_right_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_offset_filtered = FirstOrderFilter(0.0, 2.0, DT_MDL)

    self.lanefull_mode = True
    self.d_prob_count = 0

  def parse_model(self, md) -> None:
    lane_lines = md.laneLines
    edges = md.roadEdges

    if len(lane_lines) >= 4 and len(lane_lines[0].t) == TRAJECTORY_SIZE:
      self.ll_t = (np.array(lane_lines[1].t) + np.array(lane_lines[2].t)) / 2
      self.ll_x = lane_lines[1].x
      self.lll_y = np.array(lane_lines[1].y)
      self.rll_y = np.array(lane_lines[2].y)
      self.lll_prob = md.laneLineProbs[1]
      self.rll_prob = md.laneLineProbs[2]
      self.lll_std = md.laneLineStds[1]
      self.rll_std = md.laneLineStds[2]

    if len(edges[0].t) == TRAJECTORY_SIZE:
      self.le_y = np.array(edges[0].y) + md.roadEdgeStds[0] * 0.4
      self.re_y = np.array(edges[1].y) - md.roadEdgeStds[1] * 0.4
    else:
      self.le_y = self.lll_y
      self.re_y = self.rll_y

    desire_state = md.meta.desireState
    if len(desire_state):
      self.l_lane_change_prob = desire_state[log.Desire.laneChangeLeft]
      self.r_lane_change_prob = desire_state[log.Desire.laneChangeRight]

    try:
      self.lane_width_left = float(md.meta.laneWidthLeft)
      self.lane_width_right = float(md.meta.laneWidthRight)
    except Exception:
      self.lane_width_left = 0.0
      self.lane_width_right = 0.0

  def get_d_path(self, v_ego: float, path_t: np.ndarray, path_xyz: np.ndarray,
                 adjust_lane_offset: float, input_time_offset: float, path_offset: float) -> tuple[np.ndarray, bool]:
    l_prob, r_prob = self.lll_prob, self.rll_prob
    width_pts = self.rll_y - self.lll_y

    prob_mods = []
    for t_check in (0.0, 1.5, 3.0):
      width_at_t = np.interp(t_check * (v_ego + 7), self.ll_x, width_pts)
      prob_mods.append(np.interp(width_at_t, [4.5, 6.0], [1.0, 0.0]))
    mod = min(prob_mods)
    l_prob *= mod
    r_prob *= mod

    l_prob *= np.interp(self.lll_std, [0.15, 0.3], [1.0, 0.0])
    r_prob *= np.interp(self.rll_std, [0.15, 0.3], [1.0, 0.0])

    current_lane_width = abs(self.rll_y[0] - self.lll_y[0])
    both_lane_available = l_prob > 0.5 and r_prob > 0.5 and self.lane_change_multiplier > 0.5
    if both_lane_available:
      self.lane_width_estimate.update(current_lane_width)
      self.lane_width_last = self.lane_width_estimate.x
    else:
      self.lane_width_estimate.update(self.lane_width_last)

    self.lane_width = self.lane_width_estimate.x
    clipped_lane_width = min(4.0, self.lane_width)
    path_from_left_lane = self.lll_y + clipped_lane_width / 2.0
    path_from_right_lane = self.rll_y - clipped_lane_width / 2.0

    self.d_prob = max(l_prob, r_prob) if not both_lane_available else 1.0

    if self.lane_width_left > 0:
      self.lane_width_left_filtered.update(self.lane_width_left)
    if self.lane_width_right > 0:
      self.lane_width_right_filtered.update(self.lane_width_right)

    adjust_curve_offset = 0.0
    adjust_limit = 0.4

    offset_curve = np.interp(0.0, [50, 200], [adjust_curve_offset, 0.0]) * np.sign(0.0)
    offset_lane = 0.0
    if self.lane_width_left_filtered.x <= 2.2 and self.lane_width_right_filtered.x > self.lane_width_left_filtered.x:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, -adjust_lane_offset])
    elif self.lane_width_right_filtered.x <= 2.2 and self.lane_width_left_filtered.x > self.lane_width_right_filtered.x:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, adjust_lane_offset])

    if self.lane_width < 2.5:
      if r_prob > 0.5 and self.lane_width_right_filtered.x < self.lane_width_left_filtered.x:
        lane_path_y = path_from_right_lane
      elif l_prob > 0.5 and self.lane_width_left_filtered.x < 2.0:
        lane_path_y = path_from_left_lane
      else:
        lane_path_y = path_from_left_lane if l_prob > 0.5 or l_prob > r_prob else path_from_right_lane
    elif l_prob > 0.7 and r_prob > 0.7:
      lane_path_y = (path_from_left_lane + path_from_right_lane) / 2.0
    else:
      lane_path_y = (l_prob * path_from_left_lane + r_prob * path_from_right_lane) / (l_prob + r_prob + 1e-4)

    diff_center = 0.0
    if offset_curve * offset_lane < 0:
      offset_total = np.clip(offset_curve + offset_lane + diff_center, -adjust_limit, adjust_limit)
    else:
      offset_total = np.clip(max(offset_curve, offset_lane, key=abs) + diff_center, -adjust_limit, adjust_limit)

    self.d_prob *= self.lane_change_multiplier
    if self.lane_change_multiplier >= 0.5:
      self.lane_offset_filtered.update(np.interp(self.d_prob, [0, 0.3], [0, offset_total]))

    self.d_prob *= np.interp(v_ego * 3.6, [5.0, 10.0], [0.0, 1.0])

    laneline_active = False
    self.d_prob_count = self.d_prob_count + 1 if self.d_prob > 0.3 else 0
    if self.lanefull_mode and self.d_prob_count > int(1 / DT_MDL):
      laneline_active = True
      safe_idxs = np.isfinite(self.ll_t)
      if safe_idxs[0]:
        lane_path_y_interp = np.interp(path_t * (1.0 + input_time_offset), self.ll_t[safe_idxs], lane_path_y[safe_idxs])
        path_xyz[:, 1] = self.d_prob * lane_path_y_interp + (1.0 - self.d_prob) * path_xyz[:, 1]

    path_xyz[:, 1] += CAMERA_OFFSET + self.lane_offset_filtered.x + path_offset
    return path_xyz, laneline_active


class IQLanePlannerController:
  def __init__(self, CP):
    self.factor1 = CP.wheelbase - CP.centerToFront
    self.factor2 = (CP.centerToFront * CP.mass) / (CP.wheelbase * CP.tireStiffnessRear)

    self.params = Params()
    self.lp = IQLanePlanner(self.params)
    self.lat_mpc = LateralMpc()
    self.x0 = np.zeros(4)
    self.v_plan = np.ones((TRAJECTORY_SIZE,)) * MIN_SPEED
    self.path_xyz = np.zeros((TRAJECTORY_SIZE, 3))
    self.plan_yaw = np.zeros((TRAJECTORY_SIZE,))
    self.plan_yaw_rate = np.zeros((TRAJECTORY_SIZE,))
    self.t_idxs = np.arange(TRAJECTORY_SIZE, dtype=float)

    self.lanelines_active = False
    self.solution_invalid_cnt = 0
    self.last_cloudlog_t = 0.0

    self.use_lane_line_speed_kph = 0.0
    self.path_offset = 0.0
    self.adjust_lane_offset = 0.0
    self.input_time_offset = 0.04
    self.path_cost = PATH_COST
    self.lateral_motion_cost = LATERAL_MOTION_COST
    self.lateral_accel_cost = LATERAL_ACCEL_COST
    self.lateral_jerk_cost = LATERAL_JERK_COST
    self.steering_rate_cost = STEERING_RATE_COST
    self.read_params = 0
    self.mode_status = "OFF"
    self.compute_every = 5
    self.compute_frame = 0
    self.last_desired_curvature: float | None = None

  def _read_params(self) -> None:
    def get_num(key: str, default: float) -> float:
      v = self.params.get(key, return_default=True)
      if v is None:
        return default
      if isinstance(v, bytes):
        try:
          v = v.decode('utf-8')
        except Exception:
          return default
      try:
        return float(v)
      except Exception:
        return default

    self.use_lane_line_speed_kph = get_num("IQLanePlannerUseLaneLineSpeed", 0.0)
    self.path_offset = get_num("IQLanePlannerPathOffset", 0.0) * 0.01
    self.adjust_lane_offset = get_num("IQLanePlannerAdjustLaneOffset", 0.0) * 0.01
    self.input_time_offset = get_num("IQLanePlannerInputTimeOffset", 4.0) * 0.01
    self.path_cost = get_num("IQLanePlannerMpcPathCost", 100.0) * 0.01
    self.lateral_motion_cost = get_num("IQLanePlannerMpcMotionCost", 11.0) * 0.01
    self.lateral_accel_cost = get_num("IQLanePlannerMpcAccelCost", 0.0) * 0.01
    self.lateral_jerk_cost = get_num("IQLanePlannerMpcJerkCost", 4.0) * 0.01
    self.steering_rate_cost = get_num("IQLanePlannerMpcSteeringRateCost", 700.0)

  def reset(self, measured_curvature: float, v_ego: float) -> None:
    self.x0 = np.zeros(4)
    self.lat_mpc.reset(x0=self.x0)
    self.x0[3] = measured_curvature * max(v_ego, MIN_SPEED)

  def update(self, sm, measured_curvature: float) -> float | None:
    self.compute_frame += 1
    if self.compute_frame % self.compute_every != 0:
      return self.last_desired_curvature

    self.read_params -= 1
    if self.read_params <= 0:
      self.read_params = 100
      self._read_params()

    md = sm['modelV2']
    v_ego = max(sm['carState'].vEgo, MIN_SPEED)
    speed_kph = v_ego * 3.6

    if len(md.position.x) != TRAJECTORY_SIZE or len(md.orientation.x) != TRAJECTORY_SIZE:
      self.mode_status = "MODEL_FALLBACK"
      self.last_desired_curvature = None
      return None

    path_xyz = np.column_stack([md.position.x, md.position.y, md.position.z])
    t_idxs = np.array(md.position.t)
    plan_yaw = np.array(md.orientation.z)
    plan_yaw_rate = np.array(md.orientationRate.z)
    velocity_xyz = np.column_stack([md.velocity.x, md.velocity.y, md.velocity.z])
    # This branch does not expose drive_helpers.get_speed_error; use model velocity directly.
    car_speed = np.linalg.norm(velocity_xyz, axis=1)
    v_plan = np.clip(car_speed, MIN_SPEED, np.inf)

    self.lp.parse_model(md)
    lane_changing = False
    try:
      lane_changing = md.meta.desire != log.Desire.none
    except Exception:
      try:
        desire_state = md.meta.desireState
        if len(desire_state) > log.Desire.laneChangeRight:
          lane_changing = (desire_state[log.Desire.laneChangeLeft] + desire_state[log.Desire.laneChangeRight]) > 0.02
      except Exception:
        lane_changing = False
    self.lp.lane_change_multiplier = 0.0 if lane_changing else 1.0
    self.lp.lanefull_mode = speed_kph >= self.use_lane_line_speed_kph
    path_xyz, self.lanelines_active = self.lp.get_d_path(v_ego, t_idxs, path_xyz,
                                                         self.adjust_lane_offset, self.input_time_offset, self.path_offset)
    self.mode_status = "LANELINE" if self.lanelines_active else "LANELESS"

    if self.lanelines_active:
      plan_yaw, plan_yaw_rate = _yaw_from_path(path_xyz, v_plan)

    self.lat_mpc.set_weights(self.path_cost, self.lateral_motion_cost, self.lateral_accel_cost,
                             self.lateral_jerk_cost, self.steering_rate_cost)
    y_pts = path_xyz[:LAT_MPC_N + 1, 1]
    heading_pts = plan_yaw[:LAT_MPC_N + 1]
    yaw_rate_pts = plan_yaw_rate[:LAT_MPC_N + 1]

    lateral_factor = np.clip(self.factor1 - (self.factor2 * v_plan ** 2), 0.0, np.inf)
    p = np.column_stack([v_plan, lateral_factor])

    try:
      self.lat_mpc.run(self.x0, p, y_pts, heading_pts, yaw_rate_pts)
      self.x0[3] = np.interp(DT_MDL, t_idxs[:LAT_MPC_N + 1], self.lat_mpc.x_sol[:, 3])
    except Exception:
      self.reset(measured_curvature, v_ego)
      self.mode_status = "MODEL_FALLBACK"
      self.last_desired_curvature = None
      return None

    mpc_nans = np.isnan(self.lat_mpc.x_sol[:, 3]).any()
    if mpc_nans or self.lat_mpc.solution_status != 0:
      self.reset(measured_curvature, v_ego)
      self.mode_status = "MODEL_FALLBACK"
      self.last_desired_curvature = None
      t = time.monotonic()
      if t > self.last_cloudlog_t + 5.0:
        self.last_cloudlog_t = t
        cloudlog.warning("lane_planner_2 mpc invalid, fallback to model curvature")
      return None

    if self.lat_mpc.cost > 1e6 or mpc_nans:
      self.solution_invalid_cnt += 1
      self.mode_status = "MODEL_FALLBACK"
      self.last_desired_curvature = None
      return None
    self.solution_invalid_cnt = 0

    v_for_curvature = max(float(v_plan[0]), MIN_SPEED)
    desired_curvature = float(self.x0[3] / v_for_curvature)
    self.last_desired_curvature = desired_curvature if math.isfinite(desired_curvature) else None
    return self.last_desired_curvature
