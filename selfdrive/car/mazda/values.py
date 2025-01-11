from dataclasses import dataclass, field
from enum import IntFlag

from cereal import car
from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car import CarSpecs, DbcDict, PlatformConfig, Platforms, dbc_dict
from openpilot.selfdrive.car.docs_definitions import CarHarness, CarDocs, CarParts
from openpilot.selfdrive.car.fw_query_definitions import FwQueryConfig, Request, StdQueries

Ecu = car.CarParams.Ecu


# 转向扭矩限制参数类
class CarControllerParams:
  STEER_MAX = 800                # 理论最大转向值 2047
  STEER_DELTA_UP = 10            # 每次刷新转向扭矩增加值
  STEER_DELTA_DOWN = 25          # 每次刷新转向扭矩减少值
  STEER_DRIVER_ALLOWANCE = 15    # 开始限制前允许的驾驶员扭矩
  STEER_DRIVER_MULTIPLIER = 1    # 驾驶员扭矩权重
  STEER_DRIVER_FACTOR = 1        # 来自DBC的因子
  STEER_ERROR_MAX = 350          # 转向命令和转向电机之间的最大差值
  STEER_STEP = 1                 # 100 Hz

  def __init__(self, CP):
    pass  # 初始化函数，目前为空


# 马自达车辆文档数据类
@dataclass
class MazdaCarDocs(CarDocs):
  package: str = "All"  # 包类型，默认为"All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.mazda]))  # 车辆部件配置


# 马自达车辆规格数据类
@dataclass(frozen=True, kw_only=True)
class MazdaCarSpecs(CarSpecs):
  tireStiffnessFactor: float = 0.7  # 轮胎刚度因子，尚未优化


# 马自达标志枚举类
class MazdaFlags(IntFlag):
  # 静态标志
  # 第一代硬件：相同的CAN消息和相同的摄像头
  GEN1 = 1


# 马自达平台配置数据类
@dataclass
class MazdaPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: dbc_dict('mazda_2017', None))  # DBC字典配置
  flags: int = MazdaFlags.GEN1  # 平台标志


# 车型定义类
class CAR(Platforms):
  # CX5车型配置
  CX5 = MazdaPlatformConfig(
    "MAZDA CX-5",
    [MazdaCarDocs("Mazda CX-5 2017-21")],
    MazdaCarSpecs(mass=3655 * CV.LB_TO_KG, wheelbase=2.7, steerRatio=15.5)
  )
  # CX9车型配置
  CX9 = MazdaPlatformConfig(
    "MAZDA CX-9",
    [MazdaCarDocs("Mazda CX-9 2016-20")],
    MazdaCarSpecs(mass=4217 * CV.LB_TO_KG, wheelbase=3.1, steerRatio=17.6)
  )
  # MAZDA3车型配置
  MAZDA3 = MazdaPlatformConfig(
    "MAZDA 3",
    [MazdaCarDocs("Mazda 3 2017-18")],
    MazdaCarSpecs(mass=2875 * CV.LB_TO_KG, wheelbase=2.7, steerRatio=14.0)
  )
  # MAZDA6车型配置
  MAZDA6 = MazdaPlatformConfig(
    "MAZDA 6",
    [MazdaCarDocs("Mazda 6 2017-20")],
    MazdaCarSpecs(mass=3443 * CV.LB_TO_KG, wheelbase=2.83, steerRatio=15.5)
  )
  # 2021款CX9配置
  CX9_2021 = MazdaPlatformConfig(
    "MAZDA CX-9 2021",
    [MazdaCarDocs("Mazda CX-9 2021-23", video_link="https://youtu.be/dA3duO4a0O4")],
    CX9.specs
  )
  # 2022款CX5配置
  CX5_2022 = MazdaPlatformConfig(
    "MAZDA CX-5 2022",
    [MazdaCarDocs("Mazda CX-5 2022-24")],
    CX5.specs,
  )


# LKAS（车道保持辅助系统）限制参数类
class LKAS_LIMITS:
  STEER_THRESHOLD = 15    # 转向阈值
  DISABLE_SPEED = 45      # 禁用速度（公里/小时）
  ENABLE_SPEED = 52       # 启用速度（公里/小时）


# 按钮定义类
class Buttons:
  NONE = 0       # 无按钮
  SET_PLUS = 1   # 增加设定
  SET_MINUS = 2  # 减少设定
  RESUME = 3     # 恢复
  CANCEL = 4     # 取消


# 固件查询配置
FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    # TODO: 检查数据以确保ABS不会在总线0上跳过ISO-TP帧
    Request(
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.MANUFACTURER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
    ),
  ],
)

# 创建车型DBC映射
DBC = CAR.create_dbc_map()
