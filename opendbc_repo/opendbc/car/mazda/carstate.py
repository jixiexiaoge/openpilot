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

    # 错误计数器，用于限制错误日志频率
    self.error_count = 0
    self.last_error_time = 0

  def update(self, can_parsers) -> structs.CarState:
    """更新车辆状态信息

    Args:
        can_parsers: CAN解析器列表 [pt_parser, cam_parser, body_parser]

    Returns:
        CarState: 更新后的车辆状态
    """
    current_time = time.time()

    # 创建新的CarState消息
    ret = structs.CarState()

    # 安全获取解析器
    cp = None
    cp_cam = None
    cp_body = None

    try:
      cp = can_parsers[Bus.pt] if len(can_parsers) > Bus.pt else None
      cp_cam = can_parsers[Bus.cam] if len(can_parsers) > Bus.cam else None
      cp_body = can_parsers[2] if len(can_parsers) > 2 else None
    except (IndexError, TypeError) as e:
      self._log_error(f"Error accessing CAN parsers: {e}")
      # 如果无法访问解析器，设置默认状态
      self.lkas_disabled = True
      self.low_speed_alert = True
      return ret

    # 如果没有有效的解析器，返回默认状态
    if cp is None:
      self.lkas_disabled = True
      self.low_speed_alert = True
      return ret

    # 保存前一次的按钮状态
    self.prev_distance_button = self.distance_button
    self.prev_cruise_buttons = self.cruise_buttons

    # === 1. 处理巡航控制按钮 ===
    self._update_cruise_buttons(cp, ret)

    # === 2. 处理车辆基本状态（速度、齿轮等）===
    self._update_vehicle_status(cp, ret)

    # === 3. 处理LKAS状态 ===
    self._update_lkas_status(cp, ret)

    # === 4. 处理巡航控制状态 ===
    self._update_cruise_state(cp, ret)

    # === 5. 处理按钮事件 ===
    self._update_button_events(ret)

    # === 6. 处理摄像头数据 ===
    self._update_camera_data(cp_cam, ret)

    # === 7. 处理车身总线数据 ===
    if cp_body is not None:
      # 处理车身总线数据，如果有的话
      pass

    # 更新最后一次状态更新的时间
    self.last_update_time = current_time

    return ret

  def _update_cruise_buttons(self, cp, ret):
    """更新巡航控制按钮状态

    Args:
        cp: CAN解析器
        ret: 车辆状态对象
    """
    try:
      # 获取距离按钮状态 - 安全检查
      if "CRZ_BTNS" in cp.vl:
        crz_btns = cp.vl["CRZ_BTNS"]
        self.distance_button = crz_btns.get("DISTANCE_LESS", 0)

        # 检测巡航按钮状态 - 使用get方法避免KeyError
        if bool(crz_btns.get("SET_P", 0)):
          self.cruise_buttons = Buttons.SET_PLUS
        elif bool(crz_btns.get("SET_M", 0)):
          self.cruise_buttons = Buttons.SET_MINUS
        elif bool(crz_btns.get("RES", 0)):
          self.cruise_buttons = Buttons.RESUME
        elif bool(crz_btns.get("CAN_OFF", 0)):
          self.cruise_buttons = Buttons.CANCEL
        else:
          self.cruise_buttons = Buttons.NONE

        # 检测是否处于公制单位
        if "MPH_UNIT" in crz_btns:
          self.is_metric = not crz_btns["MPH_UNIT"]

        # 继承CRZ_BTNS计数器
        if "CTR" in crz_btns:
          self.crz_btns_counter = crz_btns["CTR"]
      else:
        # 如果消息不存在，保持上一次的状态
        pass
    except (KeyError, AttributeError) as e:
      self._log_error(f"Error processing cruise buttons: {e}")
      # 保持上一次的状态

  def _update_vehicle_status(self, cp, ret):
    """更新车辆基本状态

    Args:
        cp: CAN解析器
        ret: 车辆状态对象
    """
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
        # 计算车辆速度
        ret.vEgoRaw = max(0.0, (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.)
        ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
      else:
        # 如果没有轮速数据，使用ENGINE_DATA中的速度
        speed_kph = cp.vl["ENGINE_DATA"].get("SPEED", 0) if "ENGINE_DATA" in cp.vl else 0
        ret.vEgoRaw = speed_kph * CV.KPH_TO_MS
        ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

      # 速度和停车状态
      speed_kph = cp.vl["ENGINE_DATA"].get("SPEED", 0) if "ENGINE_DATA" in cp.vl else 0
      # 增加边界检查，确保速度非负
      speed_kph = max(0.0, speed_kph)
      ret.standstill = speed_kph <= 0.1

      # 变速箱状态
      if "GEAR" in cp.vl:
        gear_msg = cp.vl["GEAR"]
        can_gear = int(gear_msg.get("GEAR", 0))
        # 安全解析齿轮状态
        shifter_value = self.shifter_values.get(can_gear, None)
        ret.gearShifter = self.parse_gear_shifter(shifter_value)
        ret.gearStep = gear_msg.get("GEAR_BOX", 0) if "GEAR_BOX" in gear_msg else 0

      # 发动机转速
      if "ENGINE_DATA" in cp.vl and "RPM" in cp.vl["ENGINE_DATA"]:
        ret.engineRpm = max(0, cp.vl["ENGINE_DATA"]["RPM"])  # 确保RPM非负

      # 巡航距离设置
      if "CRZ_CTRL" in cp.vl and "DISTANCE_SETTING" in cp.vl["CRZ_CTRL"]:
        can_distance_setting = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]
        # 范围检查并转换
        if 1 <= can_distance_setting <= 4:
          ret.pcmCruiseGap = 5 - can_distance_setting  # 5减去CAN值获取正确显示值
        else:
          ret.pcmCruiseGap = can_distance_setting

      # 指示灯状态
      if "BLINK_INFO" in cp.vl:
        blink_info = cp.vl["BLINK_INFO"]
        ret.genericToggle = bool(blink_info.get("HIGH_BEAMS", 0))
        left_blink = blink_info.get("LEFT_BLINK", 0) == 1
        right_blink = blink_info.get("RIGHT_BLINK", 0) == 1
        # 使用内置方法更新转向灯状态
        ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40, left_blink, right_blink)

      # 盲点监测
      if "BSM" in cp.vl:
        bsm = cp.vl["BSM"]
        ret.leftBlindspot = bsm.get("LEFT_BS_STATUS", 0) != 0
        ret.rightBlindspot = bsm.get("RIGHT_BS_STATUS", 0) != 0
      else:
        ret.leftBlindspot = False
        ret.rightBlindspot = False

      # 转向信息 - 检查所有必要的消息是否存在
      steer_msgs_available = all(k in cp.vl for k in ["STEER", "STEER_TORQUE", "STEER_RATE"])
      if steer_msgs_available:
        ret.steeringAngleDeg = cp.vl["STEER"].get("STEER_ANGLE", 0)
        ret.steeringTorque = cp.vl["STEER_TORQUE"].get("STEER_TORQUE_SENSOR", 0)
        ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD
        ret.steeringTorqueEps = cp.vl["STEER_TORQUE"].get("STEER_TORQUE_MOTOR", 0)
        ret.steeringRateDeg = cp.vl["STEER_RATE"].get("STEER_ANGLE_RATE", 0)

      # 刹车状态 - 使用适当的消息获取刹车状态
      ret.brakePressed = False  # 默认为False
      if "PEDALS" in cp.vl:
        ret.brakePressed = cp.vl["PEDALS"].get("BRAKE_ON", 0) == 1
      if "BRAKE" in cp.vl:
        ret.brake = max(0.0, cp.vl["BRAKE"].get("BRAKE_PRESSURE", 0))  # 确保刹车压力非负
      else:
        ret.brake = 0.0

      # 安全带和车门状态
      if "SEATBELT" in cp.vl:
        ret.seatbeltUnlatched = cp.vl["SEATBELT"].get("DRIVER_SEATBELT", 1) == 0

      # 车门状态 - 使用get方法安全获取
      if "DOORS" in cp.vl:
        doors = cp.vl["DOORS"]
        ret.doorOpen = any([
          doors.get("FL", 0) == 1,
          doors.get("FR", 0) == 1,
          doors.get("BL", 0) == 1,
          doors.get("BR", 0) == 1
        ])
      else:
        ret.doorOpen = False

      # 油门状态
      if "ENGINE_DATA" in cp.vl:
        engine_data = cp.vl["ENGINE_DATA"]
        ret.gas = max(0.0, engine_data.get("PEDAL_GAS", 0))  # 确保油门值非负
        ret.gasPressed = ret.gas > 0

    except Exception as e:
      self._log_error(f"Error updating vehicle status: {e}")
      # 在出错情况下设置安全值
      ret.vEgo = 0.0
      ret.standstill = True
      ret.brakePressed = False
      ret.gasPressed = False

  def _update_lkas_status(self, cp, ret):
    """更新LKAS状态

    Args:
        cp: CAN解析器
        ret: 车辆状态对象
    """
    try:
      # 安全获取LKAS阻塞状态
      lkas_blocked = False
      if "STEER_RATE" in cp.vl:
        steer_rate = cp.vl["STEER_RATE"]
        lkas_blocked = steer_rate.get("LKAS_BLOCK", 0) == 1

      # 处理LKAS启用/禁用逻辑
      if self.CP.minSteerSpeed > 0:
        # LKAS根据车速启用/禁用：52kph以上启用，45kph以下禁用
        self.lkas_allowed_speed = ret.vEgo > (LKAS_LIMITS.ENABLE_SPEED * CV.KPH_TO_MS)

        if self.lkas_allowed_speed:
          # 速度足够高，允许LKAS
          self.lkas_disabled = False
        elif lkas_blocked:
          # 检测到LKAS阻塞信号，禁用LKAS
          self.lkas_disabled = True
        elif ret.vEgo < (LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS):
          # 速度低于阈值，禁用LKAS
          self.lkas_disabled = True
      else:
        # 没有最低转向速度限制，使用LKAS_BLOCK信号
        self.lkas_disabled = lkas_blocked
        self.lkas_allowed_speed = True

      # 更新低速警告状态
      self.low_speed_alert = self.lkas_disabled

    except Exception as e:
      self._log_error(f"Error updating LKAS status: {e}")
      # 在出错情况下禁用LKAS
      self.lkas_disabled = True
      self.low_speed_alert = True

  def _update_cruise_state(self, cp, ret):
    """更新巡航控制状态

    Args:
        cp: CAN解析器
        ret: 车辆状态对象
    """
    try:
      # 安全获取巡航控制消息
      crz_ctrl = cp.vl.get("CRZ_CTRL", {})

      # 处理巡航控制激活状态
      self.cruise_setting = False
      if "CRZ_ACTIVE" in crz_ctrl:
        self.cruise_setting = crz_ctrl["CRZ_ACTIVE"] == 1
      if "RESUME_READY" in crz_ctrl:
        self.cruise_setting = self.cruise_setting or crz_ctrl["RESUME_READY"] == 1

      # 检查巡航是否可用
      ret.cruiseState.available = False
      if "CRZ_READY" in crz_ctrl:
        ret.cruiseState.available = self.cruise_setting or crz_ctrl["CRZ_READY"] == 1

      # 检查巡航是否启用
      ret.cruiseState.enabled = False
      if "CRZ_ACTIVE" in crz_ctrl:
        ret.cruiseState.enabled = crz_ctrl["CRZ_ACTIVE"] == 1

      # 获取巡航设定速度
      ret.cruiseState.speed = 0.0
      if "CRUISE_SPEED" in crz_ctrl:
        cruise_speed_kph = max(0.0, crz_ctrl["CRUISE_SPEED"])  # 确保速度非负
        ret.cruiseState.speed = cruise_speed_kph * CV.KPH_TO_MS

      # 设置其他巡航状态
      ret.cruiseState.nonAdaptive = False  # Mazda的巡航系统是自适应的
      ret.cruiseState.standstill = ret.standstill and ret.cruiseState.enabled

      # 更新显示的巡航速度
      if "CRUISE_SPEED" in crz_ctrl:
        cruise_speed_kph = max(0.0, crz_ctrl["CRUISE_SPEED"])  # 确保速度非负
        ret.cruiseState.speedCluster = cruise_speed_kph * CV.KPH_TO_MS

      # 更新巡航距离设置
      if "DISTANCE_SETTING" in crz_ctrl:
        # 确保数值在有效范围内
        distance_setting = crz_ctrl["DISTANCE_SETTING"]
        if 1 <= distance_setting <= 4:
          ret.cruiseGap = distance_setting
        else:
          ret.cruiseGap = 2  # 默认为中等距离

      # 存储状态用于比较
      self.cruiseState_enabled = ret.cruiseState.enabled
      self.cruiseState_available = ret.cruiseState.available
      self.cruiseState_speed = ret.cruiseState.speed

    except Exception as e:
      self._log_error(f"Error updating cruise state: {e}")
      # 在出错情况下设置安全默认值
      ret.cruiseState.available = False
      ret.cruiseState.enabled = False
      ret.cruiseState.speed = 0.0
      ret.cruiseState.speedCluster = 0.0

  def _update_button_events(self, ret):
    """更新按钮事件

    Args:
        ret: 车辆状态对象
    """
    try:
      # 初始化按钮事件列表
      ret.buttonEvents = []

      # 只有当按钮状态变化时才添加按钮事件
      if self.cruise_buttons != self.prev_cruise_buttons:
        be = structs.CarState.ButtonEvent.new_message()
        # 安全获取按钮类型，默认为unknown
        be.type = BUTTONS_DICT.get(self.cruise_buttons, ButtonType.unknown)
        ret.buttonEvents.append(be)

    except Exception as e:
      self._log_error(f"Error updating button events: {e}")
      # 在出错情况下返回空按钮列表
      ret.buttonEvents = []

  def _update_camera_data(self, cp_cam, ret):
    """更新摄像头数据

    Args:
        cp_cam: 摄像头CAN解析器
        ret: 车辆状态对象
    """
    try:
      # 只有当摄像头解析器可用时才处理
      if cp_cam is not None:
        # 安全获取摄像头LKAS消息
        if "CAM_LKAS" in cp_cam.vl:
          self.cam_lkas = cp_cam.vl["CAM_LKAS"]

        # 安全获取车道信息消息
        if "CAM_LANEINFO" in cp_cam.vl:
          self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]

        # 更新LKAS启用状态
        self.lkas_previously_enabled = self.lkas_enabled

        # 通过车道线数量判断LKAS是否启用
        if "CAM_LANEINFO" in cp_cam.vl and "LANE_LINES" in cp_cam.vl["CAM_LANEINFO"]:
          self.lkas_enabled = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] != 0
        else:
          # 如果没有车道线信息，使用LKAS禁用状态作为反向指示
          self.lkas_enabled = not self.lkas_disabled

    except Exception as e:
      self._log_error(f"Error updating camera data: {e}")
      # 在出错情况下保持上一次的状态

  def _log_error(self, error_msg):
    """限制错误日志频率的辅助函数

    Args:
        error_msg: 错误消息
    """
    current_time = time.time()
    # 每10秒最多记录一次相同类型的错误
    if current_time - self.last_error_time > 10:
      print(f"Mazda CarState Error: {error_msg}")
      self.last_error_time = current_time
      self.error_count = 1
    else:
      self.error_count += 1
      # 每累积10个错误打印一次摘要
      if self.error_count % 10 == 0:
        print(f"Mazda CarState: {self.error_count} errors occurred in the last 10 seconds")

  @staticmethod
  def get_can_parsers(CP):
    """获取CAN总线解析器

    Args:
        CP: 车辆参数

    Returns:
        tuple: (pt_parser, cam_parser, body_parser)
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
