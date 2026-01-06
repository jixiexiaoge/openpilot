import copy
import time
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.common.filter_simple import FirstOrderFilter
from opendbc.can import CANDefine, CANParser
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import CAR, DBC, EPS_SCALE
from opendbc.car import Bus, structs, DT_CTRL

SteerControlType = structs.CarParams.SteerControlType

class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])

    if CP.carFingerprint == CAR.QIYUAN_A05:
      try:
        self.shifter_values = can_define.dv["GW_331"]["TCU_GearForDisplay"]
      except KeyError:
        self.shifter_values = {0: "P", 1: "R", 2: "N", 3: "D"}
    else:
      try:
        self.shifter_values = can_define.dv["GW_338"]["TCU_GearForDisplay"]
      except KeyError:
        self.shifter_values = {0: "P", 1: "R", 2: "N", 3: "D"}

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.cluster_min_speed = CV.KPH_TO_MS / 2.

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.prev_distance_button = 0
    self.distance_button = 0

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.iacc_enable_switch_button_pressed = 0
    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

    self.steeringPressed = False
    self.steeringPressedMax = 0
    self.steeringPressedMin = 0

    # Custom counters and signals for controller
    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.sigs244 = {}
    self.sigs1ba = {}
    self.sigs17e = {}
    self.sigs307 = {}
    self.sigs31a = {}

    # Emergency turn detection
    self.steering_angle_threshold = 30.0
    self.steering_rate_threshold = 50.0
    self.emergency_turn_active = False
    self.last_steering_angle = 0.0
    self.steering_rate = 0.0

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Vehicle Speed
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      speed = cp.vl.get("GW_17A", {}).get("ESP_VehicleSpeed", 0)
    else:
      carspd = cp.vl.get("GW_187", {}).get("ESP_VehicleSpeed", 0)
      speed = carspd if carspd <= 5 else ((carspd/0.98)+2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # Gas, Brake, Gear, Blindspot
    if self.CP.carFingerprint == CAR.QIYUAN_A05:
      can_gear = int(cp.vl.get("GW_331", {}).get("TCU_GearForDisplay", 0))
      ret.brakePressed = cp.vl.get("GW_17D", {}).get("PCU_BrkPedlSts", 0) != 0
      ret.gasPressed = cp.vl.get("GW_17D", {}).get("PCU_RealAccPedl", 0) != 0
      self.steeringPressedMax = 1.5
      self.steeringPressedMin = 0.5
      ret.leftBlindspot = (cp.vl.get("GW_2A4", {}).get("LCDAR_Left_BSD_LCAAlert", 0) in (1, 2))
      ret.rightBlindspot = (cp.vl.get("GW_2A4", {}).get("LCDAR_BSD_LCAAlert", 0) in (1, 2))
    elif self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      can_gear = int(cp.vl.get("GW_338", {}).get("TCU_GearForDisplay", 0))
      ret.brakePressed = cp.vl.get("GW_1A6", {}).get("EMS_BrakePedalStatus", 0) != 0
      ret.gasPressed = cp.vl.get("GW_1C6", {}).get("EMS_RealAccPedal", 0) != 0
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
      ret.leftBlindspot = False
      ret.rightBlindspot = False
    else:
      can_gear = int(cp.vl.get("GW_338", {}).get("TCU_GearForDisplay", 0))
      ret.brakePressed = cp.vl.get("GW_196", {}).get("EMS_BrakePedalStatus", 0) != 0
      ret.gasPressed = cp.vl.get("GW_196", {}).get("EMS_RealAccPedal", 0) != 0
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6
      ret.leftBlindspot = False
      ret.rightBlindspot = False

    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Lights
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(
      200,
      cp.vl.get("GW_28B", {}).get("BCM_TurnIndicatorRight", 0) == 1,
      cp.vl.get("GW_28B", {}).get("BCM_TurnIndicatorLeft", 0) == 1
    )
    ret.genericToggle = False

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl.get("GW_180", {}).get("SAS_SteeringAngle", 0)
    ret.steeringRateDeg = cp.vl.get("GW_180", {}).get("SAS_SteeringAngleSpeed", 0)
    ret.steeringTorque = cp.vl.get("GW_17E", {}).get("EPS_MeasuredTorsionBarTorque", 0)
    ret.steeringTorqueEps = cp.vl.get("GW_170", {}).get("EPS_ActualTorsionBarTorq", 0)

    # Steering Pressed Logic
    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # Emergency Turn Detection
    current_steering_angle = ret.steeringAngleDeg
    self.steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
    self.last_steering_angle = current_steering_angle

    # Doors / Seatbelt
    ret.doorOpen = any([cp.vl.get("GW_28B", {}).get("BCM_DriverDoorStatus", 0)])
    ret.seatbeltUnlatched = cp.vl.get("GW_50", {}).get("SRS_DriverBuckleSwitchStatus", 0) == 1
    ret.parkingBrake = False

    # Cruise Control Logic
    if self.CP.carFingerprint == CAR.QIYUAN_A05:
      if cp.vl.get("GW_28C", {}).get("GW_MFS_IACCenable_switch_signal", 0) == 1:
        self.cruiseEnable = True
      if cp.vl.get("GW_28C", {}).get("GW_MFS_Cancle_switch_signal", 0) == 1 or ret.brakePressed:
        self.cruiseEnable = False
    else:
      self.iacc_enable_switch_button_pressed = cp.vl.get("GW_28C", {}).get("GW_MFS_IACCenable_switch_signal", 0)
      self.iacc_enable_switch_button_rising_edge = self.iacc_enable_switch_button_pressed == 1 and self.iacc_enable_switch_button_prev == 0

      if self.cruiseEnable and (self.iacc_enable_switch_button_rising_edge or ret.brakePressed):
          self.cruiseEnable = False
      elif not self.cruiseEnable and self.iacc_enable_switch_button_rising_edge:
          self.cruiseEnable = True

      self.iacc_enable_switch_button_prev = self.iacc_enable_switch_button_pressed

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed

    if cp.vl.get("GW_28C", {}).get("GW_MFS_RESPlus_switch_signal", 0) == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5

    if cp.vl.get("GW_28C", {}).get("GW_MFS_SETReduce_switch_signal", 0) == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.cruiseEnablePrev = self.cruiseEnable
    self.buttonPlus = cp.vl.get("GW_28C", {}).get("GW_MFS_RESPlus_switch_signal", 0)
    self.buttonReduce = cp.vl.get("GW_28C", {}).get("GW_MFS_SETReduce_switch_signal", 0)

    # Cruise State
    ret.cruiseState.available = cp_cam.vl.get("GW_31A", {}).get("ACC_IACCHWAEnable", 0) == 1
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.standstill = ret.standstill
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS
    if ret.cruiseState.speed != 0:
      ret.cruiseState.speedCluster = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults / Alerts
    ret.accFaulted = cp_cam.vl.get("GW_244", {}).get("ACC_ACCMode", 0) == 7 or cp_cam.vl.get("GW_31A", {}).get("ACC_IACCHWAMode", 0) == 7
    ret.stockFcw = cp_cam.vl.get("GW_244", {}).get("ACC_FCWPreWarning", 0) == 1
    #ret.stockAeb = cp_cam.vl.get("GW_244", {}).get("ACC_AEBCtrlType", 0) > 0
    ret.steerFaultTemporary = cp.vl.get("GW_24F", {}).get("EPS_EPSFailed", 0) != 0 or cp.vl.get("GW_17E", {}).get("EPS_LatCtrlAvailabilityStatus", 0) == 2

    # Copy signals for controller
    self.sigs244 = copy.copy(cp_cam.vl.get("GW_244", {}))
    self.sigs1ba = copy.copy(cp_cam.vl.get("GW_1BA", {}))
    self.sigs17e = copy.copy(cp.vl.get("GW_17E", {}))
    self.sigs307 = copy.copy(cp_cam.vl.get("GW_307", {}))
    self.sigs31a = copy.copy(cp_cam.vl.get("GW_31A", {}))
    self.counter_244 = cp_cam.vl.get("GW_244", {}).get("ACC_RollingCounter_24E", 0)
    self.counter_1ba = cp_cam.vl.get("GW_1BA", {}).get("ACC_RollingCounter_1BA", 0)
    self.counter_17e = cp.vl.get("GW_17E", {}).get("EPS_RollingCounter_17E", 0)
    self.counter_307 = cp_cam.vl.get("GW_307", {}).get("ACC_RollingCounter_35E", 0)
    self.counter_31a = cp_cam.vl.get("GW_31A", {}).get("ACC_RollingCounter_36D", 0)

    # Distance button
    self.prev_distance_button = self.distance_button
    self.distance_button = cp_cam.vl.get("GW_307", {}).get("ACC_DistanceLevel", 0)

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
      pt_messages += [("GW_17A", 100)]
    else:
      pt_messages += [("GW_187", 100)]

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
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.cam], cam_messages, 2),
    }

