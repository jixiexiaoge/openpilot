from collections import namedtuple
from dataclasses import dataclass, field
from enum import Enum, IntFlag
from openpilot.common.params import Params
from openpilot.system.hardware import PC
from opendbc.car import AngleSteeringLimits, Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, structs
from opendbc.car.structs import CarParams
from opendbc.car.docs_definitions import CarHarness, CarDocs, CarParts
from opendbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries
from opendbc.car.byd.tuning import Tuning

Ecu = CarParams.Ecu
#Button = namedtuple('Button', ['event_type', 'can_addr', 'can_msg', 'values'])


class CarControllerParams:
  STEER_MAX = 300
  STEER_DELTA_UP = 17
  STEER_DELTA_DOWN = 17

  STEER_DRIVER_ALLOWANCE = 68
  STEER_DRIVER_MULTIPLIER = 3
  STEER_DRIVER_FACTOR = 1
  STEER_ERROR_MAX = 80
  # Steer torque clip = STEER_MAX - (DriverTorque - STEER_DRIVER_ALLOWANCE) * STEER_DRIVER_MULTIPLIER (Only work when DriverTorque > STEER_DRIVER_ALLOWANCE)
  # So DriverTorque(max) = STEER_MAX / STEER_DRIVER_MULTIPLIER + STEER_DRIVER_ALLOWANCE = 300/3+68 = 168
  # i.e. when drivertorque > 168, new_steer will be cliped to 0

  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    # When output steering Angle not within range -1311 and 1310,
    #   CANPacker packs wrong angle output to be decoded by panda
    Tuning.ANGLE_SPEED_MAX,  # deg, reasonable limit
    (Tuning.ANGLE_SPEED_BP, Tuning.ANGLE_SPEED_UP),
    (Tuning.ANGLE_SPEED_BP, Tuning.ANGLE_SPEED_DOWN),
  )
  LKAS_MAX_TORQUE = Tuning.LKAS_MAX_TORQUE
  STEER_THRESHOLD = Tuning.STEER_THRESHOLD

  # When output steering Angle not within range -1311 and 1310,
  #   CANPacker packs wrong angle output to be decoded by panda
  MAX_STEER_ANGLE = Tuning.MAX_STEER_ANGLE

  ACCEL_MAX = 3.0
  ACCEL_MIN = -4.5

  K_DASHSPEED = 0.0719088 #convert pulse to kph

  # op long control
  K_accel_jerk_upper = 0.1
  K_accel_jerk_lower = 0.5
  K_jerk_xp = [4, 10, 20, 40, 80]  # meters
  K_jerk_base_lower_fp = [-2.0, -1.8, -1.4, -1.0, -0.4]
  K_jerk_base_upper_fp = [ 0.8,  0.7,  0.6,  0.3,  0.2]

  def __init__(self, CP):
    CanBus.checkPanda()

class BydFlags(IntFlag):
  CANFD = 0x1
  ANGLE_CONTROL = 0x2 #角度模式，海豹用
  ALT_INDICATOR = 0x4 #用 TURN_SIGNAL_SWITCH
  SETSPEED_X10 = 0x8 #设定速度x10
  BCM_SEAL = 0x10
  ALT_ACC_EPS = 0x20
  ALT_ACC_EPS_SEAL = 0x40
  ALT_PCM_BTN = 0x80

class BydSafetyFlags(IntFlag):
  HAN_TANG_DMEV = 0x1 #default option, pre 2021 models with veoneer mpc/radar solution
  HAN_DMI = 0x2
  TANG_DMI = 0x4 #note tang dmi is not tang dm
  SONG_PLUS_DMI = 0x8 #note song pro is similar but not song dmi
  QIN_PLUS_DMI = 0x10
  YUAN_PLUS_DMI_ATTO3 = 0x20 #yuan plus is atto3
  SEAL = 0x40

@dataclass
class BydCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))

@dataclass(frozen=True, kw_only=True)
class BydCarSpecs(CarSpecs):
  tireStiffnessFactor: float = 1.0



@dataclass
class BydPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: "byd_generic_pt"})

  def init(self):
    super().init()
    #self.flags |= BydFlags.CANFD

class CAR(Platforms):
  BYD_HAN_DM_20 = BydPlatformConfig(
    [BydCarDocs("Byd Han DM 20")],
    CarSpecs(mass=2080., wheelbase=2.920, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_HAN_DMI_22 = BydPlatformConfig(
    [BydCarDocs("Byd Han DMI 22")],
    CarSpecs(mass=2080., wheelbase=2.920, steerRatio=15.0, centerToFrontRatio=0.44),
    flags=BydFlags.CANFD | BydFlags.SETSPEED_X10 | BydFlags.ALT_INDICATOR | BydFlags.BCM_SEAL | BydFlags.ALT_PCM_BTN | BydFlags.ALT_ACC_EPS,
  )

  BYD_HAN_EV_20 = BydPlatformConfig(
    [BydCarDocs("Byd Han EV 20")],
    CarSpecs(mass=2100., wheelbase=2.959, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_TANG_DM = BydPlatformConfig(
    [BydCarDocs("Byd Tang DM")],
    CarSpecs(mass=2250., wheelbase=2.820, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_TANG_DMI_21 = BydPlatformConfig(
    [BydCarDocs("Byd Tang DMI 21")],
    CarSpecs(mass=2250., wheelbase=2.820, steerRatio=15.0, centerToFrontRatio=0.44),
    flags=BydFlags.CANFD | BydFlags.ALT_INDICATOR | BydFlags.BCM_SEAL | BydFlags.ALT_PCM_BTN | BydFlags.ALT_ACC_EPS,
  )

  BYD_SONG_PLUS_DMI_21 = BydPlatformConfig(
    [BydCarDocs("Byd Song Plus DMI 21")],
    CarSpecs(mass=1785., wheelbase=2.765, steerRatio=15.0, centerToFrontRatio=0.44),
    flags=BydFlags.ALT_INDICATOR,
  )

  BYD_SONG_PRO_DMI_22 = BydPlatformConfig(
    [BydCarDocs("Byd Song Pro DMI 22")],
    CarSpecs(mass=1785., wheelbase=2.712, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_QIN_PLUS_DMI_23 = BydPlatformConfig(
    [BydCarDocs("Byd Qin Plus DMI 23")],
    CarSpecs(mass=1580., wheelbase=2.718, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_YUAN_PLUS_DMI_22 = BydPlatformConfig(
    [BydCarDocs("Byd Yuan Plus DMI 22")],
    CarSpecs(mass=1625., wheelbase=2.720, steerRatio=15.0, centerToFrontRatio=0.44),
  )

  BYD_SEAL_23 = BydPlatformConfig(
    [BydCarDocs("Byd Seal 23")],
    CarSpecs(mass=2150., wheelbase=2.920, steerRatio=15.0, centerToFrontRatio=0.3424),
    flags=BydFlags.CANFD | BydFlags.ANGLE_CONTROL  | BydFlags.ALT_INDICATOR | BydFlags.BCM_SEAL | BydFlags.ALT_PCM_BTN,
  )


class LKASConfig:
  DISABLE = 0
  ALARM = 1
  LKA = 2
  ALARM_AND_LKA = 3

class CanBus:
  ESC = 0
  MRR = 1
  MPC = 2
  LOOPBACK = 128
  DROPPED = 192

  @staticmethod
  def checkPanda():
    if Params().get_bool("UseRedPanda"):
      CanBus.ESC = 0 + 4
      CanBus.MRR = 1 + 4
      CanBus.MPC = 2 + 4
      CanBus.LOOPBACK = 128 + 4
      CanBus.DROPPED = 192 + 4
      print("Using External Panda")
    else:
      CanBus.ESC = 0
      CanBus.MRR = 1
      CanBus.MPC = 2
      CanBus.LOOPBACK = 128
      CanBus.DROPPED = 192
      print("Using Internal Panda")

if not PC:
  CanBus.checkPanda() #如果在PC运行就需要先注释掉

FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.UDS_VERSION_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.UDS_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.eps],
      bus=CanBus.ESC,
    ),
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.UDS_VERSION_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.UDS_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.adas, Ecu.fwdCamera],
      bus=CanBus.MPC,
    ),
  ]
)

PLATFORM_HAN_DMEV = {CAR.BYD_HAN_DM_20, CAR.BYD_HAN_EV_20}
PLATFORM_HAN_DMI = {CAR.BYD_HAN_DMI_22}
PLATFORM_TANG_DM = {CAR.BYD_TANG_DM}
PLATFORM_TANG_DMI = {CAR.BYD_TANG_DMI_21}
PLATFORM_SONG_PRO = {CAR.BYD_SONG_PRO_DMI_22}
PLATFORM_SONG_PLUS_DMI = {CAR.BYD_SONG_PLUS_DMI_21}
PLATFORM_QIN_PLUS_DMI = {CAR.BYD_QIN_PLUS_DMI_23}
PLATFORM_YUAN_PLUS_DMI_ATTO3 = {CAR.BYD_YUAN_PLUS_DMI_22}
PLATFORM_SEAL = {CAR.BYD_SEAL_23}

# power train canbus is located and accessible in in MPC connector
MPC_ACC_CAR = PLATFORM_HAN_DMEV | PLATFORM_HAN_DMI | PLATFORM_TANG_DM | PLATFORM_TANG_DMI | PLATFORM_SEAL | PLATFORM_SONG_PLUS_DMI | PLATFORM_SONG_PRO

# power train canbus contains mrr radar info
PT_RADAR_CAR = PLATFORM_HAN_DMEV | PLATFORM_HAN_DMI

# normal radar
RADAR_CAR = PLATFORM_TANG_DM

# use torque lat control, otherwise use angle mode
TORQUE_LAT_CAR = PLATFORM_HAN_DMEV | PLATFORM_HAN_DMI | PLATFORM_TANG_DM | PLATFORM_TANG_DMI | PLATFORM_SONG_PLUS_DMI | PLATFORM_SONG_PRO

# use experimental long mode
EXP_LONG_CAR = PLATFORM_HAN_DMEV | PLATFORM_HAN_DMI | PLATFORM_TANG_DM | PLATFORM_TANG_DMI | PLATFORM_SEAL | PLATFORM_SONG_PLUS_DMI | PLATFORM_SONG_PRO

DBC = CAR.create_dbc_map()

if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)
