import numpy as np
import pytest

from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_planner import get_accel_candidates, get_e2e_accel


def model_velocity(v_ego, v_future):
  return np.interp(T_IDXS, [T_IDXS[0], T_IDXS[-1]], [v_ego, v_future])


class TestE2eCruiseConvergence:
  def test_converges_when_model_wants_to_accelerate(self):
    assert get_e2e_accel(20.0, 30.0, model_velocity(20.0, 25.0), 0.1, False) == pytest.approx(0.5)

  def test_scales_down_near_cruise_speed(self):
    assert get_e2e_accel(28.5, 30.0, model_velocity(28.5, 30.0), 0.0, False) == pytest.approx(0.05)

  def test_preserves_active_model_deceleration(self):
    assert get_e2e_accel(20.0, 30.0, model_velocity(20.0, 25.0), -0.05, False) == pytest.approx(-0.05)

  def test_preserves_future_model_slowdown(self):
    assert get_e2e_accel(20.0, 30.0, model_velocity(20.0, 18.0), 0.1, False) == pytest.approx(0.1)

  @pytest.mark.parametrize("v_ego, v_cruise, should_stop", [
    (30.0, 30.0, False),
    (31.0, 30.0, False),
    (20.0, 30.0, True),
  ])
  def test_never_overrides_cruise_or_stop(self, v_ego, v_cruise, should_stop):
    assert get_e2e_accel(v_ego, v_cruise, model_velocity(v_ego, v_ego + 5.0), -0.2, should_stop) == pytest.approx(-0.2)


class TestAccelCandidates:
  MPC = (-0.2, LongitudinalPlanSource.lead0, True)
  CRUISE = (0.5, LongitudinalPlanSource.cruise, False)
  E2E = (0.1, LongitudinalPlanSource.e2e, False)

  def test_e2e_without_lead_frees_model_from_mpc(self):
    candidates = get_accel_candidates(True, False, self.MPC, self.CRUISE, self.E2E)
    assert candidates == [self.CRUISE, self.E2E]
    assert min(candidates, key=lambda c: c[0])[1] == LongitudinalPlanSource.e2e
    assert not any(should_stop for _, _, should_stop in candidates)

  def test_e2e_with_lead_keeps_mpc_safety_constraint(self):
    candidates = get_accel_candidates(True, True, self.MPC, self.CRUISE, self.E2E)
    assert candidates == [self.MPC, self.CRUISE, self.E2E]
    assert min(candidates, key=lambda c: c[0])[1] == LongitudinalPlanSource.lead0
    assert any(should_stop for _, _, should_stop in candidates)

  def test_acc_without_lead_keeps_mpc_policy(self):
    candidates = get_accel_candidates(False, False, self.MPC, self.CRUISE, self.E2E)
    assert candidates == [self.MPC, self.CRUISE]
