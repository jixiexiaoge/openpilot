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
    self.shifter_values = can_define.dv["GW_338"]["TCU_GearForDisplay"]

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.0
    self.cluster_min_speed = CV.KPH_TO_MS / 2.0

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.iacc_pressed_prev = 0
    self.plus_pressed_prev = 0
    self.minus_pressed_prev = 0

    self.steeringPressed = False
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
    else:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6

    self.sigs = {
      "GW_1BA": {},
      "GW_244": {},
      "GW_17E": {},
      "GW_307": {},
      "GW_31A": {},
    }
    self.counter_1ba = 0
    self.counter_244 = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0
    self.counter_187 = 0
    self.counter_196 = 0

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Door / Seatbelt
    ret.doorOpen = cp.vl.get("GW_28B", {}).get("BCM_DriverDoorStatus", 0) == 1
    ret.seatbeltUnlatched = cp.vl.get("GW_50", {}).get("SRS_DriverBuckleSwitchStatus", 0) == 1
    ret.parkingBrake = False

    # Vehicle Speed
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["VEHICLE_SPEED"]["VEHICLE_SPEED"]
    else:
      carspd = cp.vl["GW_187"]["ESP_VehicleSpeed"]
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3

    # Gas, Brake, Gear
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = cp.vl["GW_1A6"]["BRAKE_PRESSED"] != 0
      ret.gasPressed = cp.vl["GW_1C6"]["EMS_RealAccPedal"] != 0
    else:
      ret.brakePressed = cp.vl["GW_196"]["EMS_BrakePedalStatus"] != 0
      ret.gasPressed = cp.vl["GW_196"]["EMS_RealAccPedal"] != 0

    can_gear = cp.vl["GW_338"]["TCU_GearForDisplay"]
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.leftBlindspot = False
    ret.rightBlindspot = False

    # Lights
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(
      200, cp.vl["GW_28B"]["BCM_TurnIndicatorLeft"] == 1, cp.vl["GW_28B"]["BCM_TurnIndicatorRight"] == 1
    )

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl["GW_180"]["SAS_SteeringAngle"]
    ret.steeringRateDeg = cp.vl["GW_180"]["SAS_SteeringAngleSpeed"]
    ret.steeringTorque = cp.vl["GW_17E"]["EPS_MeasuredTorsionBarTorque"]
    ret.steeringTorqueEps = cp.vl["GW_170"]["EPS_ActualTorsionBarTorq"] * self.eps_torque_scale

    # Steering Pressed Logic (Reference uses thresholds)
    if self.steeringPressed:
      if abs(ret.steeringTorque) < self.steeringPressedMin and abs(ret.steeringAngleDeg) < 90:
        self.steeringPressed = False
    else:
      if abs(ret.steeringTorque) > self.steeringPressedMax:
        self.steeringPressed = True
    ret.steeringPressed = self.steeringPressed

    # Cruise Control Logic - Rising Edge Toggle from Reference
    buttons = cp.vl["GW_28C"]
    iacc_button = buttons["GW_MFS_IACCenable_switch_signal"]
    iacc_rising_edge = iacc_button == 1 and not self.iacc_pressed_prev

    if self.cruiseEnable and (iacc_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and iacc_rising_edge:
      self.cruiseEnable = True

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = speed if self.cruiseSpeed == 0 else self.cruiseSpeed

    if self.cruiseEnable:
      if buttons["GW_MFS_RESPlus_switch_signal"] == 1 and self.plus_pressed_prev == 0:
        self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
      if buttons["GW_MFS_SETReduce_switch_signal"] == 1 and self.minus_pressed_prev == 0:
        self.cruiseSpeed = max(((self.cruiseSpeed // 5) - 1) * 5, 0)

    self.iacc_pressed_prev = iacc_button
    self.plus_pressed_prev = buttons["GW_MFS_RESPlus_switch_signal"]
    self.minus_pressed_prev = buttons["GW_MFS_SETReduce_switch_signal"]
    self.cruiseEnablePrev = self.cruiseEnable

    # Cruise State Output
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.available = cp_cam.vl["GW_31A"]["ACC_IACCHWAEnable"] == 1
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # Faults
    ret.accFaulted = cp_cam.vl["GW_244"]["ACC_ACCMode"] == 7 or cp_cam.vl["GW_31A"]["ACC_IACCHWAMode"] == 7
    ret.steerFaultTemporary = cp.vl["GW_17E"]["EPS_LatCtrlAvailabilityStatus"] == 2

    ret.stockFcw = cp_cam.vl["GW_244"]["ACC_FCWPreWarning"] == 1
    ret.stockAeb = cp_cam.vl["GW_244"]["ACC_AEBCtrlType"] > 0

    # Snapshots for Controller
    self.sigs["GW_1BA"] = copy.copy(cp_cam.vl["GW_1BA"])
    self.sigs["GW_244"] = copy.copy(cp_cam.vl["GW_244"])
    self.sigs["GW_307"] = copy.copy(cp_cam.vl["GW_307"])
    self.sigs["GW_31A"] = copy.copy(cp_cam.vl["GW_31A"])
    self.sigs["GW_17E"] = copy.copy(cp.vl["GW_17E"])

    # Rolling Counters
    self.counter_1ba = int(cp_cam.vl["GW_1BA"]["ACC_RollingCounter_1BA"])
    self.counter_244 = int(cp_cam.vl["GW_244"]["ACC_RollingCounter_24E"])
    self.counter_17e = int(cp.vl["GW_17E"]["EPS_RollingCounter_17E"])
    self.counter_307 = int(cp_cam.vl["GW_307"]["ACC_RollingCounter_35E"])
    self.counter_31a = int(cp_cam.vl["GW_31A"]["ACC_RollingCounter_36D"])

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_50", 2),
      ("GW_28B", 25),
      ("GW_17E", 100),
      ("GW_180", 100),
      ("GW_28C", 25),
      ("GW_338", 10),
      ("GW_170", 100),
      ("GW_187", 100),  # Include always for fallbacks
      ("GW_196", 100),  # Include always for fallbacks
    ]

    if CP.flags & ChanganFlags.IDD:
      pt_messages += [
        ("GW_1A6", 100),
        ("GW_1C6", 100),
        ("VEHICLE_SPEED", 100),
      ]

    cam_messages = [
      ("GW_1BA", 100),
      ("GW_244", 50),
      ("GW_307", 10),
      ("GW_31A", 10),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
