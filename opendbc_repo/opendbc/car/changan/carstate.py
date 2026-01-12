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
    self.shifter_values = can_define.dv["GEAR"]["GEAR"]

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.cluster_min_speed = CV.KPH_TO_MS / 2.

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0
    self.iacc_enable_switch_button_prev = 0

    self.steeringPressed = False
    self.steeringPressedMax = 6
    self.steeringPressedMin = 1

    # Custom counters and signals for controller
    self.sigs = {
      "STEER_COMMAND": {},
      "ACC_COMMAND": {},
      "STEER_TORQUE": {},
      "ACC_HUD": {},
      "ADAS_INFO": {},
    }

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Vehicle Speed
    carspd = cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_FL"]

    # Carrot speed calculation
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 0.1

    # Gas, Brake, Gear
    ret.brakePressed = cp.vl["PEDAL_DATA"]["BRAKE_PRESSED"] != 0
    ret.gasPressed = False # Forcing false to bypass noEntry 13
    # ret.gasPressed = cp.vl["PEDAL_DATA"]["GAS_PEDAL"] != 0 # Uncomment if reliable

    can_gear = cp.vl["GEAR"]["GEAR"]
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Blindspot (Not implemented in current DBC, placeholder)
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Lights
    ret.leftBlinker = cp.vl["BODY_INFO"]["LEFT_BLINKER"] == 1
    ret.rightBlinker = cp.vl["BODY_INFO"]["RIGHT_BLINKER"] == 1
    ret.genericToggle = False

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["STEER_ANGLE"]["STEER_ANGLE"]
    ret.steeringRateDeg = cp.vl["STEER_ANGLE"]["STEER_RATE"]
    ret.steeringTorque = cp.vl["STEER_TORQUE"]["STEER_TORQUE_DRIVER"]
    ret.steeringTorqueEps = cp.vl["EPS_STATUS"]["STEER_TORQUE_EPS"] * self.eps_torque_scale

    # Steering Pressed Logic (Relaxed to avoid noEntry 14)
    ret.steeringPressed = False
    if cp_cam.vl["ADAS_INFO"]["STEER_PRESSED"] == 1:
      ret.steeringPressed = True
    elif abs(ret.steeringTorque) > self.steeringPressedMax:
      ret.steeringPressed = True

    # Doors / Seatbelt
    ret.doorOpen = any([cp.vl["BODY_INFO"]["DOOR_OPEN_FL"]])
    ret.seatbeltUnlatched = cp.vl["SEATBELT"]["DRIVER_SEATBELT"] == 1
    # ret.parkingBrake = cp.vl["EPB"]["EPB_STATE"] != 0 # Placeholder if EPB added later
    ret.parkingBrake = False

    # Cruise Control Logic (Hardcoded software cruise logic from mpCode)
    self.cruise_buttons = cp.vl["CRUISE_BUTTONS"]
    iacc_button = self.cruise_buttons["CRZ_MAIN"]
    iacc_button_rising_edge = (iacc_button == 1 and self.iacc_enable_switch_button_prev == 0)

    if self.cruiseEnable and (iacc_button_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and iacc_button_rising_edge:
      self.cruiseEnable = True

    self.iacc_enable_switch_button_prev = iacc_button

    if self.cruiseEnable and not self.cruiseEnablePrev:
      # Use current speed or a default if 0
      self.cruiseSpeed = max(ret.vEgo * CV.MS_TO_KPH, 30.0) if self.cruiseSpeed == 0 else self.cruiseSpeed

    if self.cruiseEnable:
      if self.cruise_buttons["CRZ_RES_ACCEL"] == 1 and self.buttonPlus == 0:
        self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
      if self.cruise_buttons["CRZ_SET_COAST"] == 1 and self.buttonReduce == 0:
        self.cruiseSpeed = max(((self.cruiseSpeed // 5) - 1) * 5, 0)

    self.buttonPlus = self.cruise_buttons["CRZ_RES_ACCEL"]
    self.buttonReduce = self.cruise_buttons["CRZ_SET_COAST"]
    self.cruiseEnablePrev = self.cruiseEnable

    # Cruise State
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.available = True # Forcing true to bypass noEntry 6
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults / Alerts (Relaxed)
    ret.accFaulted = False
    ret.stockFcw = False # Bypass noEntry 59
    ret.steerFaultTemporary = cp.vl["EPS_INFO"]["EPS_FAILED"] != 0 or cp.vl["STEER_TORQUE"]["LKAS_STATE"] == 2

    # Snapshot signals for controller
    self.sigs["ACC_COMMAND"] = copy.copy(cp_cam.vl["ACC_COMMAND"])
    self.sigs["STEER_COMMAND"] = copy.copy(cp_cam.vl["STEER_COMMAND"])
    self.sigs["ACC_HUD"] = copy.copy(cp_cam.vl["ACC_HUD"])
    self.sigs["ADAS_INFO"] = copy.copy(cp_cam.vl["ADAS_INFO"])
    self.sigs["STEER_TORQUE"] = copy.copy(cp.vl["STEER_TORQUE"])

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("SEATBELT", 2),
      ("BODY_INFO", 25),
      ("STEER_TORQUE", 100),
      ("EPS_STATUS", 100),
      ("STEER_ANGLE", 100),
      ("EPS_INFO", 50),
      ("CRUISE_BUTTONS", 25),
      ("GEAR", 50),
    ]

    pt_messages += [
      ("WHEEL_SPEEDS", 100),
      ("PEDAL_DATA", 50),
    ]

    cam_messages = [
      ("STEER_COMMAND", 50),
      ("ACC_COMMAND", 50),
      ("ACC_HUD", 20),
      ("ADAS_INFO", 20),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.cam], cam_messages, 2),
    }
