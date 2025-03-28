from dataclasses import dataclass, field
from enum import IntFlag, Enum

from cereal import car
from opendbc.can.parser import CANParser
from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.structs import CarParams
from opendbc.car.docs_definitions import CarFootnote, CarHarness, CarDocs, CarParts, Column
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


class BYDFlags(IntFlag):
  CANFD = 1
  EV = 2
  HYBRID = 4
  CAMERA_SCC = 8
  RADAR_SCC = 16
  MANDO_RADAR = 32
  LEGACY = 64
  UNSUPPORTED_LONGITUDINAL = 128
  CHECKSUM_CRC8 = 256
  CHECKSUM_6B = 512
  CLUSTER_GEARS = 1024
  TCU_GEARS = 2048
  MIN_STEER_32_MPH = 4096
  ANGLE_CONTROL = 8192
  CC_ONLY_CAR = 16384


class BYDExtFlags(IntFlag):
  HAS_SCC13 = 1
  HAS_SCC14 = 2
  NAVI_CLUSTER = 4
  HAS_LFAHDA = 8
  HAS_LFA_BUTTON = 16
  CANFD_GEARS_NONE = 32
  BSM_IN_ADAS = 64
  CANFD_TPMS = 128
  CANFD_GEARS_69 = 256
  CANFD_161 = 512
  CRUISE_BUTTON_ALT = 1024


class Footnote(Enum):
  CANFD = CarFootnote(
    "Requires a CAN FD panda kit if not using comma 3X for this CAN FD car.",
    Column.MODEL, shop_footnote=False)


@dataclass
class BYDCarDocs(CarDocs):
  package: str = "智能驾驶辅助系统"

  def init_make(self, CP: CarParams):
    if CP.flags & BYDFlags.CANFD:
      self.footnotes.insert(0, Footnote.CANFD)


@dataclass(frozen=True, kw_only=True)
class BYDCarSpecs(CarSpecs):
  tireStiffnessFactor: float = 0.7  # not optimized yet


@dataclass
class BYDPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'byd_2023'})
  flags: int = BYDFlags.CANFD


class CAR(Platforms):
  # BYD Han
  BYD_HAN_DM_20 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪汉DM 2020", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example1")],
    BYDCarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_HAN_EV_20 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪汉EV 2020", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example2")],
    BYDCarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.EV | BYDFlags.CAMERA_SCC
  )

  # BYD Tang
  BYD_TANG_DM = BYDPlatformConfig(
    [BYDCarDocs("比亚迪唐DM", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example3")],
    BYDCarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_TANG_DMI_21 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪唐DM-i 2021", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example4")],
    BYDCarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  # BYD Song
  BYD_SONG_PLUS_DMI_21 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪宋PLUS DM-i 2021", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example5")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_SONG_PLUS_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪宋PLUS DM-i 2022", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example6")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_SONG_PLUS_5G_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪宋PLUS 5G DM-i 2022", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example7")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_SONG_PLUS_DMI_23 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪宋PLUS DM-i 2023", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example8")],
    BYDCarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  BYD_SONG_PRO_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪宋PRO DM-i 2022", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example9")],
    BYDCarSpecs(mass=1700, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  # BYD Qin
  BYD_QIN_PLUS_DMI_23 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪秦PLUS DM-i 2023", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example10")],
    BYDCarSpecs(mass=1600, wheelbase=2.72, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
  )

  # BYD Yuan
  BYD_YUAN_PLUS_DMI_22 = BYDPlatformConfig(
    [BYDCarDocs("比亚迪元PLUS DM-i 2022", "智能驾驶辅助系统", video_link="https://www.youtube.com/watch?v=example11")],
    BYDCarSpecs(mass=1500, wheelbase=2.62, steerRatio=15.0, centerToFrontRatio=0.4),
    flags=BYDFlags.HYBRID | BYDFlags.CAMERA_SCC
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
  LFA_BUTTON = 5


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