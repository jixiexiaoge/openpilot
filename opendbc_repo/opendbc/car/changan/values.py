from collections import defaultdict
from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.docs_definitions import CarDocs

Ecu = structs.CarParams.Ecu

from enum import IntFlag

class ChanganFlags(IntFlag):
  # Detected flags
  IDD = 1

class CarControllerParams:
  ACCEL_MAX = 2.0
  ACCEL_MIN = -3.5
  STEER_STEP = 1
  STEER_MAX = 480
  STEER_ERROR_MAX = 650
  MAX_STEERING_ANGLE = 480.0 # From reference
  STEERING_SMOOTHING_FACTOR = 0.3
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    480,
    ([10, 50], [1.4, 1.4]), # Matches reference
    ([10, 50], [1.4, 1.4]), # Matches reference
  )
  def __init__(self, CP):
    if CP.lateralTuning.which == 'torque':
      self.STEER_DELTA_UP = 15
      self.STEER_DELTA_DOWN = 25
    else:
      self.STEER_DELTA_UP = 10
      self.STEER_DELTA_DOWN = 25

class CAR(Platforms):
  CHANGAN_Z6 = PlatformConfig(
    [CarDocs("Changan Z6", package="All")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict({Bus.pt: "changan_z6_pt", Bus.cam: "changan_z6_pt"}),
  )
  CHANGAN_Z6_IDD = PlatformConfig(
    [CarDocs("Changan Z6 iDD", package="All")],
    CHANGAN_Z6.specs,
    CHANGAN_Z6.dbc_dict,
    flags=ChanganFlags.IDD,
  )

STEER_THRESHOLD = 15 # Matches reference
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