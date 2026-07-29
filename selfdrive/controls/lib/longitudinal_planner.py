#!/usr/bin/env python3
import math
import numpy as np

import cereal.messaging as messaging
from iqdbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, DEFAULT_STOPPING_SPEED, get_accel_from_plan
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog
from openpilot.common.issue_debug import log_issue_limited

from openpilot.iqpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerIQ

A_CRUISE_MAX_VALS = [2.0, 1.6, 0.8, 0.6]
A_CRUISE_MAX_BP = [0., 10.0, 25., 40.]
A_CRUISE_MIN = -1.2
J_CRUISE = 1.0
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
MIN_ALLOW_THROTTLE_SPEED = 2.5

LAUNCH_DISARM_SPEED = 2.0
LAUNCH_COMMIT_T = 3.5
LAUNCH_MOVING_SPEED = 1.2
LAUNCH_MAX_ACCEL = 1.5

E2E_CRUISE_CONVERGENCE_TAU = 15.0
E2E_CRUISE_ACCEL_MAX = 0.5
E2E_MODEL_SPEED_HORIZON = 5.0
E2E_ACCEL_INTENT_BP = [-0.05, 0.05]
E2E_MODEL_SPEED_INTENT_BP = [-0.5, 0.0]

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]

def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py

def get_lead_distance(radarState):
  if radarState.leadOne.status and (not radarState.leadTwo.status or radarState.leadOne.dRel < radarState.leadTwo.dRel):
    return radarState.leadOne.dRel
  if radarState.leadTwo.status:
    return radarState.leadTwo.dRel
  return 0

def get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, angle_steers, CP, dt, accel_coast, allow_throttle):
  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)

  if not e2e:
    a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
    a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
    a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))
    max_accel = min(max_accel, a_x_allowed)
  if not allow_throttle:
    clipped_accel_coast = max(accel_coast, ACCEL_MIN)
    coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED*2], [max_accel, clipped_accel_coast])
    max_accel = min(max_accel, coast_limit)

  target_accel = np.clip(v_cruise - v_ego, A_CRUISE_MIN, max_accel)
  if not e2e:
    target_accel = float(np.clip(target_accel, a_cruise_prev - J_CRUISE * dt, a_cruise_prev + J_CRUISE * dt))

  cruise_should_stop = v_cruise == 0.0
  return target_accel, cruise_should_stop


def get_e2e_accel(v_ego, v_cruise, model_v, a_target, should_stop):
  if should_stop or v_cruise <= v_ego or len(model_v) != len(T_IDXS_MPC):
    return a_target

  convergence_accel = min((v_cruise - v_ego) / E2E_CRUISE_CONVERGENCE_TAU, E2E_CRUISE_ACCEL_MAX)
  if convergence_accel <= a_target:
    return a_target

  # Only help the model converge to cruise when both its immediate action and
  # velocity trajectory show no active deceleration intent. The lead MPC and
  # cruise candidates remain hard upper bounds on the final acceleration.
  accel_intent = np.interp(a_target, E2E_ACCEL_INTENT_BP, [0.0, 1.0])
  model_speed = np.interp(E2E_MODEL_SPEED_HORIZON, T_IDXS_MPC, model_v)
  speed_intent = np.interp(model_speed - v_ego, E2E_MODEL_SPEED_INTENT_BP, [0.0, 1.0])
  return float(np.interp(min(accel_intent, speed_intent), [0.0, 1.0], [a_target, convergence_accel]))


def get_accel_candidates(e2e, has_lead, mpc_candidate, cruise_candidate, e2e_candidate):
  candidates = []
  # With no lead, the MPC follows a synthetic fast lead. It remains the ACC
  # policy, but must not limit the model policy in full E2E.
  if not e2e or has_lead:
    candidates.append(mpc_candidate)
  candidates.append(cruise_candidate)
  if e2e:
    candidates.append(e2e_candidate)
  return candidates


class LongitudinalPlanner(LongitudinalPlannerIQ):
  def __init__(self, CP, CP_IQ, init_v=0.0, init_a=0.0, dt=DT_MDL):
    self.CP = CP
    self.stopping_speed = CP_IQ.longitudinalStoppingSpeedOverride or DEFAULT_STOPPING_SPEED
    self.mpc = LongitudinalMpc(dt=dt)
    LongitudinalPlannerIQ.__init__(self, self.CP, CP_IQ, self.mpc)
    self.fcw = False
    self.dt = dt
    self.allow_throttle = True

    self.a_desired = init_a
    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = 0.0
    self.output_a_target = 0.0
    self.output_should_stop = False
    self.launch_armed = False
    try:
      self.exp_speed_conv = Params().get_bool("expSpeedConv")
    except UnknownKeyName:
      self.exp_speed_conv = False

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)

  @staticmethod
  def parse_model(model_msg):
    if (len(model_msg.position.x) == ModelConstants.IDX_N and
      len(model_msg.velocity.x) == ModelConstants.IDX_N and
      len(model_msg.acceleration.x) == ModelConstants.IDX_N):
      x = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.position.x)
      v = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.velocity.x)
      a = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.acceleration.x)
      j = np.zeros(len(T_IDXS_MPC))
    else:
      x = np.zeros(len(T_IDXS_MPC))
      v = np.zeros(len(T_IDXS_MPC))
      a = np.zeros(len(T_IDXS_MPC))
      j = np.zeros(len(T_IDXS_MPC))
    if len(model_msg.meta.disengagePredictions.gasPressProbs) > 1:
      throttle_prob = model_msg.meta.disengagePredictions.gasPressProbs[1]
    else:
      throttle_prob = 1.0
    return x, v, a, j, throttle_prob

  def update(self, sm):
    LongitudinalPlannerIQ.update(self, sm)

    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized
    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['liveParameters'].angleOffsetDeg

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.a_desired = np.clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))
    _, model_v, model_a, _, throttle_prob = self.parse_model(sm['modelV2'])
    # Don't clip at low speeds since throttle_prob doesn't account for creep
    self.allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED

    # Get new v_cruise and a_desired from Smart Cruise Control and Speed Limit Assist
    v_cruise, self.a_desired = LongitudinalPlannerIQ.update_targets(self, sm, self.v_desired_filter.x, self.a_desired, v_cruise)

    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    personality = sm['selfdriveState'].personality
    self.mpc.set_weights(personality=personality)
    self.mpc.set_cur_state(self.v_desired_filter.x, self.a_desired)
    self.mpc.update(sm['modelV2'], sm['radarState'], personality=personality)

    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = self.mpc.crash_cnt > 2 and not sm['carState'].standstill
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Save starting point for next iteration
    a_prev = self.a_desired

    action_t =  self.CP.longitudinalActuatorDelay + DT_MDL
    output_a_target_mpc, output_should_stop_mpc = get_accel_from_plan(self.v_desired_trajectory, self.a_desired_trajectory, CONTROL_N_T_IDX,
                                                                        action_t=action_t, stopping_speed=self.stopping_speed)

    output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
    output_should_stop_e2e = sm['modelV2'].action.shouldStop
    output_a_target_e2e, output_should_stop_e2e = self.apply_e2e_stop_distance(sm, v_ego, output_a_target_e2e, output_should_stop_e2e)
    if self.is_e2e(sm) and self.exp_speed_conv and not self.mpc.status:
      output_a_target_e2e = get_e2e_accel(v_ego, v_cruise, model_v, output_a_target_e2e, output_should_stop_e2e)

    if sm['carState'].standstill:
      self.launch_armed = True
    elif v_ego > LAUNCH_DISARM_SPEED:
      self.launch_armed = False
    if (self.launch_armed and self.is_e2e(sm) and not output_should_stop_e2e and
        np.interp(LAUNCH_COMMIT_T, T_IDXS_MPC, model_v) > LAUNCH_DISARM_SPEED):
      t_cut = min(float(T_IDXS_MPC[np.argmax(model_v > LAUNCH_MOVING_SPEED)]), LAUNCH_COMMIT_T)
      t_shifted = T_IDXS_MPC + t_cut
      v_shifted = np.interp(t_shifted, T_IDXS_MPC, model_v)
      a_shifted = np.interp(t_shifted, T_IDXS_MPC, model_a)
      a_launch = get_accel_from_plan(v_shifted, a_shifted, T_IDXS_MPC, action_t=action_t)[0]
      a_launch_max = np.interp(v_ego, [LAUNCH_MOVING_SPEED, LAUNCH_DISARM_SPEED], [LAUNCH_MAX_ACCEL, 0.])
      output_a_target_e2e = max(output_a_target_e2e, min(a_launch, a_launch_max))

    e2e = self.is_e2e(sm)
    self.a_cruise, cruise_should_stop = get_cruise_accel(e2e, v_cruise, v_ego, self.a_cruise,
                                                          steer_angle_without_offset, self.CP, self.dt,
                                                          accel_coast, self.allow_throttle)

    candidates = get_accel_candidates(
      e2e,
      self.mpc.status,
      (output_a_target_mpc, self.mpc.source, output_should_stop_mpc),
      (self.a_cruise, LongitudinalPlanSource.cruise, cruise_should_stop),
      (output_a_target_e2e, LongitudinalPlanSource.e2e, output_should_stop_e2e),
    )

    output_a_target, self.mpc.source, _ = min(candidates, key=lambda c: c[0])
    self.output_should_stop = any(should_stop for _, _, should_stop in candidates)

    self.output_should_stop = self.output_should_stop or self.forcing_stop
    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)

    self.a_desired = float(self.output_a_target)
    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    gate_services = ['carState', 'controlsState', 'selfdriveState', 'radarState']
    plan_send.valid = sm.all_checks(service_list=gate_services)
    if not plan_send.valid:
      log_issue_limited(
        "longitudinal_plan_invalid",
        "planner",
        f"longitudinalPlan invalid alive={ {s: sm.alive[s] for s in gate_services} } "
        f"freq_ok={ {s: sm.freq_ok[s] for s in gate_services} } valid={ {s: sm.valid[s] for s in gate_services} } "
        f"subchecks=({sm.all_alive(gate_services)},{sm.all_freq_ok(gate_services)},{sm.all_valid(gate_services)}) "
        f"recheck={sm.all_checks(service_list=gate_services)}",
        interval_sec=5.0,
      )

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = (sm['modelV2'].leadsV3[0].prob > 0.5) if self.mpc.new_lead_mpc else sm['radarState'].leadOne.status
    longitudinalPlan.leadDistance = get_lead_distance(sm['radarState'])
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.leadTrajectoryX0 = self.mpc.lead_xv_0[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV0 = self.mpc.lead_xv_0[:, 1].tolist()
    longitudinalPlan.leadTrajectoryX1 = self.mpc.lead_xv_1[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV1 = self.mpc.lead_xv_1[:, 1].tolist()

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    pm.send('longitudinalPlan', plan_send)

    self.publish_longitudinal_plan_iq(sm, pm)
