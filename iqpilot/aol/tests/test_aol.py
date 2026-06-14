"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from types import SimpleNamespace

from cereal import custom
from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from openpilot.iqpilot.aol.aol import AlwaysOnLateral
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents
from openpilot.selfdrive.selfdrived.events import Events


ButtonType = structs.CarState.ButtonEvent.Type
EventNameIQ = custom.IQOnroadEvent.EventName


class MockParams:
  def __init__(self, main_cruise_allowed: bool = False):
    self.main_cruise_allowed = main_cruise_allowed

  def get_bool(self, key: str) -> bool:
    return {
      "AolEnabled": True,
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


def make_selfdrive(cp_flags: int, brand: str = "hyundai", main_cruise_allowed: bool = False):
  cp = SimpleNamespace(
    brand=brand,
    flags=cp_flags,
    passive=False,
    safetyModel=structs.CarParams.SafetyModel.noOutput,
  )
  cp_iq = SimpleNamespace(flags=0)
  return SimpleNamespace(
    CP=cp,
    CP_IQ=cp_iq,
    params=MockParams(main_cruise_allowed),
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


def make_vw_car_state(cruise_available: bool):
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
    lateralAvailable=True,
    buttonEvents=[],
  )


def test_hyundai_lkas_button_can_enable_aol_with_lda_button_before_lateral_available():
  selfdrive = make_selfdrive(HyundaiFlags.HAS_LDA_BUTTON)
  aol = AlwaysOnLateral(selfdrive)

  aol.update_events(make_car_state())

  assert selfdrive.events_iq.has(EventNameIQ.lkasEnable)


def test_hyundai_lkas_button_does_not_enable_aol_without_hyundai_always_toggle_support():
  selfdrive = make_selfdrive(0)
  aol = AlwaysOnLateral(selfdrive)

  aol.update_events(make_car_state())

  assert not selfdrive.events_iq.has(EventNameIQ.lkasEnable)


def test_main_cruise_off_disables_aol_even_if_lateral_available_stays_true():
  selfdrive = make_selfdrive(0, brand="volkswagen", main_cruise_allowed=True)
  selfdrive.CS_prev = make_vw_car_state(cruise_available=True)
  aol = AlwaysOnLateral(selfdrive)
  aol.enabled = True

  aol.update_events(make_vw_car_state(cruise_available=False))

  assert selfdrive.events_iq.has(EventNameIQ.lkasDisable)
