#!/usr/bin/env python3
from iqdbc.car import structs
from iqdbc.car.interfaces import CarInterfaceBase
from iqdbc.car.mock.carcontroller import CarController
from iqdbc.car.mock.carstate import CarState


# mocked car interface for dashcam mode
class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "mock"
    ret.mass = 1700.
    ret.wheelbase = 2.70
    ret.centerToFront = ret.wheelbase * 0.5
    ret.steerRatio = 13.
    ret.dashcamOnly = True
    return ret
