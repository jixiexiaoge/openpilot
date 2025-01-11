from cereal import car, custom
from openpilot.common.conversions import Conversions as CV
from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from openpilot.selfdrive.car.interfaces import CarStateBase
from openpilot.selfdrive.car.mazda.values import DBC, LKAS_LIMITS, MazdaFlags, Buttons

class CarState(CarStateBase):
  """马自达车辆状态类"""
  def __init__(self, CP):
    """初始化车辆状态"""
    super().__init__(CP)

    # 初始化CAN定义和变速器值
    can_define = CANDefine(DBC[CP.carFingerprint]["pt"])
    self.shifter_values = can_define.dv["GEAR"]["GEAR"]

    # 初始化各种状态变量
    self.crz_btns_counter = 0  # 巡航按钮计数器
    self.acc_active_last = False  # 上一次ACC激活状态
    self.low_speed_alert = False  # 低速警告标志
    self.lkas_allowed_speed = False  # LKAS允许速度标志
    self.lkas_disabled = False  # LKAS禁用标志

    # 初始化距离按钮状态
    self.prev_distance_button = 0  # 上一次距离按钮状态
    self.distance_button = 0  # 当前距离按钮状态

  def update(self, cp, cp_cam, frogpilot_variables):
    """更新车辆状态"""
    # 创建新的车辆状态消息
    ret = car.CarState.new_message()
    fp_ret = custom.FrogPilotCarState.new_message()

    # 更新距离按钮状态
    self.prev_distance_button = self.distance_button
    self.distance_button = cp.vl["CRZ_BTNS"]["DISTANCE_LESS"]

    # 保存上一次巡航按钮状态
    self.prev_cruise_buttons = self.cruise_buttons

    # 根据按钮状态更新巡航控制按钮
    if bool(cp.vl["CRZ_BTNS"]["SET_P"]):
      self.cruise_buttons = Buttons.SET_PLUS  # 设置增加
    elif bool(cp.vl["CRZ_BTNS"]["SET_M"]):
      self.cruise_buttons = Buttons.SET_MINUS  # 设置减少
    elif bool(cp.vl["CRZ_BTNS"]["RES"]):
      self.cruise_buttons = Buttons.RESUME  # 恢复
    else:
      self.cruise_buttons = Buttons.NONE  # 无按钮

    # 获取车轮速度
    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["WHEEL_SPEEDS"]["FL"],  # 左前轮速度
      cp.vl["WHEEL_SPEEDS"]["FR"],  # 右前轮速度
      cp.vl["WHEEL_SPEEDS"]["RL"],  # 左后轮速度
      cp.vl["WHEEL_SPEEDS"]["RR"],  # 右后轮速度
    )
    # 计算车辆速度
    ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

    # 匹配熊猫速度读数
    speed_kph = cp.vl["ENGINE_DATA"]["SPEED"]
    ret.standstill = speed_kph <= .1  # 判断车辆是否静止

    # 获取变速器状态
    can_gear = int(cp.vl["GEAR"]["GEAR"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # 更新车辆状态
    ret.genericToggle = bool(cp.vl["BLINK_INFO"]["HIGH_BEAMS"])  # 远光灯状态
    ret.leftBlindspot = cp.vl["BSM"]["LEFT_BS_STATUS"] != 0  # 左侧盲点状态
    ret.rightBlindspot = cp.vl["BSM"]["RIGHT_BS_STATUS"] != 0  # 右侧盲点状态
    # 更新转向灯状态
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40,
                                                                      cp.vl["BLINK_INFO"]["LEFT_BLINK"] == 1,
                                                                      cp.vl["BLINK_INFO"]["RIGHT_BLINK"] == 1)

    # 更新转向相关状态
    ret.steeringAngleDeg = cp.vl["STEER"]["STEER_ANGLE"]  # 方向盘角度
    ret.steeringTorque = cp.vl["STEER_TORQUE"]["STEER_TORQUE_SENSOR"]  # 方向盘扭矩
    ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD  # 判断是否有转向操作

    ret.steeringTorqueEps = cp.vl["STEER_TORQUE"]["STEER_TORQUE_MOTOR"]  # 电动助力转向扭矩
    ret.steeringRateDeg = cp.vl["STEER_RATE"]["STEER_ANGLE_RATE"]  # 转向角速度

    # TODO: 这应该是0-1之间的值
    ret.brakePressed = cp.vl["PEDALS"]["BRAKE_ON"] == 1  # 刹车踏板状态
    ret.brake = cp.vl["BRAKE"]["BRAKE_PRESSURE"]  # 刹车压力

    # 安全带和车门状态
    ret.seatbeltUnlatched = cp.vl["SEATBELT"]["DRIVER_SEATBELT"] == 0  # 驾驶员安全带状态
    ret.doorOpen = any([cp.vl["DOORS"]["FL"], cp.vl["DOORS"]["FR"],
                       cp.vl["DOORS"]["BL"], cp.vl["DOORS"]["BR"]])  # 车门开启状态

    # TODO: 这应该是0-1之间的值
    ret.gas = cp.vl["ENGINE_DATA"]["PEDAL_GAS"]  # 油门踏板位置
    ret.gasPressed = ret.gas > 0  # 判断是否踩油门

    # 由于低速或手离开方向盘导致的LKAS阻塞
    lkas_blocked = cp.vl["STEER_RATE"]["LKAS_BLOCK"] == 1

    # 处理LKAS速度限制
    if self.CP.minSteerSpeed > 0:
      # LKAS在速度上升到52kph时启用，在速度下降到45kph时禁用
      # 上升时等待LKAS_BLOCK信号清除，因为它有时会滞后于速度
      if speed_kph > LKAS_LIMITS.ENABLE_SPEED and not lkas_blocked:
        self.lkas_allowed_speed = True
      elif speed_kph < LKAS_LIMITS.DISABLE_SPEED:
        self.lkas_allowed_speed = False
    else:
      self.lkas_allowed_speed = True

    # TODO: 用于available的信号似乎是自适应巡航信号，而不是主开关
    #       它应该用于carState.cruiseState.nonAdaptive
    # 更新巡航控制状态
    ret.cruiseState.available = cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"] == 1  # 巡航可用
    ret.cruiseState.enabled = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1  # 巡航启用
    ret.cruiseState.standstill = cp.vl["PEDALS"]["STANDSTILL"] == 1  # 车辆静止
    ret.cruiseState.speed = cp.vl["CRZ_EVENTS"]["CRZ_SPEED"] * CV.KPH_TO_MS  # 巡航速度

    # 处理低速警告
    if ret.cruiseState.enabled:
      if not self.lkas_allowed_speed and self.acc_active_last:
        self.low_speed_alert = True
      else:
        self.low_speed_alert = False

    # 检查LKAS是否由于缺乏驾驶员扭矩而被禁用
    # 只有在LKAS首次激活并再次失去后才发出警告
    ret.steerFaultTemporary = self.lkas_allowed_speed and lkas_blocked

    self.acc_active_last = ret.cruiseState.enabled

    self.crz_btns_counter = cp.vl["CRZ_BTNS"]["CTR"]

    # 相机信号
    self.lkas_disabled = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0  # LKAS禁用状态
    self.cam_lkas = cp_cam.vl["CAM_LKAS"]  # LKAS相机数据
    self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]  # 车道信息
    ret.steerFaultPermanent = cp_cam.vl["CAM_LKAS"]["ERR_BIT_1"] == 1  # 永久性转向故障

    # FrogPilot车辆状态函数
    self.lkas_previously_enabled = self.lkas_enabled  # 更新上一次LKAS状态
    self.lkas_enabled = not self.lkas_disabled  # 更新当前LKAS状态

    return ret, fp_ret

  @staticmethod
  def get_can_parser(CP):
    """获取CAN解析器配置"""
    # 定义需要解析的CAN消息
    messages = [
      # sig_address, frequency
      ("BLINK_INFO", 10),  # 转向灯信息
      ("STEER", 67),  # 转向信息
      ("STEER_RATE", 83),  # 转向速率
      ("STEER_TORQUE", 83),  # 转向扭矩
      ("WHEEL_SPEEDS", 100),  # 车轮速度
    ]

    # 对于第一代车型添加额外的消息
    if CP.flags & MazdaFlags.GEN1:
      messages += [
        ("ENGINE_DATA", 100),  # 发动机数据
        ("CRZ_CTRL", 50),  # 巡航控制
        ("CRZ_EVENTS", 50),  # 巡航事件
        ("CRZ_BTNS", 10),  # 巡航按钮
        ("PEDALS", 50),  # 踏板状态
        ("BRAKE", 50),  # 制动状态
        ("SEATBELT", 10),  # 安全带状态
        ("DOORS", 10),  # 车门状态
        ("GEAR", 20),  # 变速器状态
        ("BSM", 10),  # 盲点监测
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, 0)

  @staticmethod
  def get_cam_can_parser(CP):
    """获取相机CAN解析器配置"""
    messages = []

    # 对于第一代车型添加相机相关消息
    if CP.flags & MazdaFlags.GEN1:
      messages += [
        # sig_address, frequency
        ("CAM_LANEINFO", 2),  # 相机车道信息
        ("CAM_LKAS", 16),  # 相机LKAS信息
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, 2)
