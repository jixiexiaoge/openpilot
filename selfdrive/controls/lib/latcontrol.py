import numpy as np
from abc import abstractmethod, ABC

from openpilot.common.realtime import DT_CTRL

from cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
LaneChangeState = log.LaneChangeState

MIN_LATERAL_CONTROL_SPEED = 0.3  # m/s


class LatControl(ABC):
  def __init__(self, CP, CI):
    self.sat_count_rate = 1.0 * DT_CTRL
    self.sat_limit = CP.steerLimitTimer
    self.sat_count = 0.
    self.sat_check_min_speed = 10.

    # we define the steer torque scale as [-1.0...1.0]
    self.steer_max = 1.0

    self._steer_pressed_rc = 0.6
    self._steer_pressed_factor = FirstOrderFilter(1.0, self._steer_pressed_rc, DT_CTRL)

  def _is_lane_changing(self, model_data) -> bool:
    try:
      st = model_data.meta.laneChangeState
      return st in (LaneChangeState.laneChangeStarting, LaneChangeState.laneChangeFinishing)
    except Exception:
      return False

  def _get_steer_pressed_factor(self, CS, model_data) -> float:
    target = 0.25 if CS.steeringPressed else 1.0
    rc = 0.9 if self._is_lane_changing(model_data) else 0.6

    if rc != self._steer_pressed_rc:
      self._steer_pressed_factor.update_alpha(rc)
      self._steer_pressed_rc = rc

    return self._steer_pressed_factor.update(target)
    
      
  @abstractmethod
  def update(self, active, CS, VM, params, steer_limited_by_controls, desired_curvature, CC, curvature_limited, model_data=None):
    pass

  def reset(self):
    self.sat_count = 0.

  def _check_saturation(self, saturated, CS, steer_limited_by_controls, curvature_limited):
    # Saturated only if control output is not being limited by car torque/angle rate limits
    if (saturated or curvature_limited) and CS.vEgo > self.sat_check_min_speed and not steer_limited_by_controls and not CS.steeringPressed:
      self.sat_count += self.sat_count_rate
    else:
      self.sat_count -= self.sat_count_rate
    self.sat_count = np.clip(self.sat_count, 0.0, self.sat_limit)
    return self.sat_count > (self.sat_limit - 1e-3)
