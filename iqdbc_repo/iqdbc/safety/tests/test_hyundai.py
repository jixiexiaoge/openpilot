import pytest

from iqdbc.car.hyundai.values import HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.hyundai_common import TESTER_PRESENT, classic_accel, classic_steer, packet
from iqdbc.safety.tests.libsafety import libsafety_py


@pytest.fixture
def safety():
  return libsafety_py.libsafety


@pytest.mark.parametrize("mode", (CarParams.SafetyModel.hyundai, CarParams.SafetyModel.hyundaiLegacy))
@pytest.mark.parametrize("param", (
  0,
  HyundaiSafetyFlags.EV_GAS,
  HyundaiSafetyFlags.HYBRID_GAS,
  HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.CAMERA_SCC,
  HyundaiSafetyFlags.ALT_LIMITS,
  HyundaiSafetyFlags.FCEV_GAS,
  HyundaiSafetyFlags.ALT_LIMITS_2,
))
def test_classic_safety_configurations_initialize(safety, mode, param):
  assert safety.set_safety_hooks(mode, param) == 0
  safety.init_tests()
  assert safety.get_current_safety_param() == param


@pytest.mark.parametrize("mode", (CarParams.SafetyModel.hyundai, CarParams.SafetyModel.hyundaiLegacy))
def test_classic_tx_whitelist_and_steering_limits(safety, mode):
  safety.set_safety_hooks(mode, 0)
  safety.init_tests()

  assert not safety.safety_tx_hook(packet(0x123, 0, 8))
  assert not safety.safety_tx_hook(packet(0x340, 1, 8))

  safety.set_controls_allowed(False)
  assert safety.safety_tx_hook(classic_steer(0, False))
  assert not safety.safety_tx_hook(classic_steer(1))

  safety.set_controls_allowed(True)
  assert safety.safety_tx_hook(classic_steer(10))
  safety.set_desired_torque_last(512)
  safety.set_rt_torque_last(512)
  assert safety.safety_tx_hook(classic_steer(512))
  assert not safety.safety_tx_hook(classic_steer(513))
  assert not safety.safety_tx_hook(classic_steer(-513))


def test_classic_alt_limits_2(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundai, HyundaiSafetyFlags.ALT_LIMITS_2)
  safety.init_tests()
  safety.set_controls_allowed(True)
  safety.set_desired_torque_last(170)
  safety.set_rt_torque_last(170)
  assert safety.safety_tx_hook(classic_steer(170))
  assert not safety.safety_tx_hook(classic_steer(171))


def test_classic_longitudinal_accel_and_aeb_guards(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundai, HyundaiSafetyFlags.LONG)
  safety.init_tests()

  safety.set_controls_allowed(False)
  assert safety.safety_tx_hook(classic_accel(0))
  assert not safety.safety_tx_hook(classic_accel(1))

  safety.set_controls_allowed(True)
  for accel in (-400, 0, 250):
    assert safety.safety_tx_hook(classic_accel(accel))
  for accel in (-401, 251):
    assert not safety.safety_tx_hook(classic_accel(accel))
  assert not safety.safety_tx_hook(classic_accel(0, aeb_decel=1))
  assert not safety.safety_tx_hook(classic_accel(0, aeb_request=True))

  assert safety.safety_tx_hook(packet(0x38D, 0, 8))
  assert not safety.safety_tx_hook(packet(0x38D, 0, 8, {1: 1}))
  assert not safety.safety_tx_hook(packet(0x38D, 0, 8, {2: 1 << 4}))
  assert not safety.safety_tx_hook(packet(0x38D, 0, 8, {3: 1 << 7}))


def test_classic_buttons(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundai, 0)
  safety.init_tests()

  safety.set_controls_allowed(False)
  assert not safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 1}))
  assert not safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 2}))
  assert not safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 4}))

  safety.set_controls_allowed(True)
  assert safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 1}))
  assert not safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 2}))
  assert safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 4}))

  safety.set_controls_allowed(False)
  safety.set_cruise_engaged_prev(True)
  assert safety.safety_tx_hook(packet(0x4F1, 0, 4, {0: 4}))


def test_classic_diagnostic_payload_is_restricted(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundai, HyundaiSafetyFlags.LONG)
  safety.init_tests()
  assert safety.safety_tx_hook(packet(0x7D0, 0, 8, dict(enumerate(TESTER_PRESENT))))
  assert not safety.safety_tx_hook(packet(0x7D0, 0, 8, {0: 3, 1: 0x22}))
