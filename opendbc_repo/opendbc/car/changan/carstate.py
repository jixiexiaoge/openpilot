import copy
from opendbc.can.parser import CANParser, CANDefine
from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.common.filter_simple import FirstOrderFilter
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import DBC, EPS_SCALE, CAR

class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR_PACKET"]["GEAR"]

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.cluster_min_speed = CV.KPH_TO_MS / 2.

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0

    self.iacc_enable_switch_button_pressed = 0
    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

    self.steeringPressed = False
    self.steeringPressedMax = 6
    self.steeringPressedMin = 1

    # Custom counters and signals for controller
    self.sigs = {
      "STEERING_LKA": {},
      "ACC_CONTROL": {},
      "STEER_TORQUE_SENSOR": {},
      "ACC_HUD": {},
      "ACC_STATE": {},
    }

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Vehicle Speed
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["VEHICLE_SPEED"]["VEHICLE_SPEED"]
    else:
      carspd = cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_FL"]
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # Gas, Brake, Gear
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = cp.vl["BRAKE_MODULE_ALT"]["BRAKE_PRESSED"] != 0
      ret.gasPressed = cp.vl["GAS_PEDAL_ALT"]["GAS_PEDAL_USER"] != 0
    else:
      ret.brakePressed = cp.vl["BRAKE_MODULE"]["BRAKE_PRESSED"] != 0
      ret.gasPressed = cp.vl["BRAKE_MODULE"]["GAS_PEDAL_USER"] != 0

    can_gear = int(cp.vl["GEAR_PACKET"]["GEAR"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Blindspot (Not implemented in current DBC, placeholder)
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Lights
    ret.leftBlinker = cp.vl["BODY_CONTROL_STATE_2"]["TURN_SIGNALS"] == 1
    ret.rightBlinker = cp.vl["BODY_CONTROL_STATE_2"]["TURN_SIGNALS"] == 2
    ret.genericToggle = False

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["STEER_ANGLE_SENSOR"]["STEER_ANGLE"]
    ret.steeringRateDeg = cp.vl["STEER_ANGLE_SENSOR"]["STEER_RATE"]
    ret.steeringTorque = cp.vl["STEER_TORQUE_SENSOR"]["STEER_TORQUE_DRIVER"]
    ret.steeringTorqueEps = cp.vl["STEER_TORQUE_SENSOR_2"]["STEER_TORQUE_EPS"] * self.eps_torque_scale

    # Steering Pressed Logic
    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # Doors / Seatbelt
    ret.doorOpen = any([cp.vl["BODY_CONTROL_STATE_2"]["DOOR_OPEN_FL"]])
    ret.seatbeltUnlatched = cp.vl["BODY_CONTROL_STATE"]["SEATBELT_DRIVER_UNLATCHED"] == 1
    ret.parkingBrake = False

    # Cruise Control Logic (Hardcoded software cruise logic from mpCode)
    self.iacc_enable_switch_button_pressed = cp.vl["MFS_BUTTONS"]["CRUISE_ENABLE_BUTTON"]
    self.iacc_enable_switch_button_rising_edge = self.iacc_enable_switch_button_pressed == 1 and self.iacc_enable_switch_button_prev == 0

    if self.cruiseEnable and (self.iacc_enable_switch_button_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and self.iacc_enable_switch_button_rising_edge:
      self.cruiseEnable = True

    self.iacc_enable_switch_button_prev = self.iacc_enable_switch_button_pressed

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed

    if cp.vl["MFS_BUTTONS"]["RES_PLUS_BUTTON"] == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5

    if cp.vl["MFS_BUTTONS"]["SET_MINUS_BUTTON"] == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    self.cruiseEnablePrev = self.cruiseEnable
    self.buttonPlus = cp.vl["MFS_BUTTONS"]["RES_PLUS_BUTTON"]
    self.buttonReduce = cp.vl["MFS_BUTTONS"]["SET_MINUS_BUTTON"]

    # Cruise State
    ret.cruiseState.available = cp_cam.vl["ACC_STATE"]["ACC_IACC_HWA_ENABLE"] == 1
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.standstill = ret.standstill
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS
    if ret.cruiseState.speed != 0:
      ret.cruiseState.speedCluster = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults / Alerts
    ret.accFaulted = cp_cam.vl["ACC_CONTROL"]["ACC_MODE"] == 7 or cp_cam.vl["ACC_STATE"]["ACC_IACC_HWA_MODE"] == 7
    ret.stockFcw = cp_cam.vl["ACC_CONTROL"]["FCW_PRE_WARNING"] == 1
    ret.steerFaultTemporary = cp.vl["EPS_STATUS"]["EPS_FAILED"] != 0 or cp.vl["STEER_TORQUE_SENSOR"]["LKA_STATE"] == 2

    # Snapshot signals for controller
    self.sigs["ACC_CONTROL"] = copy.copy(cp_cam.vl["ACC_CONTROL"])
    self.sigs["STEERING_LKA"] = copy.copy(cp_cam.vl["STEERING_LKA"])
    self.sigs["ACC_STATE"] = copy.copy(cp_cam.vl["ACC_STATE"])
    self.sigs["STEER_TORQUE_SENSOR"] = copy.copy(cp.vl["STEER_TORQUE_SENSOR"])

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("BODY_CONTROL_STATE", 2),
      ("BODY_CONTROL_STATE_2", 25),
      ("STEER_TORQUE_SENSOR", 100),
      ("STEER_TORQUE_SENSOR_2", 100),
      ("STEER_ANGLE_SENSOR", 100),
      ("MFS_BUTTONS", 25),
      ("GEAR_PACKET", 10),
      ("EPS_STATUS", 50),
    ]

    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [
        ("VEHICLE_SPEED", 100),
        ("BRAKE_MODULE_ALT", 100),
        ("GAS_PEDAL_ALT", 100),
      ]
    else:
      pt_messages += [
        ("WHEEL_SPEEDS", 100),
        ("BRAKE_MODULE", 100),
      ]

    cam_messages = [
      ("STEERING_LKA", 100),
      ("ACC_CONTROL", 50),
      ("ACC_HUD", 10),
      ("ACC_STATE", 10),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.cam], cam_messages, 2),
    }
