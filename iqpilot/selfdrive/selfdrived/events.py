import cereal.messaging as messaging
from cereal import log, car, custom
from openpilot.common.constants import CV
from openpilot.iqpilot.selfdrive.selfdrived.events_base import EventsBase, Priority, ET, Alert, \
  NoEntryAlert, ImmediateDisableAlert, EngagementAlert, NormalPermanentAlert, AlertCallbackType, wrong_car_mode_alert
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit_controller import SpeedLimitAssistState


AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
AudibleAlertIQ = custom.IQState.AudibleAlert
EventNameIQ = custom.IQOnroadEvent.EventName


# get event name from enum
EVENT_NAME_IQ = {v: k for k, v in EventNameIQ.schema.enumerants.items()}


def _get_longitudinal_plan_ext(sm: messaging.SubMaster):
  return sm['iqPlan']


def speed_limit_adjust_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  plan = _get_longitudinal_plan_ext(sm)
  resolver = plan.speedLimit.resolver
  assist = plan.speedLimit.assist
  speed_conv = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
  speed = round(resolver.speedLimit * speed_conv)
  unit = "km/h" if metric else "mph"
  if assist.state == SpeedLimitAssistState.adapting:
    message = f"Speed Limit: Adjusting to {speed} {unit}"
  else:
    message = f"Speed Limit: Active at {speed} {unit}"
  return Alert(
    message,
    "",
    AlertStatus.normal, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlert.none, 4.)


def speed_limit_pre_active_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  plan = _get_longitudinal_plan_ext(sm)
  resolver = plan.speedLimit.resolver
  speed_conv = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
  unit = "km/h" if metric else "mph"
  pending_speed = round(resolver.speedLimit * speed_conv)
  last_speed = resolver.speedLimitFinalLast * speed_conv
  is_lower = pending_speed < last_speed or last_speed <= 0
  confirm_hint = "SET" if is_lower else "RES"
  return Alert(
    f"Speed Limit: {pending_speed} {unit}",
    f"Press {confirm_hint} to apply",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleLow, .1)


def speed_limit_changed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  resolver = _get_longitudinal_plan_ext(sm).speedLimit.resolver
  speed_conv = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
  speed = round(resolver.speedLimit * speed_conv)
  unit = "km/h" if metric else "mph"
  return Alert(
    f"Speed Limit changed to {speed} {unit}",
    "",
    AlertStatus.normal, AlertSize.small,
    Priority.LOW, VisualAlert.none, AudibleAlertIQ.promptSingleHigh, 3.)


_CAMERA_LABELS = {
  int(custom.IQNavState.CameraType.fixedSpeed): "Speed Camera",
  int(custom.IQNavState.CameraType.mobileSpeed): "Mobile Speed Camera",
  int(custom.IQNavState.CameraType.sectionStart): "Average-Speed Zone",
  int(custom.IQNavState.CameraType.sectionEnd): "Average-Speed Zone Ends",
  int(custom.IQNavState.CameraType.averageZone): "Average-Speed Zone",
  int(custom.IQNavState.CameraType.redLight): "Red-Light Camera",
  int(custom.IQNavState.CameraType.bump): "Speed Bump",
}


def speed_camera_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> Alert:
  nav = sm['iqNavState']
  label = _CAMERA_LABELS.get(int(getattr(nav.cameraType, "raw", nav.cameraType)), "Speed Camera")
  distance = float(nav.cameraDistance)
  if metric:
    dist_str = f"{distance:.0f} m" if distance < 1000.0 else f"{distance / 1000.0:.1f} km"
  else:
    feet = distance * 3.28084
    dist_str = f"{int(round(feet / 10.0) * 10)} ft" if feet < 1000.0 else f"{distance * 0.000621371:.1f} mi"
  detail = dist_str
  if float(nav.cameraSpeedLimit) > 0.0:
    speed_conv = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
    unit = "km/h" if metric else "mph"
    detail += f" • {round(float(nav.cameraSpeedLimit) * speed_conv)} {unit}"
  return Alert(
    label,
    detail,
    AlertStatus.normal, AlertSize.mid,
    Priority.MID, VisualAlert.none, AudibleAlert.prompt, .2)


class IQEvents(EventsBase):
  def __init__(self):
    super().__init__()
    self.event_counters = dict.fromkeys(EVENTS_IQ.keys(), 0)

  def get_events_mapping(self) -> dict[int, dict[str, Alert | AlertCallbackType]]:
    return EVENTS_IQ

  def get_event_name(self, event: int):
    return EVENT_NAME_IQ[event]

  def get_event_msg_type(self):
    return custom.IQOnroadEvent.Event


EVENTS_IQ: dict[int, dict[str, Alert | AlertCallbackType]] = {
  # iqpilot
  EventNameIQ.lkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventNameIQ.lkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventNameIQ.manualSteeringRequired: {
    ET.USER_DISABLE: Alert(
      "Automatic Lane Centering is OFF",
      "Manual Steering Required",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.disengage, 1.),
  },

  EventNameIQ.manualLongitudinalRequired: {
    ET.WARNING: Alert(
      "Smart/Adaptive Cruise Control: OFF",
      "Manual Speed Control Required",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.silentLkasEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameIQ.silentLkasDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
  },

  EventNameIQ.silentBrakeHold: {
    ET.WARNING: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert("Brake Hold Active"),
  },

  EventNameIQ.silentWrongGear: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: Alert(
      "Gear not D",
      "openpilot Unavailable",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0.),
  },

  EventNameIQ.silentReverseGear: {
    ET.PERMANENT: Alert(
      "Reverse\nGear",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.NO_ENTRY: NoEntryAlert("Reverse Gear"),
  },

  EventNameIQ.silentDoorOpen: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert("Door Open"),
  },

  EventNameIQ.silentSeatbeltNotLatched: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert("Seatbelt Unlatched"),
  },

  EventNameIQ.silentParkBrake: {
    ET.WARNING: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0.),
    ET.NO_ENTRY: NoEntryAlert("Parking Brake Engaged"),
  },

  EventNameIQ.controlsMismatchLateral: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Controls Mismatch: Lateral"),
    ET.NO_ENTRY: NoEntryAlert("Controls Mismatch: Lateral"),
  },

  EventNameIQ.experimentalModeSwitched: {
    ET.WARNING: NormalPermanentAlert("Experimental Mode Switched", duration=1.5)
  },

  EventNameIQ.wrongCarModeAlertOnly: {
    ET.WARNING: wrong_car_mode_alert,
  },

  EventNameIQ.pedalPressedAlertOnly: {
    ET.WARNING: NoEntryAlert("Pedal Pressed")
  },

  EventNameIQ.laneTurnLeft: {
    ET.WARNING: Alert(
      "Turning Left",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.laneTurnRight: {
    ET.WARNING: Alert(
      "Turning Right",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventNameIQ.navTurnLeft: {
    ET.WARNING: Alert(
      "Navigation Turn Left",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.5),
  },

  EventNameIQ.navTurnRight: {
    ET.WARNING: Alert(
      "Navigation Turn Right",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.5),
  },

  EventNameIQ.navExitLeft: {
    ET.WARNING: Alert(
      "Navigation Exit Left",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.5),
  },

  EventNameIQ.navExitRight: {
    ET.WARNING: Alert(
      "Navigation Exit Right",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.5),
  },

  EventNameIQ.speedLimitActive: {
    ET.WARNING: speed_limit_adjust_alert,
  },

  EventNameIQ.speedLimitChanged: {
    ET.WARNING: speed_limit_changed_alert,
  },

  EventNameIQ.speedLimitPreActive: {
    ET.WARNING: speed_limit_pre_active_alert,
  },

  EventNameIQ.e2eChime: {
    ET.PERMANENT: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.MID, VisualAlert.none, AudibleAlert.prompt, 3.),
  },

  EventNameIQ.steeringOverrideReengageAlc: {
    ET.WARNING: Alert(
      "Steering Overridden By Driver",
      "Re-Engage ALC",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.none, AudibleAlert.prompt, 2.0),
  },

  EventNameIQ.speedCameraAhead: {
    ET.WARNING: speed_camera_alert,
  },
}
