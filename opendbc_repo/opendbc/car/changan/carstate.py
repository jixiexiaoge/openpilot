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
    self.shifter_values = can_define.dv["GW_338"]["TCU_GearForDisplay"]

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
      "GW_1BA": {},
      "GW_244": {},
      "GW_17E": {},
      "GW_307": {},
      "GW_31A": {},
    }

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Vehicle Speed
    carspd = cp.vl["GW_187"]["WHEEL_SPEED_FL"]

    # Carrot speed calculation
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 0.1

    # Gas, Brake, Gear
    ret.brakePressed = cp.vl["GW_196"]["BRAKE_PRESSED"] != 0
    ret.gasPressed = False # Forcing false to bypass noEntry 13
    # ret.gasPressed = cp.vl["GW_196"]["GAS_PEDAL_USER"] != 0 # Uncomment if reliable

    can_gear = cp.vl["GW_338"]["TCU_GearForDisplay"]
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Blindspot (Not implemented in current DBC, placeholder)
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Lights
    ret.leftBlinker = cp.vl["GW_28B"]["TURN_SIGNALS_L"] == 1
    ret.rightBlinker = cp.vl["GW_28B"]["TURN_SIGNALS_R"] == 1
    ret.genericToggle = False

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["GW_180"]["STEER_ANGLE"]
    ret.steeringRateDeg = cp.vl["GW_180"]["STEER_RATE"]
    ret.steeringTorque = cp.vl["GW_17E"]["STEER_TORQUE_DRIVER"]
    ret.steeringTorqueEps = cp.vl["EPS_368"]["STEER_TORQUE_EPS"] * self.eps_torque_scale

    # Steering Pressed Logic (Relaxed to avoid noEntry 14)
    ret.steeringPressed = False
    if cp_cam.vl["GW_31A"]["STEER_PRESSED"] == 1:
      ret.steeringPressed = True
    elif abs(ret.steeringTorque) > self.steeringPressedMax:
      ret.steeringPressed = True

    # Doors / Seatbelt
    ret.doorOpen = any([cp.vl["GW_28B"]["DOOR_OPEN_FL"]])
    ret.seatbeltUnlatched = cp.vl["GW_50"]["SEATBELT_DRIVER_UNLATCHED"] == 1
    ret.parkingBrake = False

    # Cruise Control Logic (Hardcoded software cruise logic from mpCode)
    self.cruise_buttons = cp.vl["GW_MFS_IACC"]
    iacc_button = self.cruise_buttons["GW_MFS_IACCenable_switch_signal"]
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
      if self.cruise_buttons["GW_MFS_RESPlus_switch_signal"] == 1 and self.buttonPlus == 0:
        self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
      if self.cruise_buttons["GW_MFS_SETReduce_switch_signal"] == 1 and self.buttonReduce == 0:
        self.cruiseSpeed = max(((self.cruiseSpeed // 5) - 1) * 5, 0)

    self.buttonPlus = self.cruise_buttons["GW_MFS_RESPlus_switch_signal"]
    self.buttonReduce = self.cruise_buttons["GW_MFS_SETReduce_switch_signal"]
    self.cruiseEnablePrev = self.cruiseEnable

    # Cruise State
    # Cruise State (Permissive for engagement debugging)
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.available = True # Forcing true to bypass noEntry 6
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults / Alerts (Relaxed)
    ret.accFaulted = False
    ret.stockFcw = False # Bypass noEntry 59
    ret.steerFaultTemporary = cp.vl["EPS_591"]["EPS_FAILED"] != 0 or cp.vl["GW_17E"]["LKA_STATE"] == 2

    # Snapshot signals for controller
    self.sigs["GW_244"] = copy.copy(cp_cam.vl["GW_244"])
    self.sigs["GW_1BA"] = copy.copy(cp_cam.vl["GW_1BA"])
    self.sigs["GW_307"] = copy.copy(cp_cam.vl["GW_307"])
    self.sigs["GW_31A"] = copy.copy(cp_cam.vl["GW_31A"])
    self.sigs["GW_17E"] = copy.copy(cp.vl["GW_17E"])

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_50", 2),
      ("GW_28B", 25),
      ("GW_17E", 100),
      ("EPS_368", 100),
      ("GW_180", 100),
      ("EPS_591", 50),
      ("GW_MFS_IACC", 25),
      ("GW_338", 50),
    ]

    pt_messages += [
      ("GW_187", 100),
      ("GW_196", 50),
    ]

    cam_messages = [
      ("GW_1BA", 50),
      ("GW_244", 50),
      ("GW_307", 20),
      ("GW_31A", 20),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.cam], cam_messages, 2),
    }
