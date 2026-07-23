from types import SimpleNamespace

from cereal import car, log

from openpilot.selfdrive.selfdrived.events import EVENTS, ET


EventName = log.OnroadEvent.EventName
AudibleAlert = car.CarControl.HUDControl.AudibleAlert


def test_driver_monitoring_alert_stages():
  expected_sounds = {
    EventName.driverDistracted1: AudibleAlert.preAlert,
    EventName.driverDistracted2: AudibleAlert.promptDistracted,
    EventName.driverDistracted3: AudibleAlert.warningImmediate,
    EventName.driverUnresponsive1: AudibleAlert.none,
    EventName.driverUnresponsive2: AudibleAlert.promptDistracted,
    EventName.driverUnresponsive3: AudibleAlert.warningImmediate,
  }

  for event_name, audible_alert in expected_sounds.items():
    assert EVENTS[event_name][ET.PERMANENT].audible_alert == audible_alert


def test_driver_monitoring_lockout_alert():
  callback = EVENTS[EventName.tooDistracted][ET.NO_ENTRY]
  sm = {'driverMonitoringState': SimpleNamespace(lockout=True, lockoutMinutesRemaining=5)}
  alert = callback(None, None, sm, False, 0, None)

  assert alert.alert_text_1 == "5 minutes Left"
  assert alert.alert_text_2 == "Too Distracted"
