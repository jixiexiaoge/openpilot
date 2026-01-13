from collections import defaultdict
from enum import IntFlag
from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.docs_definitions import CarDocs, CarParts, CarHarness

Ecu = structs.CarParams.Ecu

class CarControllerParams:
  ACCEL_MAX = 2.0
  ACCEL_MIN = -3.5
  STEER_STEP = 1
  STEER_MAX = 980
  STEER_ERROR_MAX = 1200
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    980,
    ([10, 40], [1.4, 1.4]),
    ([10, 40], [1.4, 1.4]),
  )
  def __init__(self, CP):
    self.STEER_DELTA_UP = 25 if CP.lateralTuning.which == 'torque' else 15
    self.STEER_DELTA_DOWN = 30 if CP.lateralTuning.which == 'torque' else 35

class CAR(Platforms):
  CHANGAN_Z6 = PlatformConfig(
    "changan_z6",
    [CarDocs("Changan Z6", package="All")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict("changan_z6_pt", None)
  )
  CHANGAN_Z6_IDD = PlatformConfig(
    "changan_z6_idd",
    [CarDocs("Changan Z6 iDD", package="All")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict("changan_z6_pt", None)
  )

STEER_THRESHOLD = 10
EPS_SCALE = defaultdict(lambda: 73)
DBC = CAR.create_dbc_map()