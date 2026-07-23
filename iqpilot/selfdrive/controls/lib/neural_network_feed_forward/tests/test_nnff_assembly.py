"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Off-device checks for the NNFF controller wiring and the nav torque pulse,
built on lightweight fakes so they run without a car interface.
"""
import os
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import log
from openpilot.common.params import Params
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.latcontrol_torque import NeuralNetworkFeedForward
from openpilot.selfdrive.controls.lib.latcontrol_torque import TORQUE_NN_MODEL_PATH

_REAL_MODEL = next((f for f in sorted(os.listdir(TORQUE_NN_MODEL_PATH))
                    if f.endswith(".json") and f != "MOCK.json"))


def _torque_fn():
  def fn(inputs, tp, gravity_adjusted=False):
    base = inputs.lateral_acceleration - (inputs.roll_compensation if gravity_adjusted else 0.0)
    return base * 0.4
  return fn


class FakeCI:
  def torque_from_lateral_accel_in_torque_space(self):
    return _torque_fn()


class FakeVM:
  @staticmethod
  def calc_curvature(angle, v, roll):
    return angle / (max(v, 1.0) ** 2 * 0.05 + 2.0)


def _model_v2():
  t = np.array(ModelConstants.T_IDXS)
  return SimpleNamespace(
    orientation=SimpleNamespace(x=(0.02 * np.sin(t)).tolist(), y=(0.01 * np.cos(t)).tolist()),
    acceleration=SimpleNamespace(y=(0.8 * np.sin(2.0 * t)).tolist()))


def _make_controller(model_file):
  Params().put_bool("NeuralNetworkFeedForward", True)
  path = os.path.join(TORQUE_NN_MODEL_PATH, model_file)
  cp = SimpleNamespace(steerActuatorDelay=0.15)
  cp_iq = SimpleNamespace(iqLateralNet=SimpleNamespace(
    model=SimpleNamespace(path=path, name=os.path.splitext(model_file)[0])))
  lac = SimpleNamespace(steer_max=1.0, torque_params=SimpleNamespace(
    latAccelFactor=2.5, latAccelOffset=0.0, friction=0.1, steeringAngleDeadzoneDeg=0.0))
  return NeuralNetworkFeedForward(lac, cp, cp_iq, FakeCI())


def _drive_once(nnff, step=1, pressed=False):
  nnff.update_model_v2(_model_v2())
  v = 20.0
  dla = 1.0
  cs = SimpleNamespace(vEgo=v, aEgo=0.2, steeringPressed=pressed, steeringRateDeg=1.0)
  cal = SimpleNamespace(roll=0.02)
  pose = SimpleNamespace(orientation=SimpleNamespace(pitch=0.01))
  pid = PIDController([[1, 30], [10.0, 0.8]], 0.15, rate=100)
  pid.set_limits(1.0, -1.0)
  pt = log.ControlsState.LateralTorqueState.new_message()
  return nnff.update(cs, FakeVM(), pid, cal, dla, pt, dla, 0.8 * dla, pose, 0.02 * 9.81,
                     dla, 0.8 * dla, 0.01, dla - 0.02 * 9.81, dla / v ** 2, 0.8 * dla / v ** 2, False, 0.3)


class TestControllerWiring:
  def test_real_model_reports_present(self):
    nnff = _make_controller(_REAL_MODEL)
    assert nnff.has_nn_model is True

  def test_mock_model_reports_absent(self):
    nnff = _make_controller("MOCK.json")
    assert nnff.has_nn_model is False
    assert nnff.model.input_size >= 2  # MOCK still loads as a valid net

  def test_update_returns_finite_torque(self):
    nnff = _make_controller(_REAL_MODEL)
    pid_log, torque = _drive_once(nnff)
    assert np.isfinite(torque)
    assert np.isfinite(pid_log.error)

  def test_lag_update_refreshes_future_times(self):
    nnff = _make_controller(_REAL_MODEL)
    before = list(nnff.nn_future_times)
    nnff.update_lateral_lag(0.5)
    after = list(nnff.nn_future_times)
    assert after != before
    assert all(a == pytest.approx(f + nnff.desired_lat_jerk_time) for a, f in zip(after, nnff.future_times, strict=True))

  def test_disabled_when_model_invalid(self):
    nnff = _make_controller(_REAL_MODEL)
    nnff.model_valid = False
    assert nnff._nnff_enabled is False
