import math

import numpy as np
from cereal import log

from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT


def get_calibrated_rpy(live_calib: log.LiveCalibrationData) -> np.ndarray | None:
  if live_calib.calStatus != log.LiveCalibrationData.Status.calibrated:
    return None

  if len(live_calib.rpyCalib) != 3:
    return None

  calib_rpy = np.asarray(live_calib.rpyCalib, dtype=np.float32)
  return calib_rpy if np.isfinite(calib_rpy).all() else None


def get_render_path_height(live_calib: log.LiveCalibrationData) -> float:
  if live_calib.calStatus != log.LiveCalibrationData.Status.calibrated:
    return float(HEIGHT_INIT[0])

  if len(live_calib.height) != 1:
    return float(HEIGHT_INIT[0])

  height = float(live_calib.height[0])
  return height if math.isfinite(height) else float(HEIGHT_INIT[0])
