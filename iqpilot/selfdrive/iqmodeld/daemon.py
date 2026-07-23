#!/usr/bin/env python3
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import cereal.messaging as messaging
import numpy as np

from cereal import car, custom, log
from cereal.messaging import PubMaster, SubMaster
from msgq.visionipc import VisionBuf, VisionIpcClient, VisionStreamType
from iqdbc.car.car_helpers import get_demo_car_params
from setproctitle import setproctitle

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.iq_perf import PerfSample, PerfTraceEmitter, PerfTraceRing
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.common.transformations.model import get_warp_matrix
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.drive_helpers import (
  MODEL_SMOOTHING_MAX_TOTAL_SEC,
  dynamic_lat_smooth_extra_seconds,
  get_accel_from_plan,
  smooth_value,
)
from openpilot.selfdrive.locationd.calibration_helpers import get_calibrated_rpy
from openpilot.system import sentry

from openpilot.iqpilot.common.steer_delay import resolve_steer_delay
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import get_active_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.models.inference_state import InferenceStateBase
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import get_model_runner
from openpilot.iqpilot.selfdrive.iqmodeld.camera import CameraOffsetHelper
from openpilot.iqpilot.selfdrive.iqmodeld.config import Plan
from openpilot.iqpilot.selfdrive.iqmodeld.messaging import (
  DrivePacketMemory,
  pick_curvature,
  populate_drive_messages,
  populate_odometry_message,
)
from openpilot.iqpilot.selfdrive.iqmodeld.metadata import select_meta_layout

try:
  from openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx import RoadProjector, WarpContext
except ModuleNotFoundError:
  class WarpContext:
    def __init__(self, *args, **kwargs):
      raise ModuleNotFoundError("openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx is not built")

  class RoadProjector:
    def __init__(self, *args, **kwargs):
      raise ModuleNotFoundError("openpilot.iqpilot.selfdrive.iqmodeld.native.iqmodel_pyx is not built")


PROCESS_NAME = "iqpilot.selfdrive.iqmodeld.daemon"
IQP_NAV_MODEL_INFLUENCE_ENABLED = False
TurnDirection = custom.IQTurnSignalDirection
IQMODEL_EVAL_WARN_US = int(DT_MDL * 1_000_000)
IQMODEL_EVAL_ERROR_US = IQMODEL_EVAL_WARN_US * 2


def _plan_y_std_1s(outputs: dict[str, np.ndarray]) -> float:
  # plan_stds is (batch, IDX_N, PLAN_WIDTH); index 10 ~= 1s ahead (see ModelConstants.T_IDXS),
  # POSITION is an (x, y, z) slice within PLAN_WIDTH so [1] picks the lateral (y) std.
  try:
    return float(outputs["plan_stds"][0, 10, Plan.POSITION][1])
  except (KeyError, IndexError):
    return 0.0


def _model_lat_smooth_max_sec(params: Params) -> float:
  if not params.get_bool("ModelSmoothingEnabled"):
    return 0.0
  try:
    raw = params.get("ModelLatSmoothSec", return_default=True)
    raw = 0 if raw is None else int(raw)
  except (ValueError, TypeError):
    raw = 0
  return min(max(raw, 0), 30) * 0.01


@dataclass
class CaptureStamp:
  frame_id: int = 0
  timestamp_sof: int = 0
  timestamp_eof: int = 0

  @classmethod
  def from_vipc(cls, client: VisionIpcClient) -> "CaptureStamp":
    return cls(client.frame_id, client.timestamp_sof, client.timestamp_eof)


@dataclass(frozen=True)
class StreamLayout:
  dual_camera: bool
  main_is_wide: bool
  primary_stream: VisionStreamType


class ReplayLedger:
  def __init__(self, tensor_shapes: dict[str, tuple[int, ...]], frame_inputs: list[str]):
    self.inputs: dict[str, np.ndarray] = {}
    self.archive: dict[str, np.ndarray] = {}
    self.selectors: dict[str, np.ndarray] = {}
    self._frame_inputs = set(frame_inputs)
    self._pulse_name: str | None = None
    self._pulse_memory: np.ndarray | None = None

    feature_shape = tensor_shapes.get("features_buffer")
    for tensor_name, tensor_shape in tensor_shapes.items():
      if tensor_name in self._frame_inputs:
        continue

      self.inputs[tensor_name] = np.zeros(tensor_shape, dtype=np.float32)
      if len(tensor_shape) != 3 or tensor_shape[1] <= 1:
        continue

      history_len = self._history_length(tensor_shape, feature_shape)
      self.archive[tensor_name] = np.zeros((1, history_len, tensor_shape[2]), dtype=np.float32)
      export_index = self._export_index(tensor_shape, history_len, feature_shape)
      if export_index is not None:
        self.selectors[tensor_name] = export_index

      if tensor_name.startswith("desire"):
        self._pulse_name = tensor_name
        self._pulse_memory = np.zeros(tensor_shape[2], dtype=np.float32)

  @staticmethod
  def _history_length(tensor_shape: tuple[int, ...], feature_shape: tuple[int, ...] | None) -> int:
    if tensor_shape[1] >= 99:
      return tensor_shape[1]
    if tensor_shape[1] in (24, 25) and feature_shape is not None and feature_shape[1] == 24:
      return (feature_shape[1] + 1) * 4
    return tensor_shape[1] * 4

  @staticmethod
  def _export_index(tensor_shape: tuple[int, ...], history_len: int,
                    feature_shape: tuple[int, ...] | None) -> np.ndarray | None:
    if tensor_shape[1] in (24, 25) and feature_shape is not None and feature_shape[1] == 24:
      stride = int(-history_len / tensor_shape[1])
      return np.arange(stride, stride * (tensor_shape[1] + 1), stride)[::-1]
    if tensor_shape[1] == 25:
      skip = history_len // tensor_shape[1]
      return np.arange(history_len)[-1 - (skip * (tensor_shape[1] - 1))::skip]
    if tensor_shape[1] >= 99:
      return np.arange(tensor_shape[1])
    return None

  @property
  def pulse_name(self) -> str:
    if self._pulse_name is None:
      raise KeyError("No desire-like pulse input present in model inputs")
    return self._pulse_name

  def _shift_archive(self, tensor_name: str) -> np.ndarray:
    history = self.archive[tensor_name]
    history[0, :-1] = history[0, 1:]
    return history

  def inject_pulse(self, pulse_values: np.ndarray) -> None:
    pulse = pulse_values.copy()
    pulse[0] = 0
    assert self._pulse_memory is not None
    rising = np.where(pulse - self._pulse_memory > 0.99, pulse, 0)
    self._pulse_memory[:] = pulse

    history = self._shift_archive(self.pulse_name)
    history[0, -1] = rising
    exported_shape = self.inputs[self.pulse_name].shape
    if history.shape[1] > exported_shape[1]:
      stride = history.shape[1] // exported_shape[1]
      self.inputs[self.pulse_name][:] = history[0].reshape(
        exported_shape[0], exported_shape[1], stride, -1
      ).max(axis=2)
      return
    self.inputs[self.pulse_name][:] = history[0, self.selectors[self.pulse_name]]

  def merge_inputs(self, fresh_inputs: dict[str, np.ndarray]) -> None:
    pulse_name = self.pulse_name
    for tensor_name, tensor_value in fresh_inputs.items():
      if tensor_name in self.inputs and tensor_name != pulse_name:
        self.inputs[tensor_name][:] = tensor_value

  def note_hidden_state(self, hidden_state: np.ndarray) -> None:
    if "features_buffer" not in self.archive:
      return
    history = self._shift_archive("features_buffer")
    history[0, -1] = hidden_state[0]
    self.inputs["features_buffer"][:] = history[0, self.selectors["features_buffer"]]

  def note_feedback(self, tensor_name: str, values: np.ndarray, zero_export: bool = False) -> None:
    if tensor_name not in self.archive:
      return
    history = self._shift_archive(tensor_name)
    history[0, -1, :] = values[0]
    exported = history[0, self.selectors[tensor_name]]
    self.inputs[tensor_name][:] = 0 * exported if zero_export else exported


def _planplus_gain(vehicle_speed: float) -> float:
  return 0.75 if vehicle_speed >= 25.0 else 1.0


def _merged_plan(runtime_state: "NeuralEngineState", outputs: dict[str, np.ndarray], vehicle_speed: float) -> np.ndarray:
  base_plan = outputs["plan"][0]
  if "planplus" not in outputs:
    return base_plan
  return base_plan + (runtime_state.PLANPLUS_CONTROL * _planplus_gain(vehicle_speed)) * outputs["planplus"][0]


class NeuralEngineState(InferenceStateBase):
  frames: dict[str, RoadProjector]

  def __init__(self, gpu_context: WarpContext):
    super().__init__()
    runner = get_model_runner()
    bundle = get_active_bundle()

    self.model_runner = runner
    self.constants = runner.constants
    self.generation = bundle.generation if bundle is not None else None

    knob_values = {entry.key: entry.value for entry in bundle.overrides} if bundle is not None else {}
    self.LAT_SMOOTH_SECONDS = float(knob_values.get("lat", ".0"))
    self.LONG_SMOOTH_SECONDS = float(knob_values.get("long", ".0"))
    self.MIN_LAT_CONTROL_SPEED = 0.3
    self.PLANPLUS_CONTROL = 1.0
    self.model_smoothing_max_extra_sec = 0.0

    context_depth = 5 if runner.is_20hz else 2
    self.frames = {
      stream_name: RoadProjector(gpu_context, context_depth)
      for stream_name in runner.vision_input_names
    }

    self._ledger = ReplayLedger(runner.input_shapes, runner.vision_input_names)
    self.numpy_inputs = self._ledger.inputs
    self.temporal_buffers = self._ledger.archive
    self.temporal_idxs_map = self._ledger.selectors

  @property
  def mlsim(self) -> bool:
    return bool(self.generation is not None and self.generation >= 11)

  @property
  def desire_key(self) -> str:
    return self._ledger.pulse_name

  def _warp_frames(self, vision_bufs: dict[str, VisionBuf],
                   transform_map: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
      stream_name: self.frames[stream_name].stage(vision_bufs[stream_name], transform_map[stream_name].flatten())
      for stream_name in self.model_runner.vision_input_names
    }

  def _run_split_model(self) -> dict[str, np.ndarray]:
    if hasattr(self.model_runner, "run_vision"):
      vision_packet = self.model_runner.run_vision()
      self._ledger.note_hidden_state(vision_packet["hidden_state"])
      self.model_runner.refresh_policy_features(self.numpy_inputs["features_buffer"])
      return {**vision_packet, **self.model_runner.run_policy()}

    result = self.model_runner.run_model()
    if "hidden_state" in result:
      self._ledger.note_hidden_state(result["hidden_state"])
    return result

  def _write_curvature_memory(self, outputs: dict[str, np.ndarray]) -> None:
    if "desired_curvature" not in outputs:
      return

    feedback_slot = None
    if "prev_desired_curvs" in self.numpy_inputs:
      feedback_slot = "prev_desired_curvs"
    elif "prev_desired_curv" in self.numpy_inputs:
      feedback_slot = "prev_desired_curv"

    if feedback_slot is not None:
      self._ledger.note_feedback(feedback_slot, outputs["desired_curvature"], zero_export=self.mlsim)

  def run(self, vision_bufs: dict[str, VisionBuf], transform_map: dict[str, np.ndarray],
          fresh_inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray] | None:
    if not getattr(self.model_runner, "uses_opencl_warp", True):
      return self.model_runner.run_fused(vision_bufs, transform_map, fresh_inputs)

    self._ledger.inject_pulse(fresh_inputs[self.desire_key])
    self._ledger.merge_inputs(fresh_inputs)
    warped_frames = self._warp_frames(vision_bufs, transform_map)
    self.model_runner.prepare_inputs(warped_frames, self.numpy_inputs, self.frames)

    outputs = self._run_split_model()
    self._write_curvature_memory(outputs)
    return outputs

  def get_action_from_model(self, outputs: dict[str, np.ndarray], previous_action: log.ModelDataV2.Action,
                            lat_action_t: float, long_action_t: float, vehicle_speed: float,
                            lat_smooth_seconds: float | None = None) -> log.ModelDataV2.Action:
    if lat_smooth_seconds is None:
      lat_smooth_seconds = self.LAT_SMOOTH_SECONDS

    if "action" in outputs:
      curvature_cmd = outputs["action"][0, 0] / (max(1.0, vehicle_speed)) ** 2
      accel_cmd = outputs["action"][0, 1]
      should_stop = bool(vehicle_speed < 0.3 and accel_cmd < 0.1)

      accel_cmd = smooth_value(accel_cmd, previous_action.desiredAcceleration, self.LONG_SMOOTH_SECONDS)
      if vehicle_speed > self.MIN_LAT_CONTROL_SPEED:
        curvature_cmd = smooth_value(curvature_cmd, previous_action.desiredCurvature, lat_smooth_seconds)
      else:
        curvature_cmd = previous_action.desiredCurvature

      return log.ModelDataV2.Action(
        desiredCurvature=float(curvature_cmd),
        desiredAcceleration=float(accel_cmd),
        shouldStop=should_stop,
      )

    plan_rows = _merged_plan(self, outputs, vehicle_speed)
    accel_cmd, should_stop = get_accel_from_plan(
      plan_rows[:, Plan.VELOCITY][:, 0],
      plan_rows[:, Plan.ACCELERATION][:, 0],
      self.constants.T_IDXS,
      action_t=long_action_t,
    )
    accel_cmd = smooth_value(accel_cmd, previous_action.desiredAcceleration, self.LONG_SMOOTH_SECONDS)

    curvature_cmd = pick_curvature(outputs, plan_rows, vehicle_speed, lat_action_t, self.mlsim)
    if self.generation is not None and self.generation >= 10:
      if vehicle_speed > self.MIN_LAT_CONTROL_SPEED:
        curvature_cmd = smooth_value(curvature_cmd, previous_action.desiredCurvature, lat_smooth_seconds)
      else:
        curvature_cmd = previous_action.desiredCurvature

    return log.ModelDataV2.Action(
      desiredCurvature=float(curvature_cmd),
      desiredAcceleration=float(accel_cmd),
      shouldStop=bool(should_stop),
    )


class CameraIngress:
  def __init__(self, gpu_context: WarpContext):
    self.layout = self._discover_layout()
    self._primary = VisionIpcClient("camerad", self.layout.primary_stream, True, gpu_context)
    self._secondary = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, False, gpu_context)

    while not self._primary.connect(False):
      time.sleep(0.1)
    while self.layout.dual_camera and not self._secondary.connect(False):
      time.sleep(0.1)

    cloudlog.warning(
      f"connected main cam with buffer size: {self._primary.buffer_len} ({self._primary.width} x {self._primary.height})"
    )
    if self.layout.dual_camera:
      cloudlog.warning(
        f"connected extra cam with buffer size: {self._secondary.buffer_len} ({self._secondary.width} x {self._secondary.height})"
      )

  @staticmethod
  def _discover_layout() -> StreamLayout:
    while True:
      available = VisionIpcClient.available_streams("camerad", block=False)
      if available:
        dual_camera = (
          VisionStreamType.VISION_STREAM_WIDE_ROAD in available
          and VisionStreamType.VISION_STREAM_ROAD in available
        )
        main_is_wide = VisionStreamType.VISION_STREAM_ROAD not in available
        primary_stream = VisionStreamType.VISION_STREAM_WIDE_ROAD if main_is_wide else VisionStreamType.VISION_STREAM_ROAD
        cloudlog.warning(
          f"vision stream set up, main_wide_camera: {main_is_wide}, use_extra_client: {dual_camera}"
        )
        return StreamLayout(dual_camera=dual_camera, main_is_wide=main_is_wide, primary_stream=primary_stream)
      time.sleep(0.1)

  def pull(self) -> tuple[VisionBuf, VisionBuf, CaptureStamp, CaptureStamp] | None:
    main_buf = None
    wide_buf = None
    main_stamp = CaptureStamp()
    wide_stamp = CaptureStamp()

    while main_stamp.timestamp_sof < wide_stamp.timestamp_sof + 25000000:
      main_buf = self._primary.recv()
      main_stamp = CaptureStamp.from_vipc(self._primary)
      if main_buf is None:
        return None

    if not self.layout.dual_camera:
      return main_buf, main_buf, main_stamp, main_stamp

    while True:
      wide_buf = self._secondary.recv()
      wide_stamp = CaptureStamp.from_vipc(self._secondary)
      if wide_buf is None or main_stamp.timestamp_sof < wide_stamp.timestamp_sof + 25000000:
        break

    if wide_buf is None:
      return None

    if abs(main_stamp.timestamp_sof - wide_stamp.timestamp_sof) > 10000000:
      cloudlog.error(
        f"frames out of sync! main: {main_stamp.frame_id} ({main_stamp.timestamp_sof / 1e9:.5f}),"
        f" extra: {wide_stamp.frame_id} ({wide_stamp.timestamp_sof / 1e9:.5f})"
      )
    return main_buf, wide_buf, main_stamp, wide_stamp


class CalibrationAtlas:
  def __init__(self):
    self.main_warp = np.zeros((3, 3), dtype=np.float32)
    self.extra_warp = np.zeros((3, 3), dtype=np.float32)
    self.ready = False
    self._offset_tuner = CameraOffsetHelper()

  def set_offset(self, offset_value: Any) -> None:
    self._offset_tuner.set_offset(offset_value)

  def refresh(self, sm: SubMaster, main_is_wide: bool, dual_camera: bool) -> tuple[np.ndarray, np.ndarray, bool]:
    if not (sm.seen["liveCalibration"] and sm.seen["roadCameraState"] and sm.seen["deviceState"]):
      return self.main_warp, self.extra_warp, self.ready

    rpy = get_calibrated_rpy(sm["liveCalibration"])
    if rpy is None:
      live_calib = sm["liveCalibration"]
      if len(live_calib.rpyCalib) == 3:
        rpy = np.array(live_calib.rpyCalib, dtype=np.float32)
      else:
        rpy = np.zeros(3, dtype=np.float32)

    device_key = (str(sm["deviceState"].deviceType), str(sm["roadCameraState"].sensor))
    device_camera = DEVICE_CAMERAS[device_key]
    main_intrinsics = device_camera.ecam.intrinsics if main_is_wide else device_camera.fcam.intrinsics
    extra_uses_wide_camera = dual_camera or main_is_wide
    extra_intrinsics = device_camera.ecam.intrinsics if extra_uses_wide_camera else device_camera.fcam.intrinsics
    self.main_warp = get_warp_matrix(rpy, main_intrinsics, False).astype(np.float32)
    self.extra_warp = get_warp_matrix(rpy, extra_intrinsics, True).astype(np.float32)
    self.main_warp, self.extra_warp = self._offset_tuner.update(
      self.main_warp, self.extra_warp, sm, main_is_wide, extra_uses_wide_camera
    )
    self.ready = True
    return self.main_warp, self.extra_warp, self.ready


class FrameDropMeter:
  def __init__(self, model_freq: float):
    self._smoother = FirstOrderFilter(0.0, 10.0, 1.0 / model_freq)
    self._warm_frames = 0
    self._last_frame_id = 0

  def sample(self, frame_id: int) -> tuple[int, float, bool]:
    dropped = max(0, frame_id - self._last_frame_id - 1)
    smooth = self._smoother.update(min(dropped, 10))
    if self._warm_frames < 10:
      self._smoother.x = 0.0
      smooth = 0.0
    self._warm_frames += 1
    return dropped, smooth / (1 + smooth), dropped > 0

  def commit(self, frame_id: int) -> None:
    self._last_frame_id = frame_id


class InferenceDaemon:
  def __init__(self, demo: bool = False):
    cloudlog.warning("iqmodeld init")
    sentry.set_tag("daemon", PROCESS_NAME)
    cloudlog.bind(daemon=PROCESS_NAME)
    setproctitle(PROCESS_NAME)
    config_realtime_process(7, 54)

    cloudlog.warning("setting up CL context")
    self._gpu = WarpContext()
    cloudlog.warning("CL context ready; loading model")
    self._runtime = NeuralEngineState(self._gpu)
    self._meta_layout = select_meta_layout()
    cloudlog.warning("models loaded, iqmodeld starting")

    self._cameras = CameraIngress(self._gpu)
    self._pub = PubMaster(["modelV2", "drivingModelData", "cameraOdometry", "iqDriveModelData", "iqPerfTrace"])
    self._sub = SubMaster([
      "deviceState", "carState", "roadCameraState", "liveCalibration",
      "driverMonitoringState", "carControl", "liveDelay", "iqNavState", "radarState",
    ])
    self._message_memory = DrivePacketMemory()
    self._params = Params()
    self._frame_meter = FrameDropMeter(self._runtime.constants.MODEL_FREQ)
    self._warps = CalibrationAtlas()
    self._perf = PerfTraceEmitter("iqmodeld", pubmaster=self._pub)
    self._perf_ring = PerfTraceRing()

    self._car_params = self._load_car_params(demo)
    self._long_action_delay = self._car_params.longitudinalActuatorDelay + self._runtime.LONG_SMOOTH_SECONDS
    self._previous_action = log.ModelDataV2.Action()
    self._desire_logic = DesireHelper()
    self._lat_smooth_extra_sec = 0.0

  def _load_car_params(self, demo: bool):
    car_params = get_demo_car_params() if demo else messaging.log_from_bytes(
      self._params.get("CarParams", block=True), car.CarParams)
    cloudlog.info("iqmodeld got CarParams: %s", car_params.brand)
    return car_params

  def _refresh_tunables(self, tick: int) -> None:
    if tick % 60 != 0:
      return
    self._runtime.lat_delay = resolve_steer_delay(self._params, self._sub["liveDelay"].lateralDelay)
    self._runtime.PLANPLUS_CONTROL = self._params.get("PlanplusControl", return_default=True)
    self._runtime.model_smoothing_max_extra_sec = _model_lat_smooth_max_sec(self._params)
    self._warps.set_offset(self._params.get("CameraOffset", return_default=True))

  def _traffic_side(self) -> np.ndarray:
    traffic = np.zeros(2, dtype=np.float32)
    traffic[int(self._sub["driverMonitoringState"].isRHD)] = 1
    return traffic

  def _desire_pulse(self) -> np.ndarray:
    pulse = np.zeros(self._runtime.constants.DESIRE_LEN, dtype=np.float32)
    desire_idx = self._desire_logic.desire
    if 0 <= desire_idx < self._runtime.constants.DESIRE_LEN:
      pulse[desire_idx] = 1
    return pulse

  def _compose_inputs(self, vehicle_speed: float, lat_horizon: float, long_horizon: float) -> dict[str, np.ndarray]:
    inputs: dict[str, np.ndarray] = {
      self._runtime.desire_key: self._desire_pulse(),
      "traffic_convention": self._traffic_side(),
    }
    if "lateral_control_params" in self._runtime.numpy_inputs:
      inputs["lateral_control_params"] = np.array([vehicle_speed, lat_horizon], dtype=np.float32)
    if "action_t" in self._runtime.numpy_inputs:
      inputs["action_t"] = np.array([lat_horizon, long_horizon], dtype=np.float32)
    return inputs

  def _publish(self, outputs: dict[str, np.ndarray], main_stamp: CaptureStamp, extra_stamp: CaptureStamp,
               road_frame_id: int, frame_drop_ratio: float, dropped_frames: int,
               execution_time: float, live_calib_seen: bool,
               lat_horizon: float, long_horizon: float, vehicle_speed: float) -> None:
    model_msg = messaging.new_message("modelV2")
    driving_msg = messaging.new_message("drivingModelData")
    pose_msg = messaging.new_message("cameraOdometry")
    iq_msg = messaging.new_message("iqDriveModelData")

    self._lat_smooth_extra_sec = dynamic_lat_smooth_extra_seconds(
      _plan_y_std_1s(outputs), self._runtime.model_smoothing_max_extra_sec
    )
    lat_smooth_total_sec = min(self._runtime.LAT_SMOOTH_SECONDS + self._lat_smooth_extra_sec, MODEL_SMOOTHING_MAX_TOTAL_SEC)
    action = self._runtime.get_action_from_model(
      outputs, self._previous_action, lat_horizon, long_horizon, vehicle_speed, lat_smooth_total_sec
    )
    self._previous_action = action

    populate_drive_messages(
      driving_msg,
      model_msg,
      outputs,
      action,
      self._message_memory,
      main_stamp.frame_id,
      extra_stamp.frame_id,
      road_frame_id,
      frame_drop_ratio,
      main_stamp.timestamp_eof,
      execution_time,
      live_calib_seen,
      self._meta_layout,
    )

    desire_state = model_msg.modelV2.meta.desireState
    lane_change_prob = desire_state[log.Desire.laneChangeLeft] + desire_state[log.Desire.laneChangeRight]
    self._desire_logic.update(
      self._sub["carState"],
      self._sub["carControl"].latActive,
      lane_change_prob,
      self._sub["iqNavState"],
      model_msg.modelV2,
      self._sub["radarState"],
    )
    model_msg.modelV2.meta.laneChangeState = self._desire_logic.lane_change_state
    model_msg.modelV2.meta.laneChangeDirection = self._desire_logic.lane_change_direction
    driving_msg.drivingModelData.meta.laneChangeState = self._desire_logic.lane_change_state
    driving_msg.drivingModelData.meta.laneChangeDirection = self._desire_logic.lane_change_direction
    iq_msg.iqDriveModelData.turnSignalDirection = self._desire_logic.lane_turn_direction

    populate_odometry_message(
      pose_msg,
      outputs,
      main_stamp.frame_id,
      dropped_frames,
      main_stamp.timestamp_eof,
      live_calib_seen,
    )

    self._pub.send("modelV2", model_msg)
    self._pub.send("drivingModelData", driving_msg)
    self._pub.send("cameraOdometry", pose_msg)
    self._pub.send("iqDriveModelData", iq_msg)

  def serve(self) -> None:
    tick = 0
    while True:
      frame_pair = self._cameras.pull()
      if frame_pair is None:
        cloudlog.debug("visionipc frame missing")
        continue

      main_buf, extra_buf, main_stamp, extra_stamp = frame_pair
      self._sub.update(0)
      self._refresh_tunables(tick)

      vehicle_speed = max(self._sub["carState"].vEgo, 0.0)
      lat_horizon = self._runtime.lat_delay + self._runtime.LAT_SMOOTH_SECONDS + self._lat_smooth_extra_sec + DT_MDL
      long_horizon = self._long_action_delay + DT_MDL

      main_warp, extra_warp, live_calib_seen = self._warps.refresh(
        self._sub, self._cameras.layout.main_is_wide, self._cameras.layout.dual_camera
      )
      dropped_frames, frame_drop_ratio, prepare_only = self._frame_meter.sample(main_stamp.frame_id)

      vision_bufs = {
        stream_name: extra_buf if "big" in stream_name else main_buf
        for stream_name in self._runtime.model_runner.vision_input_names
      }
      warp_map = {
        stream_name: extra_warp if "big" in stream_name else main_warp
        for stream_name in self._runtime.model_runner.vision_input_names
      }
      fresh_inputs = self._compose_inputs(vehicle_speed, lat_horizon, long_horizon)

      started_at = time.perf_counter()
      outputs = self._runtime.run(vision_bufs, warp_map, fresh_inputs)
      execution_time = time.perf_counter() - started_at
      execution_us = int(execution_time * 1_000_000)

      sample = PerfSample(
        frame_id=main_stamp.frame_id,
        model_eval_us=execution_us,
        model_dropped_frames=dropped_frames,
        model_backlog=max(0, dropped_frames),
      )
      self._perf_ring.push(sample)
      if dropped_frames > 0 or execution_us >= IQMODEL_EVAL_WARN_US:
        severity = "warning"
        if dropped_frames > 0 or execution_us >= IQMODEL_EVAL_ERROR_US:
          severity = "error"
        self._perf.emit(
          "iqmodeld_dropped_frames" if dropped_frames > 0 else "iqmodeld_slow_eval",
          severity=severity,
          frame_id=main_stamp.frame_id,
          total_time_us=execution_us,
          dropped_frames=dropped_frames,
          backlog=max(0, dropped_frames),
          samples=self._perf_ring.snapshot(),
          detail=(
            f"model_eval_us={execution_us} dropped_frames={dropped_frames} prepare_only={int(prepare_only)} "
            f"road_frame_id={self._sub['roadCameraState'].frameId}"
          ),
          min_interval_s=0.25,
        )

      if outputs is not None:
        self._publish(
          outputs,
          main_stamp,
          extra_stamp,
          self._sub["roadCameraState"].frameId,
          frame_drop_ratio,
          dropped_frames,
          execution_time,
          live_calib_seen,
          lat_horizon,
          long_horizon,
          vehicle_speed,
        )

      self._frame_meter.commit(main_stamp.frame_id)
      tick += 1


def main(demo: bool = False):
  InferenceDaemon(demo=demo).serve()


__all__ = [
  "PROCESS_NAME",
  "IQP_NAV_MODEL_INFLUENCE_ENABLED",
  "TurnDirection",
  "CaptureStamp",
  "ReplayLedger",
  "NeuralEngineState",
  "CameraIngress",
  "CalibrationAtlas",
  "FrameDropMeter",
  "InferenceDaemon",
  "main",
]


if __name__ == "__main__":
  try:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Run iqmodeld in demo mode.")
    args = parser.parse_args()
    main(demo=args.demo)
  except KeyboardInterrupt:
    cloudlog.warning(f"child {PROCESS_NAME} got SIGINT")
  except Exception:
    sentry.capture_exception()
    raise
