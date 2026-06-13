#!/usr/bin/env python3
'''
This process finds calibration values. More info on what these calibration values
are can be found here https://github.com/commaai/openpilot/tree/master/common/transformations
While the roll calibration is a real value that can be estimated, here we assume it's zero,
and the image input into the neural network is not corrected for roll.
'''

import os
import capnp
import numpy as np
from typing import NoReturn

from cereal import log, car
import cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.issue_debug import log_issue_limited
from openpilot.common.realtime import config_realtime_process
from openpilot.common.transformations.orientation import rot_from_euler, euler_from_rot
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE

MIN_SPEED_FILTER = 15 * CV.MPH_TO_MS
MAX_VEL_ANGLE_STD = np.radians(0.25)
MAX_YAW_RATE_FILTER = np.radians(2)  # per second

MAX_HEIGHT_STD = np.exp(-3.5)

# This is at model frequency, blocks needed for efficiency
SMOOTH_CYCLES = 10
BLOCK_SIZE = 100
INPUTS_NEEDED = 5   # Minimum blocks needed for valid calibration
INPUTS_WANTED = 50   # We want a little bit more than we need for stability
MAX_ALLOWED_YAW_SPREAD = np.radians(2)
MAX_ALLOWED_PITCH_SPREAD = np.radians(4)
TICI_FAMILY_PITCH_SPREAD_RESET = np.radians(3)
RPY_INIT = np.array([0.0,0.0,0.0])
WIDE_FROM_DEVICE_EULER_INIT = np.array([0.0, 0.0, 0.0])
HEIGHT_INIT = np.array([1.22])
DEVICE_IS_TICI_FAMILY = HARDWARE.get_device_type() in ("tici", "tizi")

# These values are needed to accommodate the model frame in the narrow cam
if HARDWARE.get_device_type() == 'mici':
  PITCH_LIMITS = np.array([-0.143101, 0.22235988])
else:
  PITCH_LIMITS = np.array([-0.09074112085129739, 0.17])
YAW_LIMITS = np.array([-0.06912048084718224, 0.06912048084718235])
DEBUG = os.getenv("DEBUG") is not None

def is_calibration_valid(rpy: np.ndarray) -> bool:
  return (PITCH_LIMITS[0] < rpy[1] < PITCH_LIMITS[1]) and (YAW_LIMITS[0] < rpy[2] < YAW_LIMITS[1])


def sanity_clip(rpy: np.ndarray) -> np.ndarray:
  if np.isnan(rpy).any():
    rpy = RPY_INIT
  return np.array([rpy[0],
                   np.clip(rpy[1], PITCH_LIMITS[0] - .005, PITCH_LIMITS[1] + .005),
                   np.clip(rpy[2], YAW_LIMITS[0] - .005, YAW_LIMITS[1] + .005)])

def moving_avg_with_linear_decay(prev_mean: np.ndarray, new_val: np.ndarray, idx: int, block_size: float) -> np.ndarray:
  return (idx*prev_mean + (block_size - idx) * new_val) / block_size

class Calibrator:
  def __init__(self, param_put: bool = False):
    self.param_put = param_put

    self.not_car = False
    self.stable_rpy = RPY_INIT.copy()
    self.stable_wide_from_device_euler = WIDE_FROM_DEVICE_EULER_INIT.copy()
    self.stable_height = HEIGHT_INIT.copy()
    self.has_stable_snapshot = False

    # Read saved calibration
    self.params = Params()
    calibration_params = self.params.get("CalibrationParams")
    rpy_init = RPY_INIT
    wide_from_device_euler = WIDE_FROM_DEVICE_EULER_INIT
    height = HEIGHT_INIT
    valid_blocks = 0
    self.cal_status = log.LiveCalibrationData.Status.uncalibrated

    if param_put and calibration_params:
      try:
        with log.Event.from_bytes(calibration_params) as msg:
          rpy_init = np.array(msg.liveCalibration.rpyCalib)
          valid_blocks = msg.liveCalibration.validBlocks
          wide_from_device_euler = np.array(msg.liveCalibration.wideFromDeviceEuler)
          height = np.array(msg.liveCalibration.height)
      except Exception:
        cloudlog.exception("Error reading cached CalibrationParams")

    self.reset(rpy_init, valid_blocks, wide_from_device_euler, height)
    self.update_status()

    # If saved calibration is immediately invalid (e.g. bad params from a previous
    # bootstrap bug or device remount), auto-clear it so we recalibrate from scratch
    # instead of getting permanently stuck in the "Calibration Invalid" state.
    if self.cal_status == log.LiveCalibrationData.Status.invalid:
      cloudlog.warning("calibrationd: saved CalibrationParams are invalid, clearing and starting fresh")
      if param_put:
        self.params.remove("CalibrationParams")
      self.reset()
      self.update_status()

  def _remember_stable_solution(self) -> None:
    self.stable_rpy = self.rpy.copy()
    self.stable_wide_from_device_euler = self.wide_from_device_euler.copy()
    self.stable_height = self.height.copy()
    self.has_stable_snapshot = True

  def reset(self, rpy_init: np.ndarray = RPY_INIT,
                  valid_blocks: int = 0,
                  wide_from_device_euler_init: np.ndarray = WIDE_FROM_DEVICE_EULER_INIT,
                  height_init: np.ndarray = HEIGHT_INIT,
                  smooth_from: np.ndarray | None = None) -> None:
    if not np.isfinite(rpy_init).all():
      self.rpy = RPY_INIT.copy()
    else:
      self.rpy = rpy_init.copy()

    if not np.isfinite(height_init).all() or len(height_init) != 1:
      self.height = HEIGHT_INIT.copy()
    else:
      self.height = height_init.copy()

    if not np.isfinite(wide_from_device_euler_init).all() or len(wide_from_device_euler_init) != 3:
      self.wide_from_device_euler = WIDE_FROM_DEVICE_EULER_INIT.copy()
    else:
      self.wide_from_device_euler = wide_from_device_euler_init.copy()

    if not np.isfinite(valid_blocks) or valid_blocks < 0:
      self.valid_blocks = 0
    else:
      self.valid_blocks = valid_blocks

    self.rpys = np.tile(self.rpy, (INPUTS_WANTED, 1))
    self.wide_from_device_eulers = np.tile(self.wide_from_device_euler, (INPUTS_WANTED, 1))
    self.heights = np.tile(self.height, (INPUTS_WANTED, 1))

    self.idx = 0
    self.block_idx = 0
    self.v_ego = 0.0

    if smooth_from is None:
      self.old_rpy = RPY_INIT
      self.old_rpy_weight = 0.0
    else:
      self.old_rpy = smooth_from
      self.old_rpy_weight = 1.0

  def get_valid_idxs(self) -> list[int]:
    # exclude current block_idx from validity window
    before_current = list(range(self.block_idx))
    after_current = list(range(min(self.valid_blocks, self.block_idx + 1), self.valid_blocks))
    return before_current + after_current

  def update_status(self) -> None:
    valid_idxs = self.get_valid_idxs()
    if valid_idxs:
      self.wide_from_device_euler = np.mean(self.wide_from_device_eulers[valid_idxs], axis=0)
      self.height = np.mean(self.heights[valid_idxs], axis=0)
      rpys = self.rpys[valid_idxs]
      self.rpy = np.mean(rpys, axis=0)
      max_rpy_calib = np.array(np.max(rpys, axis=0))
      min_rpy_calib = np.array(np.min(rpys, axis=0))
      self.calib_spread = np.abs(max_rpy_calib - min_rpy_calib)
    else:
      self.calib_spread = np.zeros(3)

    if self.valid_blocks < INPUTS_NEEDED:
      if self.cal_status == log.LiveCalibrationData.Status.recalibrating:
        self.cal_status = log.LiveCalibrationData.Status.recalibrating
      else:
        self.cal_status = log.LiveCalibrationData.Status.uncalibrated
    elif is_calibration_valid(self.rpy):
      self.cal_status = log.LiveCalibrationData.Status.calibrated
    else:
      self.cal_status = log.LiveCalibrationData.Status.invalid

    # If spread is too high, assume mounting was changed and reset to last block.
    # Make the transition smooth. Abrupt transitions are not good for feedback loop through supercombo model.
    # TODO: add height spread check with smooth transition too
    pitch_spread_limit = TICI_FAMILY_PITCH_SPREAD_RESET if DEVICE_IS_TICI_FAMILY else MAX_ALLOWED_PITCH_SPREAD
    spread_too_high = self.calib_spread[1] > pitch_spread_limit or self.calib_spread[2] > MAX_ALLOWED_YAW_SPREAD
    if self.cal_status == log.LiveCalibrationData.Status.calibrated and not spread_too_high:
      self._remember_stable_solution()

    if spread_too_high and self.cal_status == log.LiveCalibrationData.Status.calibrated:
      use_stable_snapshot = DEVICE_IS_TICI_FAMILY and self.has_stable_snapshot
      if use_stable_snapshot:
        reset_rpy = self.stable_rpy
        reset_wide = self.stable_wide_from_device_euler
        reset_height = self.stable_height
      else:
        reset_rpy = self.rpys[self.block_idx - 1]
        reset_wide = self.wide_from_device_eulers[self.block_idx - 1]
        reset_height = self.heights[self.block_idx - 1]

      log_issue_limited(
        "calibrationd_reset_spread",
        "calibration",
        f"calibrationd reset unstable solution pitchSpread={self.calib_spread[1]:.6f} "
        f"yawSpread={self.calib_spread[2]:.6f} pitchLimit={pitch_spread_limit:.6f} "
        f"use_stable_snapshot={use_stable_snapshot} rpy={self.rpy.tolist()}",
        interval_sec=0.5,
      )
      self.reset(reset_rpy, valid_blocks=1, wide_from_device_euler_init=reset_wide,
                 height_init=reset_height, smooth_from=self.stable_rpy if use_stable_snapshot else self.rpy)
      self.cal_status = log.LiveCalibrationData.Status.recalibrating

    write_this_cycle = (self.idx == 0) and (self.block_idx % (INPUTS_WANTED//5) == 5)
    if self.param_put and write_this_cycle:
      self.params.put_nonblocking("CalibrationParams", self.get_msg(True).to_bytes())

  def handle_v_ego(self, v_ego: float) -> None:
    self.v_ego = v_ego

  def get_smooth_rpy(self) -> np.ndarray:
    if self.old_rpy_weight > 0:
      return self.old_rpy_weight * self.old_rpy + (1.0 - self.old_rpy_weight) * self.rpy
    else:
      return self.rpy

  def handle_cam_odom(self, trans: list[float],
                            rot: list[float],
                            wide_from_device_euler: list[float],
                            trans_std: list[float],
                            road_transform_trans: list[float],
                            road_transform_trans_std: list[float]) -> np.ndarray | None:
    self.old_rpy_weight = max(0.0, self.old_rpy_weight - 1/SMOOTH_CYCLES)

    fast_enough = self.v_ego > MIN_SPEED_FILTER
    motion_speed = max(float(self.v_ego), float(trans[0]))
    cam_fast_enough = motion_speed > MIN_SPEED_FILTER
    yaw_ok = abs(rot[2]) < MAX_YAW_RATE_FILTER
    straight_and_fast = fast_enough and cam_fast_enough and yaw_ok
    angle_std_threshold = MAX_VEL_ANGLE_STD
    height_std_threshold = MAX_HEIGHT_STD
    rpy_certain = np.arctan2(trans_std[1], motion_speed) < angle_std_threshold
    if len(road_transform_trans_std) == 3:
      height_certain = road_transform_trans_std[2] < height_std_threshold
    else:
      height_certain = True

    certain_if_calib = rpy_certain
    if not (straight_and_fast and certain_if_calib):
      log_issue_limited(
        "calibrationd_rejected_sample",
        "calibration",
        f"calibrationd rejected sample vEgo={self.v_ego:.2f} trans0={trans[0]:.2f} yawRate={rot[2]:.4f} "
        f"fast_enough={fast_enough} cam_fast_enough={cam_fast_enough} motion_speed={motion_speed:.2f} yaw_ok={yaw_ok} "
        f"rpy_certain={rpy_certain} height_certain={height_certain} valid_blocks={self.valid_blocks} idx={self.idx}",
        interval_sec=1.0,
      )
      return None

    observed_rpy = np.array([0,
                             -np.arctan2(trans[2], trans[0]),
                             np.arctan2(trans[1], trans[0])])
    new_rpy = euler_from_rot(rot_from_euler(self.get_smooth_rpy()).dot(rot_from_euler(observed_rpy)))
    new_rpy = sanity_clip(new_rpy)

    if len(wide_from_device_euler) == 3:
      new_wide_from_device_euler = np.array(wide_from_device_euler)
    else:
      new_wide_from_device_euler = WIDE_FROM_DEVICE_EULER_INIT

    if (len(road_transform_trans) == 3):
      new_height = np.array([road_transform_trans[2]])
    else:
      new_height = HEIGHT_INIT

    self.rpys[self.block_idx] = moving_avg_with_linear_decay(self.rpys[self.block_idx], new_rpy, self.idx, float(BLOCK_SIZE))
    self.wide_from_device_eulers[self.block_idx] = moving_avg_with_linear_decay(self.wide_from_device_eulers[self.block_idx],
                                                                                new_wide_from_device_euler, self.idx, float(BLOCK_SIZE))
    self.heights[self.block_idx] = moving_avg_with_linear_decay(self.heights[self.block_idx], new_height, self.idx, float(BLOCK_SIZE))

    self.idx = (self.idx + 1) % BLOCK_SIZE
    if self.idx == 0:
      self.block_idx += 1
      self.valid_blocks = max(self.block_idx, self.valid_blocks)
      self.block_idx = self.block_idx % INPUTS_WANTED

    self.update_status()

    if self.idx == 0:
      log_issue_limited(
        "calibrationd_progress_block",
        "calibration",
        f"calibrationd progress status={int(self.cal_status)} valid_blocks={self.valid_blocks} "
        f"calPerc={min(100 * (self.valid_blocks * BLOCK_SIZE + self.idx) // (INPUTS_NEEDED * BLOCK_SIZE), 100)} "
        f"rpy={self.rpy.tolist()} spread={self.calib_spread.tolist()}",
        interval_sec=0.5,
      )

    return new_rpy

  def get_msg(self, valid: bool) -> capnp.lib.capnp._DynamicStructBuilder:
    smooth_rpy = self.get_smooth_rpy()

    msg = messaging.new_message('liveCalibration')
    msg.valid = valid

    liveCalibration = msg.liveCalibration
    liveCalibration.validBlocks = self.valid_blocks
    liveCalibration.calStatus = self.cal_status
    liveCalibration.calPerc = min(100 * (self.valid_blocks * BLOCK_SIZE + self.idx) // (INPUTS_NEEDED * BLOCK_SIZE), 100)
    liveCalibration.rpyCalib = smooth_rpy.tolist()
    liveCalibration.rpyCalibSpread = self.calib_spread.tolist()
    liveCalibration.wideFromDeviceEuler = self.wide_from_device_euler.tolist()
    liveCalibration.height = self.height.tolist()

    return msg

  def send_data(self, pm: messaging.PubMaster, valid: bool) -> None:
    pm.send('liveCalibration', self.get_msg(valid))


def main() -> NoReturn:
  config_realtime_process([0, 1, 2, 3], 5)

  pm = messaging.PubMaster(['liveCalibration'])
  sm = messaging.SubMaster(['cameraOdometry', 'carState'], poll='cameraOdometry')

  params_reader = Params()
  CP = messaging.log_from_bytes(params_reader.get("CarParams", block=True), car.CarParams)

  calibrator = Calibrator(param_put=True)
  calibrator.not_car = CP.notCar

  while 1:
    timeout = 0 if sm.frame == -1 else 100
    sm.update(timeout)

    if sm.updated['cameraOdometry']:
      calibrator.handle_v_ego(sm['carState'].vEgo)
      new_rpy = calibrator.handle_cam_odom(sm['cameraOdometry'].trans,
                                           sm['cameraOdometry'].rot,
                                           sm['cameraOdometry'].wideFromDeviceEuler,
                                           sm['cameraOdometry'].transStd,
                                           sm['cameraOdometry'].roadTransformTrans,
                                           sm['cameraOdometry'].roadTransformTransStd)

      if DEBUG and new_rpy is not None:
        print('got new rpy', new_rpy)

    # 4Hz driven by cameraOdometry
    if sm.frame % 5 == 0:
      calibrator.send_data(pm, sm.all_checks())


if __name__ == "__main__":
  main()
