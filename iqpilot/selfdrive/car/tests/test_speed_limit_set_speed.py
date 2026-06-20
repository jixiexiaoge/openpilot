from types import SimpleNamespace

import pytest

from cereal import car, custom
from openpilot.common.constants import CV
from openpilot.iqpilot.selfdrive.car.enhanced_stock_longitudinal_control import build_iq_control_params_from_plan
from openpilot.selfdrive.car.cruise import VCruiseHelper


class TestSpeedLimitSetSpeedMirror:
  def setup_method(self):
    self.CP = car.CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    self.CP_IQ = custom.IQCarParams(pcmCruiseSpeed=True)
    self.v_cruise_helper = VCruiseHelper(self.CP, self.CP_IQ)

  @staticmethod
  def _iq_plan(limit_mps: float, state) -> SimpleNamespace:
    resolver = SimpleNamespace(
      speedLimitValid=limit_mps > 0,
      speedLimitLastValid=limit_mps > 0,
      speedLimitFinalLast=limit_mps,
    )
    assist = SimpleNamespace(state=state)
    return SimpleNamespace(speedLimit=SimpleNamespace(resolver=resolver, assist=assist))

  def test_op_long_mirrors_active_speed_limit_target_into_cluster_speed(self):
    self.v_cruise_helper.update_speed_limit_assist(False, self._iq_plan(17.88, custom.IQPlan.SpeedLimit.AssistState.active))

    CS = car.CarState(cruiseState={"available": True, "speed": 22.35, "speedCluster": 22.35})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    assert self.v_cruise_helper.v_cruise_kph == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
    assert self.v_cruise_helper.v_cruise_cluster_kph == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)

  def test_op_long_syncs_to_new_limit_even_when_assist_not_active(self):
    self.v_cruise_helper.update_speed_limit_assist(False, self._iq_plan(17.88, custom.IQPlan.SpeedLimit.AssistState.inactive))

    CS = car.CarState(cruiseState={"available": True, "speed": 22.35, "speedCluster": 22.35})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    assert self.v_cruise_helper.v_cruise_kph == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
    assert self.v_cruise_helper.v_cruise_cluster_kph == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)

  def test_op_long_allows_manual_set_speed_changes_between_limit_changes(self):
    self.v_cruise_helper.update_speed_limit_assist(False, self._iq_plan(17.88, custom.IQPlan.SpeedLimit.AssistState.inactive))

    # First cycle after a valid limit appears will sync to the resolved target.
    CS = car.CarState(cruiseState={"available": True, "speed": 22.35, "speedCluster": 22.35})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    # On later cycles with the same limit, manual set speed changes should be preserved.
    CS = car.CarState(cruiseState={"available": True, "speed": 15.64, "speedCluster": 15.64})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    assert self.v_cruise_helper.v_cruise_kph == pytest.approx(15.64 * CV.MS_TO_KPH, abs=0.1)
    assert self.v_cruise_helper.v_cruise_cluster_kph == pytest.approx(15.64 * CV.MS_TO_KPH, abs=0.1)

  def test_op_long_resyncs_when_limit_changes(self):
    self.v_cruise_helper.update_speed_limit_assist(False, self._iq_plan(17.88, custom.IQPlan.SpeedLimit.AssistState.inactive))

    CS = car.CarState(cruiseState={"available": True, "speed": 22.35, "speedCluster": 22.35})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    CS = car.CarState(cruiseState={"available": True, "speed": 15.64, "speedCluster": 15.64})
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    self.v_cruise_helper.update_speed_limit_assist(False, self._iq_plan(13.41, custom.IQPlan.SpeedLimit.AssistState.inactive))
    self.v_cruise_helper.update_v_cruise(CS, enabled=True, is_metric=False)

    assert self.v_cruise_helper.v_cruise_kph == pytest.approx(13.41 * CV.MS_TO_KPH, abs=0.1)
    assert self.v_cruise_helper.v_cruise_cluster_kph == pytest.approx(13.41 * CV.MS_TO_KPH, abs=0.1)


def test_enhanced_stock_longitudinal_control_syncs_once_then_follows_cluster_speed():
  CP = car.CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
  resolver = SimpleNamespace(speedLimitFinalLast=17.88)
  assist = SimpleNamespace(enabled=True)
  iq_plan = SimpleNamespace(speedLimit=SimpleNamespace(resolver=resolver, assist=assist))

  params, sync_limit, pending_limit = build_iq_control_params_from_plan(
    CP, iq_plan, True, current_set_speed_kph=100.0, previous_sync_limit_kph=None, pending_sync_limit_kph=None
  )
  assert sync_limit == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
  assert pending_limit == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
  assert float(params[0]["value"].decode("utf-8")) == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)

  params, sync_limit, pending_limit = build_iq_control_params_from_plan(
    CP, iq_plan, True, current_set_speed_kph=22.0, previous_sync_limit_kph=sync_limit, pending_sync_limit_kph=pending_limit
  )
  assert sync_limit == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
  assert pending_limit == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
  assert float(params[0]["value"].decode("utf-8")) == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)

  params, sync_limit, pending_limit = build_iq_control_params_from_plan(
    CP, iq_plan, True, current_set_speed_kph=17.88 * CV.MS_TO_KPH, previous_sync_limit_kph=sync_limit, pending_sync_limit_kph=pending_limit
  )
  assert sync_limit == pytest.approx(17.88 * CV.MS_TO_KPH, abs=0.1)
  assert pending_limit is None

  params, sync_limit, pending_limit = build_iq_control_params_from_plan(
    CP, iq_plan, True, current_set_speed_kph=22.0, previous_sync_limit_kph=sync_limit, pending_sync_limit_kph=pending_limit
  )
  assert float(params[0]["value"].decode("utf-8")) == pytest.approx(22.0, abs=0.1)
