from numpy import clip, interp

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, MIN_SPEED, MAX_LATERAL_JERK
from openpilot.iqpilot.modeld.constants import ModelConstants


def _is_plan_usable(heading_series, curvature_series) -> bool:
  return len(heading_series) == CONTROL_N and len(curvature_series) >= CONTROL_N


def _normalize_plan_input(heading_series, curvature_series):
  if _is_plan_usable(heading_series, curvature_series):
    return heading_series, curvature_series
  fallback = [0.0] * CONTROL_N
  return fallback, fallback


def _bounded_curvature_step(goal_curvature, seed_curvature, speed_value):
  jerk_to_curvature = MAX_LATERAL_JERK / (speed_value ** 2)
  min_band = seed_curvature - jerk_to_curvature * DT_MDL
  max_band = seed_curvature + jerk_to_curvature * DT_MDL
  return float(clip(goal_curvature, min_band, max_band))


def _project_curvature(delay_s, speed_value, heading_series, seed_curvature):
  heading_future = float(interp(delay_s, ModelConstants.T_IDXS[:CONTROL_N], heading_series))
  geometric_curvature = heading_future / (speed_value * delay_s)
  return (2.0 * geometric_curvature) - seed_curvature


def solve_lag_curvature(steer_delay, v_ego, psis, curvatures):
  heading_series, curvature_series = _normalize_plan_input(psis, curvatures)
  speed_value = max(MIN_SPEED, v_ego)
  delay_s = max(float(steer_delay), 1e-3)
  seed_curvature = float(curvature_series[0])
  projected_curvature = _project_curvature(delay_s, speed_value, heading_series, seed_curvature)
  return _bounded_curvature_step(projected_curvature, seed_curvature, speed_value)


get_lag_adjusted_curvature = solve_lag_curvature
