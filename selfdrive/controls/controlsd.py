#!/usr/bin/env python3
import math
import time
from numbers import Number

from cereal import car, log
import cereal.messaging as messaging
from openpilot.common.constants import CV
from openpilot.common.iq_perf import PerfSample, PerfTraceEmitter, PerfTraceRing
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process, lock_memory, DT_CTRL, Priority, Ratekeeper
from openpilot.common.swaglog import cloudlog

from iqdbc.car.car_helpers import interfaces
from iqdbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.lib.drive_helpers import clip_curvature
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle, STEER_ANGLE_SATURATION_THRESHOLD
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.selfdrive.controls.lib.latcontrol_torque_pq import LatControlTorquePQ
from openpilot.selfdrive.controls.lib.longcontrol import LongControl
from openpilot.selfdrive.modeld.modeld import LAT_SMOOTH_SECONDS
from openpilot.selfdrive.locationd.helpers import PoseCalibrator, Pose

from openpilot.iqpilot.selfdrive.controls.iq_controls_layer import IQControlsLayer

State = log.SelfdriveState.OpenpilotState
LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

ACTUATOR_FIELDS = tuple(car.CarControl.Actuators.schema.fields.keys())
CTRL_ESSENTIAL_SERVICES = ("carState", "modelV2", "longitudinalPlan", "liveParameters", "selfdriveState")
CTRL_LOOP_WARN_US = 15_000
CTRL_LOOP_BAD_US = 25_000
CTRL_LOOP_SEVERE_US = 50_000
CTRL_PHASE_WARN_US = 8_000
CTRL_TAIL_WARN_US = 8_000
CTRL_FLAG_MISSING_INPUTS = 1 << 0
CTRL_FLAG_RK_OVERRUN = 1 << 1


class Controls(IQControlsLayer):
  def __init__(self) -> None:
    self.params = Params()
    cloudlog.info("controlsd is waiting for CarParams")
    self.CP = messaging.log_from_bytes(self.params.get("CarParams", block=True), car.CarParams)
    cloudlog.info("controlsd got CarParams")

    # Initialize iqpilot controlsd extension and base model state
    IQControlsLayer.__init__(self, self.CP, self.params)

    self.CI = interfaces[self.CP.carFingerprint](self.CP, self.CP_IQ)

    self.sm = messaging.SubMaster(['liveDelay', 'liveParameters', 'liveTorqueParameters', 'modelV2', 'selfdriveState',
                                   'liveCalibration', 'livePose', 'longitudinalPlan', 'lateralManeuverPlan',
                                   'carState', 'carOutput', 'driverMonitoringState', 'onroadEvents',
                                   'driverAssistance', 'liveDelay'] + self.iq_sub_services,
                                  poll='selfdriveState')
    self.pm = messaging.PubMaster(['carControl', 'controlsState', 'iqPerfTrace'] + self.iq_pub_services)

    self.steer_limited_by_safety = False
    self.curvature = 0.0
    self.desired_curvature = 0.0
    self.roll_compensation = 0.0

    self._perf = PerfTraceEmitter("controlsd", pubmaster=self.pm)
    self._perf_ring = PerfTraceRing()

    self._param_update_time = 0.0
    self.enable_curvature_controller = False
    self.enable_speed_limit_control = False
    self.enable_speed_limit_predicative = False
    self.enable_pred_react_to_speed_limits = False
    self.enable_pred_react_to_curves = False
    self.enable_long_comfort_mode = False
    self.force_rhd_for_bsm = False
    self._update_params()

    self.pose_calibrator = PoseCalibrator()
    self.calibrated_pose: Pose | None = None

    self.LoC = LongControl(self.CP, self.CP_IQ)
    self.VM = VehicleModel(self.CP)
    self.LaC: LatControl
    if self.CP.steerControlType in (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED):
      self.LaC = LatControlAngle(self.CP, self.CP_IQ, self.CI, DT_CTRL)
    elif self.CP.lateralTuning.which() == 'pid':
      self.LaC = LatControlPID(self.CP, self.CP_IQ, self.CI, DT_CTRL)
    elif self.CP.lateralTuning.which() == 'torque':
      self.LaC = LatControlTorque(self.CP, self.CP_IQ, self.CI, DT_CTRL)
      if self._use_pq_torque():
        try:
          self.LaC = LatControlTorquePQ(self.CP, self.CP_IQ, self.CI, DT_CTRL)
        except Exception:
          cloudlog.exception("LatControlTorquePQ init failed; using generic torque")

  def _use_pq_torque(self) -> bool:
    try:
      if self.CP.brand != 'volkswagen':
        return False
      from iqdbc.car.volkswagen.values import VolkswagenFlags
      return bool(self.CP.flags & VolkswagenFlags.PQ)
    except Exception:
      cloudlog.exception("pq torque selection failed; using generic torque")
      return False

  def _update_params(self) -> None:
    self.enable_curvature_controller = self.params.get_bool("EnableCurvatureController")
    self.enable_speed_limit_control = self.params.get_bool("EnableSpeedLimitControl")
    self.enable_speed_limit_predicative = self.params.get_bool("EnableSpeedLimitPredicative")
    self.enable_pred_react_to_speed_limits = self.params.get_bool("EnableSLPredReactToSL")
    self.enable_pred_react_to_curves = self.params.get_bool("EnableSLPredReactToCurves")
    self.enable_long_comfort_mode = self.params.get_bool("EnableLongComfortMode")
    self.force_rhd_for_bsm = self.params.get_bool("ForceRHDForBSM")

  def update(self):
    self.sm.update(15)
    if self.sm.updated["liveCalibration"]:
      self.pose_calibrator.feed_live_calib(self.sm['liveCalibration'])
    if self.sm.updated["livePose"]:
      device_pose = Pose.from_live_pose(self.sm['livePose'])
      self.calibrated_pose = self.pose_calibrator.build_calibrated_pose(device_pose)
    if time.monotonic() - self._param_update_time > 3:
      self._update_params()
      self._param_update_time = time.monotonic()

  def state_control(self):
    CS = self.sm['carState']

    # Update VehicleModel
    lp = self.sm['liveParameters']
    x = max(lp.stiffnessFactor, 0.1)
    sr = max(lp.steerRatio, 0.1)
    self.VM.update_params(x, sr)

    steer_angle_without_offset = math.radians(CS.steeringAngleDeg - lp.angleOffsetDeg)
    self.curvature = -self.VM.calc_curvature(steer_angle_without_offset, CS.vEgo, lp.roll)
    self.roll_compensation = -self.VM.roll_compensation(lp.roll, CS.vEgo)

    lac_ext = getattr(self.LaC, "extension", None)
    if self.CP.lateralTuning.which() == 'torque' and hasattr(self.LaC, "update_live_torque_params"):
      torque_params = self.sm['liveTorqueParameters']
      if self.sm.all_checks(['liveTorqueParameters']) and torque_params.useParams:
        self.LaC.update_live_torque_params(torque_params.latAccelFactorFiltered, torque_params.latAccelOffsetFiltered,
                                           torque_params.frictionCoefficientFiltered)

        if lac_ext is not None:
          lac_ext.update_limits()

      if lac_ext is not None:
        lac_ext.update_model_v2(self.sm['modelV2'])

      if lac_ext is not None:
        lac_ext.update_lateral_lag(self.CP.steerActuatorDelay)

    long_plan = self.sm['longitudinalPlan']
    model_v2 = self.sm['modelV2']

    CC = car.CarControl.new_message()
    CC.enabled = self.sm['selfdriveState'].enabled

    # Check which actuators can be enabled
    standstill = abs(CS.vEgo) <= max(self.CP.minSteerSpeed, 0.3) or CS.standstill

    # Get which state to use for active lateral control
    _lat_active = self.iq_lateral_allowed(self.sm)

    CC.latActive = _lat_active and not CS.steerFaultTemporary and not CS.steerFaultPermanent and \
                   (not standstill or self.CP.steerAtStandstill)
    CC.longActive = CC.enabled and not getattr(CS, 'cruiseFaultLateralMode', False) and \
                    not any(e.overrideLongitudinal for e in self.sm['onroadEvents']) and \
                    (self.CP.openpilotLongitudinalControl or not self.CP_IQ.pcmCruiseSpeed)

    actuators = CC.actuators
    actuators.longControlState = self.LoC.long_control_state

    if not CC.latActive:
      self.LaC.reset()

    if not CC.longActive:
      self.LoC.reset()

    # accel PID loop
    pid_accel_limits = self.CI.get_pid_accel_limits(self.CP, self.CP_IQ, CS.vEgo, CS.vCruise * CV.KPH_TO_MS)
    actuators.accel = float(self.LoC.update(CC.longActive, CS, long_plan.aTarget, long_plan.shouldStop, pid_accel_limits,
                                            long_plan.leadDistance, long_plan.hasLead))

    # Steering PID loop and lateral MPC
    # Reset desired curvature to current to avoid violating the limits on engage
    if not CC.latActive:
      new_desired_curvature = self.curvature
    elif self.sm.valid['lateralManeuverPlan']:
      new_desired_curvature = self.sm['lateralManeuverPlan'].desiredCurvature
    else:
      new_desired_curvature = model_v2.action.desiredCurvature

    lat_accel_override = bool(CS.gasPressed) or bool(self.sm['iqState'].aol.active)
    self.desired_curvature, curvature_limited = clip_curvature(CS.vEgo, self.desired_curvature, new_desired_curvature, lp.roll, lat_accel_override)
    lat_delay = self.sm["liveDelay"].lateralDelay + LAT_SMOOTH_SECONDS

    actuators.curvature = self.desired_curvature
    steer, steeringAngleDeg, lac_log = self.LaC.update(CC.latActive, CS, self.VM, lp,
                                                       self.steer_limited_by_safety, self.desired_curvature,
                                                       self.calibrated_pose, curvature_limited, lat_delay)
    if self.CP.steerControlType in (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED):
      actuators.torque = 0.0
      actuators.steeringAngleDeg = float(steeringAngleDeg)
    else:
      actuators.torque = float(steer)
      actuators.steeringAngleDeg = float(steeringAngleDeg)
    # Ensure no NaNs/Infs
    for p in ACTUATOR_FIELDS:
      attr = getattr(actuators, p)
      if not isinstance(attr, Number):
        continue

      if not math.isfinite(attr):
        cloudlog.error(f"actuators.{p} not finite {actuators.to_dict()}")
        setattr(actuators, p, 0.0)

    return CC, lac_log

  def publish(self, CC, lac_log):
    CS = self.sm['carState']

    CC.curvatureControllerActive = self.enable_curvature_controller
    CC.steerLimited = self.steer_limited_by_safety
    CC.forceRHDForBSM = self.force_rhd_for_bsm
    CC.longComfortMode = self.enable_long_comfort_mode

    # Orientation and angle rates can be useful for carcontroller
    # Only calibrated (car) frame is relevant for the carcontroller
    CC.currentCurvature = self.curvature
    CC.rollCompensation = self.roll_compensation
    if self.calibrated_pose is not None:
      CC.orientationNED = self.calibrated_pose.orientation.xyz.tolist()
      CC.angularVelocity = self.calibrated_pose.angular_velocity.xyz.tolist()

    CC.cruiseControl.override = CC.enabled and not CC.longActive and (self.CP.openpilotLongitudinalControl or not self.CP_IQ.pcmCruiseSpeed)
    CC.cruiseControl.cancel = CS.cruiseState.enabled and (not CC.enabled or not self.CP.pcmCruise)
    CC.cruiseControl.resume = CC.enabled and CS.cruiseState.standstill and not self.sm['longitudinalPlan'].shouldStop
    CC.cruiseControl.speedLimit = self.enable_speed_limit_control
    CC.cruiseControl.speedLimitPredicative = self.enable_speed_limit_predicative
    CC.cruiseControl.speedLimitPredReactToSL = self.enable_pred_react_to_speed_limits
    CC.cruiseControl.speedLimitPredReactToCurves = self.enable_pred_react_to_curves

    hudControl = CC.hudControl
    hudControl.setSpeed = float(CS.vCruiseCluster * CV.KPH_TO_MS)
    hudControl.speedVisible = CC.enabled
    hudControl.lanesVisible = CC.enabled
    hudControl.leadVisible = self.sm['longitudinalPlan'].hasLead
    hudControl.leadDistance = self.sm['longitudinalPlan'].leadDistance
    hudControl.leadDistanceBars = self.sm['selfdriveState'].personality.raw + 1
    if self.sm['selfdriveState'].personality.raw == log.LongitudinalPersonality.relaxed:
      hudControl.leadFollowTime = 1.75
    elif self.sm['selfdriveState'].personality.raw == log.LongitudinalPersonality.aggressive:
      hudControl.leadFollowTime = 1.25
    else:
      hudControl.leadFollowTime = 1.45
    hudControl.visualAlert = self.sm['selfdriveState'].alertHudVisual
    hudControl.audibleAlert = self.sm['selfdriveState'].alertSound
    hudControl.driverUnresponsive = self.sm['driverMonitoringState'].noResponseForceDecel

    hudControl.rightLaneVisible = True
    hudControl.leftLaneVisible = True
    if self.sm.valid['driverAssistance']:
      hudControl.leftLaneDepart = self.sm['driverAssistance'].leftLaneDeparture
      hudControl.rightLaneDepart = self.sm['driverAssistance'].rightLaneDeparture

    if self.sm['selfdriveState'].active:
      CO = self.sm['carOutput']
      if self.CP.steerControlType in (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED):
        self.steer_limited_by_safety = abs(CC.actuators.steeringAngleDeg - CO.actuatorsOutput.steeringAngleDeg) > \
                                              STEER_ANGLE_SATURATION_THRESHOLD
      else:
        self.steer_limited_by_safety = abs(CC.actuators.torque - CO.actuatorsOutput.torque) > 1e-2

    # TODO: both controlsState and carControl valids should be set by
    #       sm.all_checks(), but this creates a circular dependency

    # controlsState
    dat = messaging.new_message('controlsState')
    dat.valid = CS.canValid
    cs = dat.controlsState

    cs.curvature = self.curvature
    cs.longitudinalPlanMonoTime = self.sm.logMonoTime['longitudinalPlan']
    cs.lateralPlanMonoTime = self.sm.logMonoTime['modelV2']
    cs.desiredCurvature = self.desired_curvature
    cs.longControlState = self.LoC.long_control_state
    cs.upAccelCmd = float(self.LoC.pid.p)
    cs.uiAccelCmd = float(self.LoC.pid.i)
    cs.ufAccelCmd = float(self.LoC.pid.f)
    cs.forceDecel = bool(self.sm['driverMonitoringState'].noResponseForceDecel or
                         (self.sm['selfdriveState'].state == State.softDisabling))

    lat_tuning = self.CP.lateralTuning.which()
    if self.CP.steerControlType in (car.CarParams.SteerControlType.angle, car.CarParams.SteerControlType.curvatureDEPRECATED):
      cs.lateralControlState.angleState = lac_log
    elif lat_tuning == 'pid':
      cs.lateralControlState.pidState = lac_log
    elif lat_tuning == 'torque':
      cs.lateralControlState.torqueState = lac_log

    self.pm.send('controlsState', dat)

    # carControl
    cc_send = messaging.new_message('carControl')
    cc_send.valid = CS.canValid
    cc_send.carControl = CC
    self.pm.send('carControl', cc_send)

  def _tail_work(self) -> int:
    started_ns = time.monotonic_ns()
    self.refresh_iq_params(self.sm)
    self.publish_iq_state(self.sm, self.pm)
    return (time.monotonic_ns() - started_ns) // 1000

  def _missing_services(self) -> list[str]:
    missing = []
    for service in CTRL_ESSENTIAL_SERVICES:
      if not self.sm.alive[service] or not self.sm.freq_ok[service] or not self.sm.valid[service]:
        missing.append(service)
    return missing

  def _emit_perf_trace(self, frame_id: int, loop_dt_us: int, update_us: int, state_control_us: int,
                       publish_us: int, tail_work_us: int, rk_remaining_us: int) -> None:
    missing_services = self._missing_services()
    flags = 0
    if missing_services:
      flags |= CTRL_FLAG_MISSING_INPUTS
    if rk_remaining_us < 0:
      flags |= CTRL_FLAG_RK_OVERRUN

    sample = PerfSample(
      frame_id=frame_id,
      loop_dt_us=loop_dt_us,
      update_us=update_us,
      state_control_us=state_control_us,
      publish_us=publish_us,
      tail_work_us=tail_work_us,
      rk_remaining_us=rk_remaining_us,
      flags=flags,
    )
    self._perf_ring.push(sample)

    slow_phase = max(update_us, state_control_us, publish_us, tail_work_us)
    if loop_dt_us < CTRL_LOOP_WARN_US and slow_phase < CTRL_PHASE_WARN_US and tail_work_us < CTRL_TAIL_WARN_US and flags == 0:
      return

    if loop_dt_us >= CTRL_LOOP_SEVERE_US:
      severity = "critical"
    elif loop_dt_us >= CTRL_LOOP_BAD_US or rk_remaining_us < -10_000:
      severity = "error"
    else:
      severity = "warning"

    detail = (
      f"update_us={update_us} state_control_us={state_control_us} publish_us={publish_us} "
      f"tail_work_us={tail_work_us} rk_remaining_us={rk_remaining_us}"
    )
    self._perf.emit(
      "controlsd_slow_loop",
      severity=severity,
      frame_id=frame_id,
      total_time_us=loop_dt_us,
      rk_remaining_us=rk_remaining_us,
      flags=flags,
      samples=self._perf_ring.snapshot(),
      missing_services=missing_services,
      detail=detail,
      min_interval_s=0.25,
    )

  def run(self):
    rk = Ratekeeper(100, print_delay_threshold=None)
    while True:
      started_ns = time.monotonic_ns()
      checkpoint_ns = started_ns
      self.update()
      update_us = (time.monotonic_ns() - checkpoint_ns) // 1000
      checkpoint_ns = time.monotonic_ns()

      CC, lac_log = self.state_control()
      state_control_us = (time.monotonic_ns() - checkpoint_ns) // 1000
      checkpoint_ns = time.monotonic_ns()

      self.publish(CC, lac_log)
      publish_us = (time.monotonic_ns() - checkpoint_ns) // 1000
      checkpoint_ns = time.monotonic_ns()

      tail_work_us = self._tail_work()
      loop_dt_us = (time.monotonic_ns() - started_ns) // 1000
      rk_remaining_us = int(rk.remaining * 1_000_000)
      self._emit_perf_trace(self.sm.frame, int(loop_dt_us), int(update_us), int(state_control_us),
                            int(publish_us), int(tail_work_us), rk_remaining_us)
      rk.monitor_time()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  lock_memory()
  controls = Controls()
  controls.run()


if __name__ == "__main__":
  main()
