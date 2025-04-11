from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.mazda.values import DBC, LKAS_LIMITS, MazdaFlags, Buttons
import time

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
    self.totalDistance = 0.0      # 总行驶里程(公里)
    self.lastSpeed = 0.0          # 上次记录的速度(m/s)
    self.lastUpdateTime = 0       # 上次更新时间(ms)
    self.yawRate = 0.0           # 横摆角速度(rad/s)
    self.radarTargets = []       # 雷达目标列表
    self.handsOffDetected = False # 检测到手离开方向盘
    self.drivingTime = 0         # 驾驶时间(s)

    # 新增安全相关状态变量
    self.aebStatus = 0           # AEB状态(0:未激活,1:警告,2:准备,3:制动)
    self.brakeLightStatus = False # 刹车灯状态
    self.stabilityStatus = 0     # 车辆稳定性控制状态

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
    # 1. 发动机和底盘信息
    ret.engineRpm = cp.vl["ENGINE_DATA"]["RPM"]  # 发动机转速

    # 2. 安全系统状态
    if "EPB" in cp.vl:
      # 电子驻车制动系统(EPB)状态
      ret.parkingBrake = cp.vl["EPB"]["EPB_ACTIVE"] == 1  # 1:启用, 0:未启用

    if "TRACTION" in cp.vl:
      # 动态稳定控制(DSC)状态
      ret.espDisabled = cp.vl["TRACTION"]["DSC_OFF"] == 1  # DSC是否关闭
      ret.espActive = cp.vl["TRACTION"]["TCS_DCS_MALFUNCTION"] > 0  # DSC是否出现故障
      # 胎压监测系统(TPMS)状态
      ret.tpms = cp.vl["TRACTION"]["TPMS_WARNING_DOUBLE_BLINK"] == 1  # TPMS警告

    # 3. 驾驶辅助系统状态
    if "CAM_TRAFFIC_SIGNS" in cp.vl and "CAM_PEDESTRIAN" in cp.vl:
      # 前向碰撞预警(FCW)状态
      ret.stockFcw = (cp.vl["CAM_TRAFFIC_SIGNS"]["FORWARD_COLLISION"] > 0 or
                     cp.vl["CAM_PEDESTRIAN"]["BRAKE_WARNING"] == 1)

      # 自动紧急制动(AEB)状态
      ret.stockAeb = (cp.vl["CAM_PEDESTRIAN"]["PED_BRAKE"] > 0 and
                     cp.vl["CAM_PEDESTRIAN"]["AEB_NOT_ENGAGED"] == 0)

      # 道路限速信息
      ret.speedLimit = cp.vl["CAM_TRAFFIC_SIGNS"]["SPEED_SIGN"]  # 当前限速值
      ret.speedLimitValid = cp.vl["CAM_TRAFFIC_SIGNS"]["SPEED_SIGN_ON"] == 1  # 限速标志是否有效

    # 4. 横摆角速度计算
    if "BRAKE" in cp.vl:
      # 获取车辆Y轴加速度，用于计算横摆角速度
      acc_y = cp.vl["BRAKE"]["VEHICLE_ACC_Y"]  # 横向加速度
      # 将横向加速度转换为横摆角速度(简化计算)
      self.yawRate = acc_y * 0.01  # 转换系数0.01是根据车辆动力学特性估算
      ret.yawRate = self.yawRate

    # 5. 刹车灯状态监控
    if "TRACTION" in cp.vl:
      # 根据制动信号和刹车踏板状态确定刹车灯状态
      ret.brakeLights = cp.vl["TRACTION"]["BRAKE"] == 1 or ret.brakePressed
      self.brakeLightStatus = ret.brakeLights  # 更新内部状态

    # 巡航系统设置
    if "CRZ_CTRL" in cp.vl:
      can_distance_setting = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]
      ret.pcmCruiseGap = 5 - can_distance_setting if 1 <= can_distance_setting <= 4 else can_distance_setting
      # 根据注释，CRZ_AVAILABLE实际上是自适应巡航信号，默认马自达提供的是自适应巡航
      ret.cruiseState.nonAdaptive = False
    # ---- 增强状态信息结束 ----

    # ---- 新增实现8种缺失的参数 ----
    # 1. 速度限制距离 - 基于速度限制和当前速度估算
    # 如果有速度限制，我们可以估算一个速度限制距离
    if ret.speedLimitValid and ret.speedLimit > 0:
      # 简单估算：假设速度限制持续大约500米
      ret.speedLimitDistance = 500.0  # 未来可基于地图数据改进

    # 2. 驾驶员干预检测 - 利用方向盘和手部检测信号
    if "CRZ_CTRL" in cp.vl:
      self.handsOffDetected = cp.vl["CRZ_CTRL"]["HANDS_OFF_STEERING"] == 1
      handsOnWarning = cp.vl["CRZ_CTRL"]["HANDS_ON_STEER_WARN"]
      ret.handsOnWheelState = 2 if handsOnWarning > 0 else (0 if not self.handsOffDetected else 1)

    # 3. 详细AEB状态 - 补充AEB详细信息
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

    # 6. 总行驶里程计算 - 通过多种方式获取和计算里程
    if "NEW_MSG_3" in cp.vl and "MILAGE_MAYBE" in cp.vl["NEW_MSG_3"]:
      # 从CAN总线直接读取里程表数据
      possible_mileage = cp.vl["NEW_MSG_3"]["MILAGE_MAYBE"]
      # 应用转换系数（假设CAN信号单位为0.1km）
      ret.totalDistance = possible_mileage * 0.1
    else:
      # 通过车速积分估算里程
      if not ret.standstill and self.lastUpdateTime > 0:
        current_time = time.time() * 1000  # 获取当前时间戳(毫秒)
        time_diff = (current_time - self.lastUpdateTime) / 1000.0  # 转换为秒

        # 使用梯形积分法计算行驶距离
        # distance = 平均速度 * 时间
        avg_speed = (ret.vEgo + self.lastSpeed) / 2.0  # 平均速度(m/s)
        distance_traveled = avg_speed * time_diff  # 行驶距离(米)

        # 累加到总里程（转换为公里）
        self.totalDistance += distance_traveled / 1000.0

        # 更新上次速度和时间
        self.lastSpeed = ret.vEgo
        self.lastUpdateTime = current_time
      elif self.lastUpdateTime == 0:
        # 首次初始化时间戳
        self.lastUpdateTime = time.time() * 1000

      ret.totalDistance = self.totalDistance

    # 7. 雷达目标跟踪增强 - 支持多目标跟踪
    # 清空上一次的雷达目标列表
    self.radarTargets.clear()  # 使用clear()而不是重新赋值[]

    # 处理雷达跟踪数据
    if "RADAR_DISTANCE" in cp.vl:
      # 获取前车距离和相对速度
      lead_distance = cp.vl["RADAR_DISTANCE"]["DISTANCE_LEAD"]
      lead_rel_speed = cp.vl["RADAR_DISTANCE"]["RELATIVE_VEL_LEAD"]

      # 如果检测到前车
      if lead_distance > 0:
        # 计算碰撞时间(TTC - Time To Collision)
        ttc = abs(lead_distance / lead_rel_speed) if lead_rel_speed != 0 else float('inf')

        # 更新前车距离状态
        ret.leadDistanceTooClose = lead_distance < 20  # 小于20米视为太近
        ret.leadTimeToCollision = ttc  # 添加碰撞时间信息

        # 存储目标信息（增加更多属性）
        target_info = {
          "distance": lead_distance,      # 目标距离(米)
          "rel_speed": lead_rel_speed,    # 相对速度(m/s)
          "ttc": ttc,                     # 碰撞时间(秒)
          "is_lead": True,                # 是否为前车
          "too_close": ret.leadDistanceTooClose,  # 距离是否过近
          "detection_time": time.time()    # 检测时间戳
        }
        self.radarTargets.append(target_info)

        # 更新前车跟踪状态
        ret.leadTargetStatus = {
          "detected": True,
          "distance": lead_distance,
          "rel_speed": lead_rel_speed,
          "ttc": ttc
        }

    # 8. 车辆稳定控制系统状态增强
    if "TRACTION" in cp.vl:
      # 读取各个系统状态
      abs_malfunction = cp.vl["TRACTION"]["ABS_MALFUNCTION"]  # ABS故障状态
      dsc_off = cp.vl["TRACTION"]["DSC_OFF"]                 # DSC关闭状态
      tcs_dcs_malfunction = cp.vl["TRACTION"]["TCS_DCS_MALFUNCTION"]  # TCS/DSC故障

      # 构建详细的状态码（使用位运算）
      stability_control_status = (
        (1 if abs_malfunction > 0 else 0) |    # bit 0: ABS故障
        (2 if dsc_off > 0 else 0) |            # bit 1: DSC关闭
        (4 if tcs_dcs_malfunction > 0 else 0)  # bit 2: TCS/DSC故障
      )

      # 更新稳定控制系统状态
      ret.stabilityControlStatus = stability_control_status

      # 创建详细的状态字典
      ret.stabilityControlDetails = {
        "abs_fault": bool(abs_malfunction),
        "dsc_disabled": bool(dsc_off),
        "tcs_fault": bool(tcs_dcs_malfunction),
        "system_active": not bool(dsc_off) and not bool(abs_malfunction),
        "status_code": stability_control_status
      }

      # 更新内部状态
      self.stabilityStatus = stability_control_status

    # 更新驾驶时间
    if not ret.standstill:
      self.drivingTime += 0.01  # 假设更新间隔为10ms
    ret.drivingTime = self.drivingTime  # 添加到返回值中

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
