import copy
from opendbc.can.parser import CANParser, CANDefine
from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.common.filter_simple import FirstOrderFilter
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import DBC, EPS_SCALE, CAR, ChanganFlags


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR"]["gearShifter"]

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.0
    self.cluster_min_speed = CV.KPH_TO_MS / 2.0

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.steeringPressed = False
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
    else:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6

    self.iacc_enable_switch_button_pressed = 0
    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

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

    # Door / Seatbelt
    ret.doorOpen = cp.vl["GW_28B"]["doorOpen"] == 1
    ret.seatbeltUnlatched = cp.vl["GW_50"]["seatbeltUnlatched"] == 1
    ret.parkingBrake = False

    # Vehicle Speed
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["SPEED"]["wheelSpeeds"]
    else:
      carspd = cp.vl["GW_187"]["ESP_VehicleSpeed"]
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # Gas, Brake, Gear
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = cp.vl["GW_1A6"]["brakePressed"] != 0
      ret.gasPressed = cp.vl["GW_1A6"]["gasPressed"] != 0
    else:
      ret.brakePressed = cp.vl["GW_196"]["brakePressed"] != 0
      ret.gasPressed = cp.vl["GW_196"]["gasPressed"] != 0

    can_gear = int(cp.vl["GEAR"]["gearShifter"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Lights
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(200, cp.vl["GW_28B"]["leftBlinker"] == 1, cp.vl["GW_28B"]["rightBlinker"] == 2)

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["GW_180"]["steeringAngleDeg"]
    ret.steeringRateDeg = cp.vl["GW_180"]["SAS_SteeringAngleSpeed"]
    ret.steeringTorque = cp.vl["GW_17E"]["EPS_MeasuredTorsionBarTorque"]
    ret.steeringTorqueEps = cp.vl["GW_170"]["EPS_ActualTorsionBarTorq"] * self.eps_torque_scale

    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # 巡航状态 (Cruise State) - 兼容多总线获取 IACC 按钮信号
    button_iacc = 0
    if "Button_iACC" in cp.vl["buttonEvents"]:
      button_iacc = cp.vl["buttonEvents"]["Button_iACC"]
    if button_iacc == 0 and "Button_iACC" in cp_cam.vl["buttonEvents"]:
      button_iacc = cp_cam.vl["buttonEvents"]["Button_iACC"]

    self.iacc_enable_switch_button_rising_edge = (button_iacc == 1 and self.iacc_enable_switch_button_prev == 0)
    self.iacc_enable_switch_button_prev = button_iacc

    if self.iacc_enable_switch_button_rising_edge:
      self.cruiseEnable = not self.cruiseEnable
    elif ret.brakePressed:
      self.cruiseEnable = False

    ret.cruiseState.available = True
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.speed = cp_cam.vl["GW_307"]["vCruise"] * CV.KPH_TO_MS if "vCruise" in cp_cam.vl["GW_307"] else 0
    ret.cruiseState.standstill = ret.standstill

    # 系统故障与安全预警 (Faults & Safety)
    ret.accFaulted = cp_cam.vl["GW_244"]["ACC_ACCMode"] == 7 or cp_cam.vl["GW_31A"]["ACC_IACCHWAMode"] == 7
    ret.steerFaultTemporary = cp.vl["GW_17E"]["EPS_LatCtrlAvailabilityStatus"] == 2
    ret.steerFaultPermanent = False

    # 原车 ADAS 状态透传
    ret.stockFcw = cp_cam.vl["GW_244"]["ACC_FCWPreWarning"] == 1
    ret.stockAeb = cp_cam.vl["GW_244"]["ACC_AEBCtrlType"] > 0
    ret.genericToggle = False

    # 供控制器使用的信号快照 (对齐 DBC 内部命名)
    self.sigs244 = copy.copy(cp_cam.vl["GW_244"])
    self.sigs1ba = copy.copy(cp_cam.vl["GW_1BA"])
    self.sigs17e = copy.copy(cp.vl["GW_17E"])
    self.sigs307 = copy.copy(cp_cam.vl["GW_307"])
    self.sigs31a = copy.copy(cp_cam.vl["GW_31A"])

    # 滚动计数器提取 (严格遵循 changan_can.dbc)
    self.counter_244 = cp_cam.vl["GW_244"]["ACC_RollingCounter_24E"]
    self.counter_1ba = cp_cam.vl["GW_1BA"]["Counter_1BA"]
    self.counter_17e = cp.vl["GW_17E"]["EPS_RollingCounter_17E"]
    self.counter_307 = cp_cam.vl["GW_307"]["Counter_35E"]
    self.counter_31a = cp_cam.vl["GW_31A"]["Counter_36D"]

    # 跟车距离按钮状态采集与追踪
    self.prev_distance_button = self.distance_button
    self.distance_button = cp_cam.vl["GW_307"]["ACC_DistanceLevel"]

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_50", 1),
      ("GW_170", 100),
      ("GW_17E", 50),
      ("GW_180", 100),
      ("GW_24F", 20),
      ("GW_28B", 10),
      ("buttonEvents", 10),
      ("GEAR", 10),
    ]

    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [
        ("SPEED", 50),
        ("GW_1A6", 50),
      ]
    else: #Z6
      pt_messages += [
        ("GW_187", 50),
        ("GW_196", 50),
      ]

    cam_messages = [
      ("GW_1BA", 100),
      ("GW_244", 50),
      ("GW_307", 10),
      ("GW_31A", 10),
      ("buttonEvents", 10),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
