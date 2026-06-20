#!/usr/bin/env python3

import math
import numpy as np

from cereal import messaging, car
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL, Ratekeeper
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

LongCtrlState = car.CarControl.Actuators.LongControlState
MAX_LAT_ACCEL = 5.0
MAX_STEERING_ANGLE_DEG = 500.0
ACCEL_RELEASE_THRESHOLD = 0.01
DECEL_REQUEST_THRESHOLD = -0.02
STOPPING_HOLD_SPEED_MARGIN = 0.3


def get_lateral_joystick_outputs(CP: car.CarParams, VM: VehicleModel, v_ego: float, roll: float, steer_axis: float) -> tuple[float, float, float]:
  steer_axis = float(np.clip(steer_axis, -1, 1))
  steering_angle_deg = steer_axis * MAX_STEERING_ANGLE_DEG
  curvature = -VM.calc_curvature(math.radians(steering_angle_deg), v_ego, roll)

  if CP.steerControlType in (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED):
    return 0.0, steering_angle_deg, curvature

  max_curvature = MAX_LAT_ACCEL / max(v_ego ** 2, 5)
  max_angle = min(math.degrees(VM.get_steer_from_curvature(max_curvature, v_ego, roll)), MAX_STEERING_ANGLE_DEG)
  return steer_axis, steer_axis * max_angle, steer_axis * -max_curvature


def joystickd_thread():
  params = Params()
  cloudlog.info("joystickd is waiting for CarParams")
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  VM = VehicleModel(CP)

  sm = messaging.SubMaster(['carState', 'onroadEvents', 'liveParameters', 'selfdriveState', 'iqState', 'testJoystick'], frequency=1. / DT_CTRL)
  pm = messaging.PubMaster(['carControl', 'controlsState'])

  # Stop-hold behavior for joystick long control:
  # - enter hold only when user requested decel and we are near/at stop
  # - neutral input does not request decel while rolling
  # - release hold on positive accel request
  decel_intent_latched = False
  stop_hold_latched = False

  rk = Ratekeeper(100, print_delay_threshold=None)
  while 1:
    sm.update(0)

    cc_msg = messaging.new_message('carControl')
    cc_msg.valid = True
    CC = cc_msg.carControl
    ss = sm['selfdriveState']
    ss_iq = sm['iqState']
    aol_enabled = bool(getattr(ss_iq.aol, 'enabled', False))
    aol_active = bool(getattr(ss_iq.aol, 'active', False))
    joystick_angle_lat_active = aol_active or (
      aol_enabled and CP.steerControlType == car.CarParams.SteerControlType.angle
    )

    CC.enabled = bool(ss.enabled or aol_enabled)
    CC.latActive = bool(ss.active or joystick_angle_lat_active) and not sm['carState'].steerFaultTemporary and not sm['carState'].steerFaultPermanent
    CC.longActive = bool(ss.enabled) and not any(e.overrideLongitudinal for e in sm['onroadEvents']) and CP.openpilotLongitudinalControl
    CC.cruiseControl.cancel = sm['carState'].cruiseState.enabled and (not CC.enabled or not CP.pcmCruise)
    CC.hudControl.leadDistanceBars = 2

    actuators = CC.actuators

    # reset joystick if it hasn't been received in a while
    should_reset_joystick = sm.recv_frame['testJoystick'] == 0 or (sm.frame - sm.recv_frame['testJoystick'])*DT_CTRL > 0.2

    if not should_reset_joystick:
      joystick_axes = sm['testJoystick'].axes
    else:
      joystick_axes = [0.0, 0.0]

    if CC.longActive:
      accel_cmd = float(np.clip(joystick_axes[0], -1, 1))
      actuators.accel = 4.0 * accel_cmd

      positive_accel_requested = accel_cmd > ACCEL_RELEASE_THRESHOLD
      negative_accel_requested = accel_cmd < DECEL_REQUEST_THRESHOLD
      near_stop = sm['carState'].standstill or sm['carState'].vEgo <= (CP.vEgoStopping + STOPPING_HOLD_SPEED_MARGIN)

      if positive_accel_requested:
        stop_hold_latched = False
        decel_intent_latched = False
      elif negative_accel_requested:
        decel_intent_latched = True

      if decel_intent_latched and near_stop and not positive_accel_requested:
        stop_hold_latched = True

      # If we are moving again and driver is not asking for decel, clear stale hold state.
      if stop_hold_latched and sm['carState'].vEgo > (CP.vEgoStopping + STOPPING_HOLD_SPEED_MARGIN) and not negative_accel_requested:
        stop_hold_latched = False
        decel_intent_latched = False

      actuators.longControlState = LongCtrlState.stopping if stop_hold_latched else LongCtrlState.pid
      CC.cruiseControl.resume = positive_accel_requested
    else:
      decel_intent_latched = False
      stop_hold_latched = False

    if CC.latActive:
      torque, steering_angle_deg, curvature = get_lateral_joystick_outputs(CP, VM, sm['carState'].vEgo, sm['liveParameters'].roll, joystick_axes[1])
      actuators.torque = torque
      actuators.steeringAngleDeg = steering_angle_deg
      actuators.curvature = curvature

    pm.send('carControl', cc_msg)

    cs_msg = messaging.new_message('controlsState')
    cs_msg.valid = True
    controlsState = cs_msg.controlsState
    controlsState.lateralControlState.init('debugState')

    lp = sm['liveParameters']
    steer_angle_without_offset = math.radians(sm['carState'].steeringAngleDeg - lp.angleOffsetDeg)
    controlsState.curvature = -VM.calc_curvature(steer_angle_without_offset, sm['carState'].vEgo, lp.roll)

    pm.send('controlsState', cs_msg)

    rk.keep_time()


def main():
  joystickd_thread()


if __name__ == "__main__":
  main()
