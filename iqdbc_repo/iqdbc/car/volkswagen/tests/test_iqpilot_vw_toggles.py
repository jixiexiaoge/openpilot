from types import SimpleNamespace

from iqdbc.car.volkswagen import mqbcan, pqcan
from iqdbc.car.volkswagen.carcontroller import CarController
from iqdbc.car.volkswagen.values import CAR, MQB_A0_CARS


def test_is_mqb_a0_car_matches_expected_platforms():
  assert CAR.VOLKSWAGEN_POLO_MK6 in MQB_A0_CARS
  assert CAR.VOLKSWAGEN_TCROSS_MK1 in MQB_A0_CARS
  assert CAR.SKODA_FABIA_MK4 in MQB_A0_CARS
  assert CAR.SKODA_KAMIQ_MK1 in MQB_A0_CARS
  assert CarController._is_mqb_a0_car(CAR.VOLKSWAGEN_POLO_MK6)
  assert CarController._is_mqb_a0_car(CAR.VOLKSWAGEN_TCROSS_MK1)
  assert CarController._is_mqb_a0_car(CAR.SKODA_FABIA_MK4)
  assert CarController._is_mqb_a0_car(CAR.SKODA_KAMIQ_MK1)
  assert not CarController._is_mqb_a0_car(CAR.VOLKSWAGEN_GOLF_MK7)


def test_mqb_steering_torque_scale_only_changes_when_toggle_enabled():
  controller = object.__new__(CarController)
  controller.CCS = mqbcan
  assert controller._get_mqb_steering_torque_scale(0.4, False) == 1.0

  assert controller._get_mqb_steering_torque_scale(0.4, True) == 0.8
  assert controller._get_mqb_steering_torque_scale(4.0, True) == 1.0

  controller.CCS = pqcan
  assert controller._get_mqb_steering_torque_scale(0.4, True) == 1.0


def test_mqb_a0_resume_spam_requires_toggle_platform_and_window():
  controller = object.__new__(CarController)
  controller.CCS = mqbcan
  controller.is_mqb_a0 = True
  controller.frame = 10
  cs = SimpleNamespace(out=SimpleNamespace(standstill=True))

  assert controller._should_spam_mqb_a0_resume(cs, True)

  controller.frame = 20
  assert not controller._should_spam_mqb_a0_resume(cs, True)

  controller.frame = 10
  controller.is_mqb_a0 = False
  assert not controller._should_spam_mqb_a0_resume(cs, True)

  controller.is_mqb_a0 = True
  assert not controller._should_spam_mqb_a0_resume(cs, False)
