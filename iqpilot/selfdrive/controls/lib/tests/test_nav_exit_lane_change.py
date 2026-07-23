"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import custom, log
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeState
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import AutoLaneChangeMode

ManeuverType = custom.IQNavState.ManeuverType
NavDirection = custom.NavDirection
LaneChangeDirection = log.LaneChangeDirection


class DummyCarState:
  def __init__(self, vEgo=25.0, leftBlinker=False, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
               steeringPressed=False, steeringTorque=0, brakePressed=False):
    self.vEgo = vEgo
    self.leftBlinker = leftBlinker
    self.rightBlinker = rightBlinker
    self.leftBlindspot = leftBlindspot
    self.rightBlindspot = rightBlindspot
    self.steeringPressed = steeringPressed
    self.steeringTorque = steeringTorque
    self.brakePressed = brakePressed


class DummyNavState:
  def __init__(self, active=True, nextManeuverValid=True, nextManeuverType=int(ManeuverType.exit),
               nextManeuverDistance=300.0, nextManeuverDirection=int(NavDirection.right)):
    self.active = active
    self.nextManeuverValid = nextManeuverValid
    self.nextManeuverType = nextManeuverType
    self.nextManeuverDistance = nextManeuverDistance
    self.nextManeuverDirection = nextManeuverDirection


def _make_dh(enabled: bool, enable_bsm: bool):
  dh = DesireHelper()
  dh.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGE
  dh.nav_exit._read_enabled = lambda: enabled  # bypass the (unregistered) param in tests
  dh.nav_exit._enable_bsm = enable_bsm
  return dh


def _run(dh, carstate, nav_state, n=20):
  for _ in range(n):
    dh.update(carstate, True, 1.0, nav_state)
  return dh.desire


def test_feature_off_no_exit_lane_change():
  dh = _make_dh(enabled=False, enable_bsm=True)
  cs = DummyCarState(rightBlindspot=False)
  assert _run(dh, cs, DummyNavState()) == log.Desire.none


def test_no_bsm_requires_nudge_holds_without_one():
  # No blindspot monitor: nav exit must NOT auto-start; without a nudge it stays in preLaneChange.
  dh = _make_dh(enabled=True, enable_bsm=False)
  cs = DummyCarState(steeringPressed=False)
  assert _run(dh, cs, DummyNavState()) == log.Desire.none
  assert dh.lane_change_state == LaneChangeState.preLaneChange
  assert dh.lane_change_direction == LaneChangeDirection.right


def test_no_bsm_starts_on_driver_nudge():
  # Driver nudges the wheel toward the exit (right -> negative torque) -> lane change starts.
  dh = _make_dh(enabled=True, enable_bsm=False)
  cs = DummyCarState(steeringPressed=True, steeringTorque=-1)
  assert _run(dh, cs, DummyNavState()) == log.Desire.laneChangeRight


def test_bsm_auto_starts_when_clear():
  dh = _make_dh(enabled=True, enable_bsm=True)
  cs = DummyCarState(rightBlindspot=False)
  assert _run(dh, cs, DummyNavState()) == log.Desire.laneChangeRight


def test_bsm_holds_when_blindspot_occupied():
  dh = _make_dh(enabled=True, enable_bsm=True)
  cs = DummyCarState(rightBlindspot=True)
  assert _run(dh, cs, DummyNavState()) == log.Desire.none


def test_only_exit_maneuvers_trigger():
  # A turn maneuver (not an exit) must not trigger the exit lane change.
  dh = _make_dh(enabled=True, enable_bsm=True)
  cs = DummyCarState(rightBlindspot=False)
  nav = DummyNavState(nextManeuverType=int(ManeuverType.turn))
  assert _run(dh, cs, nav) == log.Desire.none


def test_too_far_does_not_trigger():
  dh = _make_dh(enabled=True, enable_bsm=True)
  cs = DummyCarState(rightBlindspot=False)
  nav = DummyNavState(nextManeuverDistance=900.0)
  assert _run(dh, cs, nav) == log.Desire.none
