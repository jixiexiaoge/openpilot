import copy
import time
from openpilot.common.conversions import Conversions as CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_CTRL
from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import CAR, DBC, STEER_THRESHOLD, EPS_SCALE
from opendbc.car import Bus, structs


SteerControlType = structs.CarParams.SteerControlType

# These steering fault definitions seem to be common across LKA (torque) and LTA (angle):
# - high steer rate fault: goes to 21 or 25 for 1 frame, then 9 for 2 seconds
# - lka/lta msg drop out: goes to 9 then 11 for a combined total of 2 seconds, then 3.
#     if using the other control command, goes directly to 3 after 1.5 seconds
# - initializing: LTA can report 0 as long as STEER_TORQUE_SENSOR->STEER_ANGLE_INITIALIZING is 1,
#     and is a catch-all for LKA
TEMP_STEER_FAULTS = (0, 9, 11, 21, 25)
# - lka/lta msg drop out: 3 (recoverable)
# - prolonged high driver torque: 17 (permanent)
PERM_STEER_FAULTS = (3, 17)


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    if CP.carFingerprint == CAR.QIYUAN_A05:
      self.shifter_values = can_define.dv["GW_331"]["TCU_GearForDisplay"]
    else:
      self.shifter_values = can_define.dv["GW_338"]["TCU_GearForDisplay"]
    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.cluster_min_speed = CV.KPH_TO_MS / 2.

    # On cars with cp.vl["STEER_TORQUE_SENSOR"]["STEER_ANGLE"]
    # the signal is zeroed to where the steering angle is at start.
    # Need to apply an offset as soon as the steering angle measurements are both received
    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.prev_distance_button = 0
    self.distance_button = 0

    self.pcm_follow_distance = 0

    self.low_speed_lockout = False
    self.acc_type = 1
    self.lkas_hud = {}
    self.cruiseEnable = False
    self.cruiseTiming = time.time()
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.sigs244 = 0
    self.sigs1ba = 0
    self.sigs17e = 0
    self.sigs307 = 0
    self.sigs31a = 0

    self.steeringPressed = False
    self.steeringPressedMax = 0
    self.steeringPressedMin = 0

    self.iacc_enable_switch_button_pressed = 0
    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False


  def update(self, can_parsers) -> structs.CarState: # type: ignore
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    ret.doorOpen = any([cp.vl["GW_28B"]["BCM_DriverDoorStatus"]]) # 门开
    ret.seatbeltUnlatched = cp.vl["GW_50"]["SRS_DriverBuckleSwitchStatus"] == 1 # 安全带
    ret.parkingBrake = False # 手刹 无相应can报文

    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["GW_17A"]["ESP_VehicleSpeed"]
    else:
      carspd = cp.vl["GW_187"]["ESP_VehicleSpeed"]
    speed = carspd if carspd <= 5 else ((carspd/0.98)+2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    # ret.vEgoCluster = ret.vEgo * 1.015  # minimum of all the cars 仪表显示速度
    ret.vEgoCluster = ret.vEgo  # minimum of all the cars 仪表显示速度

    ret.standstill = abs(ret.vEgoRaw) < 1e-3 # 车辆停止

    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["GW_180"]["SAS_SteeringAngle"] # 方向盘角度
    ret.steeringRateDeg = cp.vl["GW_180"]["SAS_SteeringAngleSpeed"] # 方向盘速率

    if self.CP.carFingerprint == CAR.QIYUAN_A05:
      can_gear = int(cp.vl["GW_331"]["TCU_GearForDisplay"]) # 档位
      ret.brakePressed = cp.vl["GW_17D"]["PCU_BrkPedlSts"] != 0 # 刹车
      ret.gasPressed = cp.vl["GW_17D"]["PCU_RealAccPedl"] != 0 # 油门踏板开度
      self.steeringPressedMax = 1.5
      self.steeringPressedMin = 0.5
      ret.leftBlindspot = (cp.vl["GW_2A4"]["LCDAR_Left_BSD_LCAAlert"] == 1) or (cp.vl["GW_2A4"]["LCDAR_Left_BSD_LCAAlert"] == 2)
      ret.rightBlindspot = (cp.vl["GW_2A4"]["LCDAR_BSD_LCAAlert"] == 1) or (cp.vl["GW_2A4"]["LCDAR_BSD_LCAAlert"] == 2)
    elif self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      can_gear = int(cp.vl["GW_338"]["TCU_GearForDisplay"]) # 档位
      ret.brakePressed = cp.vl["GW_1A6"]["EMS_BrakePedalStatus"] != 0 # 刹车
      ret.gasPressed = cp.vl["GW_1C6"]["EMS_RealAccPedal"] != 0 # 油门踏板开度
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
      ret.leftBlindspot = False
      ret.rightBlindspot = False
    else:
      can_gear = int(cp.vl["GW_338"]["TCU_GearForDisplay"]) # 档位
      ret.brakePressed = cp.vl["GW_196"]["EMS_BrakePedalStatus"] != 0 # 刹车
      ret.gasPressed = cp.vl["GW_196"]["EMS_RealAccPedal"] != 0 # 油门踏板开度
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6
      ret.leftBlindspot = False
      ret.rightBlindspot = False
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.leftBlinker, ret.rightBlinker= self.update_blinker_from_stalk(200,
                                                                      cp.vl["GW_28B"]["BCM_TurnIndicatorLeft"] == 1,
                                                                      cp.vl["GW_28B"]["BCM_TurnIndicatorRight"] == 1)  # 左转向灯

    ret.steeringTorque = cp.vl["GW_17E"]["EPS_MeasuredTorsionBarTorque"] # 转向扭矩
    ret.steeringTorqueEps = cp.vl["GW_170"]["EPS_ActualTorsionBarTorq"] # eps 转向扭矩
    # we could use the override bit from dbc, but it's triggered at too high torque values
    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # Check EPS LKA/LTA fault status
    ret.steerFaultTemporary = cp.vl["GW_24F"]["EPS_EPSFailed"] != 0 or cp.vl["GW_17E"]["EPS_LatCtrlAvailabilityStatus"] == 2  # 转向故障

    if self.CP.carFingerprint == CAR.QIYUAN_A05:
      if cp.vl["GW_28C"]["GW_MFS_IACCenable_switch_signal"] == 1:
        self.cruiseEnable = True
      if cp.vl["GW_28C"]["GW_MFS_Cancle_switch_signal"] == 1 or ret.brakePressed:
        self.cruiseEnable = False
    else:
      self.iacc_enable_switch_button_pressed = cp.vl["GW_28C"]["GW_MFS_IACCenable_switch_signal"]
      self.iacc_enable_switch_button_rising_edge = self.iacc_enable_switch_button_pressed == 1 and self.iacc_enable_switch_button_prev == 0

      if self.cruiseEnable and (self.iacc_enable_switch_button_rising_edge or ret.brakePressed):
          self.cruiseEnable = False
      elif not self.cruiseEnable and self.iacc_enable_switch_button_rising_edge:
          self.cruiseEnable = True

      self.iacc_enable_switch_button_prev = self.iacc_enable_switch_button_pressed

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed

    if cp.vl["GW_28C"]["GW_MFS_RESPlus_switch_signal"] == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5

    if cp.vl["GW_28C"]["GW_MFS_SETReduce_switch_signal"] == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.cruiseEnablePrev = self.cruiseEnable
    self.buttonPlus = cp.vl["GW_28C"]["GW_MFS_RESPlus_switch_signal"]
    self.buttonReduce = cp.vl["GW_28C"]["GW_MFS_SETReduce_switch_signal"]

    ret.accFaulted = cp_cam.vl["GW_244"]["ACC_ACCMode"] == 7 or cp_cam.vl["GW_31A"]["ACC_IACCHWAMode"] == 7
    ret.cruiseState.available = cp_cam.vl["GW_31A"]["ACC_IACCHWAEnable"] == 1 # 巡航状态 可用
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS
    cluster_set_speed = self.cruiseSpeed

    # UI_SET_SPEED is always non-zero when main is on, hide until first enable
    if ret.cruiseState.speed != 0:
      ret.cruiseState.speedCluster = cluster_set_speed* CV.KPH_TO_MS # 巡航仪表显示速度

    ret.stockFcw = cp_cam.vl["GW_244"]["ACC_FCWPreWarning"] == 1  # 前碰撞预警

    # ignore standstill state in certain vehicles, since pcm allows to restart with just an acceleration request
    ret.cruiseState.standstill = ret.standstill # 巡航状态 停止

    ret.cruiseState.enabled = self.cruiseEnable

    ret.genericToggle = False # 自动远光灯
    # ret.espDisabled = True # ESP 关闭

    ret.stockAeb = cp_cam.vl["GW_244"]["ACC_AEBCtrlType"] > 0 # 前碰撞刹车

    self.sigs244 = copy.copy(cp_cam.vl["GW_244"])
    self.sigs1ba = copy.copy(cp_cam.vl["GW_1BA"])
    self.sigs17e = copy.copy(cp.vl["GW_17E"])
    self.sigs307 = copy.copy(cp_cam.vl["GW_307"])
    self.sigs31a = copy.copy(cp_cam.vl["GW_31A"])
    self.counter_244 = (cp_cam.vl["GW_244"]["ACC_RollingCounter_24E"])
    self.counter_1ba = (cp_cam.vl["GW_1BA"]["ACC_RollingCounter_1BA"])
    self.counter_17e = (cp.vl["GW_17E"]["EPS_RollingCounter_17E"])
    self.counter_307 = (cp_cam.vl["GW_307"]["ACC_RollingCounter_35E"])
    self.counter_31a = (cp_cam.vl["GW_31A"]["ACC_RollingCounter_36D"])

    # distance button is wired to the ACC module (camera or radar)
    self.prev_distance_button = self.distance_button
    self.distance_button = cp_cam.vl["GW_307"]["ACC_DistanceLevel"]

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_28B", 25),
      ("GW_50", 2),
      ("GW_17E", 100),
      ("GW_180", 100),
      ("GW_24F", 50),
      ("GW_170", 100),
      ("GW_28C", 25),
    ]

    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [
        ("GW_17A", 100),
      ]
    else:
      pt_messages += [
        ("GW_187", 100),
      ]

    if CP.carFingerprint == CAR.QIYUAN_A05:
      pt_messages += [
        ("GW_331", 10),
        ("GW_17D", 100),
        ("GW_2A4", 20),
      ]
    elif CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [
        ("GW_1A6", 100),
        ("GW_1C6", 100),
        ("GW_338", 10),
      ]
    else:
      pt_messages += [
        ("GW_338", 10),
        ("GW_196", 100),
      ]


    cam_messages = [
      ("GW_1BA", 100),
      ("GW_244", 50),
      ("GW_307", 10),
      ("GW_31A", 10),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }

