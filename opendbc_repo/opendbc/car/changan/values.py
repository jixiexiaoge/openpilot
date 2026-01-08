# Rebuilt values.py for Changan Z6 with 480° steering and enhanced limits

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.docs_definitions import CarDocs, CarParts, CarHarness

Ecu = structs.CarParams.Ecu
MIN_ACC_SPEED = 19. * CV.MPH_TO_MS
PEDAL_TRANSITION = 10. * CV.MPH_TO_MS

class CarControllerParams:
  ACCEL_MAX = 2.0
  ACCEL_MIN = -3.5

  STEER_STEP = 1
  STEER_MAX = 480
  STEER_ERROR_MAX = 650

  # LTA steering limits with expanded max steering angle to 480°
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    480,  # deg (expanded per user request)
    ([10, 20], [1.4, 1.4]),
    ([10, 20], [1.4, 1.4]),
  )

  def __init__(self, CP):
    self.STEER_DELTA_UP = 15
    self.STEER_DELTA_DOWN = 25

class ChanganSafetyFlags(IntFlag):
  CHANGAN_Z6_FLAG = 0x1
  CHANGAN_Z6_IDD_FLAG = 0x4

@dataclass
class ChangAnCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))

@dataclass
class ChanganPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: "changan_z6_pt", Bus.cam: "changan_z6_pt"})

class CAR(Platforms):
  CHANGAN_Z6 = ChanganPlatformConfig(
    [ChangAnCarDocs("changan z6")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15, tireStiffnessFactor=0.444),
  )
  CHANGAN_Z6_IDD = ChanganPlatformConfig(
    [ChangAnCarDocs("changan z6 idd")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15, tireStiffnessFactor=0.444),
  )

STEER_THRESHOLD = 15
EPS_SCALE = defaultdict(lambda: 73)
DBC = CAR.create_dbc_map()


if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)