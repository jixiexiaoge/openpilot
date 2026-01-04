import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, IntFlag

from openpilot.common.conversions import Conversions as CV
from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.docs_definitions import CarDocs, CarParts, CarHarness

Ecu = structs.CarParams.Ecu
MIN_ACC_SPEED = 19. * CV.MPH_TO_MS
PEDAL_TRANSITION = 10. * CV.MPH_TO_MS


class CarControllerParams:
  ACCEL_MAX = 2.0  # m/s2, lower than allowed 2.0 m/s2 for tuning reasons
  ACCEL_MIN = -3.5  # m/s2

  STEER_STEP = 1
  STEER_MAX = 980
  STEER_ERROR_MAX = 1200     # max delta between torque cmd and torque motor

  # Lane Tracing Assist (LTA) control limits
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    # EPS ignores commands above this angle and causes PCS to fault
    980,  # deg
    # Assuming a steering ratio of 13.7:
    # Limit to ~2.0 m/s^3 up (7.5 deg/s), ~3.5 m/s^3 down (13 deg/s) at 75 mph
    # Worst case, the low speed limits will allow ~4.0 m/s^3 up (15 deg/s) and ~4.9 m/s^3 down (18 deg/s) at 75 mph,
    # however the EPS has its own internal limits at all speeds which are less than that:
    # Observed internal torque rate limit on TSS 2.5 Camry and RAV4 is ~1500 units/sec up and down when using LTA
    ([10, 40], [1.4, 1.4]),
    ([10, 40], [1.4, 1.4]),
  )

  def __init__(self, CP):
    if CP.lateralTuning.which == 'torque':
      self.STEER_DELTA_UP = 25       # 1.0s time to peak torque
      self.STEER_DELTA_DOWN = 30     # always lower than 45 otherwise the Rav4 faults (Prius seems ok with 50)
    else:
      self.STEER_DELTA_UP = 15       # 1.5s time to peak torque
      self.STEER_DELTA_DOWN = 35     # always lower than 45 otherwise the Rav4 faults (Prius seems ok with 50)

#FD to be added later
class ChanganSafetyFlags(IntFlag):
  CHANGAN_Z6_FLAG = 0x1 #pre 2021 models with veoneer mpc/radar solution
  QIYUAN_A05_FLAG = 0x2 #note tang dmi is not tang dm
  CHANGAN_Z6_IDD_FLAG = 0x4 #note tang dmi is not tang dm

@dataclass
class ChangAnCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))

@dataclass
class ChanganPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: "toyota_secocs_pt_generated"})

@dataclass
class QiyuanPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: "hyundai_santafes_2007"})


class CAR(Platforms):
  CHANGAN_Z6 = ChanganPlatformConfig(
    [
      ChangAnCarDocs("changan z6"),
    ],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15, tireStiffnessFactor=0.444),
  )

  CHANGAN_Z6_IDD = ChanganPlatformConfig(
    [
      ChangAnCarDocs("changan z6 idd"),
    ],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15, tireStiffnessFactor=0.444),
  )

  QIYUAN_A05 = QiyuanPlatformConfig(
    [ChangAnCarDocs("changan qiyuan a05")],
    CarSpecs(mass=1965, wheelbase=2.76, steerRatio=13.9, tireStiffnessFactor=0.444),
  )

STEER_THRESHOLD = 10

# These cars have non-standard EPS torque scale factors. All others are 73
EPS_SCALE = defaultdict(lambda: 73)

DBC = CAR.create_dbc_map()
