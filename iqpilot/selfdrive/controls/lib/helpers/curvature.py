"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

from numpy import clip, interp

from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, MAX_LATERAL_JERK, MIN_SPEED


def _sanitize_plan(headings, curvatures):
  valid_shape = len(headings) == CONTROL_N and len(curvatures) >= CONTROL_N
  if valid_shape:
    return headings, curvatures
  placeholder = [0.0] * CONTROL_N
  return placeholder, placeholder


def _project_future_heading(delay_s: float, headings) -> float:
  return float(interp(delay_s, ModelConstants.T_IDXS[:CONTROL_N], headings))


def _convert_heading_to_curvature(projected_heading: float, speed_mps: float, current_curvature: float, delay_s: float) -> float:
  turning_arc = projected_heading / (speed_mps * delay_s)
  return (2.0 * turning_arc) - current_curvature


def _limit_curvature_rate(target_curvature: float, current_curvature: float, speed_mps: float) -> float:
  curvature_step = MAX_LATERAL_JERK / (speed_mps ** 2)
  lower = current_curvature - (curvature_step * DT_MDL)
  upper = current_curvature + (curvature_step * DT_MDL)
  return float(clip(target_curvature, lower, upper))


def solve_lag_curvature(steer_delay, v_ego, psis, curvatures):
  headings, curvature_track = _sanitize_plan(psis, curvatures)
  speed_mps = max(MIN_SPEED, v_ego)
  delay_s = max(float(steer_delay), 1e-3)
  current_curvature = float(curvature_track[0])
  projected_heading = _project_future_heading(delay_s, headings)
  target_curvature = _convert_heading_to_curvature(projected_heading, speed_mps, current_curvature, delay_s)
  return _limit_curvature_rate(target_curvature, current_curvature, speed_mps)


get_lag_adjusted_curvature = solve_lag_curvature
