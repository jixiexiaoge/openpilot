from __future__ import annotations

import os
from dataclasses import dataclass, field

import capnp
import numpy as np

from cereal import log
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import plan_x_idxs_helper
from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants, Plan
from openpilot.selfdrive.controls.lib.drive_helpers import get_curvature_from_plan

SEND_RAW_PRED = os.getenv("SEND_RAW_PRED")
ConfidenceClass = log.ModelDataV2.ConfidenceClass


def pick_curvature(outputs: dict[str, np.ndarray], plan_rows: np.ndarray, vehicle_speed: float,
                   action_horizon: float, synthetic_lane_logic: bool) -> float:
  direct_signal = None if synthetic_lane_logic else outputs.get("desired_curvature")
  if direct_signal is not None:
    return float(direct_signal[0, 0])

  yaw_track = plan_rows[:, Plan.T_FROM_CURRENT_EULER][:, 2]
  yaw_rate_track = plan_rows[:, Plan.ORIENTATION_RATE][:, 2]
  return float(get_curvature_from_plan(yaw_track, yaw_rate_track, ModelConstants.T_IDXS, vehicle_speed, action_horizon))


@dataclass
class DrivePacketMemory:
  disengage_rollup: np.ndarray = field(default_factory=lambda: np.zeros(
    ModelConstants.CONFIDENCE_BUFFER_LEN * ModelConstants.DISENGAGE_WIDTH, dtype=np.float32))
  brake_watch_5: np.ndarray = field(default_factory=lambda: np.zeros(
    ModelConstants.FCW_5MS2_PROBS_WIDTH, dtype=np.float32))
  brake_watch_3: np.ndarray = field(default_factory=lambda: np.zeros(
    ModelConstants.FCW_3MS2_PROBS_WIDTH, dtype=np.float32))


def _assign_xyz(builder, t_points, x_track, y_track, z_track,
                x_std=None, y_std=None, z_std=None) -> None:
  builder.t = t_points
  builder.x = x_track.tolist()
  builder.y = y_track.tolist()
  builder.z = z_track.tolist()
  if x_std is not None:
    builder.xStd = x_std.tolist()
  if y_std is not None:
    builder.yStd = y_std.tolist()
  if z_std is not None:
    builder.zStd = z_std.tolist()


def _assign_xyva(builder, t_points, x_track, y_track, v_track, a_track,
                 x_std=None, y_std=None, v_std=None, a_std=None) -> None:
  builder.t = t_points
  builder.x = x_track.tolist()
  builder.y = y_track.tolist()
  builder.v = v_track.tolist()
  builder.a = a_track.tolist()
  if x_std is not None:
    builder.xStd = x_std.tolist()
  if y_std is not None:
    builder.yStd = y_std.tolist()
  if v_std is not None:
    builder.vStd = v_std.tolist()
  if a_std is not None:
    builder.aStd = a_std.tolist()


def _fit_path(builder, degree: int, x_track: np.ndarray, y_track: np.ndarray, z_track: np.ndarray) -> None:
  stacked = np.stack([x_track, y_track, z_track], axis=1)
  coeffs = np.polynomial.polynomial.polyfit(ModelConstants.T_IDXS, stacked, deg=degree)
  builder.xCoefficients = coeffs[:, 0].tolist()
  builder.yCoefficients = coeffs[:, 1].tolist()
  builder.zCoefficients = coeffs[:, 2].tolist()


def _lane_snapshot(builder, lane_lines, lane_probs: list[float]) -> None:
  builder.leftY = lane_lines[1].y[0]
  builder.leftProb = lane_probs[1]
  builder.rightY = lane_lines[2].y[0]
  builder.rightProb = lane_probs[2]


def _roll_brake_watch(outputs: dict[str, np.ndarray], memory: DrivePacketMemory, meta_layout) -> bool:
  memory.brake_watch_5[:-1] = memory.brake_watch_5[1:]
  memory.brake_watch_5[-1] = outputs["meta"][0, meta_layout.HARD_BRAKE_5][0]
  memory.brake_watch_3[:-1] = memory.brake_watch_3[1:]
  memory.brake_watch_3[-1] = outputs["meta"][0, meta_layout.HARD_BRAKE_3][0]
  return bool(
    (memory.brake_watch_5 > ModelConstants.FCW_THRESHOLDS_5MS2).all()
    and (memory.brake_watch_3 > ModelConstants.FCW_THRESHOLDS_3MS2).all()
  )


def _confidence_bucket(outputs: dict[str, np.ndarray], memory: DrivePacketMemory, meta_layout, frame_id: int):
  width = ModelConstants.DISENGAGE_WIDTH
  if frame_id % (2 * ModelConstants.MODEL_FREQ) == 0:
    brake_probs = outputs["meta"][0, meta_layout.BRAKE_DISENGAGE]
    gas_probs = outputs["meta"][0, meta_layout.GAS_DISENGAGE]
    steer_probs = outputs["meta"][0, meta_layout.STEER_OVERRIDE]
    takeover_curve = 1 - ((1 - brake_probs) * (1 - gas_probs) * (1 - steer_probs))
    independent = np.r_[takeover_curve[0], np.diff(takeover_curve) / (1 - takeover_curve[:-1])]
    memory.disengage_rollup[:-width] = memory.disengage_rollup[width:]
    memory.disengage_rollup[-width:] = independent

  score = 0.0
  for idx in range(width):
    score += memory.disengage_rollup[idx * width + width - 1 - idx].item() / width

  if score < ModelConstants.RYG_GREEN:
    return ConfidenceClass.green
  if score < ModelConstants.RYG_YELLOW:
    return ConfidenceClass.yellow
  return ConfidenceClass.red


def _write_plan_family(model_packet, driving_packet, outputs: dict[str, np.ndarray]) -> None:
  plan_rows = outputs["plan"][0]
  plan_stds = outputs["plan_stds"][0]
  _assign_xyz(model_packet.position, ModelConstants.T_IDXS, *plan_rows[:, Plan.POSITION].T, *plan_stds[:, Plan.POSITION].T)
  _assign_xyz(model_packet.velocity, ModelConstants.T_IDXS, *plan_rows[:, Plan.VELOCITY].T)
  _assign_xyz(model_packet.acceleration, ModelConstants.T_IDXS, *plan_rows[:, Plan.ACCELERATION].T)
  _assign_xyz(model_packet.orientation, ModelConstants.T_IDXS, *plan_rows[:, Plan.T_FROM_CURRENT_EULER].T)
  _assign_xyz(model_packet.orientationRate, ModelConstants.T_IDXS, *plan_rows[:, Plan.ORIENTATION_RATE].T)
  _fit_path(driving_packet.path, ModelConstants.POLY_PATH_DEGREE, *plan_rows[:, Plan.POSITION].T)


def _write_temporal_pose(model_packet, outputs: dict[str, np.ndarray]) -> None:
  pose_packet = model_packet.temporalPoseDEPRECATED
  if "sim_pose" in outputs:
    half_width = ModelConstants.POSE_WIDTH // 2
    pose_packet.trans = outputs["sim_pose"][0, :half_width].tolist()
    pose_packet.transStd = outputs["sim_pose_stds"][0, :half_width].tolist()
    pose_packet.rot = outputs["sim_pose"][0, half_width:].tolist()
    pose_packet.rotStd = outputs["sim_pose_stds"][0, half_width:].tolist()
    return

  pose_packet.trans = outputs["plan"][0, 0, Plan.VELOCITY].tolist()
  pose_packet.transStd = outputs["plan_stds"][0, 0, Plan.VELOCITY].tolist()
  pose_packet.rot = outputs["plan"][0, 0, Plan.ORIENTATION_RATE].tolist()
  pose_packet.rotStd = outputs["plan_stds"][0, 0, Plan.ORIENTATION_RATE].tolist()


def _write_lane_family(model_packet, driving_packet, outputs: dict[str, np.ndarray]) -> None:
  time_axis = plan_x_idxs_helper(ModelConstants, Plan, outputs)
  model_packet.init("laneLines", 4)
  for lane_idx in range(4):
    lane_builder = model_packet.laneLines[lane_idx]
    _assign_xyz(
      lane_builder,
      time_axis,
      np.array(ModelConstants.X_IDXS),
      outputs["lane_lines"][0, lane_idx, :, 0],
      outputs["lane_lines"][0, lane_idx, :, 1],
    )
  model_packet.laneLineStds = outputs["lane_lines_stds"][0, :, 0, 0].tolist()
  model_packet.laneLineProbs = outputs["lane_lines_prob"][0, 1::2].tolist()
  _lane_snapshot(driving_packet.laneLineMeta, model_packet.laneLines, model_packet.laneLineProbs)

  model_packet.init("roadEdges", 2)
  for edge_idx in range(2):
    edge_builder = model_packet.roadEdges[edge_idx]
    _assign_xyz(
      edge_builder,
      time_axis,
      np.array(ModelConstants.X_IDXS),
      outputs["road_edges"][0, edge_idx, :, 0],
      outputs["road_edges"][0, edge_idx, :, 1],
    )
  model_packet.roadEdgeStds = outputs["road_edges_stds"][0, :, 0, 0].tolist()


def _write_leads(model_packet, outputs: dict[str, np.ndarray]) -> None:
  model_packet.init("leadsV3", 3)
  for lead_idx in range(3):
    lead_builder = model_packet.leadsV3[lead_idx]
    _assign_xyva(
      lead_builder,
      ModelConstants.LEAD_T_IDXS,
      *outputs["lead"][0, lead_idx].T,
      *outputs["lead_stds"][0, lead_idx].T,
    )
    lead_builder.prob = outputs["lead_prob"][0, lead_idx].tolist()
    lead_builder.probTime = ModelConstants.LEAD_T_OFFSETS[lead_idx]


def _write_meta(model_packet, outputs: dict[str, np.ndarray], memory: DrivePacketMemory, meta_layout, frame_id: int) -> None:
  meta = model_packet.meta
  meta.desireState = outputs["desire_state"][0].reshape(-1).tolist()
  meta.desirePrediction = outputs["desire_pred"][0].reshape(-1).tolist()
  meta.engagedProb = outputs["meta"][0, meta_layout.ENGAGED].item()
  meta.init("disengagePredictions")

  pred = meta.disengagePredictions
  pred.t = ModelConstants.META_T_IDXS
  pred.brakeDisengageProbs = outputs["meta"][0, meta_layout.BRAKE_DISENGAGE].tolist()
  pred.gasDisengageProbs = outputs["meta"][0, meta_layout.GAS_DISENGAGE].tolist()
  pred.steerOverrideProbs = outputs["meta"][0, meta_layout.STEER_OVERRIDE].tolist()
  pred.brake3MetersPerSecondSquaredProbs = outputs["meta"][0, meta_layout.HARD_BRAKE_3].tolist()
  pred.brake4MetersPerSecondSquaredProbs = outputs["meta"][0, meta_layout.HARD_BRAKE_4].tolist()
  pred.brake5MetersPerSecondSquaredProbs = outputs["meta"][0, meta_layout.HARD_BRAKE_5].tolist()

  if hasattr(meta_layout, "GAS_PRESS") and hasattr(meta_layout, "BRAKE_PRESS"):
    pred.gasPressProbs = outputs["meta"][0, meta_layout.GAS_PRESS].tolist()
    pred.brakePressProbs = outputs["meta"][0, meta_layout.BRAKE_PRESS].tolist()

  meta.hardBrakePredicted = _roll_brake_watch(outputs, memory, meta_layout)
  model_packet.confidence = _confidence_bucket(outputs, memory, meta_layout, frame_id)


def populate_drive_messages(primary_msg: capnp._DynamicStructBuilder, extended_msg: capnp._DynamicStructBuilder,
                            outputs: dict[str, np.ndarray], action: log.ModelDataV2.Action,
                            memory: DrivePacketMemory, vipc_frame_id: int, vipc_frame_id_extra: int,
                            frame_id: int, frame_drop: float, timestamp_eof: int,
                            model_execution_time: float, valid: bool, meta_layout) -> None:
  frame_age = frame_id - vipc_frame_id if frame_id > vipc_frame_id else 0
  frame_drop_percent = frame_drop * 100
  primary_msg.valid = valid
  extended_msg.valid = valid

  driving_packet = primary_msg.drivingModelData
  driving_packet.frameId = vipc_frame_id
  driving_packet.frameIdExtra = vipc_frame_id_extra
  driving_packet.frameDropPerc = frame_drop_percent
  driving_packet.modelExecutionTime = model_execution_time
  driving_packet.action = action

  model_packet = extended_msg.modelV2
  model_packet.frameId = vipc_frame_id
  model_packet.frameIdExtra = vipc_frame_id_extra
  model_packet.frameAge = frame_age
  model_packet.frameDropPerc = frame_drop_percent
  model_packet.timestampEof = timestamp_eof
  model_packet.modelExecutionTime = model_execution_time
  model_packet.action = action

  _write_plan_family(model_packet, driving_packet, outputs)
  _write_temporal_pose(model_packet, outputs)
  _write_lane_family(model_packet, driving_packet, outputs)
  _write_leads(model_packet, outputs)
  _write_meta(model_packet, outputs, memory, meta_layout, vipc_frame_id)

  if SEND_RAW_PRED:
    model_packet.rawPredictions = outputs["raw_pred"].tobytes()


def populate_odometry_message(msg: capnp._DynamicStructBuilder, outputs: dict[str, np.ndarray],
                              vipc_frame_id: int, vipc_dropped_frames: int,
                              timestamp_eof: int, live_calib_seen: bool) -> None:
  msg.valid = live_calib_seen & (vipc_dropped_frames < 1)
  odo = msg.cameraOdometry
  odo.frameId = vipc_frame_id
  odo.timestampEof = timestamp_eof
  odo.trans = outputs["pose"][0, :3].tolist()
  odo.rot = outputs["pose"][0, 3:].tolist()
  odo.wideFromDeviceEuler = outputs["wide_from_device_euler"][0, :].tolist()
  odo.roadTransformTrans = outputs["road_transform"][0, :3].tolist()
  odo.transStd = outputs["pose_stds"][0, :3].tolist()
  odo.rotStd = outputs["pose_stds"][0, 3:].tolist()
  odo.wideFromDeviceEulerStd = outputs["wide_from_device_euler_stds"][0, :].tolist()
  odo.roadTransformTransStd = outputs["road_transform_stds"][0, :3].tolist()

__all__ = [
  "DrivePacketMemory",
  "pick_curvature",
  "populate_drive_messages",
  "populate_odometry_message",
]
