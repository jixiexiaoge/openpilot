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

import time
import numpy as np
from openpilot.common.swaglog import cloudlog

# Configuration parameters
SPEED_RATIO = 0.98  # Must be within 2% over cruise speed
TTC_THRESHOLD = 3.0  # seconds - disable ACM when lead is within this time

# Emergency thresholds - IMMEDIATELY disable ACM
EMERGENCY_TTC = 2.0  # seconds - emergency situation
EMERGENCY_RELATIVE_SPEED = 10.0  # m/s (~36 km/h closing speed - only for rapid closing)
EMERGENCY_DECEL_THRESHOLD = -1.5  # m/s² - if MPC wants this much braking, emergency disable

# Safety cooldown after lead detection
LEAD_COOLDOWN_TIME = 0.5  # seconds - brief cooldown to handle sensor glitches

# Speed-based distance scaling - more practical for real traffic
SPEED_BP = [0., 10., 20., 30.]  # m/s (0, 36, 72, 108 km/h)
MIN_DIST_V = [15., 20., 25., 30.]  # meters - closer to original 25m baseline


class ACM:
  def __init__(self):
    self.enabled = False
    self._is_speed_over_cruise = False
    self._has_lead = False
    self._active_prev = False
    self._last_lead_time = 0.0  # Track when we last saw a lead

    self.active = False
    self.just_disabled = False

  def _check_emergency_conditions(self, lead, v_ego, current_time):
    """Check for emergency conditions that require immediate ACM disable."""
    if not lead or not lead.status:
      return False

    self.lead_ttc = lead.dRel / max(v_ego, 0.1)
    relative_speed = v_ego - lead.vLead  # Positive = closing

    # Speed-adaptive minimum distance
    min_dist_for_speed = np.interp(v_ego, SPEED_BP, MIN_DIST_V)

    # Emergency disable conditions - only for truly dangerous situations
    # Require BOTH close distance AND (fast closing OR very short TTC)
    if lead.dRel < min_dist_for_speed and (
        self.lead_ttc < EMERGENCY_TTC or
        relative_speed > EMERGENCY_RELATIVE_SPEED):

      self._last_lead_time = current_time
      if self.active:  # Only log if we're actually disabling
        cloudlog.warning(f"ACM emergency disable: dRel={lead.dRel:.1f}m, TTC={self.lead_ttc:.1f}s, relSpeed={relative_speed:.1f}m/s")
      return True

    return False

  def _update_lead_status(self, lead, v_ego, current_time):
    """Update lead vehicle detection status."""
    if lead and lead.status:
      self.lead_ttc = lead.dRel / max(v_ego, 0.1)

      if self.lead_ttc < TTC_THRESHOLD:
        self._has_lead = True
        self._last_lead_time = current_time
      else:
        self._has_lead = False
    else:
      self._has_lead = False
      self.lead_ttc = float('inf')

  def _check_cooldown(self, current_time):
    """Check if we're still in cooldown period after lead detection."""
    time_since_lead = current_time - self._last_lead_time
    return time_since_lead < LEAD_COOLDOWN_TIME

  def _should_activate(self, user_ctrl_lon, v_ego, v_cruise, in_cooldown):
    """Determine if ACM should be active based on all conditions."""
    self._is_speed_over_cruise = v_ego > (v_cruise * SPEED_RATIO)

    return (not user_ctrl_lon and
            not self._has_lead and
            not in_cooldown and
            self._is_speed_over_cruise)

  def update_states(self, cc, rs, user_ctrl_lon, v_ego, v_cruise):
    """Update ACM state with multiple safety checks."""
    # Basic validation
    if not self.enabled or len(cc.orientationNED) != 3:
      self.active = False
      return

    current_time = time.monotonic()
    lead = rs.leadOne

    # Check emergency conditions first (highest priority)
    if self._check_emergency_conditions(lead, v_ego, current_time):
      self.active = False
      self._active_prev = self.active
      return

    # Update normal lead status
    self._update_lead_status(lead, v_ego, current_time)

    # Check cooldown period
    in_cooldown = self._check_cooldown(current_time)

    # Determine if ACM should be active
    self.active = self._should_activate(user_ctrl_lon, v_ego, v_cruise, in_cooldown)

    # Track state changes for logging
    self.just_disabled = self._active_prev and not self.active
    if self.active and not self._active_prev:
      cloudlog.info(f"ACM activated: v_ego={v_ego*3.6:.1f} km/h, v_cruise={v_cruise*3.6:.1f} km/h")
    elif self.just_disabled:
      cloudlog.info("ACM deactivated")

    self._active_prev = self.active

  def update_a_desired_trajectory(self, a_desired_trajectory):
    """
    Modify acceleration trajectory to allow coasting.
    SAFETY: Check for any strong braking request and abort.
    """
    if not self.active:
      return a_desired_trajectory

    # SAFETY CHECK: If MPC wants significant braking, DON'T suppress it
    min_accel = np.min(a_desired_trajectory)
    if min_accel < EMERGENCY_DECEL_THRESHOLD:
      cloudlog.warning(f"ACM aborting: MPC requested {min_accel:.2f} m/s² braking")
      self.active = False  # Immediately deactivate
      return a_desired_trajectory  # Return unmodified trajectory

    # Only suppress very mild braking (> -1.0 m/s²)
    # This allows coasting but preserves any meaningful braking
    modified_trajectory = np.copy(a_desired_trajectory)
    for i in range(len(modified_trajectory)):
      if -1.0 < modified_trajectory[i] < 0:
        # Only suppress very gentle braking for cruise control
        modified_trajectory[i] = 0.0
      # Any braking stronger than -1.0 m/s² is preserved!

    return modified_trajectory
