"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Original concept ("Increased Stop Distance") by SpysyWeeb (github.com/SpysyWeeb)
"""
from types import SimpleNamespace

from iqdbc.car.interfaces import ACCEL_MIN
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.iqpilot.selfdrive.controls.lib.custom_stop_distance import (
  CustomStopDistance,
  MIN_ADJUSTED_D_REL,
)


def _build(distance):
  c = CustomStopDistance.__new__(CustomStopDistance)
  c.frame = 0
  c.distance = float(distance)
  return c


def _model_msg(stop_distance, end_velocity):
  x = [0.0] * (ModelConstants.IDX_N - 1) + [stop_distance]
  v = [0.0] * (ModelConstants.IDX_N - 1) + [end_velocity]
  return SimpleNamespace(position=SimpleNamespace(x=x), velocity=SimpleNamespace(x=v))


def test_zero_distance_is_a_no_op():
  c = _build(0)
  lead = {'status': True, 'dRel': 10.0, 'vLead': 0.0}
  assert c.apply_lead(dict(lead)) == lead


def test_positive_distance_reduces_reported_lead_distance():
  c = _build(2)
  lead = {'status': True, 'dRel': 10.0, 'vLead': 0.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == 8.0


def test_negative_distance_increases_reported_lead_distance():
  c = _build(-2)
  lead = {'status': True, 'dRel': 10.0, 'vLead': 0.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == 12.0


def test_positive_distance_never_reports_below_floor():
  c = _build(2)
  lead = {'status': True, 'dRel': 1.5, 'vLead': 0.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == MIN_ADJUSTED_D_REL


def test_positive_distance_never_reports_further_than_reality():
  c = _build(2)
  lead = {'status': True, 'dRel': 0.5, 'vLead': 0.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == 0.5


def test_offset_fades_out_as_lead_speeds_up():
  c = _build(2)
  lead = {'status': True, 'dRel': 10.0, 'vLead': 3.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == 10.0


def test_no_lead_is_untouched():
  c = _build(2)
  lead = {'status': False, 'dRel': 10.0, 'vLead': 0.0}
  out = c.apply_lead(dict(lead))
  assert out['dRel'] == 10.0


def test_e2e_negative_distance_is_a_no_op():
  c = _build(-2)
  a_target, should_stop = c.adjust_e2e_stop(-0.5, False, 0.2, _model_msg(3.0, 0.0))
  assert (a_target, should_stop) == (-0.5, False)


def test_e2e_zero_distance_is_a_no_op():
  c = _build(0)
  a_target, should_stop = c.adjust_e2e_stop(-0.5, False, 0.2, _model_msg(3.0, 0.0))
  assert (a_target, should_stop) == (-0.5, False)


def test_e2e_stop_sign_plans_are_untouched():
  c = _build(2)
  # model plan still moving at the end -> proceeding through (stop sign), not held
  a_target, should_stop = c.adjust_e2e_stop(-0.5, False, 0.2, _model_msg(3.0, 5.0))
  assert (a_target, should_stop) == (-0.5, False)


def test_e2e_holds_short_of_model_stop_when_already_stopped():
  c = _build(2)
  a_target, should_stop = c.adjust_e2e_stop(0.0, False, 0.1, _model_msg(stop_distance=3.0, end_velocity=0.0))
  assert should_stop is True


def test_e2e_does_not_hold_once_past_offset_and_buffer():
  c = _build(2)
  a_target, should_stop = c.adjust_e2e_stop(0.0, False, 0.1, _model_msg(stop_distance=10.0, end_velocity=0.0))
  assert should_stop is False


def test_e2e_deepens_braking_already_in_progress():
  c = _build(2)
  a_target, should_stop = c.adjust_e2e_stop(-0.5, False, 5.0, _model_msg(stop_distance=10.0, end_velocity=0.0))
  assert a_target < -0.5
  assert a_target >= ACCEL_MIN


def test_e2e_never_relaxes_braking():
  c = _build(2)
  a_target, should_stop = c.adjust_e2e_stop(0.0, False, 5.0, _model_msg(stop_distance=10.0, end_velocity=0.0))
  assert a_target == 0.0
