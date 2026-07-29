import numpy as np
import pytest

import cereal.messaging as messaging
from cereal import log

from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT
from openpilot.selfdrive.locationd.calibration_helpers import get_calibrated_rpy, get_render_path_height
from openpilot.selfdrive.locationd.helpers import PoseCalibrator


def build_live_calibration(status: log.LiveCalibrationData.Status,
                           rpy: tuple[float, float, float] = (0.0, 0.0, 0.0),
                           height: tuple[float, ...] = (1.22,)):
  msg = messaging.new_message("liveCalibration")
  msg.liveCalibration.calStatus = status
  msg.liveCalibration.rpyCalib = list(rpy)
  msg.liveCalibration.height = list(height)
  return msg.liveCalibration


def test_get_calibrated_rpy_requires_calibrated_status():
  live_calib = build_live_calibration(log.LiveCalibrationData.Status.uncalibrated, rpy=(0.1, 0.2, 0.3))
  assert get_calibrated_rpy(live_calib) is None

  live_calib = build_live_calibration(log.LiveCalibrationData.Status.calibrated, rpy=(0.1, 0.2, 0.3))
  np.testing.assert_allclose(get_calibrated_rpy(live_calib), np.array([0.1, 0.2, 0.3], dtype=np.float32))


def test_get_render_path_height_uses_default_until_calibrated():
  live_calib = build_live_calibration(log.LiveCalibrationData.Status.uncalibrated, height=(1.5,))
  assert get_render_path_height(live_calib) == float(HEIGHT_INIT[0])

  live_calib = build_live_calibration(log.LiveCalibrationData.Status.calibrated, height=(1.5,))
  assert get_render_path_height(live_calib) == 1.5


def test_calibrated_values_are_used_even_when_identity_override_is_disabled():
  live_calib = build_live_calibration(log.LiveCalibrationData.Status.calibrated, rpy=(0.3, -0.2, 0.1), height=(1.6,))
  np.testing.assert_allclose(get_calibrated_rpy(live_calib), np.array([0.3, -0.2, 0.1], dtype=np.float32))
  assert get_render_path_height(live_calib) == pytest.approx(1.6)


def test_pose_calibrator_holds_identity_until_calibrated():
  calibrator = PoseCalibrator()

  uncalibrated = build_live_calibration(log.LiveCalibrationData.Status.uncalibrated, rpy=(0.1, 0.2, 0.3))
  calibrator.feed_live_calib(uncalibrated)
  np.testing.assert_allclose(calibrator.calib_from_device, np.eye(3))
  assert not calibrator.calib_valid

  calibrated = build_live_calibration(log.LiveCalibrationData.Status.calibrated, rpy=(0.0, 0.1, 0.0))
  calibrator.feed_live_calib(calibrated)
  assert not np.allclose(calibrator.calib_from_device, np.eye(3))
  assert calibrator.calib_valid

  recalibrating = build_live_calibration(log.LiveCalibrationData.Status.recalibrating, rpy=(0.2, 0.2, 0.2))
  frozen_transform = calibrator.calib_from_device.copy()
  calibrator.feed_live_calib(recalibrating)
  np.testing.assert_allclose(calibrator.calib_from_device, frozen_transform)
  assert not calibrator.calib_valid
