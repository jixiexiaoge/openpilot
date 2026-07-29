"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from types import SimpleNamespace

import pytest

import cereal.messaging as messaging
from cereal import custom
from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.controls.lib.helpers.e2e_alerts import (
  EndToEndAlertEngine, CONFIRM_S, SETTLE_S, HORIZON_TAIL, PATH_SPEED_MPS, LEAD_SPEED_MPS, LEAD_GAP_M)

E2E_CHIME = custom.IQOnroadEvent.EventName.e2eChime


class _Events(list):
  def add(self, name):
    self.append(name)


def _model(horizon):
  msg = messaging.new_message('modelV2')
  msg.modelV2.velocity.x = [0.0] * (33 - HORIZON_TAIL) + [horizon] * HORIZON_TAIL
  return msg.as_reader().modelV2


def _sm(*, v_ego=0.0, standstill=True, gas=False, enabled=False, cruise=False,
        horizon=0.0, lead=None):
  lead = lead or SimpleNamespace(status=False, dRel=0.0, vLead=0.0)
  return {
    'carState': SimpleNamespace(vEgo=v_ego, standstill=standstill, gasPressed=gas,
                                cruiseState=SimpleNamespace(enabled=cruise)),
    'selfdriveState': SimpleNamespace(enabled=enabled),
    'radarState': SimpleNamespace(leadOne=lead),
    'modelV2': _model(horizon),
  }


def _engine(path=True, lead=True):
  engine = EndToEndAlertEngine()
  engine._refresh_params = lambda: None
  engine._on = {"path": path, "lead": lead}
  return engine


def _run(engine, sm, seconds):
  events = _Events()
  chimes = 0
  for _ in range(int(seconds / DT_MDL)):
    engine.update(sm, events)
    chimes += events.count(E2E_CHIME)
    events.clear()
  return chimes


def _lead(d_rel, v_lead=0.0):
  return SimpleNamespace(status=True, dRel=d_rel, vLead=v_lead)


def test_path_opens_chimes_once():
  engine = _engine()
  assert _run(engine, _sm(horizon=0.0), SETTLE_S + 1.0) == 0
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), CONFIRM_S + 1.0) == 1
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), 5.0) == 0


def test_path_needs_the_settle_dwell():
  engine = _engine()
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), SETTLE_S - 0.2) == 0


def test_path_silent_while_openpilot_long_is_engaged():
  engine = _engine()
  _run(engine, _sm(horizon=0.0, enabled=True), SETTLE_S + 1.0)
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0, enabled=True), 5.0) == 0


def test_path_silent_while_stock_acc_holds_the_car():
  engine = _engine()
  _run(engine, _sm(horizon=0.0, cruise=True), SETTLE_S + 1.0)
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0, cruise=True), 5.0) == 0


def test_path_chimes_under_aol():
  engine = _engine()
  _run(engine, _sm(horizon=0.0), SETTLE_S + 1.0)
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), CONFIRM_S + 1.0) == 1


def test_path_ignores_a_visible_lead():
  engine = _engine(lead=False)
  _run(engine, _sm(horizon=0.0, lead=_lead(6.0)), SETTLE_S + 1.0)
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0, lead=_lead(6.0)), 5.0) == 0


def test_lead_pullaway_chimes_once():
  engine = _engine()
  assert _run(engine, _sm(lead=_lead(6.0)), SETTLE_S + 1.0) == 0
  moving = _sm(lead=_lead(6.0 + LEAD_GAP_M + 0.5, LEAD_SPEED_MPS + 1.0))
  assert _run(engine, moving, CONFIRM_S + 1.0) == 1
  assert _run(engine, moving, 5.0) == 0


def test_lead_creep_inside_the_gap_stays_silent():
  engine = _engine()
  _run(engine, _sm(lead=_lead(6.0)), SETTLE_S + 1.0)
  assert _run(engine, _sm(lead=_lead(6.0 + LEAD_GAP_M / 2, LEAD_SPEED_MPS + 1.0)), 5.0) == 0


def test_lead_far_ahead_is_not_a_queue():
  engine = _engine()
  _run(engine, _sm(lead=_lead(40.0)), SETTLE_S + 1.0)
  assert _run(engine, _sm(lead=_lead(44.0, LEAD_SPEED_MPS + 1.0)), 5.0) == 0


def test_gas_and_motion_rearm_the_dwell():
  engine = _engine()
  _run(engine, _sm(horizon=0.0), SETTLE_S + 1.0)
  _run(engine, _sm(v_ego=5.0, standstill=False, horizon=8.0), 2.0)
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), SETTLE_S - 0.2) == 0
  assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), CONFIRM_S + 1.0) == 1


@pytest.mark.parametrize("param_off", ["path", "lead"])
def test_each_param_gates_only_its_own_trigger(param_off):
  engine = _engine(path=param_off != "path", lead=param_off != "lead")
  if param_off == "path":
    _run(engine, _sm(horizon=0.0), SETTLE_S + 1.0)
    assert _run(engine, _sm(horizon=PATH_SPEED_MPS + 2.0), 5.0) == 0
  else:
    _run(engine, _sm(lead=_lead(6.0)), SETTLE_S + 1.0)
    assert _run(engine, _sm(lead=_lead(8.0, LEAD_SPEED_MPS + 1.0)), 5.0) == 0
