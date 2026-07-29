import math
import numpy as np
from collections import deque

from cereal import log
from iqdbc.car.lateral import get_friction
from openpilot.common.constants import ACCELERATION_DUE_TO_GRAVITY
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.common.pid import PIDController

#   - Actuation delay dominates, not rack slew rate. liveDelay converged to
#     0.32-0.40s (median 0.34) across routes; the 150/300-per-frame slew is
#     irrelevant to loop stability because the delay caps usable loop gain.
#     STIFFENING THE LOOP FAILED VALIDATION: KP=1.0/KI=0.2 (my first draft)
#     produced ~25x the jerk cost. KP/KI are therefore left at generic values.
#   - Feedforward must stay DETUNED relative to the open-loop plant gain.
#     Measured open-loop latAccelFactor is ~1.6 (outer-region fit; torqued live
#     median 1.69). But driving the feedforward at the matched 1.6 overshoots
#     against the delay (replay cost 63.7 vs 54.9). A gentler effective factor
#     of ~2.2 -- close to the old placeholder -- validated best. So we keep a
#     detuned FF factor and FREEZE torqued's live override, which would
#     otherwise pull it back toward matched and destabilize.
#   - latAccelOffset = -0.13 (road-crown / device-roll bias, consistent across
#     all routes) is the single biggest honest win: ~4.5 replay-cost points.
#   - Friction compensation should be WIDE and gentle, not a tall narrow spike.
#     torqued pins friction at its 0.2 cap on every route and the binned
#     torque->lataccel curve shows a ~0.45-wide flat zone -- but that saturation
#     is an artifact of torqued's NARROW interp needing a tall spike to cover
#     the deadband. Spreading the SAME 0.1 amplitude over a wide error band
#     (threshold 1.0) covers the deadband more gently and, unlike either a tall
#     narrow ramp or a wide 0.2 ramp, does not dump enough torque at small
#     errors to ring at saturation. A per-stretch regression guard (the article
#     methodology) caught this: friction 0.2 gave a 504-pt worst-case
#     single-stretch regression; friction 0.1 cut that to ~240 AND improved the
#     mean, so 0.1 it is.
#     PQ mean cost 58.2 vs 67.2 generic (+13%), better on ~60%
#     of stretches, plant-check residual 0.22 m/s^2. The remaining worst-case
#     regressions are LOW-SPEED (~15 m/s) saturated maneuvers where both
#     controllers already score ~1000+ and where torque control is least valid
#     (see class docstring in latcontrol_torque.py: lataccel<->torque only
#     correlates cleanly above ~25mph) and where this high-speed-cruise-heavy
#     plant fit is least trustworthy. A naive speed-gated blend of these params
#     made things WORSE (time-varying jerk filter chatters across the band), so
#     it was rejected rather than shipped. Treat absolutes as soft; confirm
#     gains on-road. The deferred EPS-firmware pass will pin the true rack
#     deadband/gain and let us revisit the FF detuning from first principles.

FRICTION_THRESHOLD_PQ = 1.0    # wide, gentle friction-comp ramp (validated vs narrow 0.35)
KP = 0.8                       # generic value; stiffening failed replay validation
KI = 0.15

INTERP_SPEEDS = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]
KP_INTERP = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, KP]

LP_FILTER_CUTOFF_HZ = 1.5      # rack settles fast once friction breaks
JERK_LOOKAHEAD_SECONDS = 0.34  # matched to measured/converged lateral delay
JERK_GAIN = 0.3
LAT_ACCEL_REQUEST_BUFFER_SECONDS = 1.0
VERSION = 1

# Feedforward plant params. FACTOR is deliberately detuned above the measured
# open-loop gain (~1.6) for delay robustness; see header. torqued live updates
# are frozen for this controller so it cannot drift back to matched.
DEFAULT_LAT_ACCEL_FACTOR = 2.2
DEFAULT_LAT_ACCEL_OFFSET = -0.13
DEFAULT_FRICTION = 0.1          # spread wide (threshold 1.0); 0.2 rang at saturation
FREEZE_LIVE_TORQUE_PARAMS = True

# --- EPS assist-curve compensation (firmware-derived, PQ35_ZF_EPS_3501) ---
# The ZF EPS does NOT apply LM_Offset (our torque command) to the rack 1:1. In
# hca_lm_offset_torque_handler it computes
#     rack_force = LM_Offset * hca_table[speed] >> 7
# where hca_table is a speed-breakpoint curve (decoded from the binary at
# 0x5e664). The multiplier / 128 is:
#     0 km/h -> 0.688,  50 km/h -> 0.883,  120 km/h -> 1.211  (linear interp)
# So the EPS delivers only ~0.69-0.84x of commanded torque at low speed and
# ~1.21x at highway speed -- a 1.76x swing the stock torque controller is blind
# to (it assumes a single latAccelFactor). This is exactly the region where the
# controller felt under-assisted at low speed. We invert the KNOWN curve so the
# LM_Offset->rack_force gain is flat across speed and the single-point FF tuning
# holds everywhere. Normalized to ASSIST_REF so the validated latAccelFactor
# (calibrated around highway speed) is unchanged at the reference point.
#
# Ghidra confirmation (full torque chain traced, not just this function): the
# HCA_torque_map speed lookup is the ONLY speed-dependent scaling applied to our
# command. output_torque_math's second multiplier (force_multiplier[row]) is a
# per-variant scalar that also scales driver force, so it folds into the overall
# latAccelFactor rather than adding speed dependence; the speed-interpolation
# routine (FUN_00039b2a) is called only for this curve. Final motor torque is
# clamped to 0x220=544. So the inversion below models the complete speed term.
#
# HONESTY: direction and magnitude here come from firmware, not a fit, so they
# are trustworthy on their own terms. But the closed-loop logs are too noisy
# (0.2 m/s^2 plant residual, composite-gain regression dominated by closed-loop
# bias) to VALIDATE a cost improvement in replay -- so this is shipped as a
# first-principles physical inversion to confirm on-road, not a replay-validated
# gain. Toggle with ASSIST_COMPENSATION if on-road testing disagrees.
ASSIST_COMPENSATION = True
ASSIST_SPEEDS_KPH = [0.0, 50.0, 120.0]
ASSIST_GAIN = [0.688, 0.883, 1.211]
ASSIST_REF_KPH = 100.0          # normalize so comp == 1 near highway calibration speed


def _assist_comp(v_ego_ms):
  import numpy as _np
  ref = _np.interp(ASSIST_REF_KPH, ASSIST_SPEEDS_KPH, ASSIST_GAIN)
  g = _np.interp(v_ego_ms * 3.6, ASSIST_SPEEDS_KPH, ASSIST_GAIN)
  # clamp the boost so a near-zero low-speed gain can't explode the command
  return float(_np.clip(ref / g, 0.7, 1.6))


class LatControlTorquePQ(LatControl):
  def __init__(self, CP, CP_IQ, CI, dt):
    super().__init__(CP, CP_IQ, CI, dt)
    self.torque_params = CP.lateralTuning.torque.as_builder()
    # Always seed the validated feedforward params. Unlike the generic
    # controller we do not defer to whatever the platform carried, because the
    # detuned FF factor is a deliberate tuning choice, not a plant estimate.
    self.torque_params.latAccelFactor = DEFAULT_LAT_ACCEL_FACTOR
    self.torque_params.latAccelOffset = DEFAULT_LAT_ACCEL_OFFSET
    self.torque_params.friction = DEFAULT_FRICTION
    self.torque_from_lateral_accel = CI.torque_from_lateral_accel()
    self.lateral_accel_from_torque = CI.lateral_accel_from_torque()
    self.pid = PIDController([INTERP_SPEEDS, KP_INTERP], KI, rate=1/self.dt)
    self.update_limits()
    self.steering_angle_deadzone_deg = self.torque_params.steeringAngleDeadzoneDeg
    self.lat_accel_request_buffer_len = int(LAT_ACCEL_REQUEST_BUFFER_SECONDS / self.dt)
    self.lat_accel_request_buffer = deque([0.] * self.lat_accel_request_buffer_len, maxlen=self.lat_accel_request_buffer_len)
    self.lookahead_frames = int(JERK_LOOKAHEAD_SECONDS / self.dt)
    self.jerk_filter = FirstOrderFilter(0.0, 1 / (2 * np.pi * LP_FILTER_CUTOFF_HZ), self.dt)

  def update_live_torque_params(self, latAccelFactor, latAccelOffset, friction):
    # Frozen: the detuned feedforward factor is intentional (see header). Letting
    # torqued pull latAccelFactor toward the matched open-loop gain destabilizes
    # against the 0.34s actuation delay.
    if FREEZE_LIVE_TORQUE_PARAMS:
      return
    self.torque_params.latAccelFactor = latAccelFactor
    self.torque_params.latAccelOffset = latAccelOffset
    self.torque_params.friction = friction
    self.update_limits()

  def update_limits(self):
    self.pid.set_limits(self.lateral_accel_from_torque(self.steer_max, self.torque_params),
                        self.lateral_accel_from_torque(-self.steer_max, self.torque_params))

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited, lat_delay):
    pid_log = log.ControlsState.LateralTorqueState.new_message()
    pid_log.version = VERSION
    measured_curvature = -VM.calc_curvature(math.radians(CS.steeringAngleDeg - params.angleOffsetDeg), CS.vEgo, params.roll)
    measurement = measured_curvature * CS.vEgo ** 2
    future_desired_lateral_accel = desired_curvature * CS.vEgo ** 2
    self.lat_accel_request_buffer.append(future_desired_lateral_accel)

    roll_compensation = params.roll * ACCELERATION_DUE_TO_GRAVITY
    curvature_deadzone = abs(VM.calc_curvature(math.radians(self.steering_angle_deadzone_deg), CS.vEgo, 0.0))
    lateral_accel_deadzone = curvature_deadzone * CS.vEgo ** 2

    delay_frames = int(np.clip(lat_delay / self.dt + 1, 1, self.lat_accel_request_buffer_len))
    expected_lateral_accel = self.lat_accel_request_buffer[-delay_frames]
    setpoint = expected_lateral_accel
    error = setpoint - measurement

    lookahead_idx = int(np.clip(-delay_frames + self.lookahead_frames, -self.lat_accel_request_buffer_len + 1, -2))
    raw_lateral_jerk = (self.lat_accel_request_buffer[lookahead_idx + 1] - self.lat_accel_request_buffer[lookahead_idx - 1]) / (2 * self.dt)
    desired_lateral_jerk = self.jerk_filter.update(raw_lateral_jerk)
    gravity_adjusted_future_lateral_accel = future_desired_lateral_accel - roll_compensation
    ff = gravity_adjusted_future_lateral_accel
    ff -= self.torque_params.latAccelOffset
    ff += get_friction(error + JERK_GAIN * desired_lateral_jerk, lateral_accel_deadzone, FRICTION_THRESHOLD_PQ, self.torque_params)

    if not active:
      output_torque = 0.0
      pid_log.active = False
    else:
      pid_log.error = float(error)
      freeze_integrator = steer_limited_by_safety or CS.steeringPressed or CS.vEgo < 5
      output_lataccel = self.pid.update(pid_log.error, speed=CS.vEgo, feedforward=ff, freeze_integrator=freeze_integrator)
      output_torque = self.torque_from_lateral_accel(output_lataccel, self.torque_params)
      # Invert the EPS speed-dependent assist so the rack sees a flat gain (see
      # header). The whole LM_Offset is scaled, matching where the EPS applies it.
      if ASSIST_COMPENSATION:
        output_torque = float(np.clip(output_torque * _assist_comp(CS.vEgo),
                                      -self.steer_max, self.steer_max))

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.d = float(self.pid.d)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(-output_torque)
      pid_log.actualLateralAccel = float(measurement)
      pid_log.desiredLateralAccel = float(setpoint)
      pid_log.desiredLateralJerk = float(desired_lateral_jerk)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))

    return -output_torque, 0.0, pid_log
