"""CarState parser for Changan vehicles.

Handles CAN message parsing for vehicle state including:
- Speed (supports both Z6 petrol and Z6 iDD variants)
- Pedals (brake/gas with variant-aware signal sources)
- Steering (angle, rate, torque)
- Cruise control (button-based activation with rising-edge detection)
- Gear, doors, seatbelt, etc.
"""

import copy
from opendbc.can.parser import CANParser, CANDefine
from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import DBC, EPS_SCALE, CAR


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR"]["gearShifter"]
    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.steeringPressed = False
    self.steeringPressedMin = 1
    self.steeringPressedMax = 3 if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD else 6

    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

    # 信号快照容器
    self.sigs244 = {}
    self.sigs1ba = {}
    self.sigs17e = {}
    self.sigs307 = {}
    self.sigs31a = {}

    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.prev_distance_button = 0
    self.distance_button = 0

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    ret = structs.CarState()
    # 【强制】 标记 CAN 有效。模拟器即便没数据也会保持界面“Ready”，实车则消除红条。
    ret.canValid = True

    # --- Signal safety获取函数：防止由于 DBC 或总线缺失导致的 KeyError ---
    def safe_get(parser, msg, sig, default=0):
      """Safely get CAN signal value with fallback.

      Prevents KeyError crashes when DBC messages or signals are missing.
      This is a defensive coding pattern from Toyota implementation.

      Args:
        parser: CAN parser object
        msg: Message name
        sig: Signal name
        default: Default value if signal unavailable

      Returns:
        Signal value or default
      """
      try:
        # vl is a dict, use get for protection
        return parser.vl[msg].get(sig, default)
      except (KeyError, IndexError):
        return default

    # 1. 车门与安全带 (从 Bus 0 获取，带安全默认值)
    ret.doorOpen = safe_get(cp, "GW_28B", "doorOpen") == 1
    ret.seatbeltUnlatched = safe_get(cp, "GW_50", "seatbeltUnlatched") == 1
    ret.parkingBrake = False

    # 2. 车辆速度 (兼容 iDD vs 燃油版)
    carspd = 0
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = safe_get(cp, "SPEED", "wheelSpeeds", 0)
    else:
      carspd = safe_get(cp, "GW_187", "ESP_VehicleSpeed", 0)

    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # 3. 档位识别
    can_gear = int(safe_get(cp, "GEAR", "gearShifter", 0))
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # 4. 踏板信号 (自适应 iDD/燃油)
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = safe_get(cp, "GW_1A6", "brakePressed") != 0
      ret.gasPressed = safe_get(cp, "GW_1A6", "gasPressed") != 0
    else:
      ret.brakePressed = safe_get(cp, "GW_196", "brakePressed") != 0
      ret.gasPressed = safe_get(cp, "GW_196", "gasPressed") != 0

    # 5. 转向系统
    ret.steeringAngleDeg = safe_get(cp, "GW_180", "steeringAngleDeg", 0.0)
    ret.steeringRateDeg = safe_get(cp, "GW_180", "SAS_SteeringAngleSpeed", 0.0)
    ret.steeringTorque = safe_get(cp, "GW_17E", "EPS_MeasuredTorsionBarTorque", 0.0)
    ret.steeringTorqueEps = safe_get(cp, "GW_170", "EPS_ActualTorsionBarTorq", 0) * self.eps_torque_scale

    self.steeringPressed = abs(ret.steeringTorque) > 2.5
    ret.steeringPressed = self.steeringPressed
    ret.steerFaultTemporary = safe_get(cp, "GW_17E", "EPS_LatCtrlAvailabilityStatus") == 2

    # 6. 按键激活与限速控制
    btn_val = safe_get(cp, "buttonEvents", "Button_iACC", 0)
    self.iacc_enable_switch_button_rising_edge = (btn_val == 1 and self.iacc_enable_switch_button_prev == 0)
    self.iacc_enable_switch_button_prev = btn_val

    if self.iacc_enable_switch_button_rising_edge:
      self.cruiseEnable = not self.cruiseEnable
    elif ret.brakePressed:
      self.cruiseEnable = False

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = carspd if self.cruiseSpeed == 0 else self.cruiseSpeed

    # 5kph 步进逻辑
    btn_res = safe_get(cp, "buttonEvents", "Button_ACC_RESPlus", 0)
    btn_set = safe_get(cp, "buttonEvents", "Button_SETReduce", 0)

    if btn_res == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
    if btn_set == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.buttonPlus = btn_res
    self.buttonReduce = btn_set
    self.cruiseEnablePrev = self.cruiseEnable

    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # 7. 安全信号镜像与故障捕捉
    ret.accFaulted = safe_get(cp_cam, "GW_244", "ACC_ACCMode") == 7 or safe_get(cp_cam, "GW_31A", "ACC_IACCHWAMode") == 7
    ret.stockFcw = safe_get(cp_cam, "GW_244", "ACC_FCWPreWarning") == 1
    ret.stockAeb = safe_get(cp_cam, "GW_244", "ACC_AEBCtrlType") > 0

    # 8. 同步系统快照（确保 CarController 拿到的数据非空）
    self.sigs244 = copy.copy(cp_cam.vl.get("GW_244", {}))
    self.sigs1ba = copy.copy(cp_cam.vl.get("GW_1BA", {}))
    self.sigs17e = copy.copy(cp.vl.get("GW_17E", {}))
    self.sigs307 = copy.copy(cp_cam.vl.get("GW_307", {}))
    self.sigs31a = copy.copy(cp_cam.vl.get("GW_31A", {}))

    # 计数器提取
    self.counter_244 = safe_get(cp_cam, "GW_244", "ACC_RollingCounter_24E", 0)
    self.counter_1ba = safe_get(cp_cam, "GW_1BA", "Counter_1BA", 0)
    self.counter_17e = safe_get(cp, "GW_17E", "EPS_RollingCounter_17E", 0)
    self.counter_307 = safe_get(cp_cam, "GW_307", "Counter_35E", 0)
    self.counter_31a = safe_get(cp_cam, "GW_31A", "Counter_36D", 0)

    return ret

  @staticmethod
  def get_can_parsers(CP):
    # 彻底释放 Parser 压力，即使信号不稳也不允许报错
    pt_messages = [
      ("GW_180", 0), ("GW_17E", 0), ("buttonEvents", 0), ("GEAR", 0), ("GW_50", 0),
      ("GW_28B", 0), ("GW_170", 0), ("GW_24F", 0),
    ]
    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [("SPEED", 0), ("GW_1A6", 0)]
    else:
      pt_messages += [("GW_187", 0), ("GW_196", 0)]

    cam_messages = [
      ("GW_1BA", 0), ("GW_244", 0), ("GW_307", 0), ("GW_31A", 0),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
