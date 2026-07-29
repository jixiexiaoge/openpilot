"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS

MAX_CAMERA_OFFSET_METERS = 0.35


class _OffsetSmoother:
  def __init__(self, blend: float = 0.1):
    self._blend = blend
    self._value = 0.0

  def step(self, target: float) -> float:
    self._value = ((1.0 - self._blend) * self._value) + (self._blend * float(target))
    return self._value


def _clamped_offset(raw_offset) -> float:
  try:
    parsed = float(raw_offset)
  except (TypeError, ValueError):
    parsed = 0.0
  return float(np.clip(parsed, -MAX_CAMERA_OFFSET_METERS, MAX_CAMERA_OFFSET_METERS))


def _camera_profile(sm):
  return DEVICE_CAMERAS[(str(sm["deviceState"].deviceType), str(sm["roadCameraState"].sensor))]


def _calibration_height(sm) -> float:
  return sm["liveCalibration"].height[0] if sm["liveCalibration"].height else 1.22


def _sheared_transform(model_transform, intrinsics, height: float, lateral_offset: float):
  optical_center_y = intrinsics[1, 2]
  projection_bias = np.eye(3, dtype=np.float32)
  projection_bias[0, 1] = lateral_offset / height
  projection_bias[0, 2] = -(lateral_offset / height) * optical_center_y
  return (projection_bias @ model_transform).astype(np.float32)


class CameraOffsetHelper:
  def __init__(self):
    self.camera_offset = 0.0
    self.actual_camera_offset = 0.0
    self._smoother = _OffsetSmoother()

  @staticmethod
  def apply_camera_offset(model_transform, intrinsics, height, offset_param):
    return _sheared_transform(model_transform, intrinsics, height, offset_param)

  def set_offset(self, offset):
    self.camera_offset = _clamped_offset(offset)

  def update(self, model_transform_main, model_transform_extra, sm, main_wide_camera, extra_uses_wide_camera=True):
    self.actual_camera_offset = self._smoother.step(self.camera_offset)
    camera_bundle = _camera_profile(sm)
    camera_height = _calibration_height(sm)
    main_intrinsics = camera_bundle.ecam.intrinsics if main_wide_camera else camera_bundle.fcam.intrinsics
    extra_intrinsics = camera_bundle.ecam.intrinsics if extra_uses_wide_camera else camera_bundle.fcam.intrinsics

    return (
      self.apply_camera_offset(model_transform_main, main_intrinsics, camera_height, self.actual_camera_offset),
      self.apply_camera_offset(model_transform_extra, extra_intrinsics, camera_height, self.actual_camera_offset),
    )
