"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from types import SimpleNamespace

from cereal import custom
from iqdbc.car import structs
from iqdbc.car.hyundai.values import HyundaiFlags, HyundaiFlagsIQ
from openpilot.iqpilot.sab.behavior import SteeringAssistanceBehavior
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents
from openpilot.selfdrive.selfdrived.events import Events


ButtonType = structs.CarState.ButtonEvent.Type
EventNameIQ = custom.IQOnroadEvent.EventName


class MockParams:
  def __init__(self, main_cruise_allowed: bool = False, aol_enabled: bool = True):
    self.main_cruise_allowed = main_cruise_allowed
    self.aol_enabled = aol_enabled

  def get_bool(self, key: str) -> bool:
    return {
      "AolEnabled": self.aol_enabled,
      "AolMainCruiseAllowed": self.main_cruise_allowed,
      "AolUnifiedEngagementMode": False,
      "JoystickDebugMode": False,
    }.get(key, False)

  def get(self, key: str, return_default: bool = False):
    if key == "AolSteeringMode":
      return 0 if return_default else b"0"
    return None

  def remove(self, key: str) -> None:
    return None


def make_selfdrive(cp_flags: int, brand: str = "hyundai", main_cruise_allowed: bool = False,
                   aol_enabled: bool = True, cp_iq_flags: int = 0):
  cp = SimpleNamespace(
    brand=brand,
    flags=cp_flags,
    passive=False,
    notCar=False,
    safetyModel=structs.CarParams.SafetyModel.noOutput,
  )
  cp_iq = SimpleNamespace(flags=cp_iq_flags)
  return SimpleNamespace(
    CP=cp,
    CP_IQ=cp_iq,
    params=MockParams(main_cruise_allowed, aol_enabled),
    state_machine=SimpleNamespace(soft_disable_timer=0, current_alert_types=[]),
    events=Events(),
    events_iq=IQEvents(),
    CS_prev=SimpleNamespace(
      gasPressed=False,
      cruiseState=SimpleNamespace(available=False),
      lateralAvailable=False,
    ),
    enabled=False,
    enabled_prev=False,
    initialized=True,
  )


def make_car_state():
  return SimpleNamespace(
    started=True,
    standstill=False,
    doorOpen=False,
    seatbeltUnlatched=False,
    gearShifter=structs.CarState.GearShifter.drive,
    vEgo=0.0,
    gasPressed=False,
    brakePressed=False,
    cruiseState=SimpleNamespace(available=False),
    lateralAvailable=False,
    buttonEvents=[structs.CarState.ButtonEvent(pressed=True, type=ButtonType.lkas)],
  )


def make_vw_car_state(cruise_available: bool, cruise_fault_lateral: bool = False):
  return SimpleNamespace(
    started=True,
    standstill=False,
    doorOpen=False,
    seatbeltUnlatched=False,
    gearShifter=structs.CarState.GearShifter.drive,
    vEgo=0.0,
    gasPressed=False,
    brakePressed=False,
    cruiseState=SimpleNamespace(available=cruise_available),
    lateralAvailable=cruise_available or cruise_fault_lateral,
    cruiseFaultLateralMode=cruise_fault_lateral,
    buttonEvents=[],
  )


def test_hyundai_lkas_button_can_arm_guidance_before_lateral_available():
  selfdrive = make_selfdrive(0, cp_iq_flags=HyundaiFlagsIQ.HAS_LFA_BUTTON)
  guidance = SteeringAssistanceBehavior(selfdrive)

  guidance.update_events(make_car_state())

  assert selfdrive.events_iq.has(EventNameIQ.alcEngaged)


def test_hyundai_lkas_button_stays_inactive_without_platform_support():
  selfdrive = make_selfdrive(0)
  guidance = SteeringAssistanceBehavior(selfdrive)

  guidance.update_events(make_car_state())

  assert not selfdrive.events_iq.has(EventNameIQ.alcEngaged)


def test_main_cruise_drop_cuts_guidance_even_if_lateral_signal_stays_true():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=True)
  guidance = SteeringAssistanceBehavior(selfdrive)
  guidance.enabled = True

  guidance.update_events(make_vw_car_state(cruise_available=False))

  assert selfdrive.events_iq.has(EventNameIQ.alcDisengaged)


def test_faulted_lateral_mode_does_not_force_disable_guidance():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=True)
  guidance = SteeringAssistanceBehavior(selfdrive)
  guidance.enabled = True

  guidance.update_events(make_vw_car_state(cruise_available=False, cruise_fault_lateral=True))

  assert not selfdrive.events_iq.has(EventNameIQ.alcDisengaged)


def test_main_switch_rising_edge_arms_guidance_during_faulted_cruise():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=False, cruise_fault_lateral=False)
  guidance = SteeringAssistanceBehavior(selfdrive)

  guidance.update_events(make_vw_car_state(cruise_available=False, cruise_fault_lateral=True))

  assert selfdrive.events_iq.has(EventNameIQ.alcEngaged)


def test_main_cruise_rising_edge_does_not_engage_when_toggle_is_off():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True, aol_enabled=False)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=False)
  guidance = SteeringAssistanceBehavior(selfdrive)

  guidance.update(make_vw_car_state(cruise_available=True))

  assert not selfdrive.events_iq.has(EventNameIQ.alcEngaged)
  assert not guidance.active
  assert not guidance.enabled
  assert guidance.state_machine.state == custom.AlwaysOnLateral.AlwaysOnLateralState.disabled


def test_main_cruise_rising_edge_engages_when_toggle_is_on():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True, aol_enabled=True)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=False)
  guidance = SteeringAssistanceBehavior(selfdrive)

  guidance.update(make_vw_car_state(cruise_available=True))

  assert selfdrive.events_iq.has(EventNameIQ.alcEngaged)
  assert guidance.active
