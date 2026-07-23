from types import SimpleNamespace

from cereal import log
from iqdbc.car import structs

from openpilot.selfdrive.car.car_specific import CarSpecificEvents

EventName = log.OnroadEvent.EventName
GearShifter = structs.CarState.GearShifter


def make_car_state(**overrides):
  base = dict(
    doorOpen=False,
    seatbeltUnlatched=False,
    gearShifter=GearShifter.drive,
    cruiseState=SimpleNamespace(available=True, enabled=False, nonAdaptive=False),
    cruiseFaultLateralMode=False,
    espDisabled=False,
    espActive=False,
    stockFcw=False,
    stockAeb=False,
    stockLkas=False,
    vEgo=15.0,
    brakeHoldActive=False,
    parkingBrake=False,
    accFaulted=False,
    steeringPressed=False,
    steeringDisengage=False,
    brakePressed=False,
    standstill=False,
    gasPressed=False,
    vehicleSensorsInvalid=False,
    invalidLkasSetting=False,
    lowSpeedAlert=False,
    buttonEnable=False,
    buttonEvents=[],
    steerFaultTemporary=False,
    steerFaultPermanent=False,
    blockPcmEnable=False,
  )
  base.update(overrides)
  return SimpleNamespace(**base)


def test_pcm_disable_suppressed_during_cruise_fault_lateral_mode():
  cp = SimpleNamespace(
    brand="volkswagen",
    openpilotLongitudinalControl=False,
    minEnableSpeed=0.0,
    pcmCruise=True,
    carFingerprint="MOCK",
  )
  events = CarSpecificEvents(cp)

  cs = make_car_state(cruiseFaultLateralMode=True)
  cs_prev = make_car_state(cruiseState=SimpleNamespace(available=True, enabled=True, nonAdaptive=False))

  out = events.update(cs, cs_prev, SimpleNamespace(actuators=SimpleNamespace(accel=0.0)))

  assert not out.has(EventName.pcmDisable)


def test_cruise_fault_lateral_mode_replaces_acc_faulted_alert():
  cp = SimpleNamespace(
    brand="volkswagen",
    openpilotLongitudinalControl=False,
    minEnableSpeed=0.0,
    pcmCruise=True,
    carFingerprint="MOCK",
  )
  events = CarSpecificEvents(cp)

  cs = make_car_state(accFaulted=True, cruiseFaultLateralMode=True)
  cs_prev = make_car_state()

  out = events.update(cs, cs_prev, SimpleNamespace(actuators=SimpleNamespace(accel=0.0)))

  assert out.has(EventName.cruiseFaultLateralAllowed)
  assert not out.has(EventName.accFaulted)


def test_acc_faulted_still_emitted_without_cruise_fault_lateral_mode():
  cp = SimpleNamespace(
    brand="volkswagen",
    openpilotLongitudinalControl=False,
    minEnableSpeed=0.0,
    pcmCruise=True,
    carFingerprint="MOCK",
  )
  events = CarSpecificEvents(cp)

  cs = make_car_state(accFaulted=True)
  cs_prev = make_car_state()

  out = events.update(cs, cs_prev, SimpleNamespace(actuators=SimpleNamespace(accel=0.0)))

  assert out.has(EventName.accFaulted)
  assert not out.has(EventName.cruiseFaultLateralAllowed)


def test_pcm_disable_still_emitted_without_cruise_fault_lateral_mode():
  cp = SimpleNamespace(
    brand="volkswagen",
    openpilotLongitudinalControl=False,
    minEnableSpeed=0.0,
    pcmCruise=True,
    carFingerprint="MOCK",
  )
  events = CarSpecificEvents(cp)

  cs = make_car_state()
  cs_prev = make_car_state(cruiseState=SimpleNamespace(available=True, enabled=True, nonAdaptive=False))

  out = events.update(cs, cs_prev, SimpleNamespace(actuators=SimpleNamespace(accel=0.0)))

  assert out.has(EventName.pcmDisable)
