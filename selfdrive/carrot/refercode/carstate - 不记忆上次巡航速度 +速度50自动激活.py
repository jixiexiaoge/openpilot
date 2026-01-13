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

    # 新增：急弯检测相关参数
    self.steering_angle_threshold = 30.0  # 急弯角度阈值
    self.steering_rate_threshold = 50.0   # 急弯转向速率阈值
    self.emergency_turn_active = False     # 急弯激活标志
    self.last_steering_angle = 0.0
    self.steering_rate = 0.0
    # 新增：自动IACC触发相关参数
    self.auto_iacc_triggered = False  # 是否已经自动触发过IACC
    self.last_speed_below_50 = time.time()  # 最后一次速度低于50的时间戳
    self.speed_stable_start_time = 0  # 速度稳定在50以上的开始时间

  def update(self, can_parsers) -> structs.CarState: # type: ignore
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    ret.doorOpen = any([cp.vl["GW_28B"]["BCM_DriverDoorStatus"]])
    ret.seatbeltUnlatched = cp.vl["GW_50"]["SRS_DriverBuckleSwitchStatus"] == 1
    ret.parkingBrake = False

    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["GW_17A"]["ESP_VehicleSpeed"]
    else:
      carspd = cp.vl["GW_187"]["ESP_VehicleSpeed"]
    speed = carspd if carspd <= 5 else ((carspd/0.98)+2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
   
   # 新增：速度达到50KM/H时自动模拟按下IACC键
    current_speed_kmh = speed  # speed已经是km/h单位
    
    # 检查速度是否达到50KM/H且稳定
    if current_speed_kmh >= 50:
        if self.speed_stable_start_time == 0:
            # 第一次达到50，记录开始时间
            self.speed_stable_start_time = time.time()
        elif time.time() - self.speed_stable_start_time >= 2.0:  # 稳定2秒
            # 触发条件：速度≥50KM/H、巡航未启用、未触发过自动IACC
            if (not self.cruiseEnable and 
                not self.auto_iacc_triggered and
                not self.emergency_turn_active):  # 急弯时不触发
                
                print(f"速度达到{current_speed_kmh:.1f}KM/H，自动启用IACC")
                
                # 统一处理：模拟IACC按键按下（上升沿）
                self.iacc_enable_switch_button_pressed = 1
                self.iacc_enable_switch_button_prev = 0
                self.iacc_enable_switch_button_rising_edge = True
                
                # 触发巡航启用逻辑
                if not self.cruiseEnable and self.iacc_enable_switch_button_rising_edge:
                    self.cruiseEnable = True
                
                self.auto_iacc_triggered = True
                self.cruiseSpeed = current_speed_kmh  # 设置巡航速度为当前速度
    else:
        # 速度低于50，重置稳定计时器
        self.speed_stable_start_time = 0
        
        # 重置触发条件：当速度低于45KM/H时允许再次触发
        if current_speed_kmh < 45:
            self.auto_iacc_triggered = False
            self.last_speed_below_50 = time.time()

    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["GW_180"]["SAS_SteeringAngle"]
    ret.steeringRateDeg = cp.vl["GW_180"]["SAS_SteeringAngleSpeed"]
    
    # 新增：急弯检测逻辑
    current_steering_angle = ret.steeringAngleDeg
    self.steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
    self.last_steering_angle = current_steering_angle
    
    # 检测急弯条件
    is_emergency_turn = (abs(current_steering_angle) > self.steering_angle_threshold or 
                        self.steering_rate > self.steering_rate_threshold)
    
    if is_emergency_turn and not self.emergency_turn_active:
        self.emergency_turn_active = True
        print(f"急弯模式激活: 角度{current_steering_angle:.1f}°, 速率{self.steering_rate:.1f}°/s")
    elif not is_emergency_turn and self.emergency_turn_active:
        self.emergency_turn_active = False
        print("急弯模式关闭")

    if self.CP.carFingerprint == CAR.QIYUAN_A05:
      can_gear = int(cp.vl["GW_331"]["TCU_GearForDisplay"])
      ret.brakePressed = cp.vl["GW_17D"]["PCU_BrkPedlSts"] != 0
      ret.gasPressed = cp.vl["GW_17D"]["PCU_RealAccPedl"] != 0
      self.steeringPressedMax = 1.5
      self.steeringPressedMin = 0.5
      ret.leftBlindspot = (cp.vl["GW_2A4"]["LCDAR_Left_BSD_LCAAlert"] == 1) or (cp.vl["GW_2A4"]["LCDAR_Left_BSD_LCAAlert"] == 2)
      ret.rightBlindspot = (cp.vl["GW_2A4"]["LCDAR_BSD_LCAAlert"] == 1) or (cp.vl["GW_2A4"]["LCDAR_BSD_LCAAlert"] == 2)
    elif self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      can_gear = int(cp.vl["GW_338"]["TCU_GearForDisplay"])
      ret.brakePressed = cp.vl["GW_1A6"]["EMS_BrakePedalStatus"] != 0
      ret.gasPressed = cp.vl["GW_1C6"]["EMS_RealAccPedal"] != 0
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
      ret.leftBlindspot = False
      ret.rightBlindspot = False
    else:
      can_gear = int(cp.vl["GW_338"]["TCU_GearForDisplay"])
      ret.brakePressed = cp.vl["GW_196"]["EMS_BrakePedalStatus"] != 0
      ret.gasPressed = cp.vl["GW_196"]["EMS_RealAccPedal"] != 0
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6
      ret.leftBlindspot = False
      ret.rightBlindspot = False
      
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.leftBlinker, ret.rightBlinker= self.update_blinker_from_stalk(200,
                                                                      cp.vl["GW_28B"]["BCM_TurnIndicatorLeft"] == 1,
                                                                      cp.vl["GW_28B"]["BCM_TurnIndicatorRight"] == 1)

    ret.steeringTorque = cp.vl["GW_17E"]["EPS_MeasuredTorsionBarTorque"]
    ret.steeringTorqueEps = cp.vl["GW_170"]["EPS_ActualTorsionBarTorq"]
    
    # 修改：去除方向机故障提示
    # 原代码：ret.steerFaultTemporary = cp.vl["GW_24F"]["EPS_EPSFailed"] != 0 or cp.vl["GW_17E"]["EPS_LatCtrlAvailabilityStatus"] == 2
    # 改为：始终返回False，去除故障提示
    ret.steerFaultTemporary = False
    
    # 急弯时放宽转向压力检测阈值
    if self.emergency_turn_active:
        emergency_steering_pressed_max = self.steeringPressedMax * 1.5  # 提高50%阈值
        emergency_steering_pressed_min = self.steeringPressedMin * 0.7   # 降低30%阈值
    else:
        emergency_steering_pressed_max = self.steeringPressedMax
        emergency_steering_pressed_min = self.steeringPressedMin

    if self.steeringPressed:
      if abs(ret.steeringTorque) < emergency_steering_pressed_min and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > emergency_steering_pressed_max:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

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
      #记忆上次巡航速度
        #self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed
        #适时速度激活
        self.cruiseSpeed = speed
    if cp.vl["GW_28C"]["GW_MFS_RESPlus_switch_signal"] == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5

    if cp.vl["GW_28C"]["GW_MFS_SETReduce_switch_signal"] == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.cruiseEnablePrev = self.cruiseEnable
    self.buttonPlus = cp.vl["GW_28C"]["GW_MFS_RESPlus_switch_signal"]
    self.buttonReduce = cp.vl["GW_28C"]["GW_MFS_SETReduce_switch_signal"]

    ret.accFaulted = cp_cam.vl["GW_244"]["ACC_ACCMode"] == 7 or cp_cam.vl["GW_31A"]["ACC_IACCHWAMode"] == 7
    ret.cruiseState.available = cp_cam.vl["GW_31A"]["ACC_IACCHWAEnable"] == 1
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS
    cluster_set_speed = self.cruiseSpeed

    if ret.cruiseState.speed != 0:
      ret.cruiseState.speedCluster = cluster_set_speed* CV.KPH_TO_MS

    ret.stockFcw = cp_cam.vl["GW_244"]["ACC_FCWPreWarning"] == 1

    ret.cruiseState.standstill = ret.standstill
    ret.cruiseState.enabled = self.cruiseEnable

    ret.genericToggle = False
    ret.stockAeb = cp_cam.vl["GW_244"]["ACC_AEBCtrlType"] > 0

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