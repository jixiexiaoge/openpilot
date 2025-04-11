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


# VIN映射 - 帮助识别不同型号
VIN_MODEL_MAP = {
  # 马自达 CX-5 VIN前缀
  "VHK": CAR.MAZDA_CX5,         # 2017-2019款 CX-5
  "LVH": CAR.MAZDA_CX5_2022,    # 2022款 CX-5
  "JM0": CAR.MAZDA_CX5,         # 部分地区 CX-5
  "LVR": CAR.MAZDA_CX5_2022,    # 您的车型 (从日志中看到)
}

# 通过VIN识别车型
def get_car_from_vin(vin):
  if vin is None or len(vin) < 3:
    return None

  # 尝试匹配VIN前缀
  for prefix, car_type in VIN_MODEL_MAP.items():
    if vin.startswith(prefix):
      print(f"通过VIN前缀 {prefix} 识别为 {car_type}")
      return car_type

  # 尝试通过前三位识别
  prefix = vin[:3]
  if prefix in VIN_MODEL_MAP:
    print(f"通过VIN前三位识别为 {VIN_MODEL_MAP[prefix]}")
    return VIN_MODEL_MAP[prefix]

  print(f"无法通过VIN识别车型: {vin}")
  return None


# 定义雷达限制常量
class RADAR_LIMITS:
  RADAR_TRACK_ID_MAX = 16      # 最大雷达目标跟踪数
  MIN_DISTANCE = 0.0           # 最小检测距离(米)
  MAX_DISTANCE = 200.0         # 最大检测距离(米)
  MIN_SPEED_DIFF = -40.0       # 最小相对速度(m/s)
  MAX_SPEED_DIFF = 40.0        # 最大相对速度(m/s)
  MIN_TRACK_AGE = 3            # 最小跟踪帧数
  MAX_TRACK_AGE = 20           # 最大跟踪帧数
  RADAR_FAULT_MAX_AGE = 2.5    # 雷达故障最大持续时间(秒)


class Buttons:
  NONE = 0
  SET_PLUS = 1
  SET_MINUS = 2
  RESUME = 3
  CANCEL = 4


FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    # TODO: check data to ensure ABS does not skip ISO-TP frames on bus 0
    Request(
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
    ),
  ],
)

# 确保DBC映射正确创建并可用
DBC = CAR.create_dbc_map()

# 打印DBC映射以便调试
print("DBC Map generated:")
for car_type, dbc_dict in DBC.items():
  print(f"  {car_type}: {dbc_dict}")

if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)

# 雷达相关常量 - 使用简单整数值
RADAR_TRACK_RANGE_START = 361  # 跟踪ID起始值
RADAR_TRACK_RANGE_END = 368    # 跟踪ID结束值 (确保完整范围361-367)
RADAR_UPDATE_RATE = 20         # 更新频率(Hz)
RADAR_MAX_TRACKS = 16          # 最大跟踪目标数

# 雷达信号值
RADAR_INVALID_DISTANCE = 4095  # 无效距离值
RADAR_INVALID_ANGLE = 2046     # 无效角度值
RADAR_INVALID_SPEED = -16      # 无效速度值
RADAR_ANGLE_SCALE = 64.0       # 角度缩放因子
RADAR_DISTANCE_SCALE = 16.0    # 距离缩放因子
RADAR_SPEED_SCALE = 16.0       # 速度缩放因子

# 雷达状态值
RADAR_FAULT_NONE = 0           # 无故障
RADAR_FAULT_TEMPORARY = 1      # 临时故障
RADAR_FAULT_PERMANENT = 2      # 永久故障
RADAR_BLOCKED = 3              # 雷达被遮挡

# CAN消息ID
RADAR_DISTANCE_ID = 0x300      # 雷达距离消息ID
RADAR_RELATIVE_SPEED_ID = 0x301 # 相对速度消息ID
RADAR_CROSS_TRAFFIC_ID = 0x302 # 横向交通消息ID
RADAR_HUD_ID = 0x303           # HUD显示消息ID
RADAR_TRACK_BASE_ID = 0x400    # 雷达跟踪消息基础ID

# 雷达参数
RADAR_MIN_TRACK_PROBABILITY = 0.7  # 最小跟踪概率
RADAR_MAX_AGE_WITHOUT_UPDATE = 2.5  # 最大无更新时间(秒)
