from dataclasses import dataclass, field
from enum import IntFlag

from cereal import car
from opendbc.can.parser import CANParser
from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.structs import CarParams
from opendbc.car.docs_definitions import CarHarness, CarDocs, CarParts
from opendbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries

Ecu = CarParams.Ecu


# Steer torque limits
class CarControllerParams:
  STEER_MAX = 800                # theoretical max_steer 2047
  STEER_DELTA_UP = 10             # torque increase per refresh
  STEER_DELTA_DOWN = 25           # torque decrease per refresh
  STEER_DRIVER_ALLOWANCE = 15     # allowed driver torque before start limiting
  STEER_DRIVER_MULTIPLIER = 1     # weight driver torque
  STEER_DRIVER_FACTOR = 1         # from dbc
  STEER_ERROR_MAX = 350           # max delta between torque cmd and torque motor
  STEER_STEP = 1  # 100 Hz

  def __init__(self, CP):
    pass


@dataclass
class BYDCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.hyundai_k]))

  def __init__(self, name: str, package: str = "All", **kwargs):
    # 确保名称前缀为 BYD
    if not name.startswith("BYD "):
      name = f"BYD {name}"
    super().__init__(name=name, package=package, **kwargs)


@dataclass(frozen=True, kw_only=True)
class BYDCarSpecs(CarSpecs):
  tireStiffnessFactor: float = 0.7  # not optimized yet


class BYDFlags(IntFlag):
  # Static flags
  GEN1 = 1


@dataclass
class BYDPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'byd_2023'})
  flags: int = BYDFlags.GEN1


class CAR(Platforms):
  # BYD 比亚迪车型的
  BYD_SEAL = BYDPlatformConfig(
    [BYDCarDocs("SEAL 2023-24")],
    BYDCarSpecs(mass=2200, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  # 增加根据 fingerprints.py 中的车型
  BYD_HAN_DM_20 = BYDPlatformConfig(
    [BYDCarDocs("HAN DM 2020")],
    BYDCarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_HAN_EV_20 = BYDPlatformConfig(
    [BYDCarDocs("HAN EV 2020")],
    BYDCarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_TANG_DM = BYDPlatformConfig(
    [BYDCarDocs("TANG DM")],
    BYDCarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_TANG_DMI_21 = BYDPlatformConfig(
    [BYDCarDocs("TANG DMI 2021")],
    BYDCarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_SONG_PLUS_DMI_21 = BYDPlatformConfig(
    [BYDCarDocs("SONG PLUS DMI 2021")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_SONG_PLUS_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("SONG PLUS DMI 2022")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_SONG_PLUS_5G_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("SONG PLUS 5G DMI 2022")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_SONG_PLUS_DMI_23 = BYDPlatformConfig(
    [BYDCarDocs("SONG PLUS DMI 2023")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_SONG_PRO_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("SONG PRO DMI 2022")],
    BYDCarSpecs(mass=1700, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_QIN_PLUS_DMI_23 = BYDPlatformConfig(
    [BYDCarDocs("QIN PLUS DMI 2023")],
    BYDCarSpecs(mass=1600, wheelbase=2.72, steerRatio=15.0, centerToFrontRatio=0.4)
  )

  BYD_YUAN_PLUS_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("YUAN PLUS DMI 2022")],
    BYDCarSpecs(mass=1500, wheelbase=2.62, steerRatio=15.0, centerToFrontRatio=0.4)
  )


class LKAS_LIMITS:
  STEER_THRESHOLD = 15
  DISABLE_SPEED = 45    # kph
  ENABLE_SPEED = 52     # kph


class Buttons:
  NONE = 0
  SET_PLUS = 1
  SET_MINUS = 2
  RESUME = 3
  CANCEL = 4


FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    Request(
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
    ),
  ],
)


def get_can_parser(CP):
  signals = [
    # Steering
    ("Steering_Angle", "STEERING_ANGLE", 0),
    ("Steering_Angle_Valid", "STEERING_ANGLE", 0),
    ("Steering_Angle_Rate", "STEERING_ANGLE", 0),

    # Vehicle
    ("Vehicle_Speed", "VEHICLE_SPEED", 0),
    ("Vehicle_Acceleration", "VEHICLE_SPEED", 0),

    # Brake
    ("Brake_Pressed", "BRAKE_STATUS", 0),
    ("Brake_Pressure", "BRAKE_STATUS", 0),

    # Throttle
    ("Throttle_Percent", "THROTTLE_POSITION", 0),

    # Gear
    ("Gear", "GEAR_POSITION", 0),

    # Cruise
    ("ACC_Active", "CRUISE_CONTROL", 0),
    ("ACC_Speed_Setting", "CRUISE_CONTROL", 0),

    # Vehicle Status
    ("Power_Mode", "VEHICLE_STATUS", 0),
    ("Vehicle_Ready", "VEHICLE_STATUS", 0),
    ("EPS_Status", "VEHICLE_STATUS", 0),
  ]

  checks = [
    ("STEERING_ANGLE", 100),
    ("VEHICLE_SPEED", 50),
    ("BRAKE_STATUS", 50),
    ("THROTTLE_POSITION", 50),
    ("GEAR_POSITION", 50),
    ("CRUISE_CONTROL", 50),
    ("VEHICLE_STATUS", 10),
  ]

  return CANParser(CP.carFingerprint, signals, checks, 0)


DBC = CAR.create_dbc_map()

if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)