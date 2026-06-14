"""
Copyright Â© IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from types import SimpleNamespace

from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerIQ


class _FakeIQDynamic:
  def __init__(self, requested=True, model_length=4.0, model_stop_time=5.0, minimum_force_stop_length=15.0):
    self._requested = requested
    self.model_length = model_length
    self.model_stop_time = model_stop_time
    self.minimum_force_stop_length = minimum_force_stop_length

  def force_stop_requested(self):
    return self._requested


def _build_planner(iq_dynamic):
  planner = LongitudinalPlannerIQ.__new__(LongitudinalPlannerIQ)
  planner.iq_dynamic = iq_dynamic
  planner.force_stop_timer = 0.0
  planner.forcing_stop = False
  planner.override_force_stop = False
  planner.override_force_stop_timer = 0.0
  planner.tracked_model_length = 0.0
  return planner


def _build_sm(gas_pressed=False, accel_pressed=False, standstill=False):
  return {
    "carState": SimpleNamespace(gasPressed=gas_pressed, standstill=standstill),
    "iqCarState": SimpleNamespace(accelPressed=accel_pressed),
  }


def test_force_stop_uses_model_stop_time_as_ramp():
  planner = _build_planner(_FakeIQDynamic(model_length=20.0, model_stop_time=5.0, minimum_force_stop_length=0.0))
  sm = _build_sm()

  output = 12.0
  for _ in range(int(1.0 / DT_MDL)):
    output = planner._apply_force_stop(12.0, 0.0, sm, True)

  assert planner.forcing_stop
  assert output == 4.0


def test_force_stop_respects_minimum_force_stop_length():
  planner = _build_planner(_FakeIQDynamic(model_length=4.0, model_stop_time=5.0, minimum_force_stop_length=15.0))
  sm = _build_sm()

  output = 12.0
  for _ in range(int(1.0 / DT_MDL)):
    output = planner._apply_force_stop(12.0, 0.0, sm, True)

  assert planner.forcing_stop
  assert planner.tracked_model_length == 15.0
  assert output == 3.0
