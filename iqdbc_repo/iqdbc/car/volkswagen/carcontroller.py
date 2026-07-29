"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import sys
import os
import math
import numpy as np
import random
from iqdbc.can import CANPacker
from iqdbc.car import Bus, DT_CTRL, make_tester_present_msg, structs
from iqdbc.car.lateral import apply_driver_steer_torque_limits, apply_steer_angle_limits_simple
from iqdbc.car.lateral import apply_std_curvature_limits
from iqdbc.car.common.conversions import Conversions as CV
from iqdbc.car.common.numpy_fast import clip, interp
from iqdbc.car.interfaces import CarControllerBase
from iqdbc.car.volkswagen import mlbcan, mqbcan, pqcan, mebcan
from iqdbc.car.volkswagen.pq_radar_handler import PQRadarHandler
from iqdbc.car.volkswagen.values import (
  CanBus, CarControllerParams, MQB_A0_CARS, VolkswagenFlags, VolkswagenFlagsIQ, apply_pq_stopping_accel,
)
from iqdbc.car.volkswagen.mebutils import LongControlJerk, LongControlLimit, LatControlCurvature
from iqdbc.car.vehicle_model import VehicleModel
from openpilot.system.proprietary_runtime._verified_import import import_verified_module

iq_lvbs_alc = import_verified_module("iqpilot_alc_private", "iqpilot_private.konn3kt.iqlvbs.alc")
iq_lvbs_commander = import_verified_module("iqpilot_commander_private", "iqpilot_private.konn3kt.iqlvbs.iqlvbs_commander")

iqpilot_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, iqpilot_path)
try:
  from openpilot.common.params import Params
except ImportError:
  pass

VisualAlert = structs.CarControl.HUDControl.VisualAlert
AudibleAlert = structs.CarControl.HUDControl.AudibleAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


def dVisual(CCS, CS):
  if CCS == mqbcan:
    decelV = CS.tsk_verzoeg_anf
  elif CCS == pqcan:
    decelV = CS.br8_acc_anf
  else:
    decelV = False
  return decelV

class MQBStandstillManager:
  BRAKE_TORQUE_RAMP_RATE = 2000.0     # Nm/s
  ASSUMED_WHEEL_RADIUS = 0.328        # m, typical tire rolling radius
  GRAVITY = 9.81                      # m/s^2
  WEGIMPULSE_STILLNESS_FRAMES = 5     # frames of no wheel tick change before assuming standstill
  ESP_OVERRIDE_SPEED = 9.5 * CV.KPH_TO_MS
  MAX_SAFE_STOPPING_SPEED = 10.0 * CV.KPH_TO_MS

  def __init__(self, vehicle_mass: float = 1540.0, accel_min: float = -3.5):
    self.vehicle_mass = vehicle_mass
    self.accel_min = accel_min
    self.can_stop_forever = False
    self.rollback_detected = False
    self.start_commit_active = False
    self.frames_since_last_wheel_pulse = 0
    self.prev_sum_wegimpulse: int | None = None
    self.prev_accel = 0
    self.hold_recovery_active = False

  def get_hill_hold_decel_deficit(self, pitch: float, brake_torque: float) -> float:
    if self.vehicle_mass <= 0:
      return 0.0
    uphill_pitch = max(pitch, 0.0)
    hill_hold_decel = self.GRAVITY * math.sin(uphill_pitch)
    brake_decel = max(brake_torque, 0.0) / (self.vehicle_mass * self.ASSUMED_WHEEL_RADIUS)
    return max(hill_hold_decel - brake_decel, 0.0)

  def get_safe_speed_for_brake_torque(self, pitch: float, brake_torque: float) -> float:
    missing_brake_decel = self.get_hill_hold_decel_deficit(pitch, brake_torque)
    if missing_brake_decel <= 0 or self.vehicle_mass <= 0:
      return 0.0
    brake_decel_build_rate = self.BRAKE_TORQUE_RAMP_RATE / (self.vehicle_mass * self.ASSUMED_WHEEL_RADIUS)
    forward_speed_needed_while_brake_builds = 1.5 * missing_brake_decel ** 2 / brake_decel_build_rate
    return min(forward_speed_needed_while_brake_builds, self.MAX_SAFE_STOPPING_SPEED)

  def get_blended_brake_accel(self, raw_accel: float, v_ego: float, pitch: float, brake_torque: float) -> float:
    zero_brake_decel_deficit = self.get_hill_hold_decel_deficit(pitch, 0.0)
    current_brake_decel_deficit = self.get_hill_hold_decel_deficit(pitch, brake_torque)
    zero_brake_safe_speed = self.get_safe_speed_for_brake_torque(pitch, 0.0)
    if zero_brake_decel_deficit <= 0 or zero_brake_safe_speed <= 0:
      return raw_accel
    brake_deficit_risk = current_brake_decel_deficit / zero_brake_decel_deficit
    speed_risk = max(zero_brake_safe_speed - v_ego, 0.0) / zero_brake_safe_speed
    rollback_risk = float(np.clip(speed_risk * brake_deficit_risk, 0.0, 1.0))
    blended_accel = raw_accel + rollback_risk * (self.accel_min - raw_accel)
    return min(raw_accel, blended_accel)

  def update(self, CS, long_active: bool, accel: float, stopping: bool, starting: bool,
             max_planned_speed: float, pitch: float = 0.0,
             tsk_brake_torque: float = 0.0) -> tuple[bool, float, bool, bool, bool | None, bool | None]:

    safe_stopping_speed = self.get_safe_speed_for_brake_torque(pitch, 0.0)
    below_safe_stop_speed = CS.out.vEgo < safe_stopping_speed
    can_accelerate = max_planned_speed > safe_stopping_speed
    uphill_grade_pct = max(math.tan(pitch) * 100.0, 0.0)
    takeoff_acceleration = max(0.2, 0.1 * uphill_grade_pct)

    if CS.out.vEgo < self.ESP_OVERRIDE_SPEED:
      esp_starting_override: bool | None = True
      esp_stopping_override: bool | None = False
    else:
      esp_starting_override = None
      esp_stopping_override = None

    if CS.rolling_backward:
      self.rollback_detected = True
    elif CS.rolling_forward:
      self.rollback_detected = False

    wheel_did_pulse = CS.sum_wegimpulse != self.prev_sum_wegimpulse
    self.prev_sum_wegimpulse = CS.sum_wegimpulse
    if wheel_did_pulse:
      self.frames_since_last_wheel_pulse = 0
    else:
      self.frames_since_last_wheel_pulse += 1
    near_standstill = self.frames_since_last_wheel_pulse >= self.WEGIMPULSE_STILLNESS_FRAMES

    # acc type 1 is sensitive to control signals when brake is pressed (when preEnabled)
    if CS.out.brakePressed:
      long_active = False

    if long_active and not CS.out.gasPressed:
      if CS.esp_hold_confirmation:
        self.start_commit_active = True
      if can_accelerate and below_safe_stop_speed and accel > 0:
        self.start_commit_active = True
      elif self.start_commit_active:
        if CS.out.vEgo > safe_stopping_speed:
          self.start_commit_active = False
    else:
      self.start_commit_active = False

    if long_active:
      raw_accel = accel
      if self.start_commit_active:
        accel = max(accel, takeoff_acceleration)
        stopping = False
        starting = True
      elif self.rollback_detected:
        accel = self.accel_min
        stopping = True
        starting = False
      elif below_safe_stop_speed:
        accel = self.get_blended_brake_accel(accel, CS.out.vEgo, pitch, tsk_brake_torque)
        if accel < raw_accel:
          stopping = True
          starting = False
      if near_standstill and accel < 0 and tsk_brake_torque == 0:
        accel = self.accel_min
        stopping = True
        starting = False
      if CS.out.standstill and accel < 0:
        accel = min(accel, self.prev_accel)

    if long_active:
      if CS.out.vEgo > self.ESP_OVERRIDE_SPEED:
        self.can_stop_forever = False
      if CS.esp_hold_confirmation:
        self.can_stop_forever = False
        self.hold_recovery_active = True

      if self.start_commit_active:
        esp_starting_override = True
        esp_stopping_override = False
      elif CS.esp_stopping:
        self.can_stop_forever = True
        self.hold_recovery_active = False
        esp_starting_override = True
        esp_stopping_override = False
      elif self.can_stop_forever:
        esp_starting_override = True
        esp_stopping_override = False
      elif near_standstill:
        esp_starting_override = False
        esp_stopping_override = True
      # recover from hold confirmations while moving to prevent reconfirming them
      elif self.hold_recovery_active and not CS.out.standstill:
        esp_starting_override = False
        esp_stopping_override = True
    else:
      self.can_stop_forever = False
      self.hold_recovery_active = False

    self.prev_accel = accel
    return long_active, accel, stopping, starting, esp_starting_override, esp_stopping_override

class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP, CP_IQ):
    super().__init__(dbc_names, CP, CP_IQ)
    self._params = Params()
    self.CCP = CarControllerParams(CP)
    self.CAN = CanBus(CP)
    self.packer_pt = CANPacker(dbc_names[Bus.pt])

    self._pt_tx_bus = self.CAN.pt
    if CP.flags & VolkswagenFlags.PQ:
      self.CCS = pqcan
      if CP.flags & VolkswagenFlagsIQ.IQ_PQ_LOWLINE:
        self._pt_tx_bus = self.CAN.aux
    elif CP.flags & VolkswagenFlags.MLB:
      self.CCS = mlbcan
    elif CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      self.CCS = mebcan
    else:
      self.CCS = mqbcan

    self.accel = 0
    self.apply_torque_last = 0
    self.apply_curvature_last = 0.
    self.apply_angle_last = 0
    self.ALC_entryCounter = 0
    self.ALC_driverExit = False
    self.ALC_reentry_blocked = False
    self.ALC_override_last = False
    self.ALC_override_counter = 0
    self.entering = False
    self.active = False
    self.CSLH3_SignLast = 0
    self.CSsteeringAngleDegLast = 0
    self.steering_power_last = 0
    self.long_jerk_control = LongControlJerk(dt=(DT_CTRL * self.CCP.ACC_CONTROL_STEP)) if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO) else None
    self.long_limit_control = LongControlLimit(dt=(DT_CTRL * self.CCP.ACC_CONTROL_STEP)) if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO) else None
    self.gra_acc_counter_last = None
    self.motor3_frame_last = None
    self.motor3_was_stopping = False
    self.motor3_resuming = False
    self.sng_handoff_active = False
    self.acc_counter_seeded = False
    self.klr_counter_last = None
    self.eps_timer_soft_disable_alert = False
    self.hca_frame_timer_running = 0
    self.hca_frame_same_torque = 0
    self.accel_last = 0
    self.long_deviation = 0
    self.long_jerklimit = 0
    self.HCA_Status = 3
    self.leadDistanceBars = 0
    self.lead_distance_bars_last = None
    self.distance_bar_frame = 0
    self.speed_limit_last = 0
    self.speed_limit_changed_timer = 0
    self.blinkerActive = None
    self.hide_ea_error = False
    self.radar_disabled_warning_timer = 0
    # Check once at init whether the DBC includes MEB_AWV_01 (AEB HUD for radar-disabled camera harness cars)
    self._has_aeb_hud_msg = "MEB_AWV_01" in self.packer_pt.dbc.name_to_msg
    self.eps_timer_workaround = bool(CP.flags & (VolkswagenFlags.MLB | VolkswagenFlagsIQ.IQ_PQ_TIMEBOMB))
    self._pq_patch_checked = not bool(CP.flags & VolkswagenFlags.PQ) or self.eps_timer_workaround
    self.hca_frame_timer_resetting = 0
    self.hca_frame_low_torque = 0
    self.long_override_counter = 0
    self.long_disabled_counter = 0
    self.standstill_manager = MQBStandstillManager(CP.mass, self.CCP.ACCEL_MIN) if self.CCS == mqbcan else None
    self.radar_handler = PQRadarHandler(self.CAN) if self.CCS is pqcan else None
    self.blend_stock_radar = False
    self.unavailable = False
    self.unavailable_hold = 0
    self.VM = VehicleModel(CP)
    self.is_mqb_a0 = self._is_mqb_a0_car(CP.carFingerprint)
    self.LateralController = (
      LatControlCurvature(self.CCP.CURVATURE_PID, self.CCP.CURVATURE_LIMITS.CURVATURE_MAX, 1 / (DT_CTRL * self.CCP.STEER_STEP))
      if (CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO))
      else None
    )

  @staticmethod
  def _is_mqb_a0_car(candidate) -> bool:
    return candidate in MQB_A0_CARS

  def _get_mqb_steering_torque_scale(self, v_ego: float, enabled: bool) -> float:
    if enabled and self.CCS == mqbcan:
      return float(np.interp(v_ego, [0.4, 3.5, 4.0], [0.8, 0.95, 1.0]))
    return 1.0

  def _should_spam_mqb_a0_resume(self, CS, enabled: bool) -> bool:
    return bool(
      enabled and
      self.is_mqb_a0 and
      self.CCS == mqbcan and
      CS.out.standstill and
      self.frame % 50 < 15
    )

  def update(self, CC, CC_IQ, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl
    can_sends = []
    output_torque = 0
    apply_torque = 0
    pqhca5or7Toggle = self._params.get_bool("pqhca5or7Toggle")
    eBrakeActive = self._params.get_bool("eBrakeActive")
    iq_mqb_steering_lockout = self._params.get_bool("iqMqbSteeringLockout")
    iq_mqb_acc_resume = self._params.get_bool("iqMqbAccResume")
    self.blend_stock_radar = self._params.get_bool("IQDynamicBlendStockRadar")
    if not self._pq_patch_checked:
      self._pq_patch_checked = True
      self.eps_timer_workaround = not self._params.get_bool("VwPqEpsPatched")
    blend_active = bool(self.blend_stock_radar and self.radar_handler is not None and self.CP.openpilotLongitudinalControl)
    AngleLateralControl = iq_lvbs_alc.angle_lateral_control_enabled(self, CS)
    self.entering = CS.vw_iq_lvbs_alc_entering
    self.active = CS.vw_iq_lvbs_alc_active

    if hud_control.audibleAlert == AudibleAlert.refuse:
      self.unavailable_hold = self.CCP.IQ_PQ_UNAVAILABLE_HUD_FRAMES
    else:
      self.unavailable_hold = max(0, self.unavailable_hold - 1)
    self.unavailable = self.unavailable_hold > 0

    CS.force_rhd_for_bsm = getattr(CC, "forceRHDForBSM", False)
    CS.enable_predicative_speed_limit = getattr(CC.cruiseControl, "speedLimitPredicative", False)
    CS.enable_pred_react_to_speed_limits = getattr(CC.cruiseControl, "speedLimitPredReactToSL", False)
    CS.enable_pred_react_to_curves = getattr(CC.cruiseControl, "speedLimitPredReactToCurves", False)

    if self.frame % self.CCP.STEER_STEP == 0:
      if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        if CC.latActive:
          hca_enabled = True
          if CC.curvatureControllerActive:
            apply_curvature = self.LateralController.update(CS.out, CC, actuators.curvature)
            apply_curvature = apply_curvature + (CS.out.steeringCurvature - (CC.currentCurvature - CC.rollCompensation))
          else:
            apply_curvature = actuators.curvature + (CS.out.steeringCurvature - CC.currentCurvature)
          apply_curvature = apply_std_curvature_limits(apply_curvature, self.apply_curvature_last, CS.out.vEgoRaw, CS.out.steeringCurvature,
                                                       CS.out.steeringPressed, self.CCP.STEER_STEP, CC.latActive, self.CCP.CURVATURE_LIMITS)

          min_power = max(self.steering_power_last - self.CCP.STEERING_POWER_STEP, self.CCP.STEERING_POWER_MIN)
          max_power = min(self.steering_power_last + self.CCP.STEERING_POWER_STEP, self.CCP.STEERING_POWER_MAX)
          target_power_driver = int(np.interp(CS.out.steeringTorque, [self.CCP.STEER_DRIVER_ALLOWANCE, self.CCP.STEER_DRIVER_MAX],
                                                                     [self.CCP.STEERING_POWER_MAX, self.CCP.STEERING_POWER_MIN]))
          target_power = int(np.interp(CS.out.vEgo, [0., 0.5], [self.CCP.STEERING_POWER_MIN, target_power_driver]))
          steering_power = min(max(target_power, min_power), max_power)
        else:
          if self.LateralController is not None:
            self.LateralController.reset()
          if self.steering_power_last > 0:
            hca_enabled = True
            apply_curvature = np.clip(CS.out.steeringCurvature, -self.CCP.CURVATURE_LIMITS.CURVATURE_MAX, self.CCP.CURVATURE_LIMITS.CURVATURE_MAX)
            steering_power = max(self.steering_power_last - self.CCP.STEERING_POWER_STEP, 0)
          else:
            hca_enabled = False
            apply_curvature = 0.
            steering_power = 0

        can_sends.append(self.CCS.create_steering_control(self.packer_pt, self.CAN.pt, apply_curvature, hca_enabled, steering_power))
        self.apply_curvature_last = apply_curvature
        self.steering_power_last = steering_power
      else:
        if CC.latActive and not AngleLateralControl:
          torque_scale = self._get_mqb_steering_torque_scale(CS.out.vEgo, iq_mqb_steering_lockout)
          new_torque = int(round(actuators.torque * self.CCP.STEER_MAX * torque_scale))
          apply_torque = apply_driver_steer_torque_limits(new_torque, self.apply_torque_last, CS.out.steeringTorque, self.CCP)
          self.hca_frame_timer_running += self.CCP.STEER_STEP
          if self.apply_torque_last == apply_torque:
            self.hca_frame_same_torque += self.CCP.STEER_STEP
            if self.hca_frame_same_torque > self.CCP.STEER_TIME_STUCK_TORQUE / DT_CTRL:
              apply_torque -= (1, -1)[apply_torque < 0]
              self.hca_frame_same_torque = 0
          else:
            self.hca_frame_same_torque = 0
          hca_enabled = abs(apply_torque) > 0
          if self.eps_timer_workaround and self.hca_frame_timer_running >= self.CCP.STEER_TIME_BM / DT_CTRL:
            if abs(apply_torque) <= self.CCP.STEER_LOW_TORQUE:
              self.hca_frame_low_torque += self.CCP.STEER_STEP
              if self.hca_frame_low_torque >= self.CCP.STEER_TIME_LOW_TORQUE / DT_CTRL:
                hca_enabled = False
            else:
              self.hca_frame_low_torque = 0
              if self.hca_frame_timer_resetting > 0:
                apply_torque = 0
        else:
          self.hca_frame_low_torque = 0
          hca_enabled = False
          apply_torque = 0

        if hca_enabled:
          output_torque = apply_torque
          self.hca_frame_timer_resetting = 0
        else:
          output_torque = 0
          self.hca_frame_timer_resetting += self.CCP.STEER_STEP
          if self.hca_frame_timer_resetting >= self.CCP.STEER_TIME_RESET / DT_CTRL or not self.eps_timer_workaround:
            self.hca_frame_timer_running = 0
            apply_torque = 0

        if hca_enabled and abs(apply_torque) > 0:
          if pqhca5or7Toggle and (self.CP.flags & (VolkswagenFlags.PQ | VolkswagenFlags.MLB)):
            self.HCA_Status = 7
          else:
            self.HCA_Status = 5
        else:
          self.HCA_Status = 3

        self.eps_timer_soft_disable_alert = self.hca_frame_timer_running > self.CCP.STEER_TIME_ALERT / DT_CTRL
        self.apply_torque_last = apply_torque
        if not (AngleLateralControl and self.CCS in (mqbcan, pqcan, mlbcan)):
          can_sends.append(self.CCS.create_hca_steering_control(self.packer_pt, self._pt_tx_bus, output_torque, self.HCA_Status))

      if self.CP.flags & VolkswagenFlags.STOCK_HCA_PRESENT and self.CCS == mqbcan:
        ea_simulated_torque = float(np.clip(apply_torque * 2, -self.CCP.STEER_MAX, self.CCP.STEER_MAX))
        if abs(CS.out.steeringTorque) > abs(ea_simulated_torque):
          ea_simulated_torque = CS.out.steeringTorque
        can_sends.append(self.CCS.create_eps_update(self.packer_pt, self.CAN.cam, CS.eps_stock_values, ea_simulated_torque))

    iq_lvbs_alc.update_vw_alc(self, CC, CS, actuators, can_sends, apply_torque)
    if self.frame % self.CCP.STEER_STEP == 0:
      iq_lvbs_alc.append_private_apd(self, CC_IQ, can_sends)

    if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO) and self.CP.flags & VolkswagenFlags.STOCK_KLR_PRESENT:
      if CS.klr_stock_values:
        klr_send_ready = CS.klr_stock_values["COUNTER"] != self.klr_counter_last
        if klr_send_ready:
          can_sends.append(mebcan.create_capacitive_wheel_touch(self.packer_pt, self.CAN.cam, CC.latActive, CS.klr_stock_values))
          can_sends.append(mebcan.create_capacitive_wheel_touch(self.packer_pt, self.CAN.pt, CC.latActive, CS.klr_stock_values))
        self.klr_counter_last = CS.klr_stock_values["COUNTER"]

    if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      if self.frame % 2 == 0:
        blinker_active = CS.left_blinker_active or CS.right_blinker_active
        left_blinker = CC.leftBlinker if not blinker_active else False
        right_blinker = CC.rightBlinker if not blinker_active else False
        can_sends.append(self.CCS.create_blinker_control(self.packer_pt, self.CAN.pt, CS.ea_hud_stock_values, CS.ea_control_stock_values,
                                                         left_blinker, right_blinker, self.hide_ea_error))

    if self.CP.openpilotLongitudinalControl and self.CCS == mqbcan and not self.acc_counter_seeded and CS.acc_stock_counters:
      for name in ("ACC_02", "ACC_06", "ACC_07", "ACC_10"):
        addr = self.packer_pt.dbc.name_to_msg[name].address
        self.packer_pt.counters[addr] = (CS.acc_stock_counters[name] + 1) % 16
      self.acc_counter_seeded = True

    if self.frame % self.CCP.ACC_CONTROL_STEP == 0 and self.CP.openpilotLongitudinalControl and not CS.out.radarDisableFailed:
      stopping = actuators.longControlState == LongCtrlState.stopping
      if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        starting = actuators.longControlState == LongCtrlState.pid and (CS.esp_hold_confirmation or CS.out.vEgo < 0.25)
        accel = float(np.clip(actuators.accel, self.CCP.ACCEL_MIN, self.CCP.ACCEL_MAX) if CC.enabled else 0)

        long_override = CC.cruiseControl.override or CS.out.gasPressed
        self.long_override_counter = min(self.long_override_counter + 1, 5) if long_override else 0
        long_override_begin = long_override and self.long_override_counter < 5

        self.long_disabled_counter = min(self.long_disabled_counter + 1, 5) if not CC.enabled else 0
        long_disabling = not CC.enabled and self.long_disabled_counter < 5

        critical_state = hud_control.visualAlert == VisualAlert.fcw
        if CC.longComfortMode and self.long_jerk_control is not None and self.long_limit_control is not None:
          self.long_jerk_control.update(CC.enabled, long_override, hud_control.leadDistance, hud_control.leadVisible, accel, critical_state)
          self.long_limit_control.update(CC.enabled, CS.out.vEgoRaw, hud_control.setSpeed, hud_control.leadDistance, hud_control.leadVisible, critical_state)

        acc_control = self.CCS.acc_control_value(CS.out.cruiseState.available, CS.out.accFaulted, CC.enabled, long_override)
        acc_hold_type = self.CCS.acc_hold_type(CS.out.cruiseState.available, CS.out.accFaulted, CC.enabled, starting, stopping,
                                               CS.esp_hold_confirmation, long_override, long_override_begin, long_disabling)
        can_sends.extend(self.CCS.create_acc_accel_control(
          self.packer_pt, self.CAN.pt, self.CP, CS.acc_type, CC.enabled,
          self.long_jerk_control.get_jerk_up() if CC.longComfortMode and self.long_jerk_control is not None else 4.0,
          self.long_jerk_control.get_jerk_down() if CC.longComfortMode and self.long_jerk_control is not None else 4.0,
          self.long_limit_control.get_upper_limit() if CC.longComfortMode and self.long_limit_control is not None else 0.,
          self.long_limit_control.get_lower_limit() if CC.longComfortMode and self.long_limit_control is not None else 0.,
          accel, acc_control, acc_hold_type, stopping, starting, CS.esp_hold_confirmation,
          CS.out.vEgoRaw * CV.MS_TO_KPH, long_override, CS.travel_assist_available,
        ))
        self.accel_last = accel
      else:
        stopping = actuators.longControlState == LongCtrlState.stopping
        starting = actuators.longControlState == LongCtrlState.pid and (CS.esp_hold_confirmation or CS.out.vEgo < 0.25)
        long_active = CC.longActive
        accel = actuators.accel
        esp_starting_override = None
        esp_stopping_override = None

        if self.CCS == mqbcan and CS.acc_type == 1 and self.standstill_manager is not None:
          pitch = CC.orientationNED[1] if len(CC.orientationNED) == 3 else 0.0
          long_active, accel, stopping, starting, esp_starting_override, esp_stopping_override = self.standstill_manager.update(
            CS, long_active, accel, stopping, starting, float(getattr(actuators, "speed", 0.0)),
            pitch, CS.tsk_brake_torque,
          )

        acc_control = self.CCS.acc_control_value(CS.out.cruiseState.available, long_active, CC.cruiseControl.override, CS.out.accFaulted)
        accel = float(np.clip(accel, self.CCP.ACCEL_MIN, self.CCP.ACCEL_MAX) if (long_active or CC.cruiseControl.override) else 0)
        self.long_jerklimit = float(interp(accel, [-1.5, -0.3, 0.05], [2.0, 0.52, 0.30]))
        self.long_deviation = float(interp(accel, [-0.3, 0.1], [0.0, 0.20]))
        self.accel_last = accel

        if blend_active and getattr(CC_IQ, "useRadarAccel", False) and CS.acc_radar_sta_adr == 1 and not self.radar_handler.failed:
          accel = float(np.clip(CS.acc_radar_sollbeschl, self.CCP.ACCEL_MIN, self.CCP.ACCEL_MAX))
          self.long_jerklimit = CS.acc_radar_aendgrad
          self.long_deviation = CS.acc_radar_regelabw
          self.accel_last = accel

        if self.CCS == mqbcan:
          can_sends.extend(self.CCS.create_acc_accel_control(
            self.packer_pt, self.CAN.pt, CS.acc_type, accel, acc_control, stopping, starting, CS.esp_hold_confirmation,
            self.long_deviation, self.long_jerklimit, eBrakeActive,
            esp_starting_override=esp_starting_override, esp_stopping_override=esp_stopping_override,
          ))
        else:
          accel = apply_pq_stopping_accel(self.CP.carFingerprint, accel, stopping)

          sng_ecd_enabled = bool(self.CP.flags & VolkswagenFlagsIQ.IQ_PQ_SNG_ECD)
          low_speed = CS.out.vEgo <= self.CCP.SNG_HANDOFF_SPEED
          if sng_ecd_enabled and long_active and low_speed and accel <= 0.05 and not starting:
            self.sng_handoff_active = True
          else:
            self.sng_handoff_active = False
          sng_decel_req = float(np.clip(accel, self.CCP.ACCEL_MIN, self.CCP.SNG_HOLD_DECEL_MAX)) if self.sng_handoff_active else 0.0

          can_sends.extend(self.CCS.create_acc_accel_control(self.packer_pt, self.CAN.pt, CS.acc_type, accel, acc_control, stopping and not self.motor3_resuming, starting, CS.esp_hold_confirmation, self.long_deviation, self.long_jerklimit, eBrakeActive, sng_active=self.sng_handoff_active))
          if sng_ecd_enabled:
            can_sends.append(self.CCS.create_sng_handoff_control(self.packer_pt, self.CAN.aux, self.sng_handoff_active, sng_decel_req))

    if (self.CP.flags & VolkswagenFlags.DISABLE_RADAR) and self.CP.openpilotLongitudinalControl and not CS.out.radarDisableFailed:
      if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        if self.radar_disabled_warning_timer < 600:
          self.radar_disabled_warning_timer += 1
        else:
          self.hide_ea_error = True

        if self.frame % self.CCP.AEB_CONTROL_STEP == 0:
          can_sends.append(make_tester_present_msg(0x700, self.CAN.pt, suppress_response=True))
          can_sends.append(self.CCS.create_aeb_control(self.packer_pt, self.CAN.pt, self.CP))

        if self.frame % self.CCP.AEB_HUD_STEP == 0 and self._has_aeb_hud_msg:
          can_sends.append(self.CCS.create_aeb_hud(self.packer_pt, self.CAN.pt, self.radar_disabled_warning_timer < 600))

        if self.frame % 4 == 0:
          can_sends.append(self.CCS.create_radar_objects(self.packer_pt, self.CAN.pt))

    if self.frame % self.CCP.LDW_STEP == 0:
      hud_alert = 0
      if hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw) or CS.out.steerFaultTemporary:
        hud_alert = self.CCP.LDW_MESSAGES["laneAssistTakeOver"]
      steering_pressed_hud = (self.frame // 2) % 2 == 0 if self.entering else CS.out.steeringPressed
      if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        disable_alerts = getattr(CC, "disableCarSteerAlerts", False)
        sound_alert = self.CCP.LDW_SOUNDS["Chime"] if hud_alert != 0 and not disable_alerts else self.CCP.LDW_SOUNDS["None"]
        can_sends.append(self.CCS.create_lka_hud_control(self.packer_pt, self.CAN.pt, CS.ldw_stock_values, CC.latActive, CS.out.steeringPressed,
                                                         hud_alert, hud_control, sound_alert))
      else:
        can_sends.append(self.CCS.create_lka_hud_control(self.packer_pt, self._pt_tx_bus, CS.ldw_stock_values, CC.latActive, steering_pressed_hud,
                                                         hud_alert, hud_control, self.entering, self.CCS is pqcan and AngleLateralControl, self.active))

    if hud_control.leadDistanceBars != self.lead_distance_bars_last:
      self.distance_bar_frame = self.frame

    if self.frame % self.CCP.ACC_HUD_STEP == 0 and self.CP.openpilotLongitudinalControl:
      fcw_alert = hud_control.visualAlert == VisualAlert.fcw
      d_unresponsive = hud_control.driverUnresponsive
      if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        show_distance_bars = self.frame - self.distance_bar_frame < 400
        gap = max(8, CS.out.vEgo * hud_control.leadFollowTime)
        distance = max(8, hud_control.leadDistance) if hud_control.leadDistance != 0 else 0
        acc_hud_status = self.CCS.acc_hud_status_value(CS.out.cruiseState.available, CS.out.accFaulted, CC.enabled,
                                                       CC.cruiseControl.override or CS.out.gasPressed)

        sl_predicative_active = CC.cruiseControl.speedLimitPredicative and CS.out.cruiseState.speedLimitPredicative != 0
        if CC.cruiseControl.speedLimit and CS.out.cruiseState.speedLimit != 0 and self.speed_limit_last != CS.out.cruiseState.speedLimit:
          self.speed_limit_changed_timer = self.frame
        self.speed_limit_last = CS.out.cruiseState.speedLimit
        sl_active = self.frame - self.speed_limit_changed_timer < 400
        speed_limit = CS.out.cruiseState.speedLimitPredicative if sl_predicative_active else (CS.out.cruiseState.speedLimit if sl_active else 0)

        acc_hud_event = self.CCS.acc_hud_event(acc_hud_status, CS.esp_hold_confirmation, sl_predicative_active,
                                               CS.speed_limit_predicative_type, sl_active)

        can_sends.append(self.CCS.create_acc_hud_control(self.packer_pt, self.CAN.pt, acc_hud_status, hud_control.setSpeed * CV.MS_TO_KPH,
                                                         hud_control.leadVisible, hud_control.leadDistanceBars + 1, show_distance_bars,
                                                         CS.esp_hold_confirmation, distance, gap, fcw_alert, acc_hud_event, speed_limit))
      else:
        leadDistance = min(8, hud_control.leadDistance) if hud_control.leadDistance != 0 else 0
        self.leadDistanceBars = min(3, hud_control.leadDistanceBars)
        acc_hud_status = self.CCS.acc_hud_status_value(CS.out.cruiseState.available, CS.out.accFaulted, CC.longActive, CC.cruiseControl.override)
        set_speed = hud_control.setSpeed * CV.MS_TO_KPH
        decel = dVisual(self.CCS, CS)
        can_sends.append(self.CCS.create_acc_hud_control(self.packer_pt, self.CAN.pt, acc_hud_status, set_speed, leadDistance, self.leadDistanceBars, fcw_alert, hud_control.leadVisible, self.unavailable, decel, d_unresponsive))

    if self.CP.flags & VolkswagenFlags.PQ:
      iq_lvbs_commander.update_turn_signals(self, CC, CS, can_sends)

    if self.CP.openpilotLongitudinalControl and (self.CP.flags & VolkswagenFlags.PQ):
      if blend_active:
        can_sends.extend(self.radar_handler.update(
          self.packer_pt, self.frame, CS,
          blend_active=True,
          engage_req=getattr(CC_IQ, "radarEngageReq", False),
          cancel_req=getattr(CC_IQ, "radarCancelReq", False),
          set_speed_kph=getattr(CC_IQ, "radarSetSpeedKph", 0.0),
          gap_bars=getattr(CC_IQ, "radarGapBars", 0),
          v_ego=CS.out.vEgo,
        ))
      elif self.frame % 2 == 0:
        can_sends.append(self.CCS.filter_motor2(self.packer_pt, self.CAN.ext, CS.motor2_stock))
        can_sends.append(self.CCS.filter_motor5(self.packer_pt, self.CAN.ext, CS.motor5_stock))

    gra_send_ready = self.CP.pcmCruise and CS.gra_stock_values["COUNTER"] != self.gra_acc_counter_last
    if self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      main_cruise_latching = not bool(CS.gra_stock_values["GRA_Typ_Hauptschalter"])
      stock_cancel_pressed = bool(CS.gra_stock_values["GRA_Abbrechen"] if main_cruise_latching else CS.gra_stock_values["GRA_Hauptschalter"])
    elif self.CP.flags & VolkswagenFlags.MLB:
      stock_cancel_pressed = bool(CS.gra_stock_values["LS_Abbrechen"])
    else:
      stock_cancel_pressed = bool(CS.gra_stock_values["GRA_Abbrechen"])

    cancel_cmd = stock_cancel_pressed or CC.cruiseControl.cancel
    resume_cmd = CC.cruiseControl.resume or self._should_spam_mqb_a0_resume(CS, iq_mqb_acc_resume)
    if gra_send_ready and (cancel_cmd or resume_cmd):
      bus_send = self.CAN.aux if self.CP.flags & VolkswagenFlags.PQ else self.CAN.ext
      can_sends.append(self.CCS.create_acc_buttons_control(self.packer_pt, bus_send, CS.gra_stock_values,
                                                           cancel=cancel_cmd, resume=resume_cmd))

    if self.CP.openpilotLongitudinalControl and self.CCS == pqcan and not blend_active:
      if self.frame % 3:
        can_sends.append(self.CCS.create_gra_neu(self.packer_pt, self.CAN.ext, CS.gra_stock_values, CC.longActive))

    if self.CP.flags & VolkswagenFlagsIQ.IQ_PQ_ACC_FTS_EPB:
      is_stopping = actuators.longControlState == LongCtrlState.stopping
      if CS.out.vEgo > 0.5 or not CC.longActive:
        self.motor3_resuming = False
      elif (self.motor3_was_stopping and not is_stopping and self.CP.openpilotLongitudinalControl and CC.longActive):
        self.motor3_resuming = True
      if self.motor3_resuming and CS.motor3_stock:
        can_sends.append(self.CCS.create_motor3_resume(self.packer_pt, self.CAN.aux, CS.motor1_stock, CS.motor3_stock, resume=True))
      self.motor3_was_stopping = is_stopping

    new_actuators = actuators.as_builder()
    new_actuators.torque = self.apply_torque_last / self.CCP.STEER_MAX
    new_actuators.torqueOutputCan = self.apply_torque_last
    if self.CP.steerControlType == structs.CarParams.SteerControlType.angle:
      new_actuators.steeringAngleDeg = float(self.apply_angle_last)
    new_actuators.curvature = float(self.apply_curvature_last)
    new_actuators.accel = self.accel_last
    new_actuators.speed = float(getattr(actuators, "speed", 0.0))

    self.lead_distance_bars_last = hud_control.leadDistanceBars
    self.gra_acc_counter_last = CS.gra_stock_values["COUNTER"]
    self.motor3_frame_last = CS.motor3_frame
    self.frame += 1
    return new_actuators, can_sends
