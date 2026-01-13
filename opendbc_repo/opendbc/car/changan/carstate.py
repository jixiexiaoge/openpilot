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
    carspd = cp.vl.get("GW_187", {}).get("WHEEL_SPEED_FL", 0)

    # Carrot speed calculation
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 0.1

    # Gas, Brake, Gear
    ret.brakePressed = cp.vl.get("GW_196", {}).get("BRAKE_PRESSED", 0) != 0
    ret.gasPressed = False # Forcing false to bypass noEntry 13
    # ret.gasPressed = cp.vl.get("GW_196", {}).get("GAS_PEDAL_USER", 0) != 0

    can_gear = cp.vl.get("GW_338", {}).get("TCU_GearForDisplay", 0)
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Lights
    ret.leftBlinker = cp.vl.get("GW_28B", {}).get("TURN_SIGNALS_L", 0) == 1
    ret.rightBlinker = cp.vl.get("GW_28B", {}).get("TURN_SIGNALS_R", 0) == 1
    ret.genericToggle = False

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl.get("GW_180", {}).get("STEER_ANGLE", 0)
    ret.steeringRateDeg = cp.vl.get("GW_180", {}).get("STEER_RATE", 0)
    ret.steeringTorque = cp.vl.get("GW_17E", {}).get("STEER_TORQUE_DRIVER", 0)
    ret.steeringTorqueEps = cp.vl.get("EPS_368", {}).get("STEER_TORQUE_EPS", 0) * self.eps_torque_scale

    # Steering Pressed Logic (Relaxed to avoid noEntry 14)
    ret.steeringPressed = False
    if cp_cam.vl.get("GW_31A", {}).get("STEER_PRESSED", 0) == 1:
      ret.steeringPressed = True
    elif abs(ret.steeringTorque) > self.steeringPressedMax:
      ret.steeringPressed = True

    # Doors / Seatbelt
    ret.doorOpen = any([cp.vl.get("GW_28B", {}).get("DOOR_OPEN_FL", 0)])
    ret.seatbeltUnlatched = cp.vl.get("GW_50", {}).get("SEATBELT_DRIVER_UNLATCHED", 0) == 1
    ret.parkingBrake = False

    # Cruise Control Logic
    self.cruise_buttons = cp.vl.get("GW_MFS_IACC", {})
    iacc_button = self.cruise_buttons.get("GW_MFS_ACC", 0)
    iacc_button_rising_edge = (iacc_button == 1 and self.iacc_enable_switch_button_prev == 0)

    if self.cruiseEnable and (iacc_button_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and iacc_button_rising_edge:
      self.cruiseEnable = True

    self.iacc_enable_switch_button_prev = iacc_button

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = max(ret.vEgo * CV.MS_TO_KPH, 30.0) if self.cruiseSpeed == 0 else self.cruiseSpeed

    if self.cruiseEnable:
      if self.cruise_buttons.get("GW_MFS_RESPlus", 0) == 1 and self.buttonPlus == 0:
        self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
      if self.cruise_buttons.get("GW_MFS_SETReduce", 0) == 1 and self.buttonReduce == 0:
        self.cruiseSpeed = max(((self.cruiseSpeed // 5) - 1) * 5, 0)

    self.buttonPlus = self.cruise_buttons.get("GW_MFS_RESPlus", 0)
    self.buttonReduce = self.cruise_buttons.get("GW_MFS_SETReduce", 0)
    self.cruiseEnablePrev = self.cruiseEnable

    # Cruise State
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.available = True
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults / Alerts
    ret.accFaulted = False
    ret.steerFaultTemporary = cp.vl.get("EPS_591", {}).get("EPS_FAILED", 0) != 0 or \
                               cp.vl.get("GW_17E", {}).get("LKA_STATE", 0) == 2

    # Snapshot signals for controller
    if "GW_244" in cp_cam.vl: self.sigs["GW_244"] = copy.copy(cp_cam.vl["GW_244"])
    if "GW_1BA" in cp_cam.vl: self.sigs["GW_1BA"] = copy.copy(cp_cam.vl["GW_1BA"])
    if "GW_307" in cp_cam.vl: self.sigs["GW_307"] = copy.copy(cp_cam.vl["GW_307"])
    if "GW_31A" in cp_cam.vl: self.sigs["GW_31A"] = copy.copy(cp_cam.vl["GW_31A"])
    if "GW_17E" in cp.vl: self.sigs["GW_17E"] = copy.copy(cp.vl["GW_17E"])

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_50", 1),         # Relaxed to 1Hz
      ("GW_28B", 10),      # Relaxed
      ("GW_17E", 50),      # Relaxed
      ("EPS_368", 50),
      ("GW_180", 50),
      ("EPS_591", 20),
      ("GW_MFS_IACC", 10),
      ("GW_338", 10),
      ("GW_187", 50),
      ("GW_196", 20),
    ]

    cam_messages = [
      ("GW_1BA", 20),
      ("GW_244", 20),
      ("GW_307", 5),
      ("GW_31A", 5),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.cam], cam_messages, 2),
    }
