from collections import defaultdict
from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.docs_definitions import CarDocs

Ecu = structs.CarParams.Ecu

class CarControllerParams:
  ACCEL_MAX = 2.0
  ACCEL_MIN = -3.5
  STEER_STEP = 1
  STEER_MAX = 480
  STEER_ERROR_MAX = 650
  MAX_STEERING_ANGLE = 130.0
  STEERING_SMOOTHING_FACTOR = 0.3
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    480,
    ([10, 40], [1.4, 1.4]),
    ([10, 40], [1.4, 1.4]),
  )
  def __init__(self, CP):
    self.STEER_DELTA_UP = 25 if CP.lateralTuning.which == 'torque' else 15
    self.STEER_DELTA_DOWN = 30 if CP.lateralTuning.which == 'torque' else 35

class CAR(Platforms):
  CHANGAN_Z6 = PlatformConfig(
    [CarDocs("Changan Z6", package="All")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict({Bus.pt: "changan_z6_pt", Bus.cam: "changan_z6_pt"}),
  )
  CHANGAN_Z6_IDD = PlatformConfig(
    [CarDocs("Changan Z6 iDD", package="All")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict({Bus.pt: "changan_z6_pt", Bus.cam: "changan_z6_pt"}),
  )

STEER_THRESHOLD = 10
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