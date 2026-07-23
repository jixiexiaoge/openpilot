import json
import math
import os
import tomllib
from collections import deque
from difflib import SequenceMatcher

import numpy as np

from cereal import log, custom  # noqa: F401  (custom kept available for downstream imports)
from iqdbc.car import structs
from iqdbc.car.lateral import FRICTION_THRESHOLD, get_friction
from iqdbc.iqpilot.car.interfaces import LatControlInputs
from iqdbc.iqpilot.car.lateral_ext import get_friction as get_friction_in_torque_space
from openpilot.common.basedir import BASEDIR
from openpilot.common.constants import ACCELERATION_DUE_TO_GRAVITY
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.pid import PIDController
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.modeld.parse_model_outputs import safe_exp
from openpilot.iqpilot.selfdrive.controls.lib.helpers.nav_torque_pulse import NavTorquePulseBrain


# ===== locator =====

TORQUE_NN_MODEL_PATH = os.path.join(BASEDIR, "iqpilot", "iqpilot_iq_nnff_models", "neural_network_lateral_control")
TORQUE_NN_MODEL_SUBSTITUTE_PATH = os.path.join(BASEDIR, "iqdbc", "car", "torque_data", "substitute.toml")
MOCK_MODEL_PATH = os.path.join(TORQUE_NN_MODEL_PATH, "MOCK.json")

# A candidate must reach this score for the fingerprint(+fw) match to count as exact.
_EXACT_THRESHOLD = 0.99
# Below this, we fall back to the next candidate ladder rung.
_ACCEPT_THRESHOLD = 0.9


def _score(a: str, b: str) -> float:
  return SequenceMatcher(None, a, b).ratio()


def _best_model_for(candidate: str) -> tuple[str | None, float]:
  """Highest-scoring model file for a candidate string; (path, score)."""
  best_path, best_score = None, -1.0
  for entry in os.listdir(TORQUE_NN_MODEL_PATH):
    if not entry.endswith(".json"):
      continue
    score = _score(os.path.splitext(entry)[0], candidate)
    if score > best_score:
      best_path, best_score = os.path.join(TORQUE_NN_MODEL_PATH, entry), score
  return best_path, best_score


def _substitute_for(fingerprint: str) -> str:
  with open(TORQUE_NN_MODEL_SUBSTITUTE_PATH, 'rb') as f:
    table = tomllib.load(f)
  return table.get(fingerprint, fingerprint)


def _eps_suffix(CP: structs.CarParams) -> str:
  eps_fw = str(next((fw.fwVersion for fw in CP.carFw if fw.ecu == "eps"), ""))
  return eps_fw.replace("\\", "") if len(eps_fw) > 3 else ""


def get_nn_model_path(CP: structs.CarParams) -> tuple[str, str, bool]:
  """Pick the closest NNFF model for this car.

  Angle-steered cars always get MOCK. Otherwise walk a candidate ladder —
  fingerprint+eps-fw, then fingerprint, then the substitute mapping — accepting
  the first rung that clears the match threshold; the top rung landing at ~1.0
  marks an exact (non-fuzzy) match.
  """
  if CP.steerControlType == structs.CarParams.SteerControlType.angle:
    return MOCK_MODEL_PATH, "MOCK", False

  fingerprint = CP.carFingerprint
  suffix = _eps_suffix(CP)

  # rung 1: fingerprint + eps fw (when we have a usable fw string)
  if suffix:
    path, score = _best_model_for(f"{fingerprint} {suffix}")
    if path is not None and fingerprint in path and score >= _ACCEPT_THRESHOLD:
      name = os.path.splitext(os.path.basename(path))[0]
      return path, name, score >= _EXACT_THRESHOLD

  # rung 2: fingerprint alone
  path, score = _best_model_for(fingerprint)
  if path is not None and fingerprint in path and score >= _ACCEPT_THRESHOLD:
    name = os.path.splitext(os.path.basename(path))[0]
    return path, name, score >= _EXACT_THRESHOLD

  # rung 3: substitute mapping — never exact
  path, _ = _best_model_for(_substitute_for(fingerprint))
  name = os.path.splitext(os.path.basename(path))[0] if path else "MOCK"
  return (path or MOCK_MODEL_PATH), name, False

# ===== network =====

# The JSON model format (Twilsonco NNFF) is external: unicode 'σ' names the
# sigmoid activation, weights/biases live under keys suffixed _W/_b, and the
# input normalisation is (x - mean) / std. We translate names through a registry
# and keep the mean/std transposed once at load.
_MIN_INPUT_LEN = 2
_FRICTION_PROBE = (10.0, 0.0, 0.2)
_FRICTION_THRESHOLD = 0.1

_ACTIVATION_ALIASES = {"σ": "sigmoid"}


def _sigmoid(x):
  return 1.0 / (1.0 + safe_exp(-x))


def _identity(x):
  return x


_ACTIVATIONS = {"sigmoid": _sigmoid, "identity": _identity}


def _resolve_activation(name: str):
  for symbol, canonical in _ACTIVATION_ALIASES.items():
    name = name.replace(symbol, canonical)
  fn = _ACTIVATIONS.get(name)
  if fn is None:
    raise ValueError(f"Unknown activation: {name}")
  return fn


def _pick(layer: dict, suffix: str):
  key = next(k for k in layer if k.endswith(suffix))
  return np.array(layer[key], dtype=np.float32).T


class NNTorqueModel:
  def __init__(self, params_file, zero_bias=False):
    with open(params_file) as f:
      params = json.load(f)

    self.input_size = params["input_size"]
    self.output_size = params["output_size"]
    self.input_mean = np.array(params["input_mean"], dtype=np.float32).T
    self.input_std = np.array(params["input_std"], dtype=np.float32).T

    self._weights = []
    self._biases = []
    self._activations = []
    for layer in params["layers"]:
      weight = _pick(layer, "_W")
      bias = np.zeros_like(_pick(layer, "_b")) if zero_bias else _pick(layer, "_b")
      self._weights.append(weight)
      self._biases.append(bias)
      self._activations.append(_resolve_activation(layer["activation"]))

    self.friction_override = self.evaluate(list(_FRICTION_PROBE)) < _FRICTION_THRESHOLD

  def forward(self, x):
    for weight, bias, activation in zip(self._weights, self._biases, self._activations, strict=True):
      x = activation(x.dot(weight) + bias)
    return x

  def evaluate(self, input_array):
    if len(input_array) != self.input_size:
      if len(input_array) < _MIN_INPUT_LEN:
        raise ValueError(f"Input array length {len(input_array)} must be length 2 or greater")
      input_array = input_array + [0] * (self.input_size - len(input_array))
    x = (np.array(input_array, dtype=np.float32) - self.input_mean) / self.input_std
    return float(self.forward(x)[0, 0])

  # names kept for callers/tests that introspected the old implementation
  @staticmethod
  def sigmoid(x):
    return _sigmoid(x)

  @staticmethod
  def identity(x):
    return _identity(x)

# ===== brain =====

PLAN_SAMPLE_START = 5
LAG_EXTRA_S = 0.0

BASE_P = 0.8
BASE_I = 0.15
PID_SPEED_BP = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]
PID_P_GAIN = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, BASE_P]

_JERK_FALLBACK_IDX = 16   # T_IDXS index used when nothing exceeds the lookahead horizon


def sign(value: float) -> float:
  if value > 0.0:
    return 1.0
  if value < 0.0:
    return -1.0
  return 0.0


polarity = sign


def _pointwise_jerk(accel_trace, dt_trace) -> list:
  """Finite-difference jerk from an acceleration trace over per-step dt."""
  delta = np.diff(accel_trace)
  span = min(len(delta), len(dt_trace))
  if span <= 0:
    return []
  return (delta[:span] / np.array(dt_trace)[:span]).tolist()


def sign_locked_min(future_vals, seed_val):
  """Smallest-magnitude jerk over the horizon, but only if the whole horizon
  agrees in sign with the seed; a sign disagreement collapses to 0."""
  if not future_vals:
    return seed_val
  agreeing = [v for v in future_vals if sign(v) == sign(seed_val)]
  if len(agreeing) < len(future_vals):
    return 0.0
  return min(agreeing + [seed_val], key=abs)


class PilotLateralBrain:
  """Shared lateral-control scaffolding: PID core, model snapshot, and the
  forward-looking jerk/friction estimates the feed-forward controllers build on."""

  def __init__(self, torque_ctrl, cp, cp_iq, car_if):
    del cp_iq
    self.lac_torque = torque_ctrl
    self.torque_from_lateral_accel_in_torque_space = car_if.torque_from_lateral_accel_in_torque_space()

    self.model_v2 = None
    self.model_valid = False

    self.jerk_now = 0.0
    self.jerk_goal = 0.0
    self.jerk_obs = 0.0
    self.jerk_ahead = 0.0

    # per-cycle control snapshot
    self._ff = 0.0
    self._pid = PIDController([PID_SPEED_BP, PID_P_GAIN], BASE_I)
    self._pid_log = None
    self._accel_goal = 0.0
    self._accel_obs = 0.0
    self._roll_g = 0.0
    self._deadband = 0.0
    self._want_la = 0.0
    self._have_la = 0.0
    self._want_cv = 0.0
    self._have_cv = 0.0
    self._grav_la = 0.0
    self._capped = False
    self._out_tq = 0.0

    # friction-lookahead tuning
    self.friction_look_ahead_v = [1.4, 2.0]
    self.friction_look_ahead_bp = [9.0, 30.0]
    self.lat_jerk_friction_factor = 0.4
    self.lat_accel_friction_factor = 0.7

    self.t_diffs = np.diff(ModelConstants.T_IDXS)
    self.desired_lat_jerk_time = cp.steerActuatorDelay + LAG_EXTRA_S

  def update_model_v2(self, model_packet):
    self.model_v2 = model_packet
    self.model_valid = model_packet is not None and len(model_packet.orientation.x) >= CONTROL_N

  def update_lateral_lag(self, lag):
    self.desired_lat_jerk_time = max(0.01, lag) + LAG_EXTRA_S

  def update_friction_input(self, target_val, measured_val):
    error = target_val - measured_val
    return self.lat_accel_friction_factor * error + self.lat_jerk_friction_factor * self.jerk_ahead

  def _measured_jerk(self, car_state, vehicle_model) -> float:
    curvature_rate = -vehicle_model.calc_curvature(math.radians(car_state.steeringRateDeg), car_state.vEgo, 0.0)
    return curvature_rate * car_state.vEgo ** 2

  def _horizon_index(self, speed_mps: float) -> int:
    lookahead = np.interp(speed_mps, self.friction_look_ahead_bp, self.friction_look_ahead_v)
    return next((i for i, t in enumerate(ModelConstants.T_IDXS) if t > lookahead), _JERK_FALLBACK_IDX)

  def _reset_jerk_estimates(self, car_state, vehicle_model):
    self.jerk_now = self._measured_jerk(car_state, vehicle_model)
    self.jerk_goal = 0.0
    self.jerk_obs = 0.0
    self.jerk_ahead = 0.0

  def update_calculations(self, car_state, vehicle_model, desired_lat_accel):
    self._reset_jerk_estimates(car_state, vehicle_model)
    if not self.model_valid:
      return

    accel_y = self.model_v2.acceleration.y
    horizon_accel = np.interp(self.desired_lat_jerk_time, ModelConstants.T_IDXS, accel_y)
    desired_jerk = (horizon_accel - desired_lat_accel) / self.desired_lat_jerk_time

    forecast = _pointwise_jerk(accel_y, self.t_diffs)
    window = forecast[PLAN_SAMPLE_START:self._horizon_index(car_state.vEgo)]
    self.jerk_ahead = sign_locked_min(window, desired_jerk)

    if self.jerk_ahead == 0.0:
      self.jerk_now = 0.0
      self.lat_accel_friction_factor = 1.0

    self.jerk_goal = self.lat_jerk_friction_factor * self.jerk_ahead
    self.jerk_obs = self.lat_jerk_friction_factor * self.jerk_now


TorqueBrainCore = PilotLateralBrain

# ===== nnff =====

LOW_SPEED_X = [0, 10, 20, 30]
LOW_SPEED_Y = [12, 3, 1, 0]

# NNFF input layout expected by the trained models (dictated by the model data):
# 4 scalars (v_ego, target, jerk, roll) + past/future target repeats + past/future rolls.
_ERROR_BLEND_BP = [1.0, 2.0]
_ERROR_BLEND_V = [0.0, 1.0]


def roll_pitch_adjust(roll, pitch):
  return roll * math.cos(pitch)


class _HistoryWindow:
  """Rolling past/future sample windows the NNFF vector is assembled from."""

  def __init__(self, past_times, future_times, jerk_time):
    self.past_times = past_times
    self.future_times = future_times
    self.jerk_time = jerk_time
    self.nn_future_times = [t + jerk_time for t in future_times]

    check_frames = [int(abs(t) * 100) for t in past_times]
    self.frame_offsets = [check_frames[0] - f for f in check_frames]
    maxlen = check_frames[0]
    self.roll = deque(maxlen=maxlen)
    self.lat_accel_desired = deque(maxlen=maxlen)
    self.past_future_len = len(past_times) + len(self.nn_future_times)

  def refresh_lag(self, jerk_time):
    self.jerk_time = jerk_time
    self.nn_future_times = [t + jerk_time for t in self.future_times]

  def push(self, roll, lat_accel_desired):
    self.roll.append(roll)
    self.lat_accel_desired.append(lat_accel_desired)

  def _sample(self, buf):
    return [buf[min(len(buf) - 1, i)] for i in self.frame_offsets]

  def past_rolls(self):
    return self._sample(self.roll)

  def past_lat_accels(self):
    return self._sample(self.lat_accel_desired)


class NeuralNetworkFeedForward(PilotLateralBrain):
  def __init__(self, lac_torque, CP, CP_IQ, CI):
    super().__init__(lac_torque, CP, CP_IQ, CI)
    self.params = Params()
    self.enabled = self.params.get_bool("NeuralNetworkFeedForward")
    self.has_nn_model = CP_IQ.iqLateralNet.model.path != MOCK_MODEL_PATH
    self.model = NNTorqueModel(CP_IQ.iqLateralNet.model.path)
    self.pitch = FirstOrderFilter(0.0, 0.5, 0.01)
    self.pitch_last = 0.0

    self.future_times = [0.3, 0.6, 1.0, 1.5]
    self._window = _HistoryWindow([-0.3, -0.2, -0.1], self.future_times, self.desired_lat_jerk_time)
    self.nav_torque_pulse = NavTorquePulseBrain(lac_torque)

  # -- back-compat views onto the history window -------------------------------
  @property
  def nn_future_times(self):
    return self._window.nn_future_times

  @property
  def past_future_len(self):
    return self._window.past_future_len

  @property
  def _nnff_enabled(self):
    return self.enabled and self.model_valid and self.has_nn_model

  def update_limits(self):
    if not self._nnff_enabled:
      return
    self._pid.set_limits(self.lac_torque.steer_max, -self.lac_torque.steer_max)

  def update_lateral_lag(self, lag):
    super().update_lateral_lag(lag)
    self._window.refresh_lag(self.desired_lat_jerk_time)

  # -- torque-space feedforward (non-NN path used for error scaling) -----------
  def _torque_space(self, lateral_accel, CS, gravity_adjusted):
    return self.torque_from_lateral_accel_in_torque_space(
      LatControlInputs(lateral_accel, self._roll_g, CS.vEgo, CS.aEgo),
      self.lac_torque.torque_params, gravity_adjusted=gravity_adjusted)

  def update_feedforward_torque_space(self, CS):
    torque_from_setpoint = self._torque_space(self._accel_goal, CS, gravity_adjusted=False)
    torque_from_measurement = self._torque_space(self._accel_obs, CS, gravity_adjusted=False)
    self._pid_log.error = float(torque_from_setpoint - torque_from_measurement)
    self._ff = self._torque_space(self._grav_la, CS, gravity_adjusted=True)
    self._ff += get_friction_in_torque_space(self._want_la - self._have_la,
                                             self._deadband, FRICTION_THRESHOLD,
                                             self.lac_torque.torque_params)

  def update_output_torque(self, CS):
    freeze_integrator = self._capped or CS.steeringPressed or CS.vEgo < 5
    self._out_tq = self._pid.update(self._pid_log.error, feedforward=self._ff,
                                           speed=CS.vEgo, freeze_integrator=freeze_integrator)

  # -- NN input assembly -------------------------------------------------------
  def _effective_roll(self, params, calibrated_pose):
    roll = params.roll
    if calibrated_pose is not None:
      pitch = self.pitch.update(calibrated_pose.orientation.pitch)
      roll = roll_pitch_adjust(roll, pitch)
      self.pitch_last = pitch
    return roll

  def _future_rolls(self, roll, adjusted_future_times):
    return [roll_pitch_adjust(np.interp(t, ModelConstants.T_IDXS, self.model_v2.orientation.x) + roll,
                              np.interp(t, ModelConstants.T_IDXS, self.model_v2.orientation.y) + self.pitch_last)
            for t in adjusted_future_times]

  def _future_lat_accels(self, adjusted_future_times):
    return [np.interp(t, ModelConstants.T_IDXS, self.model_v2.acceleration.y) for t in adjusted_future_times]

  def _query(self, lead_scalar, jerk_scalar, tail):
    """Build one model input from its 4 leading scalars + the shared tail, then
    run the interpreter. `tail` is (repeat_value_or_None, extra_pairs...)."""
    head = [self._v, lead_scalar, jerk_scalar, self._roll]
    return self.model.evaluate(head + tail)

  def update_neural_network_feedforward(self, CS, params, calibrated_pose) -> None:
    if not self._nnff_enabled:
      return

    self.update_feedforward_torque_space(CS)
    creep = float(np.interp(CS.vEgo, LOW_SPEED_X, LOW_SPEED_Y)) ** 2
    self._accel_goal = self._want_la + creep * self._want_cv
    self._accel_obs = self._have_la + creep * self._have_cv

    # cache per-cycle scalars the query builder reads
    self._v = CS.vEgo
    self._roll = self._effective_roll(params, calibrated_pose)
    self._window.push(self._roll, self._want_la)

    horizon = [t + 0.5 * CS.aEgo * (t / max(CS.vEgo, 1.0)) for t in self.nn_future_times]
    roll_ctx = self._window.past_rolls() + self._future_rolls(self._roll, horizon)
    accel_ctx = self._window.past_lat_accels() + self._future_lat_accels(horizon)

    goal_torque = self._query(self._accel_goal, self.jerk_goal, [self._accel_goal] * self.past_future_len + roll_ctx)
    obs_torque = self._query(self._accel_obs, self.jerk_obs, [self._accel_obs] * self.past_future_len + roll_ctx)
    self._pid_log.error = goal_torque - obs_torque
    self._apply_error_blend()

    friction_input = self.update_friction_input(self._accel_goal, self._accel_obs)
    self._ff = self._query(self._want_la, friction_input, accel_ctx + roll_ctx)
    if self.model.friction_override:
      self._pid_log.error += get_friction(friction_input, self._deadband,
                                          FRICTION_THRESHOLD, self.lac_torque.torque_params)

    self.update_output_torque(CS)

  def _apply_error_blend(self):
    blend = float(np.interp(abs(self._want_la), _ERROR_BLEND_BP, _ERROR_BLEND_V))
    if blend <= 0.0:
      return
    # error query carries a 0.0 roll slot (not the live roll), so build it directly
    from_error = self.model.evaluate([self._v, self._accel_goal - self._accel_obs,
                                      self.jerk_goal - self.jerk_obs, 0.0])
    live = self._pid_log.error
    if sign(live) == sign(from_error) and abs(live) < abs(from_error):
      self._pid_log.error = live * (1.0 - blend) + from_error * blend

  # -- per-cycle snapshot + entry point ----------------------------------------
  def _snapshot_cycle(self, feedforward_seed, pid_core, pid_trace, torque_goal, torque_actual, roll_bias,
                      deadzone, lat_accel_goal, lat_accel_actual, curvature_goal, curvature_actual,
                      gravity_lat_accel, safety_limited, torque_output) -> None:
    self._ff = feedforward_seed
    self._pid = pid_core
    self._pid_log = pid_trace
    self._accel_goal = torque_goal
    self._accel_obs = torque_actual
    self._roll_g = roll_bias
    self._deadband = deadzone
    self._want_la = lat_accel_goal
    self._have_la = lat_accel_actual
    self._want_cv = curvature_goal
    self._have_cv = curvature_actual
    self._grav_la = gravity_lat_accel
    self._capped = safety_limited
    self._out_tq = torque_output

  def update(self, car_state, vehicle_model, pid_core, calibrator, feedforward_seed, pid_trace,
             torque_goal, torque_actual, calibrated_pose, roll_bias, lat_accel_goal, lat_accel_actual,
             deadzone, gravity_lat_accel, curvature_goal, curvature_actual, safety_limited, torque_output):
    self._snapshot_cycle(feedforward_seed, pid_core, pid_trace, torque_goal, torque_actual, roll_bias,
                         deadzone, lat_accel_goal, lat_accel_actual, curvature_goal, curvature_actual,
                         gravity_lat_accel, safety_limited, torque_output)
    self.update_calculations(car_state, vehicle_model, lat_accel_goal)
    self.update_neural_network_feedforward(car_state, calibrator, calibrated_pose)
    self._out_tq = self.nav_torque_pulse.nudge_output_torque(True, car_state, self._out_tq)
    return self._pid_log, self._out_tq


# At higher speeds (25+mph) we can assume:
# Lateral acceleration achieved by a specific car correlates to
# torque applied to the steering rack. It does not correlate to
# wheel slip, or to speed.

# This controller applies torque to achieve desired lateral
# accelerations. To compensate for the low speed effects the
# proportional gain is increased at low speeds by the PID controller.
# Additionally, there is friction in the steering wheel that needs
# to be overcome to move it at all, this is compensated for too.

KP = 0.8
KI = 0.15

INTERP_SPEEDS = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]
KP_INTERP = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, KP]

LP_FILTER_CUTOFF_HZ = 1.2
JERK_LOOKAHEAD_SECONDS = 0.19
JERK_GAIN = 0.3
LAT_ACCEL_REQUEST_BUFFER_SECONDS = 1.0
VERSION = 1

class LatControlTorque(LatControl):
  def __init__(self, CP, CP_IQ, CI, dt):
    super().__init__(CP, CP_IQ, CI, dt)
    self.torque_params = CP.lateralTuning.torque.as_builder()
    self.torque_from_lateral_accel = CI.torque_from_lateral_accel()
    self.lateral_accel_from_torque = CI.lateral_accel_from_torque()
    self.pid = PIDController([INTERP_SPEEDS, KP_INTERP], KI, rate=1/self.dt)
    self.update_limits()
    self.steering_angle_deadzone_deg = self.torque_params.steeringAngleDeadzoneDeg
    self.lat_accel_request_buffer_len = int(LAT_ACCEL_REQUEST_BUFFER_SECONDS / self.dt)
    self.lat_accel_request_buffer = deque([0.] * self.lat_accel_request_buffer_len , maxlen=self.lat_accel_request_buffer_len)
    self.lookahead_frames = int(JERK_LOOKAHEAD_SECONDS / self.dt)
    self.jerk_filter = FirstOrderFilter(0.0, 1 / (2 * np.pi * LP_FILTER_CUTOFF_HZ), self.dt)

    self.nnff_assist = NeuralNetworkFeedForward(self, CP, CP_IQ, CI)

  def update_live_torque_params(self, latAccelFactor, latAccelOffset, friction):
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

    lookahead_idx = int(np.clip(-delay_frames + self.lookahead_frames, -self.lat_accel_request_buffer_len+1, -2))
    raw_lateral_jerk = (self.lat_accel_request_buffer[lookahead_idx+1] - self.lat_accel_request_buffer[lookahead_idx-1]) / (2 * self.dt)
    desired_lateral_jerk = self.jerk_filter.update(raw_lateral_jerk)
    gravity_adjusted_future_lateral_accel = future_desired_lateral_accel - roll_compensation
    ff = gravity_adjusted_future_lateral_accel
    # latAccelOffset corrects roll compensation bias from device roll misalignment relative to car roll
    ff -= self.torque_params.latAccelOffset
    ff += get_friction(error + JERK_GAIN * desired_lateral_jerk, lateral_accel_deadzone, FRICTION_THRESHOLD, self.torque_params)

    if not active:
      output_torque = 0.0
      pid_log.active = False
    else:
      # do error correction in lateral acceleration space, convert at end to handle non-linear torque responses correctly
      pid_log.error = float(error)

      freeze_integrator = steer_limited_by_safety or CS.steeringPressed or CS.vEgo < 5
      output_lataccel = self.pid.update(pid_log.error, speed=CS.vEgo, feedforward=ff, freeze_integrator=freeze_integrator)
      output_torque = self.torque_from_lateral_accel(output_lataccel, self.torque_params)

      # Lateral acceleration torque controller extension updates
      # Overrides pid_log.error and output_torque
      pid_log, output_torque = self.nnff_assist.update(CS, VM, self.pid, params, ff, pid_log, setpoint, measurement, calibrated_pose, roll_compensation,
                                                       future_desired_lateral_accel, measurement, lateral_accel_deadzone, gravity_adjusted_future_lateral_accel,
                                                       desired_curvature, measured_curvature, steer_limited_by_safety, output_torque)

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.d = float(self.pid.d)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(-output_torque) # TODO: log lat accel?
      pid_log.actualLateralAccel = float(measurement)
      pid_log.desiredLateralAccel = float(setpoint)
      pid_log.desiredLateralJerk = float(desired_lateral_jerk)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))

    # TODO left is positive in this convention
    return -output_torque, 0.0, pid_log
