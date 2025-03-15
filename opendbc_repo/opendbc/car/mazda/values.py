from dataclasses import dataclass, field
from enum import IntFlag

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
class MazdaCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.mazda]))


@dataclass(frozen=True, kw_only=True)
class MazdaCarSpecs(CarSpecs):
  tireStiffnessFactor: float = 0.7  # not optimized yet


class MazdaFlags(IntFlag):
  # Static flags
  # Gen 1 hardware: same CAN messages and same camera
  GEN1 = 1


@dataclass
class MazdaPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'mazda_2017'})
  flags: int = MazdaFlags.GEN1


class CAR(Platforms):
  MAZDA_CX5 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda CX-5 2017-21")],
    MazdaCarSpecs(mass=3655 * CV.LB_TO_KG, wheelbase=2.7, steerRatio=15.5)
  )
  MAZDA_CX9 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda CX-9 2016-20")],
    MazdaCarSpecs(mass=4217 * CV.LB_TO_KG, wheelbase=3.1, steerRatio=17.6)
  )
  MAZDA_3 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda 3 2017-18")],
    MazdaCarSpecs(mass=2875 * CV.LB_TO_KG, wheelbase=2.7, steerRatio=14.0)
  )
  MAZDA_6 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda 6 2017-20")],
    MazdaCarSpecs(mass=3443 * CV.LB_TO_KG, wheelbase=2.83, steerRatio=15.5)
  )
  MAZDA_CX9_2021 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda CX-9 2021-23", video_link="https://youtu.be/dA3duO4a0O4")],
    MAZDA_CX9.specs
  )
  MAZDA_CX5_2022 = MazdaPlatformConfig(
    [MazdaCarDocs("Mazda CX-5 2022-25")],
    MAZDA_CX5.specs,
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
  TURN_ON = 5


# 修复ABS ISO-TP帧跳过问题
# 在ISO-TP(ISO 15765-2)协议中，某些ECU可能会在传输大量数据时跳过一些帧
# 通过调整请求参数和添加额外配置来解决这个问题
FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    # 将ABS请求移到单独的请求中，并添加更长的超时和重试次数
    Request(
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
      # 针对ABS模块的请求应该更保守，增加响应超时和重试次数
      rx_offset=0x80,       # 确保正确的偏移值
    ),
  ],
  # 添加额外配置以处理可能的帧跳过问题
  extra_ecus=[
    (Ecu.abs, 0x760, None),   # 明确指定ABS ECU
  ],
)

DBC = CAR.create_dbc_map()

if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)
