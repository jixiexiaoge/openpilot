from __future__ import annotations

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.tools.compile_supercombo import (
  _captured_devices,
  _captured_queue_depth,
  _validate_pose_outputs,
)


class _Captured:
  def __init__(self, expected_input_info):
    self.expected_input_info = expected_input_info


class _FakeJit:
  def __init__(self, expected_input_info):
    self.captured = _Captured(expected_input_info)


def test_captured_queue_helpers_extract_depth_and_device():
  infos = [
    ("noop", (), "uchar", "QCOM"),
    ("reshape(arg=None, src=(noop, stack(arg=None, src=(const(arg=5), const(arg=6), const(arg=128), const(arg=256)))))", (), "uchar", "QCOM"),
    ("reshape(arg=None, src=(noop, const(arg=3)))", (), "float", "NPY"),
  ]
  fake_jit = _FakeJit(infos)

  assert _captured_queue_depth(fake_jit) == 5
  assert _captured_devices(fake_jit) == {"QCOM", "NPY"}


def test_validate_pose_outputs_accepts_sane_odometry_payload():
  outputs = {
    "pose": np.array([[1.0, 0.5, 0.25, 0.1, 0.2, 0.3]], dtype=np.float32),
    "pose_stds": np.array([[0.5, 0.4, 0.3, 0.2, 0.2, 0.2]], dtype=np.float32),
    "wide_from_device_euler": np.array([[0.1, 0.2, 0.3]], dtype=np.float32),
    "wide_from_device_euler_stds": np.array([[0.2, 0.2, 0.2]], dtype=np.float32),
    "road_transform": np.array([[0.5, 0.4, 0.3, 0.2, 0.1, 0.0]], dtype=np.float32),
    "road_transform_stds": np.array([[0.3, 0.3, 0.3, 0.2, 0.2, 0.2]], dtype=np.float32),
  }

  _validate_pose_outputs(outputs)
