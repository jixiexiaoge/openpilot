#!/usr/bin/env python3
import os
import time
import threading

import cereal.messaging as messaging

from cereal import car, log, custom
from msgq.visionipc import VisionIpcClient, VisionStreamType


from openpilot.common.params import Params
from openpilot.common.issue_debug import log_issue_limited
from openpilot.common.realtime import config_realtime_process, lock_memory, Priority, Ratekeeper, DT_CTRL
from openpilot.common.swaglog import cloudlog
from openpilot.common.gps import get_gps_location_service

from openpilot.selfdrive.car.car_specific import CarSpecificEvents
from openpilot.selfdrive.locationd.helpers import PoseCalibrator, Pose
from openpilot.selfdrive.selfdrived.events import Events, ET
from openpilot.selfdrive.selfdrived.helpers import ExcessiveActuationCheck
from openpilot.selfdrive.selfdrived.state import StateMachine
from openpilot.selfdrive.selfdrived.alertmanager import AlertManager, set_offroad_alert

from openpilot.system.version import get_build_metadata
from openpilot.system.hardware import HARDWARE

from openpilot.iqpilot.sab.behavior import SteeringAssistanceBehavior
def get_sanitize_int_param(key, min_val, max_val, params):
  stored = params.get(key, return_default=True)
  bounded = min(max(stored, min_val), max_val)
  if bounded != stored:
    params.put(key, bounded)
  return bounded


from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import NAV_EXIT_COMMIT_DISTANCE
from openpilot.iqpilot.vehicle.vehicle import VehicleEvents
from openpilot.iqpilot.selfdrive.car.gap_button_actions import GapButtonActions
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents

REPLAY = "REPLAY" in os.environ
SIMULATION = "SIMULATION" in os.environ
TESTING_CLOSET = "TESTING_CLOSET" in os.environ

LONGITUDINAL_PERSONALITY_MAP = {v: k for k, v in log.LongitudinalPersonality.schema.enumerants.items()}

ThermalStatus = log.DeviceState.ThermalStatus
State = log.SelfdriveState.OpenpilotState
PandaType = log.PandaState.PandaType
LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
EventName = log.OnroadEvent.EventName
ButtonType = car.CarState.ButtonEvent.Type
SafetyModel = car.CarParams.SafetyModel
TurnDirection = custom.IQTurnSignalDirection
AlertLevel = log.DriverMonitoringState.AlertLevel
MonitoringPolicy = log.DriverMonitoringState.MonitoringPolicy

IGNORED_SAFETY_MODES = (SafetyModel.silent, SafetyModel.noOutput)


def _cleanup_startup_params(CP: car.CarParams, params: Params) -> None:
  if not CP.alphaLongitudinalAvailable or not CP.openpilotLongitudinalControl:
    return


class SelfdriveD(GapButtonActions):
  def __init__(self, CP=None, CP_IQ=None):
    self.params = Params()

    # Ensure the current branch is cached, otherwise the first cycle lags
    build_metadata = get_build_metadata()

    if CP is None:
      cloudlog.info("selfdrived is waiting for CarParams")
      self.CP = messaging.log_from_bytes(self.params.get("CarParams", block=True), car.CarParams)
      cloudlog.info("selfdrived got CarParams")
    else:
      self.CP = CP

    if CP_IQ is None:
      cloudlog.info("selfdrived is waiting for IQCarParams")
      self.CP_IQ = messaging.log_from_bytes(self.params.get("IQCarParams", block=True), custom.IQCarParams)
      cloudlog.info("selfdrived got IQCarParams")
    else:
      self.CP_IQ = CP_IQ

    self.car_events = CarSpecificEvents(self.CP)

    self.pose_calibrator = PoseCalibrator()
    self.calibrated_pose: Pose | None = None
    self.excessive_actuation_check = ExcessiveActuationCheck()
    self.excessive_actuation = self.params.get("Offroad_ExcessiveActuation") is not None

    # Setup sockets
    self.pm = messaging.PubMaster(['selfdriveState', 'onroadEvents'] + ['iqState', 'iqOnroadEvents'])

    self.gps_location_service = get_gps_location_service(self.params)
    self.gps_packets = [self.gps_location_service]
    self.sensor_packets = ["accelerometer", "gyroscope"]
    self.camera_packets = ["roadCameraState", "driverCameraState", "wideRoadCameraState"]
    if os.path.exists('/tmp/lite_hw'):
      self.camera_packets.remove("driverCameraState")

    # TODO: de-couple selfdrived with card/conflate on carState without introducing controls mismatches
    self.car_state_sock = messaging.sub_sock('carState', timeout=20)

    ignore = self.sensor_packets + self.gps_packets + ['alertDebug', 'lateralManeuverPlan', 'iqDriveModelData', 'iqNavState', 'liveParameters', 'driverAssistance', 'testJoystick']
    if os.path.exists('/tmp/lite_hw'):
      ignore += ['driverCameraState', 'driverMonitoringState']
    if SIMULATION:
      ignore += ['driverCameraState', 'managerState']
    if REPLAY:
      # no vipc in replay will make them ignored anyways
      ignore += ['roadCameraState', 'wideRoadCameraState']
    self.sm = messaging.SubMaster(['deviceState', 'pandaStates', 'peripheralState', 'modelV2', 'liveCalibration',
                                   'carOutput', 'driverMonitoringState', 'longitudinalPlan', 'livePose', 'liveDelay',
                                   'managerState', 'liveParameters', 'radarState', 'liveTorqueParameters',
                                   'controlsState', 'carControl', 'driverAssistance', 'alertDebug', 'userBookmark', 'audioFeedback',
                                   'lateralManeuverPlan',
                                   'iqDriveModelData', 'iqNavState', 'iqPlan', 'testJoystick'] + \
                                   self.camera_packets + self.sensor_packets + self.gps_packets,
                                  ignore_alive=ignore, ignore_avg_freq=ignore,
                                  ignore_valid=ignore, frequency=int(1/DT_CTRL))

    # read params
    self.is_metric = self.params.get_bool("IsMetric")
    self.is_ldw_enabled = self.params.get_bool("IsLdwEnabled")
    self.disengage_on_accelerator = self.params.get_bool("DisengageOnAccelerator")
    self.nav_exit_lane_change = self._read_nav_exit_lane_change()

    car_recognized = self.CP.brand != 'mock'

    _cleanup_startup_params(self.CP, self.params)

    self.CS_prev = car.CarState.new_message()
    self.AM = AlertManager()
    self.events = Events()

    self.initialized = False
    self.enabled = False
    self.active = False
    self.mismatch_counter = 0
    self.cruise_mismatch_counter = 0
    self.last_steering_pressed_frame = 0
    self.distance_traveled = 0
    self.last_functional_fan_frame = 0
    self.events_prev = []
    self.logged_comm_issue = None
    self.not_running_prev = None
    self.dm_lockout_set = False
    self.experimental_mode = False
    self.personality = get_sanitize_int_param(
      "LongitudinalPersonality",
      min(log.LongitudinalPersonality.schema.enumerants.values()),
      max(log.LongitudinalPersonality.schema.enumerants.values()),
      self.params
    )
    self.recalibrating_seen = False
    self.state_machine = StateMachine()
    self.rk = Ratekeeper(100, print_delay_threshold=None)

    self.ignored_processes = set()
    nvme_expected = os.path.exists('/dev/nvme0n1') or (not os.path.isfile("/persist/comma/living-in-the-moment"))
    if HARDWARE.get_device_type() == 'tici' and nvme_expected:
      self.ignored_processes = {'loggerd', }

    # Determine startup event
    is_remote = build_metadata.openpilot.comma_remote or build_metadata.openpilot.iqpilot_remote
    self.startup_event = EventName.startup if is_remote and build_metadata.tested_channel else EventName.startupMaster
    if HARDWARE.get_device_type() == 'mici':
      self.startup_event = None
    if not car_recognized:
      self.startup_event = EventName.startupNoCar
    elif car_recognized and self.CP.passive:
      self.startup_event = EventName.startupNoControl
    elif self.CP.secOcRequired and not self.CP.secOcKeyAvailable:
      self.startup_event = EventName.startupNoSecOcKey

    if not car_recognized:
      self.events.add(EventName.carUnrecognized, static=True)
      set_offroad_alert("Offroad_CarUnrecognized", True)
    elif self.CP.passive:
      self.events.add(EventName.dashcamMode, static=True)

    self.events_iq = IQEvents()
    self.events_iq_prev = []
    self._cached_plan_event_names: tuple[int, ...] = ()
    self._cached_model_event_names: tuple[int, ...] = ()
    self._cached_nav_event_names: tuple[int, ...] = ()

    self.aol = SteeringAssistanceBehavior(self)
    self.car_events_iq = VehicleEvents(self.CP, self.CP_IQ)

    GapButtonActions.__init__(self, self.CP)

  def _add_iq_event_names(self, event_names: tuple[int, ...] | list[int]) -> None:
    for event_name in event_names:
      self.events_iq.add(event_name)

  def _add_event_names(self, event_names: tuple[int, ...] | list[int]) -> None:
    for event_name in event_names:
      self.events.add(event_name)

  def _refresh_cached_plan_events(self) -> None:
    if self.sm.updated['iqPlan']:
      self._cached_plan_event_names = tuple(event.name.raw for event in self._get_longitudinal_plan_ext().events)

  def _refresh_cached_model_events(self) -> None:
    if not self.sm.updated['iqDriveModelData']:
      return

    lane_turn_direction = self._get_model_data_ext().turnSignalDirection
    if lane_turn_direction == TurnDirection.turnLeft:
      self._cached_model_event_names = (custom.IQOnroadEvent.EventName.modelTurnLeft,)
    elif lane_turn_direction == TurnDirection.turnRight:
      self._cached_model_event_names = (custom.IQOnroadEvent.EventName.modelTurnRight,)
    else:
      self._cached_model_event_names = ()

  def _read_nav_exit_lane_change(self) -> bool:
    try:
      return self.params.get_bool("NavExitLaneChange")
    except Exception:
      return False

  def _refresh_cached_nav_events(self) -> None:
    if not self.sm.updated['iqNavState']:
      return

    nav_state = self.sm['iqNavState']
    nav_events: list[int] = []
    if getattr(nav_state, 'active', False):
      if getattr(nav_state, 'navTurnDesireDirection', 0) == 1:
        nav_events.append(custom.IQOnroadEvent.EventName.navTurnLeft)
      elif getattr(nav_state, 'navTurnDesireDirection', 0) == 2:
        nav_events.append(custom.IQOnroadEvent.EventName.navTurnRight)
      elif self.nav_exit_lane_change and \
          getattr(nav_state, 'nextManeuverValid', False) and \
          getattr(nav_state, 'nextManeuverType', custom.IQNavState.ManeuverType.none) == custom.IQNavState.ManeuverType.exit and \
          0.0 < float(getattr(nav_state, 'nextManeuverDistance', 0.0)) <= NAV_EXIT_COMMIT_DISTANCE:
        if getattr(nav_state, 'nextManeuverDirection', 0) == 1:
          nav_events.append(custom.IQOnroadEvent.EventName.navExitLeft)
        elif getattr(nav_state, 'nextManeuverDirection', 0) == 2:
          nav_events.append(custom.IQOnroadEvent.EventName.navExitRight)

    if getattr(nav_state, 'cameraValid', False):
      nav_events.append(custom.IQOnroadEvent.EventName.speedCameraAhead)

    self._cached_nav_event_names = tuple(nav_events)

  def update_events(self, CS):
    """Compute onroadEvents from carState"""

    self.events.clear()
    self.events_iq.clear()

    if self.sm['controlsState'].lateralControlState.which() == 'debugState':
      self.events.add(EventName.joystickDebug)
      self.startup_event = None

    if self.sm.recv_frame['lateralManeuverPlan'] > 0:
      self.events.add(EventName.lateralManeuver)
      self.startup_event = None
    elif self.sm.recv_frame['alertDebug'] > 0:
      self.events.add(EventName.longitudinalManeuver)
      self.startup_event = None

    # Add startup event
    if self.startup_event is not None:
      self.events.add(self.startup_event)
      self.startup_event = None

    # Don't add any more events if not initialized
    if not self.initialized:
      self.events.add(EventName.selfdriveInitializing)
      return

    # Check for user bookmark press (bookmark button or end of LKAS button feedback)
    if self.sm.updated['userBookmark']:
      self.events.add(EventName.userBookmark)

    if self.sm.updated['audioFeedback']:
      self.events.add(EventName.audioFeedback)

    # Don't add any more events while in dashcam mode
    if self.CP.passive:
      return

    # Block resume if cruise never previously enabled
    resume_pressed = any(be.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for be in CS.buttonEvents)
    volkswagen_op_long = self.CP.brand == "volkswagen" and self.CP.openpilotLongitudinalControl
    if not self.CP.pcmCruise and CS.vCruise > 250 and resume_pressed and not volkswagen_op_long:
      self.events.add(EventName.resumeBlocked)

    if not self.CP.notCar:
      if self.sm['driverMonitoringState'].lockout and not self.dm_lockout_set:
        self.params.put_bool("DriverTooDistracted", True)
        self.dm_lockout_set = True
      elif not self.sm['driverMonitoringState'].lockout and self.dm_lockout_set:
        self.params.remove("DriverTooDistracted")
        self.dm_lockout_set = False

      if self.sm['driverMonitoringState'].lockout or self.sm['driverMonitoringState'].alwaysOnLockout:
        self.events.add(EventName.tooDistracted)

      vision_dm = self.sm['driverMonitoringState'].activePolicy == MonitoringPolicy.vision
      if self.sm['driverMonitoringState'].alertLevel == AlertLevel.one:
        self.events.add(EventName.driverDistracted1 if vision_dm else EventName.driverUnresponsive1)
      elif self.sm['driverMonitoringState'].alertLevel == AlertLevel.two:
        self.events.add(EventName.driverDistracted2 if vision_dm else EventName.driverUnresponsive2)
      elif self.sm['driverMonitoringState'].alertLevel == AlertLevel.three:
        self.events.add(EventName.driverDistracted3 if vision_dm else EventName.driverUnresponsive3)

      self._refresh_cached_plan_events()
      self._add_iq_event_names(self._cached_plan_event_names)

    # Add car events, ignore if CAN isn't valid
    if CS.canValid:
      car_events = self.car_events.update(CS, self.CS_prev, self.sm['carControl']).to_msg()
      self.events.add_from_msg(car_events)

      car_events_iq = self.car_events_iq.update(CS, self.events)
      self._add_iq_event_names(car_events_iq.names)

      if self.CP.notCar:
        # wait for everything to init first
        if self.sm.frame > int(5. / DT_CTRL) and self.initialized:
          # body always wants to enable
          self.events.add(EventName.pcmEnable)

      # Disable on rising edge of accelerator or brake. Also disable on brake when speed > 0
      if (CS.gasPressed and not self.CS_prev.gasPressed and self.disengage_on_accelerator) or \
        (CS.brakePressed and (not self.CS_prev.brakePressed or not CS.standstill)) or \
        (CS.regenBraking and (not self.CS_prev.regenBraking or not CS.standstill)):
        self.events.add(EventName.pedalPressed)

    # Create events for temperature, disk space, and memory
    if self.sm['deviceState'].thermalStatus >= ThermalStatus.red:
      self.events.add(EventName.overheat)
    if self.sm['deviceState'].freeSpacePercent < 7 and not SIMULATION:
      self.events.add(EventName.outOfSpace)
    if self.sm['deviceState'].memoryUsagePercent > 95 and not SIMULATION:
      self.events.add(EventName.lowMemory)

    # Alert if fan isn't spinning for 5 seconds
    if self.sm['peripheralState'].pandaType != log.PandaState.PandaType.unknown:
      if self.sm['peripheralState'].fanSpeedRpm < 500 and self.sm['deviceState'].fanSpeedPercentDesired > 50:
        # allow enough time for the fan controller in the panda to recover from stalls
        if (self.sm.frame - self.last_functional_fan_frame) * DT_CTRL > 15.0:
          self.events.add(EventName.fanMalfunction)
      else:
        self.last_functional_fan_frame = self.sm.frame

    # Handle calibration status
    cal_status = self.sm['liveCalibration'].calStatus
    if cal_status != log.LiveCalibrationData.Status.calibrated:
      if cal_status == log.LiveCalibrationData.Status.uncalibrated:
        self.events.add(EventName.calibrationIncomplete)
      elif cal_status == log.LiveCalibrationData.Status.recalibrating:
        if not self.recalibrating_seen:
          set_offroad_alert("Offroad_Recalibration", True)
        self.recalibrating_seen = True
        self.events.add(EventName.calibrationRecalibrating)
      else:
        self.events.add(EventName.calibrationInvalid)

    # Lane departure warning
    if self.is_ldw_enabled and self.sm.valid['driverAssistance']:
      if self.sm['driverAssistance'].leftLaneDeparture or self.sm['driverAssistance'].rightLaneDeparture:
        self.events.add(EventName.ldw)

    # ******************************************************************************************
    #  NOTE: To fork maintainers.
    #  Disabling or nerfing safety features will get you and your users banned from our servers.
    #  We recommend that you do not change these numbers from the defaults.
    if self.sm.updated['liveCalibration']:
      self.pose_calibrator.feed_live_calib(self.sm['liveCalibration'])
    if self.sm.updated['livePose']:
      device_pose = Pose.from_live_pose(self.sm['livePose'])
      self.calibrated_pose = self.pose_calibrator.build_calibrated_pose(device_pose)

    if self.calibrated_pose is not None:
      excessive_actuation = self.excessive_actuation_check.update(self.sm, CS, self.calibrated_pose)
      if not self.excessive_actuation and excessive_actuation is not None:
        set_offroad_alert("Offroad_ExcessiveActuation", True, extra_text=str(excessive_actuation))
        self.excessive_actuation = True

    if self.excessive_actuation:
      self.events.add(EventName.excessiveActuation)
    # ******************************************************************************************

    # Handle lane change
    if self.sm['modelV2'].meta.laneChangeState == LaneChangeState.preLaneChange:
      direction = self.sm['modelV2'].meta.laneChangeDirection
      if (CS.leftBlindspot and direction == LaneChangeDirection.left) or \
         (CS.rightBlindspot and direction == LaneChangeDirection.right):
        self.events.add(EventName.laneChangeBlocked)
      else:
        if direction == LaneChangeDirection.left:
          self.events.add(EventName.preLaneChangeLeft)
        else:
          self.events.add(EventName.preLaneChangeRight)
    elif self.sm['modelV2'].meta.laneChangeState in (LaneChangeState.laneChangeStarting,
                                                    LaneChangeState.laneChangeFinishing):
      self.events.add(EventName.laneChange)

    # Handle lane turn
    self._refresh_cached_model_events()
    self._add_iq_event_names(self._cached_model_event_names)

    self._refresh_cached_nav_events()
    self._add_iq_event_names(self._cached_nav_event_names)

    for i, pandaState in enumerate(self.sm['pandaStates']):
      # All pandas must match the list of safetyConfigs, and if outside this list, must be silent or noOutput
      if i < len(self.CP.safetyConfigs):
        safety_mismatch = pandaState.safetyModel != self.CP.safetyConfigs[i].safetyModel or \
                          pandaState.safetyParam != self.CP.safetyConfigs[i].safetyParam or \
                          pandaState.alternativeExperience != self.CP.alternativeExperience
      else:
        safety_mismatch = pandaState.safetyModel not in IGNORED_SAFETY_MODES

      # safety mismatch allows some time for pandad to set the safety mode and publish it back from panda
      if (safety_mismatch and self.sm.frame*DT_CTRL > 10.) or \
         pandaState.safetyRxChecksInvalid or \
         self.mismatch_counter >= 200:
        self.events.add(EventName.controlsMismatch)

      if log.PandaState.FaultType.relayMalfunction in pandaState.faults:
        self.events.add(EventName.relayMalfunction)

    # Handle HW and system malfunctions
    # Order is very intentional here. Be careful when modifying this.
    # All events here should at least have NO_ENTRY and SOFT_DISABLE.
    num_events = len(self.events)

    not_running = {p.name for p in self.sm['managerState'].processes if not p.running and p.shouldBeRunning}
    if self.sm.recv_frame['managerState'] and len(not_running):
      if not_running != self.not_running_prev:
        cloudlog.event("process_not_running", not_running=not_running, error=True)
      self.not_running_prev = not_running
    if self.sm.recv_frame['managerState'] and (not_running - self.ignored_processes):
      self.events.add(EventName.processNotRunning)
    else:
      if not SIMULATION and not self.rk.lagging:
        if not self.sm.all_alive(self.camera_packets):
          self.events.add(EventName.cameraMalfunction)
        elif not self.sm.all_freq_ok(self.camera_packets):
          self.events.add(EventName.cameraFrameRate)
    if not REPLAY and self.rk.lagging:
      log_issue_limited(
        "selfdrived_lagging",
        "lag",
        f"selfdrived lagging avg_dt={self.rk.avg_dt.get_average() * 1000:.2f}ms frame={self.sm.frame}",
        interval_sec=1.0,
      )
      self.events.add(EventName.selfdrivedLagging)
    if self.sm['radarState'].radarErrors.canError:
      self.events.add(EventName.canError)
    elif self.sm['radarState'].radarErrors.radarUnavailableTemporary:
      self.events.add(EventName.radarTempUnavailable)
    elif any(self.sm['radarState'].radarErrors.to_dict().values()):
      self.events.add(EventName.radarFault)
    if not self.sm.valid['pandaStates']:
      self.events.add(EventName.usbError)
    if CS.canTimeout:
      self.events.add(EventName.canBusMissing)
    elif not CS.canValid:
      self.events.add(EventName.canError)

    # generic catch-all. ideally, a more specific event should be added above instead
    has_disable_events = self.events.contains(ET.NO_ENTRY) and (self.events.contains(ET.SOFT_DISABLE) or self.events.contains(ET.IMMEDIATE_DISABLE))
    no_system_errors = (not has_disable_events) or (len(self.events) == num_events)
    logs = self._comm_issue_logs()
    has_not_alive = len(logs['not_alive']) > 0
    has_not_freq = len(logs['not_freq_ok']) > 0
    comm_issue_state = (tuple(logs['not_alive']), tuple(logs['not_freq_ok']))
    if (has_not_alive or has_not_freq) and no_system_errors:
      if has_not_alive:
        self.events.add(EventName.commIssue)
      else:
        self.events.add(EventName.commIssueAvgFreq)

      if comm_issue_state != self.logged_comm_issue:
        cloudlog.event("commIssue", error=True, **logs)
        self.logged_comm_issue = comm_issue_state
    else:
      self.logged_comm_issue = None

    if not self.CP.notCar:
      if not self.sm['livePose'].posenetOK:
        self.events.add(EventName.posenetInvalid)
      if not self.sm['liveParameters'].valid and cal_status == log.LiveCalibrationData.Status.calibrated and not TESTING_CLOSET and (not SIMULATION or REPLAY):
        self.events.add(EventName.paramsdTemporaryError)

    # conservative HW alert. if the data or frequency are off, locationd will throw an error
    if any((self.sm.frame - self.sm.recv_frame[s])*DT_CTRL > 10. for s in self.sensor_packets):
      self.events.add(EventName.sensorDataInvalid)

    if not REPLAY:
      # Check for mismatch between openpilot and car's PCM
      cruise_mismatch = CS.cruiseState.enabled and (not self.enabled or not self.CP.pcmCruise)
      self.cruise_mismatch_counter = self.cruise_mismatch_counter + 1 if cruise_mismatch else 0
      if self.cruise_mismatch_counter > int(6. / DT_CTRL):
        self.events.add(EventName.cruiseMismatch)

    # Send a "steering required alert" if saturation count has reached the limit
    if CS.steeringPressed:
      self.last_steering_pressed_frame = self.sm.frame
    recent_steer_pressed = (self.sm.frame - self.last_steering_pressed_frame)*DT_CTRL < 2.0
    controlstate = self.sm['controlsState']
    lac = getattr(controlstate.lateralControlState, controlstate.lateralControlState.which())
    if lac.active and not recent_steer_pressed and not self.CP.notCar:
      clipped_speed = max(CS.vEgo, 0.3)
      actual_lateral_accel = controlstate.curvature * (clipped_speed**2)
      desired_lateral_accel = self.sm['modelV2'].action.desiredCurvature * (clipped_speed**2)
      undershooting = abs(desired_lateral_accel) / abs(1e-3 + actual_lateral_accel) > 1.2
      turning = abs(desired_lateral_accel) > 1.0
      # TODO: lac.saturated includes speed and other checks, should be pulled out
      if undershooting and turning and lac.saturated:
        self.events.add(EventName.steerSaturated)

    # Check for FCW
    stock_long_is_braking = self.enabled and not self.CP.openpilotLongitudinalControl and CS.aEgo < -1.25
    model_fcw = self.sm['modelV2'].meta.hardBrakePredicted and not CS.brakePressed and not stock_long_is_braking
    planner_fcw = self.sm['longitudinalPlan'].fcw and self.enabled
    if (planner_fcw or model_fcw) and not self.CP.notCar:
      self.events.add(EventName.fcw)

    # GPS checks
    gps_ok = self.sm.recv_frame[self.gps_location_service] > 0 and (self.sm.frame - self.sm.recv_frame[self.gps_location_service]) * DT_CTRL < 2.0
    if not gps_ok and self.sm['livePose'].inputsOK and (self.distance_traveled > 1500):
      self.events.add(EventName.noGps)
    if gps_ok:
      self.distance_traveled = 0
    self.distance_traveled += abs(CS.vEgo) * DT_CTRL

    # TODO: fix simulator
    if not SIMULATION or REPLAY:
      if self.sm['modelV2'].frameDropPerc > 20:
        log_issue_limited(
          "modeld_frame_drop",
          "lag",
          f"modeld frame drops={self.sm['modelV2'].frameDropPerc:.1f}% frame={self.sm.frame}",
          interval_sec=1.0,
        )
        self.events.add(EventName.modeldLagging)

    # Mute canBusMissing in Park so standby guidance suppression does not create a false alarm.
    if CS.gearShifter == car.CarState.GearShifter.park and self.aol.enabled:
      self.events.remove(EventName.canBusMissing)

    GapButtonActions.update(self, CS, self.events_iq, self.experimental_mode)

    # decrement personality on distance button press
    if self.CP.openpilotLongitudinalControl:
      if any(not be.pressed and be.type == ButtonType.gapAdjustCruise for be in CS.buttonEvents):
        if not self.experimental_mode_switched:
          self.personality = (self.personality - 1) % 3
          self.params.put_nonblocking('LongitudinalPersonality', self.personality)
          self.events.add(EventName.personalityChanged)
        self.experimental_mode_switched = False

  def _get_model_data_ext(self):
    return self.sm['iqDriveModelData']

  def _get_longitudinal_plan_ext(self):
    return self.sm['iqPlan']

  def _comm_issue_logs(self):
    ignore_freq = getattr(self.sm, "ignore_average_freq", [])
    return {
      'invalid': [s for s, valid in self.sm.valid.items() if not valid and s not in self.sm.ignore_valid],
      'not_alive': [s for s, alive in self.sm.alive.items() if not alive and s not in self.sm.ignore_alive],
      'not_freq_ok': [s for s, freq_ok in self.sm.freq_ok.items() if not freq_ok and s not in ignore_freq],
    }

  def data_sample(self):
    started = time.monotonic()
    _car_state = messaging.recv_one(self.car_state_sock)
    car_state_wait_ms = (time.monotonic() - started) * 1000

    started = time.monotonic()
    CS = _car_state.carState if _car_state else self.CS_prev

    self.sm.update(0)
    sm_update_ms = (time.monotonic() - started) * 1000

    if not self.initialized:
      all_valid = CS.canValid and self.sm.all_checks()
      timed_out = self.sm.frame * DT_CTRL > 6.
      if all_valid or timed_out or (SIMULATION and not REPLAY):
        available_streams = VisionIpcClient.available_streams("camerad", block=False)
        if VisionStreamType.VISION_STREAM_ROAD not in available_streams:
          self.sm.ignore_alive.append('roadCameraState')
          self.sm.ignore_valid.append('roadCameraState')
        if VisionStreamType.VISION_STREAM_WIDE_ROAD not in available_streams:
          self.sm.ignore_alive.append('wideRoadCameraState')
          self.sm.ignore_valid.append('wideRoadCameraState')

        if REPLAY and any(ps.controlsAllowed for ps in self.sm['pandaStates']):
          self.state_machine.state = State.enabled

        self.initialized = True
        comm_issue_logs = self._comm_issue_logs()
        cloudlog.event(
          "selfdrived.initialized",
          dt=self.sm.frame*DT_CTRL,
          timeout=timed_out,
          canValid=CS.canValid,
          invalid=comm_issue_logs['invalid'],
          not_alive=comm_issue_logs['not_alive'],
          not_freq_ok=comm_issue_logs['not_freq_ok'],
          error=True,
        )

    # When the panda and selfdrived do not agree on controls_allowed
    # we want to disengage openpilot. However the status from the panda goes through
    # another socket other than the CAN messages and one can arrive earlier than the other.
    # Therefore we allow a mismatch for two samples, then we trigger the disengagement.
    if not self.enabled:
      self.mismatch_counter = 0

    # All pandas not in silent mode must have controlsAllowed when openpilot is enabled.
    if self.enabled and any(not ps.controlsAllowed for ps in self.sm['pandaStates']
           if ps.safetyModel not in IGNORED_SAFETY_MODES):
      self.mismatch_counter += 1

    sample_total_ms = car_state_wait_ms + sm_update_ms
    if sample_total_ms > 7.0 or car_state_wait_ms > 5.0 or sm_update_ms > 2.0:
      log_issue_limited(
        "selfdrived_sample_breakdown",
        "lag",
        f"selfdrived sample slow total_ms={sample_total_ms:.2f} car_state_wait_ms={car_state_wait_ms:.2f} "
        f"sm_update_ms={sm_update_ms:.2f}",
        interval_sec=1.0,
      )

    return CS

  def update_alerts(self, CS):
    clear_event_types = set()
    if ET.WARNING not in self.state_machine.current_alert_types:
      clear_event_types.add(ET.WARNING)
    if self.enabled:
      clear_event_types.add(ET.NO_ENTRY)

    pers = LONGITUDINAL_PERSONALITY_MAP[self.personality]
    callback_args = [self.CP, CS, self.sm, self.is_metric,
                     self.state_machine.soft_disable_timer, pers]

    alerts = self.events.create_alerts(self.state_machine.current_alert_types, callback_args)
    alerts_iq = self.events_iq.create_alerts(self.state_machine.current_alert_types, callback_args)

    self.AM.add_many(self.sm.frame, alerts + alerts_iq)
    self.AM.process_alerts(self.sm.frame, clear_event_types)

  def publish_selfdriveState(self, CS):
    # selfdriveState
    ss_msg = messaging.new_message('selfdriveState')
    ss_msg.valid = True
    ss = ss_msg.selfdriveState
    ss.enabled = self.enabled
    ss.active = self.active
    ss.state = self.state_machine.state
    ss.engageable = not self.events.contains(ET.NO_ENTRY)
    ss.experimentalMode = self.experimental_mode
    ss.personality = self.personality

    ss.alertText1 = self.AM.current_alert.alert_text_1
    ss.alertText2 = self.AM.current_alert.alert_text_2
    ss.alertSize = self.AM.current_alert.alert_size
    ss.alertStatus = self.AM.current_alert.alert_status
    ss.alertType = self.AM.current_alert.alert_type
    ss.alertSound = self.AM.current_alert.audible_alert
    ss.alertHudVisual = self.AM.current_alert.visual_alert

    self.pm.send('selfdriveState', ss_msg)

    # onroadEvents - logged every second or on change
    if (self.sm.frame % int(1. / DT_CTRL) == 0) or (self.events.names != self.events_prev):
      ce_send = messaging.new_message('onroadEvents', len(self.events))
      ce_send.valid = True
      ce_send.onroadEvents = self.events.to_msg()
      self.pm.send('onroadEvents', ce_send)
    self.events_prev = self.events.names.copy()

    # iqState
    iq_state_msg = messaging.new_message('iqState')
    iq_state_msg.valid = True
    iq_state = iq_state_msg.iqState
    aol = iq_state.aol
    aol.state = self.aol.state_machine.state
    aol.enabled = self.aol.enabled
    aol.active = self.aol.active
    aol.available = self.aol.enabled_toggle
    self.pm.send('iqState', iq_state_msg)

    # iqOnroadEvents - logged every second or on change
    if (self.sm.frame % int(1. / DT_CTRL) == 0) or (self.events_iq.names != self.events_iq_prev):
      iq_events_msg = messaging.new_message('iqOnroadEvents')
      iq_events_msg.valid = True
      iq_events_msg.iqOnroadEvents.events = self.events_iq.to_msg()
      self.pm.send('iqOnroadEvents', iq_events_msg)
    self.events_iq_prev = self.events_iq.names.copy()

  def step(self):
    started = time.monotonic()
    checkpoint = started

    CS = self.data_sample()
    sample_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    self.update_events(CS)
    events_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    if not self.CP.passive and self.initialized:
      self.enabled, self.active = self.state_machine.update(self.events)
    state_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    if not self.CP.notCar:
      self.aol.update(CS)
    aol_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    self.update_alerts(CS)
    alerts_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    self.publish_selfdriveState(CS)
    publish_ms = (time.monotonic() - checkpoint) * 1000

    self.CS_prev = CS

    total_ms = (time.monotonic() - started) * 1000
    if total_ms > 8.0 or events_ms > 4.0 or publish_ms > 3.0:
      log_issue_limited(
        "selfdrived_step_slow",
        "lag",
        f"selfdrived step slow total_ms={total_ms:.2f} sample_ms={sample_ms:.2f} events_ms={events_ms:.2f} "
        f"state_ms={state_ms:.2f} aol_ms={aol_ms:.2f} alerts_ms={alerts_ms:.2f} publish_ms={publish_ms:.2f} "
        f"nav_active={getattr(self.sm['iqNavState'], 'active', False)}",
        interval_sec=1.0,
      )

  def params_thread(self, evt):
    while not evt.is_set():
      self.is_metric = self.params.get_bool("IsMetric")
      self.is_ldw_enabled = self.params.get_bool("IsLdwEnabled")
      self.disengage_on_accelerator = self.params.get_bool("DisengageOnAccelerator")
      self.experimental_mode = self.params.get_bool("ExperimentalMode") and self.CP.openpilotLongitudinalControl
      self.personality = self.params.get("LongitudinalPersonality", return_default=True)
      self.nav_exit_lane_change = self._read_nav_exit_lane_change()

      self.aol.read_params()
      time.sleep(0.1)

  def run(self):
    e = threading.Event()
    t = threading.Thread(target=self.params_thread, args=(e, ))
    try:
      t.start()
      while True:
        self.step()
        self.rk.monitor_time()
    finally:
      e.set()
      t.join()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  lock_memory()
  s = SelfdriveD()
  s.run()

if __name__ == "__main__":
  main()
