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

    # 初始化CAN解析器
    try:
      can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
      self.shifter_values = can_define.dv["GEAR"]["GEAR"]
    except (KeyError, ValueError, AttributeError) as e:
      # 处理初始化失败的情况
      self.shifter_values = {}
      print(f"Warning: Failed to initialize shifter values: {e}")

    # 计数器和状态标志
    self.crz_btns_counter = 0
    self.acc_active_last = False
    self.low_speed_alert = False
    self.lkas_allowed_speed = False
    self.lkas_disabled = False
    self.lkas_enabled = True
    self.lkas_previously_enabled = True

    # 按钮状态
    self.prev_distance_button = 0
    self.distance_button = 0
    self.pcmCruiseGap = 0 # copy from Hyundai

    # 巡航控制相关变量
    self.cruise_buttons = Buttons.NONE
    self.prev_cruise_buttons = Buttons.NONE
    self.cruise_setting = False
    self.is_metric = True  # 默认使用公制单位

    # 存储摄像头和车身总线数据
    self.cam_lkas = {}
    self.cam_laneinfo = {}
    self.crz_info = {"ACCEL_CMD": 0}  # 初始化巡航信息

    # 巡航状态跟踪
    self.cruiseState_enabled = False
    self.cruiseState_available = False
    self.cruiseState_speed = 0

    # 记录最后一次状态更新的时间
    self.last_update_time = 0

  def update(self, can_parsers) -> structs.CarState:
    """更新车辆状态信息

    Args:
        can_parsers: CAN解析器列表 [pt_parser, cam_parser, body_parser]

    Returns:
        CarState: 更新后的车辆状态
    """
    # 创建新的CarState消息
    ret = structs.CarState()

    # 安全获取解析器
    cp = can_parsers[Bus.pt] if len(can_parsers) > Bus.pt else None
    cp_cam = can_parsers[Bus.cam] if len(can_parsers) > Bus.cam else None
    cp_body = can_parsers[2] if len(can_parsers) > 2 else None

    # 如果没有有效的解析器，返回默认状态
    if cp is None:
      self.lkas_disabled = True
      self.low_speed_alert = True
      return ret

    # 保存前一次的按钮状态
    self.prev_distance_button = self.distance_button
    self.prev_cruise_buttons = self.cruise_buttons

    try:
      # 获取距离按钮状态
      self.distance_button = cp.vl["CRZ_BTNS"]["DISTANCE_LESS"] if "DISTANCE_LESS" in cp.vl.get("CRZ_BTNS", {}) else 0

      # 检测巡航按钮状态
      crz_btns = cp.vl.get("CRZ_BTNS", {})
      if bool(crz_btns.get("SET_P", 0)):
        self.cruise_buttons = Buttons.SET_PLUS
      elif bool(crz_btns.get("SET_M", 0)):
        self.cruise_buttons = Buttons.SET_MINUS
      elif bool(crz_btns.get("RES", 0)):
        self.cruise_buttons = Buttons.RESUME
      elif bool(crz_btns.get("CANCEL", 0)):
        self.cruise_buttons = Buttons.CANCEL
      else:
        self.cruise_buttons = Buttons.NONE

      # 检测是否处于公制单位，如果字段存在则使用该值
      if "MPH_UNIT" in crz_btns:
        self.is_metric = not crz_btns["MPH_UNIT"]

      # 继承CRZ_BTNS计数器
      if "CTR" in crz_btns:
        self.crz_btns_counter = crz_btns["CTR"]
    except (KeyError, AttributeError) as e:
      # 处理异常，保持上一次的状态
      print(f"Warning: Error processing cruise buttons: {e}")

    try:
      # 车轮速度处理
      if "WHEEL_SPEEDS" in cp.vl:
        wheel_speeds = cp.vl["WHEEL_SPEEDS"]
        ret.wheelSpeeds = self.get_wheel_speeds(
          wheel_speeds.get("FL", 0),
          wheel_speeds.get("FR", 0),
          wheel_speeds.get("RL", 0),
          wheel_speeds.get("RR", 0),
        )
        ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
        ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

      # 速度和停车状态
      speed_kph = cp.vl["ENGINE_DATA"].get("SPEED", 0) if "ENGINE_DATA" in cp.vl else 0
      ret.standstill = speed_kph <= .1

      # 变速箱状态
      if "GEAR" in cp.vl:
        can_gear = int(cp.vl["GEAR"].get("GEAR", 0))
        ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
        ret.gearStep = cp.vl["GEAR"].get("GEAR_BOX", 0) if "GEAR_BOX" in cp.vl["GEAR"] else 0

      # 发动机转速
      if "ENGINE_DATA" in cp.vl and "RPM" in cp.vl["ENGINE_DATA"]:
        ret.engineRpm = cp.vl["ENGINE_DATA"]["RPM"]

      # 巡航距离设置
      if "CRZ_CTRL" in cp.vl and "DISTANCE_SETTING" in cp.vl["CRZ_CTRL"]:
        can_distance_setting = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]
        # 假设最大值为4，使用5减去CAN值来获取正确的显示值
        ret.pcmCruiseGap = 5 - can_distance_setting if 1 <= can_distance_setting <= 4 else can_distance_setting

      # 指示灯状态
      if "BLINK_INFO" in cp.vl:
        ret.genericToggle = bool(cp.vl["BLINK_INFO"].get("HIGH_BEAMS", 0))
        left_blink = cp.vl["BLINK_INFO"].get("LEFT_BLINK", 0) == 1
        right_blink = cp.vl["BLINK_INFO"].get("RIGHT_BLINK", 0) == 1
        ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40, left_blink, right_blink)

      # 盲点监测
      if "BSM" in cp.vl:
        ret.leftBlindspot = cp.vl["BSM"].get("LEFT_BS_STATUS", 0) != 0
        ret.rightBlindspot = cp.vl["BSM"].get("RIGHT_BS_STATUS", 0) != 0
      else:
        ret.leftBlindspot = False
        ret.rightBlindspot = False

      # 转向信息
      if all(k in cp.vl for k in ["STEER", "STEER_TORQUE", "STEER_RATE"]):
        ret.steeringAngleDeg = cp.vl["STEER"].get("STEER_ANGLE", 0)
        ret.steeringTorque = cp.vl["STEER_TORQUE"].get("STEER_TORQUE_SENSOR", 0)
        ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD
        ret.steeringTorqueEps = cp.vl["STEER_TORQUE"].get("STEER_TORQUE_MOTOR", 0)
        ret.steeringRateDeg = cp.vl["STEER_RATE"].get("STEER_ANGLE_RATE", 0)

      # 刹车状态
      if "PEDALS" in cp.vl:
        ret.brakePressed = cp.vl["PEDALS"].get("BRAKE_ON", 0) == 1
      if "BRAKE" in cp.vl:
        ret.brake = cp.vl["BRAKE"].get("BRAKE_PRESSURE", 0)

      # 安全带和车门状态
      if "SEATBELT" in cp.vl:
        ret.seatbeltUnlatched = cp.vl["SEATBELT"].get("DRIVER_SEATBELT", 1) == 0

      if "DOORS" in cp.vl:
        doors = cp.vl["DOORS"]
        ret.doorOpen = any([
          doors.get("FL", 0),
          doors.get("FR", 0),
          doors.get("BL", 0),
          doors.get("BR", 0)
        ])
      else:
        ret.doorOpen = False

      # 油门状态
      if "ENGINE_DATA" in cp.vl:
        ret.gas = cp.vl["ENGINE_DATA"].get("PEDAL_GAS", 0)
        ret.gasPressed = ret.gas > 0

      # LKAS状态检测
      lkas_blocked = cp.vl["STEER_RATE"].get("LKAS_BLOCK", 0) == 1 if "LKAS_BLOCK" in cp.vl.get("STEER_RATE", {}) else False

      # 处理LKAS启用/禁用逻辑
      if self.CP.minSteerSpeed > 0:
        # LKAS is enabled at 52kph going up and disabled at 45kph going down
        # If the car is going below 45kph, wait for the LKAS_BLOCK signal before disabling
        # to avoid disabling LKAS during a turn where the speed momentarily drops below 45kph...
        self.lkas_allowed_speed = ret.vEgo > (LKAS_LIMITS.ENABLE_SPEED * CV.KPH_TO_MS)
        if self.lkas_allowed_speed:
          self.lkas_disabled = False
        elif lkas_blocked:
          self.lkas_disabled = True
        # ...however, if the car is going below 40kph, disabling LKAS is correct behavior
        elif ret.vEgo < (LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS):
          self.lkas_disabled = True
      else:
        # If the car doesn't have a minimum steer speed, use the LKAS_BLOCK signal
        self.lkas_disabled = lkas_blocked
        self.lkas_allowed_speed = True

      # 更新低速警告状态
      if self.lkas_disabled:
        self.low_speed_alert = True
      else:
        self.low_speed_alert = False

      # 处理巡航控制状态
      # 安全获取巡航控制信息
      crz_ctrl = cp.vl.get("CRZ_CTRL", {})

      # 处理巡航控制状态 - 确保字段存在
      self.cruise_setting = False
      if "CRZ_ACTIVE" in crz_ctrl:
        self.cruise_setting = crz_ctrl["CRZ_ACTIVE"] == 1
      if "RESUME_READY" in crz_ctrl:
        self.cruise_setting = self.cruise_setting or crz_ctrl["RESUME_READY"] == 1

      # Check for Cruise active / available
      ret.cruiseState.available = False
      if "CRZ_READY" in crz_ctrl:
        ret.cruiseState.available = self.cruise_setting or crz_ctrl["CRZ_READY"] == 1

      ret.cruiseState.enabled = False
      if "CRZ_ACTIVE" in crz_ctrl:
        ret.cruiseState.enabled = crz_ctrl["CRZ_ACTIVE"] == 1

      ret.cruiseState.speed = 0
      if "CRUISE_SPEED" in crz_ctrl:
        ret.cruiseState.speed = crz_ctrl["CRUISE_SPEED"] * CV.KPH_TO_MS

      ret.cruiseState.nonAdaptive = False  # Mazda的巡航系统是自适应的
      ret.cruiseState.standstill = ret.standstill and ret.cruiseState.enabled

      # 更新巡航状态参数 - 确保字段存在
      if "CRUISE_SPEED" in crz_ctrl:
        ret.cruiseState.speedCluster = crz_ctrl["CRUISE_SPEED"] * CV.KPH_TO_MS

      if "DISTANCE_SETTING" in crz_ctrl:
        ret.cruiseGap = crz_ctrl["DISTANCE_SETTING"]

      # 存储前一次巡航状态用于比较
      self.cruiseState_enabled = ret.cruiseState.enabled
      self.cruiseState_available = ret.cruiseState.available
      self.cruiseState_speed = ret.cruiseState.speed

      # 通过按钮事件控制巡航功能
      ret.buttonEvents = []

      # 只有当按钮状态变化时才添加按钮事件
      if self.cruise_buttons != self.prev_cruise_buttons:
        be = structs.CarState.ButtonEvent.new_message()
        be.type = BUTTONS_DICT.get(self.cruise_buttons, ButtonType.unknown)
        ret.buttonEvents.append(be)

      # 保存摄像头相关信息，用于发送HUD警告
      if cp_cam is not None:
        if "CAM_LKAS" in cp_cam.vl:
          self.cam_lkas = cp_cam.vl["CAM_LKAS"]
        if "CAM_LANEINFO" in cp_cam.vl:
          self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]

        # 更新LKAS启用状态
        self.lkas_previously_enabled = self.lkas_enabled
        if "LANE_LINES" in cp_cam.vl.get("CAM_LANEINFO", {}):
          self.lkas_enabled = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] != 0
        else:
          self.lkas_enabled = not self.lkas_disabled

      # 保存车身总线数据（如果存在）
      if cp_body is not None:
        # 处理车身总线数据，如果有的话
        pass

    except Exception as e:
      # 捕获所有异常，确保不会导致系统崩溃
      print(f"Warning: Exception in CarState.update: {e}")
      # 设置错误状态
      self.lkas_disabled = True
      self.low_speed_alert = True

    return ret

  @staticmethod
  def get_can_parsers(CP):
    """获取CAN总线解析器

    Args:
        CP: 车辆参数

    Returns:
        list: 包含三个CAN解析器的列表 [pt_parser, cam_parser, body_parser]
    """
    signals = [
      # sig_name, sig_address
      ("LEFT_BLINK", "BLINK_INFO"),
      ("RIGHT_BLINK", "BLINK_INFO"),
      ("HIGH_BEAMS", "BLINK_INFO"),
      ("STEER_ANGLE", "STEER"),
      ("STEER_ANGLE_RATE", "STEER_RATE"),
      ("LKAS_BLOCK", "STEER_RATE"),
      ("STEER_TORQUE_SENSOR", "STEER_TORQUE"),
      ("STEER_TORQUE_MOTOR", "STEER_TORQUE"),
      ("FL", "WHEEL_SPEEDS"),
      ("FR", "WHEEL_SPEEDS"),
      ("RL", "WHEEL_SPEEDS"),
      ("RR", "WHEEL_SPEEDS"),
      ("BRAKE_ON", "PEDALS"),
      ("GEAR", "GEAR"),
      ("GEAR_BOX", "GEAR"),
      ("SPEED", "ENGINE_DATA"),
      ("PEDAL_GAS", "ENGINE_DATA"),
      ("RPM", "ENGINE_DATA"),
      ("DRIVER_SEATBELT", "SEATBELT"),
      ("FL", "DOORS"),
      ("FR", "DOORS"),
      ("BL", "DOORS"),
      ("BR", "DOORS"),
      ("BRAKE_PRESSURE", "BRAKE"),
      # Cruise state
      ("CRZ_ACTIVE", "CRZ_CTRL"),
      ("CRZ_READY", "CRZ_CTRL"),
      ("CRUISE_SPEED", "CRZ_CTRL"),
      ("RESUME_READY", "CRZ_CTRL"),
      ("SET_ALLOW", "CRZ_CTRL"),
      ("ACC_ACTIVE", "CRZ_CTRL"),
      ("DISTANCE_SETTING", "CRZ_CTRL"),
      # BSM
      ("LEFT_BS_STATUS", "BSM"),
      ("RIGHT_BS_STATUS", "BSM"),
      # Cruise buttons
      ("SET_P", "CRZ_BTNS"),
      ("SET_M", "CRZ_BTNS"),
      ("RES", "CRZ_BTNS"),
      ("CANCEL", "CRZ_BTNS"),
      ("DISTANCE_LESS", "CRZ_BTNS"),
      ("MPH_UNIT", "CRZ_BTNS"),  # 是否使用MPH单位
      ("CTR", "CRZ_BTNS"),       # 按钮计数器
    ]

    checks = [
      # sig_address, frequency
      ("BLINK_INFO", 10),
      ("STEER", 80),
      ("STEER_RATE", 80),
      ("STEER_TORQUE", 80),
      ("WHEEL_SPEEDS", 80),
      ("PEDALS", 80),
      ("GEAR", 40),
      ("ENGINE_DATA", 100),
      ("SEATBELT", 10),
      ("DOORS", 10),
      ("BRAKE", 50),
      ("CRZ_CTRL", 50),
      ("BSM", 10),
      ("CRZ_BTNS", 10),
    ]

    # Camera measurements are at 60Hz
    cam_signals = [
      # sig_name, sig_address
      ("BIT_1", "CAM_LKAS"),
      ("ERR_BIT_1", "CAM_LKAS"),
      ("LINE_NOT_VISIBLE", "CAM_LKAS"),
      ("LDW", "CAM_LKAS"),
      ("ERR_BIT_2", "CAM_LKAS"),
      # Lane info
      ("LINE_VISIBLE", "CAM_LANEINFO"),
      ("LINE_NOT_VISIBLE", "CAM_LANEINFO"),
      ("LANE_LINES", "CAM_LANEINFO"),
      ("BIT1", "CAM_LANEINFO"),
      ("BIT2", "CAM_LANEINFO"),
      ("BIT3", "CAM_LANEINFO"),
      ("NO_ERR_BIT", "CAM_LANEINFO"),
      ("S1", "CAM_LANEINFO"),
      ("S1_HBEAM", "CAM_LANEINFO"),
      ("HANDS_WARN_3_BITS", "CAM_LANEINFO"),
      ("HANDS_ON_STEER_WARN", "CAM_LANEINFO"),
      ("HANDS_ON_STEER_WARN_2", "CAM_LANEINFO"),
      ("LDW_WARN_LL", "CAM_LANEINFO"),
      ("LDW_WARN_RL", "CAM_LANEINFO"),
    ]

    cam_checks = [
      # sig_address, frequency
      ("CAM_LKAS", 16),
      ("CAM_LANEINFO", 2),
    ]

    try:
      # 创建并返回解析器
      return [
        # pt = powertrain bus
        CANParser(DBC[CP.carFingerprint][Bus.pt], signals, checks, Bus.pt),
        # cam = camera bus
        CANParser(DBC[CP.carFingerprint][Bus.pt], cam_signals, cam_checks, Bus.cam),
        # body = radar bus - 暂时没有实现
        None,
      ]
    except Exception as e:
      # 处理解析器创建失败的情况
      print(f"Error creating CAN parsers: {e}")
      # 返回None或默认解析器
      return [None, None, None]
