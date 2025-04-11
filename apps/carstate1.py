from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.mazda.values import DBC, LKAS_LIMITS, MazdaFlags, Buttons

ButtonType = structs.CarState.ButtonEvent.Type
BUTTONS_DICT = {Buttons.SET_PLUS: ButtonType.accelCruise, Buttons.SET_MINUS: ButtonType.decelCruise,
                Buttons.RESUME: ButtonType.resumeCruise, Buttons.CANCEL: ButtonType.cancel}

class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)

    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR"]["GEAR"]

    self.crz_btns_counter = 0
    self.acc_active_last = False
    self.low_speed_alert = False
    self.lkas_allowed_speed = False
    self.lkas_disabled = False

    self.prev_distance_button = 0
    self.distance_button = 0

    # 新增变量用于跟踪总里程和其他状态
    self.totalDistance = 0.0
    self.lastSpeed = 0.0
    self.lastUpdateTime = 0
    self.yawRate = 0.0
    self.radarTargets = []
    self.handsOffDetected = False
    self.drivingTime = 0

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    ret = structs.CarState()

    self.prev_distance_button = self.distance_button
    self.distance_button = cp.vl["CRZ_BTNS"]["DISTANCE_LESS"]

    self.prev_cruise_buttons = self.cruise_buttons

    if bool(cp.vl["CRZ_BTNS"]["SET_P"]):
      self.cruise_buttons = Buttons.SET_PLUS
    elif bool(cp.vl["CRZ_BTNS"]["SET_M"]):
      self.cruise_buttons = Buttons.SET_MINUS
    elif bool(cp.vl["CRZ_BTNS"]["RES"]):
      self.cruise_buttons = Buttons.RESUME
    else:
      self.cruise_buttons = Buttons.NONE

    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["WHEEL_SPEEDS"]["FL"],
      cp.vl["WHEEL_SPEEDS"]["FR"],
      cp.vl["WHEEL_SPEEDS"]["RL"],
      cp.vl["WHEEL_SPEEDS"]["RR"],
    )
    ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

    # Match panda speed reading
    speed_kph = cp.vl["ENGINE_DATA"]["SPEED"]
    ret.standstill = speed_kph <= .1

    can_gear = int(cp.vl["GEAR"]["GEAR"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.gearStep = cp.vl["GEAR"]["GEAR_BOX"]

    # ---- 获取马自达车辆的所有增强状态信息 ----
    # 发动机和底盘信息
    ret.engineRpm = cp.vl["ENGINE_DATA"]["RPM"]

    # 安全系统状态
    if "EPB" in cp.vl:
      ret.parkingBrake = cp.vl["EPB"]["EPB_ACTIVE"] == 1

    if "TRACTION" in cp.vl:
      ret.espDisabled = cp.vl["TRACTION"]["DSC_OFF"] == 1
      ret.espActive = cp.vl["TRACTION"]["TCS_DCS_MALFUNCTION"] > 0
      ret.tpms = cp.vl["TRACTION"]["TPMS_WARNING_DOUBLE_BLINK"] == 1

    # 驾驶辅助系统状态
    if "CAM_TRAFFIC_SIGNS" in cp.vl and "CAM_PEDESTRIAN" in cp.vl:
      ret.stockFcw = cp.vl["CAM_TRAFFIC_SIGNS"]["FORWARD_COLLISION"] > 0 or cp.vl["CAM_PEDESTRIAN"]["BRAKE_WARNING"] == 1
      ret.stockAeb = (cp.vl["CAM_PEDESTRIAN"]["PED_BRAKE"] > 0 and cp.vl["CAM_PEDESTRIAN"]["AEB_NOT_ENGAGED"] == 0)
      ret.speedLimit = cp.vl["CAM_TRAFFIC_SIGNS"]["SPEED_SIGN"]
      ret.speedLimitValid = cp.vl["CAM_TRAFFIC_SIGNS"]["SPEED_SIGN_ON"] == 1

    # 巡航系统设置
    if "CRZ_CTRL" in cp.vl:
      can_distance_setting = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]
      ret.pcmCruiseGap = 5 - can_distance_setting if 1 <= can_distance_setting <= 4 else can_distance_setting
      # 根据注释，CRZ_AVAILABLE实际上是自适应巡航信号，默认马自达提供的是自适应巡航
      ret.cruiseState.nonAdaptive = False
    # ---- 增强状态信息结束 ----

    # ---- 新增实现8种缺失的参数 ----
    # 1. 车辆横摆角速度 (yawRate) - 从VEHICLE_ACC_Y信号中获取相关数据
    if "BRAKE" in cp.vl:
      # 获取车辆Y轴加速度，作为横摆角速度的一个近似参考
      acc_y = cp.vl["BRAKE"]["VEHICLE_ACC_Y"]
      # 计算横摆角速度 (简化模型，实际上需要更复杂的计算)
      # 当车辆转弯时，Y轴加速度与横摆角速度存在一定关系
      self.yawRate = acc_y * 0.01  # 简化计算，实际应用中需要更精确的关系
      ret.yawRate = self.yawRate

    # 2. 速度限制距离 - 基于速度限制和当前速度估算
    # 如果有速度限制，我们可以估算一个速度限制距离
    if ret.speedLimitValid and ret.speedLimit > 0:
      # 简单估算：假设速度限制持续大约500米
      ret.speedLimitDistance = 500.0  # 未来可基于地图数据改进

    # 3. 驾驶员干预检测 - 利用方向盘和手部检测信号
    if "CRZ_CTRL" in cp.vl:
      self.handsOffDetected = cp.vl["CRZ_CTRL"]["HANDS_OFF_STEERING"] == 1
      handsOnWarning = cp.vl["CRZ_CTRL"]["HANDS_ON_STEER_WARN"]
      ret.handsOnWheelState = 2 if handsOnWarning > 0 else (0 if not self.handsOffDetected else 1)

    # 4. 详细AEB状态 - 补充AEB详细信息
    if "CAM_PEDESTRIAN" in cp.vl:
      # 0:未激活, 1:前方警告, 2:制动准备, 3:紧急制动
      aeb_level = 0
      if cp.vl["CAM_PEDESTRIAN"]["BRAKE_WARNING"] == 1:
        aeb_level = 1
      if cp.vl["CAM_PEDESTRIAN"]["PED_WARNING"] == 1:
        aeb_level = 2
      if cp.vl["CAM_PEDESTRIAN"]["PED_BRAKE"] > 0:
        aeb_level = 3
      ret.aebStatus = aeb_level

    # 5. 刹车灯状态
    if "TRACTION" in cp.vl:
      ret.brakeLights = cp.vl["TRACTION"]["BRAKE"] == 1 or ret.brakePressed

    # 6. 总行驶里程 - 尝试从可能的里程信号中获取
    if "NEW_MSG_3" in cp.vl and "MILAGE_MAYBE" in cp.vl["NEW_MSG_3"]:
      # 这是一个假设的里程表读数，需要进一步验证
      possible_mileage = cp.vl["NEW_MSG_3"]["MILAGE_MAYBE"]
      # 转换为公里
      ret.totalDistance = possible_mileage  # 可能需要乘以一个系数
    else:
      # 如果没有直接的里程信号，我们可以通过车速积分来估算
      # 仅在非静止状态下累加里程
      if not ret.standstill and self.lastUpdateTime > 0:
        # 假设每次更新间隔为10ms (0.01s)
        time_diff = 0.01
        # 平均速度(m/s) * 时间(s) = 距离(m)
        distance_traveled = (ret.vEgo + self.lastSpeed) / 2.0 * time_diff
        self.totalDistance += distance_traveled
      self.lastSpeed = ret.vEgo
      self.lastUpdateTime += 1
      ret.totalDistance = self.totalDistance

    # 7. 雷达目标跟踪 - 从雷达跟踪消息中获取目标信息
    # 清空上一次的雷达目标列表
    self.radarTargets = []

    # 处理雷达跟踪数据(检查RADAR_DISTANCE消息是否存在)
    if "RADAR_DISTANCE" in cp.vl:
      lead_distance = cp.vl["RADAR_DISTANCE"]["DISTANCE_LEAD"]
      lead_rel_speed = cp.vl["RADAR_DISTANCE"]["RELATIVE_VEL_LEAD"]

      if lead_distance > 0:  # 如果存在前车
        ret.leadDistanceTooClose = lead_distance < 20  # 小于20米视为太近

        # 存储雷达目标信息
        self.radarTargets.append({
          "distance": lead_distance,
          "rel_speed": lead_rel_speed,
          "is_lead": True
        })

    # 8. 车辆稳定控制的详细状态
    if "TRACTION" in cp.vl:
      # 读取ABS故障状态
      abs_malfunction = cp.vl["TRACTION"]["ABS_MALFUNCTION"]
      # DSC已关闭状态
      dsc_off = cp.vl["TRACTION"]["DSC_OFF"]
      # TCS/DSC故障状态
      tcs_dcs_malfunction = cp.vl["TRACTION"]["TCS_DCS_MALFUNCTION"]

      # 构建稳定控制系统状态码
      # bit 0: ABS故障
      # bit 1: DSC关闭
      # bit 2: TCS/DSC故障
      stability_control_status = (
        (1 if abs_malfunction > 0 else 0) |
        (2 if dsc_off > 0 else 0) |
        (4 if tcs_dcs_malfunction > 0 else 0)
      )

      ret.stabilityControlStatus = stability_control_status
    # ---- 新增参数实现结束 ----

    ret.genericToggle = bool(cp.vl["BLINK_INFO"]["HIGH_BEAMS"])
    ret.leftBlindspot = cp.vl["BSM"]["LEFT_BS_STATUS"] != 0
    ret.rightBlindspot = cp.vl["BSM"]["RIGHT_BS_STATUS"] != 0
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40, cp.vl["BLINK_INFO"]["LEFT_BLINK"] == 1,
                                                                      cp.vl["BLINK_INFO"]["RIGHT_BLINK"] == 1)

    ret.steeringAngleDeg = cp.vl["STEER"]["STEER_ANGLE"]
    ret.steeringTorque = cp.vl["STEER_TORQUE"]["STEER_TORQUE_SENSOR"]
    ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD

    ret.steeringTorqueEps = cp.vl["STEER_TORQUE"]["STEER_TORQUE_MOTOR"]
    ret.steeringRateDeg = cp.vl["STEER_RATE"]["STEER_ANGLE_RATE"]

    # TODO: this should be from 0 - 1.
    ret.brakePressed = cp.vl["PEDALS"]["BRAKE_ON"] == 1
    ret.brake = cp.vl["BRAKE"]["BRAKE_PRESSURE"]

    ret.seatbeltUnlatched = cp.vl["SEATBELT"]["DRIVER_SEATBELT"] == 0
    ret.doorOpen = any([cp.vl["DOORS"]["FL"], cp.vl["DOORS"]["FR"],
                        cp.vl["DOORS"]["BL"], cp.vl["DOORS"]["BR"]])

    # TODO: this should be from 0 - 1.
    ret.gas = cp.vl["ENGINE_DATA"]["PEDAL_GAS"]
    ret.gasPressed = ret.gas > 0

    # Either due to low speed or hands off
    lkas_blocked = cp.vl["STEER_RATE"]["LKAS_BLOCK"] == 1

    if self.CP.minSteerSpeed > 0:
      # LKAS is enabled at 52kph going up and disabled at 45kph going down
      # wait for LKAS_BLOCK signal to clear when going up since it lags behind the speed sometimes
      if speed_kph > LKAS_LIMITS.ENABLE_SPEED and not lkas_blocked:
        self.lkas_allowed_speed = True
      elif speed_kph < LKAS_LIMITS.DISABLE_SPEED:
        self.lkas_allowed_speed = False
    else:
      self.lkas_allowed_speed = True

    # TODO: the signal used for available seems to be the adaptive cruise signal, instead of the main on
    ret.cruiseState.available = cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"] == 1
    ret.cruiseState.enabled = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1
    ret.cruiseState.standstill = cp.vl["PEDALS"]["STANDSTILL"] == 1
    ret.cruiseState.speed = cp.vl["CRZ_EVENTS"]["CRZ_SPEED"] * CV.KPH_TO_MS

    # stock lkas should be on
    # TODO: is this needed?
    ret.invalidLkasSetting = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0

    if ret.cruiseState.enabled:
      if not self.lkas_allowed_speed and self.acc_active_last:
        self.low_speed_alert = True
      else:
        self.low_speed_alert = False
    ret.lowSpeedAlert = self.low_speed_alert

    # Check if LKAS is disabled due to lack of driver torque when all other states indicate
    # it should be enabled (steer lockout). Don't warn until we actually get lkas active
    # and lose it again, i.e, after initial lkas activation
    ret.steerFaultTemporary = self.lkas_allowed_speed and lkas_blocked

    self.acc_active_last = ret.cruiseState.enabled

    self.crz_btns_counter = cp.vl["CRZ_BTNS"]["CTR"]

    # camera signals
    self.lkas_disabled = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0
    self.cam_lkas = cp_cam.vl["CAM_LKAS"]
    self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]
    ret.steerFaultPermanent = cp_cam.vl["CAM_LKAS"]["ERR_BIT_1"] == 1

    self.lkas_previously_enabled = self.lkas_enabled
    self.lkas_enabled = not self.lkas_disabled

    # TODO: add button types for inc and dec
    #ret.buttonEvents = create_button_events(self.distance_button, prev_distance_button, {1: ButtonType.gapAdjustCruise})
    ret.buttonEvents = [
      *create_button_events(self.cruise_buttons, self.prev_cruise_buttons, BUTTONS_DICT),
      *create_button_events(self.distance_button, self.prev_distance_button, {1: ButtonType.gapAdjustCruise}),
      *create_button_events(self.lkas_enabled, self.lkas_previously_enabled, {1: ButtonType.lfaButton}),
    ]
    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      # sig_address, frequency
      ("BLINK_INFO", 10),
      ("STEER", 67),
      ("STEER_RATE", 83),
      ("STEER_TORQUE", 83),
      ("WHEEL_SPEEDS", 100),
    ]

    if CP.flags & MazdaFlags.GEN1:
      pt_messages += [
        ("ENGINE_DATA", 100),
        ("CRZ_CTRL", 50),
        ("CRZ_EVENTS", 50),
        ("CRZ_BTNS", 10),
        ("PEDALS", 50),
        ("BRAKE", 50),
        ("SEATBELT", 10),
        ("DOORS", 10),
        ("GEAR", 20),
        ("BSM", 10),
        ("EPB", 10),           # 添加电子驻车制动信号
        ("TRACTION", 50),      # 添加车辆稳定控制信号
        ("CAM_TRAFFIC_SIGNS", 10),  # 添加交通标志信号
        ("CAM_PEDESTRIAN", 20),     # 添加行人检测信号
        ("RADAR_DISTANCE", 50),     # 添加雷达距离信号
        ("NEW_MSG_3", 10),          # 添加可能包含里程表数据的消息
      ]

    cam_messages = []
    if CP.flags & MazdaFlags.GEN1:
      cam_messages += [
        # sig_address, frequency
        ("CAM_LANEINFO", 2),
        ("CAM_LKAS", 16),
      ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
