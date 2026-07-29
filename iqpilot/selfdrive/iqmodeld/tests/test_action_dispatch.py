from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from cereal import log

from openpilot.iqpilot.selfdrive.iqmodeld.config import Plan
from openpilot.iqpilot.selfdrive.iqmodeld.daemon import NeuralEngineState, _merged_plan
import openpilot.iqpilot.selfdrive.iqmodeld.daemon as iqmodeld_daemon
from openpilot.selfdrive.controls.lib.drive_helpers import smooth_value


def _fake_state(**overrides):
  base = dict(
    PLANPLUS_CONTROL=1.0,
    LONG_SMOOTH_SECONDS=0.3,
    LAT_SMOOTH_SECONDS=0.1,
    MIN_LAT_CONTROL_SPEED=0.3,
    mlsim=True,
    generation=12,
    constants=SimpleNamespace(T_IDXS=np.arange(100), DESIRE_LEN=8),
  )
  base.update(overrides)
  return SimpleNamespace(**base)


@pytest.mark.parametrize(
  ("control", "vego", "factor"),
  [
    (0.55, 20.0, 1.0),
    (1.0, 25.0, 0.75),
    (1.5, 25.1, 0.75),
    (2.0, 20.0, 1.0),
  ],
)
def test_planplus_merge_matches_speed_gate(control: float, vego: float, factor: float):
  state = _fake_state(PLANPLUS_CONTROL=control)
  base = np.random.rand(1, 100, 15).astype(np.float32)
  extra = np.random.rand(1, 100, 15).astype(np.float32)
  merged = _merged_plan(state, {"plan": base, "planplus": extra}, vego)
  expected = base[0] + (control * factor) * extra[0]
  np.testing.assert_allclose(merged, expected, rtol=1e-6, atol=1e-6)


def test_action_dispatch_uses_merged_plan_for_longitudinal_choice(monkeypatch: pytest.MonkeyPatch):
  state = _fake_state()
  previous = log.ModelDataV2.Action()
  recorded_velocity: list[np.ndarray] = []

  def fake_accel(plan_vel, plan_accel, t_idxs, action_t=0.0):
    recorded_velocity.append(plan_vel.copy())
    return 0.0, False

  monkeypatch.setattr(iqmodeld_daemon, "get_accel_from_plan", fake_accel)
  monkeypatch.setattr(iqmodeld_daemon, "pick_curvature", lambda *args: 0.0)

  plan = np.random.rand(1, 100, 15).astype(np.float32)
  planplus = np.random.rand(1, 100, 15).astype(np.float32)
  outputs = {"plan": plan.copy(), "planplus": planplus.copy()}

  NeuralEngineState.get_action_from_model(state, outputs, previous, 0.0, 0.0, 25.0)
  expected = plan[0, :, Plan.VELOCITY][:, 0] + 0.75 * planplus[0, :, Plan.VELOCITY][:, 0]
  np.testing.assert_allclose(recorded_velocity[0], expected, rtol=1e-5, atol=1e-6)


def test_action_dispatch_honors_direct_action_outputs():
  state = _fake_state(mlsim=False, generation=9)
  previous = log.ModelDataV2.Action(desiredCurvature=0.0, desiredAcceleration=0.0, shouldStop=False)
  outputs = {"action": np.array([[4.0, -0.25]], dtype=np.float32)}
  action = NeuralEngineState.get_action_from_model(state, outputs, previous, 0.0, 0.0, 10.0)
  expected_accel = smooth_value(-0.25, previous.desiredAcceleration, state.LONG_SMOOTH_SECONDS)
  expected_curvature = smooth_value(0.04, previous.desiredCurvature, state.LAT_SMOOTH_SECONDS)
  assert action.desiredAcceleration == pytest.approx(expected_accel)
  assert action.desiredCurvature == pytest.approx(expected_curvature)
  assert action.shouldStop is False
