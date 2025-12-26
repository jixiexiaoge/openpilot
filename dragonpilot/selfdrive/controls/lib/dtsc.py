"""
Copyright (c) 2025, Rick Lan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, and/or sublicense,
for non-commercial purposes only, subject to the following conditions:

- The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
- Commercial use (e.g. use in a product, service, or activity intended to
  generate revenue) is prohibited without explicit written permission from
  the copyright holder.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import numpy as np
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.common.swaglog import cloudlog

# Physics constants
COMFORT_LAT_G = 0.2  # g units - universal human comfort threshold
BASE_LAT_ACC = COMFORT_LAT_G * 9.81  # ~2.0 m/s^2
SAFETY_FACTOR = 0.9  # 10% safety margin on calculated speeds
MIN_CURVE_DISTANCE = 5.0  # meters - minimum distance to react to curves
MAX_DECEL = -2.0  # m/s^2 - maximum comfortable deceleration


class DTSC:
  """
  Dynamic Turn Speed Controller - Predictive curve speed management via MPC constraints.

  Core physics: v_max = sqrt(lateral_acceleration / curvature) * safety_factor

  Operation:
  1. Scans predicted path for curvature (up to ~10 seconds ahead)
  2. Calculates safe speed for each point using physics + comfort limits
  3. Identifies critical points where current speed would exceed safe speed
  4. Calculates required deceleration to reach safe speed at critical point
  5. Provides deceleration as MPC constraint for smooth trajectory planning
  """

  def __init__(self, aggressiveness=1.0):
    """
    Initialize DTSC with user-adjustable aggressiveness.

    Args:
      aggressiveness: Factor to adjust lateral acceleration limit
                     0.7 = 30% more conservative (slower in curves)
                     1.0 = default balanced behavior
                     1.3 = 30% more aggressive (faster in curves)
    """
    self.aggressiveness = np.clip(aggressiveness, 0.5, 1.5)
    self.active = False
    self.debug_msg = ""
    cloudlog.info(f"DTSC: Initialized with aggressiveness {self.aggressiveness:.2f}")

  def set_aggressiveness(self, value):
    """Update aggressiveness factor (0.5 to 1.5)."""
    self.aggressiveness = np.clip(value, 0.5, 1.5)
    cloudlog.info(f"DTSC: Aggressiveness updated to {self.aggressiveness:.2f}")

  def get_mpc_constraints(self, model_msg, v_ego, base_a_min, base_a_max):
    """
    Calculate MPC acceleration constraints based on predicted path curvature.

    Args:
      model_msg: ModelDataV2 containing predicted path
      v_ego: Current vehicle speed (m/s)
      base_a_min: Default minimum acceleration constraint
      base_a_max: Default maximum acceleration constraint

    Returns:
      (a_min_array, a_max_array): Modified constraints for each MPC timestep
    """

    # Initialize with base constraints
    a_min = np.ones(len(T_IDXS_MPC)) * base_a_min
    a_max = np.ones(len(T_IDXS_MPC)) * base_a_max

    # Validate model data
    if not self._is_model_data_valid(model_msg):
      self.active = False
      return a_min, a_max

    # Extract predictions for MPC horizon
    v_pred = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.velocity.x)
    turn_rates = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.orientationRate.z)
    positions = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.position.x)

    # Calculate curvature (turn_rate / velocity)
    curvatures = np.abs(turn_rates / np.clip(v_pred, 1.0, 100.0))

    # Calculate safe speeds
    lat_acc_limit = BASE_LAT_ACC * self.aggressiveness
    safe_speeds = np.sqrt(lat_acc_limit / (curvatures + 1e-6)) * SAFETY_FACTOR

    # Find speed violations
    speed_excess = v_pred - safe_speeds
    if np.all(speed_excess <= 0):
      self._deactivate()
      return a_min, a_max

    # Find critical point (maximum speed excess)
    critical_idx = np.argmax(speed_excess)
    critical_distance = positions[critical_idx]
    critical_safe_speed = safe_speeds[critical_idx]

    # Only act if we have sufficient distance
    if critical_distance <= MIN_CURVE_DISTANCE:
      self._deactivate()
      return a_min, a_max

    # Calculate required deceleration: a = (v_f^2 - v_i^2) / (2*d)
    required_decel = (critical_safe_speed**2 - v_ego**2) / (2 * critical_distance)
    required_decel = max(required_decel, MAX_DECEL)

    # Apply constraint progressively until critical point
    for i in range(len(T_IDXS_MPC)):
      t = T_IDXS_MPC[i]
      distance_at_t = v_ego * t + 0.5 * required_decel * t**2

      if distance_at_t < critical_distance:
        a_max[i] = min(a_max[i], required_decel)

    # Update status
    self.active = True
    self.debug_msg = f"Curve in {critical_distance:.0f}m → {critical_safe_speed*3.6:.0f} km/h"
    cloudlog.info(f"DTSC: {self.debug_msg} (aggr={self.aggressiveness:.1f})")

    return a_min, a_max

  def _is_model_data_valid(self, model_msg):
    """Check if model message contains valid prediction data."""
    return (len(model_msg.position.x) == ModelConstants.IDX_N and
            len(model_msg.velocity.x) == ModelConstants.IDX_N and
            len(model_msg.orientationRate.z) == ModelConstants.IDX_N)

  def _deactivate(self):
    """Clear active state and debug message."""
    self.active = False
    self.debug_msg = ""
