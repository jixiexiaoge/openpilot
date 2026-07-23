"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from __future__ import annotations

import numpy as np


def _quadratic_series(limit: float, steps: int) -> list[float]:
  peak_index = steps - 1
  return [limit * ((index / peak_index) ** 2) for index in range(steps)]


def _probability_window(*values: float) -> np.ndarray:
  return np.asarray(values, dtype=np.float32)


def _field_group(start: int, stop: int, stride: int) -> slice:
  return slice(start, stop, stride)


_IDX_COUNT = 33
_T_AXIS = _quadratic_series(10.0, _IDX_COUNT)
_X_AXIS = _quadratic_series(192.0, _IDX_COUNT)


class ModelConstants:
  IDX_N = _IDX_COUNT
  T_IDXS = _T_AXIS
  X_IDXS = _X_AXIS
  LEAD_T_IDXS = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
  LEAD_T_OFFSETS = [0.0, 2.0, 4.0]
  META_T_IDXS = [2.0, 4.0, 6.0, 8.0, 10.0]

  MODEL_FREQ = 20
  FEATURE_LEN = 512
  FULL_HISTORY_BUFFER_LEN = 99
  HISTORY_BUFFER_LEN = FULL_HISTORY_BUFFER_LEN
  DESIRE_LEN = 8
  TRAFFIC_CONVENTION_LEN = 2
  NAV_FEATURE_LEN = 256
  NAV_INSTRUCTION_LEN = 150
  LAT_PLANNER_STATE_LEN = 4
  LATERAL_CONTROL_PARAMS_LEN = 2
  PREV_DESIRED_CURV_LEN = 1

  FCW_THRESHOLDS_5MS2 = _probability_window(0.05, 0.05, 0.15, 0.15, 0.15)
  FCW_THRESHOLDS_3MS2 = _probability_window(0.7, 0.7)
  FCW_5MS2_PROBS_WIDTH = 5
  FCW_3MS2_PROBS_WIDTH = 2

  DISENGAGE_WIDTH = 5
  POSE_WIDTH = 6
  WIDE_FROM_DEVICE_WIDTH = 3
  SIM_POSE_WIDTH = 6
  LEAD_WIDTH = 4
  LANE_LINES_WIDTH = 2
  ROAD_EDGES_WIDTH = 2
  PLAN_WIDTH = 15
  DESIRE_PRED_WIDTH = 8
  LAT_PLANNER_SOLUTION_WIDTH = 4
  DESIRED_CURV_WIDTH = 1

  NUM_LANE_LINES = 4
  NUM_ROAD_EDGES = 2
  LEAD_TRAJ_LEN = 6
  DESIRE_PRED_LEN = 4

  PLAN_MHP_N = 5
  LEAD_MHP_N = 2
  PLAN_MHP_SELECTION = 1
  LEAD_MHP_SELECTION = 3

  FCW_THRESHOLD_5MS2_HIGH = 0.15
  FCW_THRESHOLD_5MS2_LOW = 0.05
  FCW_THRESHOLD_3MS2 = 0.7

  CONFIDENCE_BUFFER_LEN = 5
  RYG_GREEN = 0.01165
  RYG_YELLOW = 0.06157
  POLY_PATH_DEGREE = 4


class Plan:
  POSITION = slice(0, 3)
  VELOCITY = slice(3, 6)
  ACCELERATION = slice(6, 9)
  T_FROM_CURRENT_EULER = slice(9, 12)
  ORIENTATION_RATE = slice(12, 15)


class Meta:
  ENGAGED = _field_group(0, 1, 1)
  GAS_DISENGAGE = _field_group(1, 31, 6)
  BRAKE_DISENGAGE = _field_group(2, 31, 6)
  STEER_OVERRIDE = _field_group(3, 31, 6)
  HARD_BRAKE_3 = _field_group(4, 31, 6)
  HARD_BRAKE_4 = _field_group(5, 31, 6)
  HARD_BRAKE_5 = _field_group(6, 31, 6)
  GAS_PRESS = _field_group(31, 55, 4)
  BRAKE_PRESS = _field_group(32, 55, 4)
  LEFT_BLINKER = _field_group(33, 55, 4)
  RIGHT_BLINKER = _field_group(34, 55, 4)


class MetaTombRaider:
  ENGAGED = _field_group(0, 1, 1)
  GAS_DISENGAGE = _field_group(1, 41, 8)
  BRAKE_DISENGAGE = _field_group(2, 41, 8)
  STEER_OVERRIDE = _field_group(3, 41, 8)
  HARD_BRAKE_3 = _field_group(4, 41, 8)
  HARD_BRAKE_4 = _field_group(5, 41, 8)
  HARD_BRAKE_5 = _field_group(6, 41, 8)
  GAS_PRESS = _field_group(7, 41, 8)
  BRAKE_PRESS = _field_group(8, 41, 8)
  LEFT_BLINKER = _field_group(41, 53, 2)
  RIGHT_BLINKER = _field_group(42, 53, 2)


class MetaSimPose:
  ENGAGED = _field_group(0, 1, 1)
  GAS_DISENGAGE = _field_group(1, 36, 7)
  BRAKE_DISENGAGE = _field_group(2, 36, 7)
  STEER_OVERRIDE = _field_group(3, 36, 7)
  HARD_BRAKE_3 = _field_group(4, 36, 7)
  HARD_BRAKE_4 = _field_group(5, 36, 7)
  HARD_BRAKE_5 = _field_group(6, 36, 7)
  GAS_PRESS = _field_group(7, 36, 7)
  LEFT_BLINKER = _field_group(36, 48, 2)
  RIGHT_BLINKER = _field_group(37, 48, 2)
