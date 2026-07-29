"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Original concept and implementation by SpysyWeeb (github.com/SpysyWeeb)
"""
from openpilot.common.realtime import DT_CTRL
from openpilot.iqpilot.selfdrive.controls.lib.smooth_stops import (
  SmoothStopController,
  read_smooth_stops_enabled,
  STANDSTILL_SPEED,
  STANDSTILL_HOLD_SPEED,
  SETTLE_DECEL,
  TAPER_SPEED,
  STOP_KISS_DECEL,
  SETTLE_JERK,
  EMERGENCY_DECEL,
)

JERK_STEP = SETTLE_JERK * DT_CTRL


def _build(enabled=True):
  c = SmoothStopController.__new__(SmoothStopController)
  c.enabled = enabled
  c._v_min = float("inf")
  c._stall_s = 0.0
  return c


def test_unified_toggle_reads_force_stops():
  seen = {}

  class FakeParams:
    def get_bool(self, key):
      seen["key"] = key
      return True

  assert read_smooth_stops_enabled(FakeParams()) is True
  assert seen["key"] == "IQForceStops"


def test_hold_only_arms_at_standstill():
  c = _build()
  assert not c.want_hold(True, 0.5, False)
  assert not c.want_hold(True, STANDSTILL_SPEED + 0.05, False)
  assert not c.want_hold(True, 1.0, True)
  assert not c.want_hold(True, STANDSTILL_HOLD_SPEED + 0.05, True)
  assert c.want_hold(True, STANDSTILL_SPEED - 0.01, False)
  assert c.want_hold(True, STANDSTILL_HOLD_SPEED - 0.01, True)
  assert not c.want_hold(False, 0.0, True)


def test_settle_feathers_toward_baseline():
  c = _build()
  out = c.settle(a_target=0.0, v_ego=1.0, lead_distance=0.0, has_lead=False, last_output=0.0)
  assert out == -JERK_STEP


def test_settle_never_softer_than_mpc():
  c = _build()
  out = c.settle(a_target=-2.0, v_ego=1.0, lead_distance=0.0, has_lead=False, last_output=-1.0)
  assert out == -1.0 - JERK_STEP
  assert out < -1.0


def test_settle_emergency_bypasses_jerk_limit():
  c = _build()
  out = c.settle(a_target=-3.4, v_ego=2.0, lead_distance=0.0, has_lead=False, last_output=0.0)
  assert out == -3.4
  assert out <= -EMERGENCY_DECEL


def test_settle_lead_firms_up_when_close():
  c = _build()
  assert c.settle(a_target=0.0, v_ego=1.0, lead_distance=50.0, has_lead=True, last_output=-SETTLE_DECEL) == -SETTLE_DECEL
  c = _build()
  assert c.settle(a_target=0.0, v_ego=1.0, lead_distance=3.0, has_lead=True, last_output=-1.0) == -1.0


def test_settle_anti_creep_firms_up_when_not_slowing():
  c = _build()
  out = c.settle(a_target=0.0, v_ego=0.5, lead_distance=0.0, has_lead=False, last_output=-SETTLE_DECEL)
  for _ in range(60):
    out = c.settle(a_target=0.0, v_ego=0.5, lead_distance=0.0, has_lead=False, last_output=out)
  assert out < -SETTLE_DECEL


def test_settle_eases_off_near_stop():
  c = _build()
  near = c.settle(a_target=0.0, v_ego=0.1, lead_distance=0.0, has_lead=False, last_output=-0.305)
  c = _build()
  high = c.settle(a_target=0.0, v_ego=0.9, lead_distance=0.0, has_lead=False, last_output=-0.745)
  assert near > high
  assert near == -(STOP_KISS_DECEL + (SETTLE_DECEL - STOP_KISS_DECEL) * (0.1 / TAPER_SPEED))


def test_settle_kiss_decel_at_stop():
  c = _build()
  out = c.settle(a_target=0.0, v_ego=0.0, lead_distance=0.0, has_lead=False, last_output=-STOP_KISS_DECEL)
  assert out == -STOP_KISS_DECEL
