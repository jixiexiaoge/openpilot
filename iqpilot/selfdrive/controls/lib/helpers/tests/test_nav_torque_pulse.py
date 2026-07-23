"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import custom
import openpilot.iqpilot.selfdrive.controls.lib.helpers.nav_torque_pulse as nav_pulse
from openpilot.iqpilot.selfdrive.controls.lib.helpers.nav_torque_pulse import (
  NavTorquePulseBrain, TURN_PULSE_FRAMES, EXIT_PULSE_FRAMES)


@pytest.fixture
def influence_on():
  nav_pulse.IQP_NAV_TORQUE_INFLUENCE_ENABLED = True
  try:
    yield
  finally:
    nav_pulse.IQP_NAV_TORQUE_INFLUENCE_ENABLED = False


def _fixed_nav_sm(**fields):
  nav = SimpleNamespace(
    maneuverPhase=custom.IQNavState.ManeuverPhase.none,
    maneuverDirection=custom.NavDirection.none,
    shouldSendTurnDesire=False,
    turnDesireDirection=0,
    shouldSendLanePositioning=False,
    lanePositioningDirection=0,
  )
  for k, v in fields.items():
    setattr(nav, k, v)

  class SM:
    def update(self, _):
      return None

    def __getitem__(self, _):
      return nav
  return SM()


def _brain(nav_sm=None, steer_max=1.0):
  brain = NavTorquePulseBrain(SimpleNamespace(steer_max=steer_max))
  if nav_sm is not None:
    brain._nav_sm = nav_sm
  return brain


def test_passthrough_when_disabled():
  brain = _brain()
  cs = SimpleNamespace(steeringPressed=False)
  assert brain.nudge_output_torque(True, cs, 0.42) == 0.42


class TestPulseSign:
  @pytest.mark.parametrize("direction,expect_negative", [(1, True), (2, False)])
  def test_turn_desire_direction(self, influence_on, direction, expect_negative):
    brain = _brain(_fixed_nav_sm(shouldSendTurnDesire=True, turnDesireDirection=direction))
    cs = SimpleNamespace(steeringPressed=False)
    first = brain.nudge_output_torque(True, cs, 0.0)
    assert (first < 0.0) == expect_negative

  def test_turn_active_phase_uses_turn_frames(self, influence_on):
    brain = _brain(_fixed_nav_sm(maneuverPhase=custom.IQNavState.ManeuverPhase.turnActive,
                                 turnDesireDirection=1))
    cs = SimpleNamespace(steeringPressed=False)
    outs = [brain.nudge_output_torque(True, cs, 0.0) for _ in range(TURN_PULSE_FRAMES + 2)]
    assert outs[TURN_PULSE_FRAMES - 1] < 0.0
    assert outs[TURN_PULSE_FRAMES] == 0.0


class TestPulseLifecycle:
  def test_pulse_expires_after_its_frame_count(self, influence_on):
    brain = _brain(_fixed_nav_sm(shouldSendTurnDesire=True, turnDesireDirection=1))
    cs = SimpleNamespace(steeringPressed=False)
    outs = [brain.nudge_output_torque(True, cs, 0.0) for _ in range(TURN_PULSE_FRAMES + 3)]
    assert all(o < 0.0 for o in outs[:TURN_PULSE_FRAMES])
    assert all(o == 0.0 for o in outs[TURN_PULSE_FRAMES:])
    assert all(np.isfinite(o) for o in outs)

  def test_steering_press_suppresses_pulse(self, influence_on):
    brain = _brain(_fixed_nav_sm(shouldSendTurnDesire=True, turnDesireDirection=1))
    cs = SimpleNamespace(steeringPressed=True)
    assert brain.nudge_output_torque(True, cs, 0.4) == 0.4

  def test_inactive_suppresses_pulse(self, influence_on):
    brain = _brain(_fixed_nav_sm(shouldSendTurnDesire=True, turnDesireDirection=1))
    cs = SimpleNamespace(steeringPressed=False)
    assert brain.nudge_output_torque(False, cs, 0.4) == 0.4

  def test_output_clamped_to_steer_max(self, influence_on):
    brain = _brain(_fixed_nav_sm(shouldSendTurnDesire=True, turnDesireDirection=2), steer_max=0.5)
    cs = SimpleNamespace(steeringPressed=False)
    out = brain.nudge_output_torque(True, cs, 0.4)  # 0.4 + 0.8 nudge, clamped to 0.5
    assert out == pytest.approx(0.5)

  def test_lane_positioning_uses_exit_frames(self, influence_on):
    brain = _brain(_fixed_nav_sm(shouldSendLanePositioning=True, lanePositioningDirection=1))
    cs = SimpleNamespace(steeringPressed=False)
    outs = [brain.nudge_output_torque(True, cs, 0.0) for _ in range(EXIT_PULSE_FRAMES + 2)]
    assert outs[EXIT_PULSE_FRAMES - 1] < 0.0
    assert outs[EXIT_PULSE_FRAMES] == 0.0
