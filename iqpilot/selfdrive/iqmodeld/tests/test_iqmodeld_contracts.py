from __future__ import annotations

import copy

import cereal.messaging as messaging
import numpy as np
from cereal import log

from openpilot.iqpilot.selfdrive.iqmodeld.config import Meta, ModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.messaging import (
  DrivePacketMemory,
  pick_curvature,
  populate_drive_messages,
  populate_odometry_message,
)
from openpilot.iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.parser import ArchiveParser, PhaseParser


def _archive_sample(rng: np.random.Generator) -> dict[str, np.ndarray]:
  return {
    "plan": rng.standard_normal((1, ModelConstants.PLAN_MHP_N * (2 * ModelConstants.IDX_N * ModelConstants.PLAN_WIDTH + ModelConstants.PLAN_MHP_SELECTION)), dtype=np.float32),
    "lane_lines": rng.standard_normal((1, 2 * ModelConstants.NUM_LANE_LINES * ModelConstants.IDX_N * ModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "road_edges": rng.standard_normal((1, 2 * ModelConstants.NUM_ROAD_EDGES * ModelConstants.IDX_N * ModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "pose": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "road_transform": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "sim_pose": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "wide_from_device_euler": rng.standard_normal((1, 2 * ModelConstants.WIDE_FROM_DEVICE_WIDTH), dtype=np.float32),
    "lead": rng.standard_normal((1, ModelConstants.LEAD_MHP_N * (2 * ModelConstants.LEAD_TRAJ_LEN * ModelConstants.LEAD_WIDTH + ModelConstants.LEAD_MHP_SELECTION)), dtype=np.float32),
    "lat_planner_solution": rng.standard_normal((1, 2 * ModelConstants.IDX_N * ModelConstants.LAT_PLANNER_SOLUTION_WIDTH), dtype=np.float32),
    "desired_curvature": rng.standard_normal((1, 2 * ModelConstants.DESIRED_CURV_WIDTH), dtype=np.float32),
    "lead_prob": rng.standard_normal((1, ModelConstants.LEAD_MHP_SELECTION), dtype=np.float32),
    "lane_lines_prob": rng.standard_normal((1, ModelConstants.NUM_LANE_LINES * 2), dtype=np.float32),
    "meta": rng.standard_normal((1, 55), dtype=np.float32),
    "desire_state": rng.standard_normal((1, ModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
    "desire_pred": rng.standard_normal((1, ModelConstants.DESIRE_PRED_LEN * ModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
  }


def _phase_sample(rng: np.random.Generator) -> dict[str, np.ndarray]:
  c = SplitModelConstants
  return {
    "pose": rng.standard_normal((1, 2 * c.POSE_WIDTH), dtype=np.float32),
    "wide_from_device_euler": rng.standard_normal((1, 2 * c.WIDE_FROM_DEVICE_WIDTH), dtype=np.float32),
    "road_transform": rng.standard_normal((1, 2 * c.POSE_WIDTH), dtype=np.float32),
    "lead": rng.standard_normal((1, c.LEAD_MHP_N * (2 * c.LEAD_TRAJ_LEN * c.LEAD_WIDTH + c.LEAD_MHP_SELECTION)), dtype=np.float32),
    "plan": rng.standard_normal((1, c.PLAN_MHP_N * (2 * c.IDX_N * c.PLAN_WIDTH + c.PLAN_MHP_SELECTION)), dtype=np.float32),
    "planplus": rng.standard_normal((1, 2 * c.IDX_N * c.PLAN_WIDTH), dtype=np.float32),
    "action": rng.standard_normal((1, 2 * c.ACTION_WIDTH), dtype=np.float32),
    "desired_curvature": rng.standard_normal((1, 2 * c.DESIRED_CURV_WIDTH), dtype=np.float32),
    "desire_pred": rng.standard_normal((1, c.DESIRE_PRED_LEN * c.DESIRE_PRED_WIDTH), dtype=np.float32),
    "desire_state": rng.standard_normal((1, c.DESIRE_PRED_WIDTH), dtype=np.float32),
    "lane_lines": rng.standard_normal((1, 2 * c.NUM_LANE_LINES * c.IDX_N * c.LANE_LINES_WIDTH), dtype=np.float32),
    "lane_lines_prob": rng.standard_normal((1, c.NUM_LANE_LINES * 2), dtype=np.float32),
    "lead_prob": rng.standard_normal((1, c.LEAD_MHP_SELECTION), dtype=np.float32),
    "lat_planner_solution": rng.standard_normal((1, 2 * c.IDX_N * c.LAT_PLANNER_SOLUTION_WIDTH), dtype=np.float32),
    "meta": rng.standard_normal((1, 55), dtype=np.float32),
    "road_edges": rng.standard_normal((1, 2 * c.NUM_ROAD_EDGES * c.IDX_N * c.LANE_LINES_WIDTH), dtype=np.float32),
    "sim_pose": rng.standard_normal((1, 2 * c.POSE_WIDTH), dtype=np.float32),
  }


def test_archive_parser_contract_snapshot():
  outputs = ArchiveParser().parse_outputs(copy.deepcopy(_archive_sample(np.random.default_rng(7))))

  assert outputs["plan"].shape == (1, 33, 15)
  assert outputs["lane_lines"].shape == (1, 4, 33, 2)
  assert outputs["road_edges"].shape == (1, 2, 33, 2)
  assert outputs["desire_pred"].shape == (1, 4, 8)

  np.testing.assert_allclose(outputs["pose"][0, 0], 0.45617363, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["lane_lines_prob"][0, 2], 0.85733712, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["desire_state"][0, 0], 0.44964141, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["lead_prob"][0, 0], 0.21613698, rtol=1e-6, atol=1e-6)


def test_phase_parser_contract_snapshot():
  raw = _phase_sample(np.random.default_rng(23))
  outputs = {**PhaseParser().parse_vision_outputs(copy.deepcopy(raw)), **PhaseParser().parse_policy_outputs(copy.deepcopy(raw))}

  assert outputs["plan"].shape == (1, 33, 15)
  assert outputs["action"].shape == (1, 2)
  assert outputs["desired_curvature"].shape == (1, 1)
  assert outputs["road_edges"].shape == (1, 2, 33, 2)

  np.testing.assert_allclose(outputs["plan"][0, 0, 0], 0.09684439, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["action"][0, 0], 0.25458091, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["desired_curvature"][0, 0], -0.97072351, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(outputs["lane_lines_prob"][0, 0], 0.20073657, rtol=1e-6, atol=1e-6)


def test_message_population_contract_snapshot():
  raw = _phase_sample(np.random.default_rng(23))
  outputs = {**PhaseParser().parse_vision_outputs(copy.deepcopy(raw)), **PhaseParser().parse_policy_outputs(copy.deepcopy(raw))}
  action = log.ModelDataV2.Action(desiredCurvature=0.031, desiredAcceleration=-0.12, shouldStop=False)

  driving_msg = messaging.new_message("drivingModelData")
  model_msg = messaging.new_message("modelV2")
  odometry_msg = messaging.new_message("cameraOdometry")
  memory = DrivePacketMemory()

  populate_drive_messages(
    driving_msg, model_msg, outputs, action, memory,
    2468, 2470, 2480, 0.05, 123456789, 0.014, True, Meta,
  )
  populate_odometry_message(odometry_msg, outputs, 2468, 0, 123456789, True)

  np.testing.assert_allclose(driving_msg.drivingModelData.laneLineMeta.leftY, -0.21672775, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(model_msg.modelV2.meta.engagedProb, 0.64853197, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(odometry_msg.cameraOdometry.trans[0], 0.0360266, rtol=1e-6, atol=1e-6)
  assert int(model_msg.modelV2.confidence.raw) == 2


def test_curvature_selection_contract_snapshot():
  raw = _phase_sample(np.random.default_rng(23))
  outputs = {**PhaseParser().parse_vision_outputs(copy.deepcopy(raw)), **PhaseParser().parse_policy_outputs(copy.deepcopy(raw))}
  plan_rows = outputs["plan"][0]

  direct = pick_curvature(outputs, plan_rows, 27.5, 0.8, synthetic_lane_logic=False)
  fallback = pick_curvature(outputs, plan_rows, 27.5, 0.8, synthetic_lane_logic=True)

  np.testing.assert_allclose(direct, -0.97072351, rtol=1e-6, atol=1e-6)
  np.testing.assert_allclose(fallback, -0.0689389, rtol=1e-6, atol=1e-6)
