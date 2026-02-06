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

    # Gear shifter values - Z6 and Z6 iDD use GW_338
    # Use defensive programming to handle missing DBC definitions
    try:
      self.shifter_values = can_define.dv["GW_338"]["TCU_GearForDisplay"]
    except KeyError:
      # Fallback: create default gear values if DBC definition is missing
      self.shifter_values = {
        0: "park",
        1: "reverse",
        2: "neutral",
        3: "drive",
      }

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.steeringPressed = False
    # Steering pressure thresholds vary by variant
    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      self.steeringPressedMin = 1.0
      self.steeringPressedMax = 3.0
    else:  # CHANGAN_Z6
      self.steeringPressedMin = 1.0
      self.steeringPressedMax = 6.0

    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

    # Signal snapshot containers - store last received values
    self.sigs244 = {}
    self.sigs1ba = {}
    self.sigs17e = {}
    self.sigs307 = {}
    self.sigs31a = {}

    # Rolling counters synchronized with stock ECU
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
    # Standard Changan SRS message: SRS_DriverBuckleSwitchStatus at bit 12 (1: unlatched, 0: latched)
    ret.seatbeltUnlatched = safe_get(cp, "GW_50", "SRS_DriverBuckleSwitchStatus", 1) == 1 or \
                            safe_get(cp, "GW_50", "seatbeltUnlatched", 0) == 1
    ret.parkingBrake = False

    # 2. 车辆速度 (兼容 Z6/Z6 iDD)
    carspd = 0
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = safe_get(cp, "GW_17A", "ESP_VehicleSpeed", 0)
    else:  # CHANGAN_Z6
      carspd = safe_get(cp, "GW_187", "ESP_VehicleSpeed", 0)

    # Speed correction for accuracy (from mpCode analysis)
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # 3. 档位识别 (Z6 and Z6 iDD use GW_338)
    can_gear = int(safe_get(cp, "GW_338", "TCU_GearForDisplay", 0))
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # 4. 踏板信号 (自适应 Z6/Z6 iDD)
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = safe_get(cp, "GW_1A6", "EMS_BrakePedalStatus") != 0
      ret.gasPressed = safe_get(cp, "GW_1C6", "EMS_RealAccPedal") != 0
    else:  # CHANGAN_Z6
      ret.brakePressed = safe_get(cp, "GW_196", "EMS_BrakePedalStatus") != 0
      ret.gasPressed = safe_get(cp, "GW_196", "EMS_RealAccPedal") != 0

    # 5. 转向系统
    ret.steeringAngleDeg = safe_get(cp, "GW_180", "steeringAngleDeg", 0.0)
    ret.steeringRateDeg = safe_get(cp, "GW_180", "SAS_SteeringAngleSpeed", 0.0)
    ret.steeringTorque = safe_get(cp, "GW_17E", "EPS_MeasuredTorsionBarTorque", 0.0)
    ret.steeringTorqueEps = safe_get(cp, "GW_170", "EPS_ActualTorsionBarTorq", 0) * self.eps_torque_scale

    # Steering pressure detection with hysteresis (from mpCode)
    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # Disable EPS fault warning (from mpCode - always return False)
    ret.steerFaultTemporary = False

    # 6. 按键激活与限速控制 (from mpCode analysis)
    # Z6/Z6 iDD: Rising edge detection
    btn_iacc = safe_get(cp, "GW_28C", "GW_MFS_IACCenable_switch_signal", 0)
    btn_cancel = safe_get(cp, "GW_28C", "GW_MFS_Cancle_switch_signal", 0)

    self.iacc_enable_switch_button_rising_edge = (btn_iacc == 1 and self.iacc_enable_switch_button_prev == 0)

    if self.cruiseEnable and (self.iacc_enable_switch_button_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and self.iacc_enable_switch_button_rising_edge:
      self.cruiseEnable = True

    self.iacc_enable_switch_button_prev = btn_iacc

    # Initialize cruise speed on activation
    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed

    # 5kph step logic for speed adjustment
    btn_res = safe_get(cp, "GW_28C", "GW_MFS_RESPlus_switch_signal", 0)
    btn_set = safe_get(cp, "GW_28C", "GW_MFS_SETReduce_switch_signal", 0)

    if btn_res == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
    if btn_set == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.buttonPlus = btn_res
    self.buttonReduce = btn_set
    self.cruiseEnablePrev = self.cruiseEnable

    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS
    ret.cruiseState.speedCluster = self.cruiseSpeed * CV.KPH_TO_MS
    ret.cruiseState.available = safe_get(cp_cam, "GW_31A", "ACC_IACCHWAEnable") == 1

    # 7. 安全信号镜像与故障捕捉
    ret.accFaulted = safe_get(cp_cam, "GW_244", "ACC_ACCMode") == 7 or safe_get(cp_cam, "GW_31A", "ACC_IACCHWAMode") == 7
    ret.stockFcw = safe_get(cp_cam, "GW_244", "ACC_FCWPreWarning") == 1
    ret.stockAeb = safe_get(cp_cam, "GW_244", "ACC_AEBCtrlType") > 0

    # Blind spot detection not available on Z6/Z6 iDD
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Blinkers
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(
      200,
      safe_get(cp, "GW_28B", "BCM_TurnIndicatorLeft") == 1,
      safe_get(cp, "GW_28B", "BCM_TurnIndicatorRight") == 1
    )

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
    # Base PT-CAN messages (common to all variants)
    pt_messages = [
      ("GW_180", 100),  # Steering angle
      ("GW_17E", 100),  # EPS torque
      ("GW_28C", 25),   # Cruise buttons
      ("GW_50", 2),     # Seatbelt
      ("GW_28B", 25),   # Door/blinkers
      ("GW_170", 100),  # EPS actual torque
      ("GW_24F", 50),   # EPS fault
    ]

    # Variant-specific messages
    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [
        ("GW_17A", 100),  # Speed (iDD)
        ("GW_1A6", 100),  # Brake pedal (iDD)
        ("GW_1C6", 100),  # Gas pedal (iDD)
        ("GW_338", 10),   # Gear (Z6)
      ]
    else:  # CHANGAN_Z6
      pt_messages += [
        ("GW_187", 100),  # Speed
        ("GW_196", 100),  # Pedals (Z6)
        ("GW_338", 10),   # Gear (Z6)
      ]

    # CAM-CAN messages (common to all variants)
    cam_messages = [
      ("GW_1BA", 100),  # Steering control
      ("GW_244", 50),   # ACC control
      ("GW_307", 10),   # Cruise speed
      ("GW_31A", 10),   # ADAS HUD
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
