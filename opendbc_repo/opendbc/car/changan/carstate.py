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

    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 1000.
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.cluster_min_speed = CV.KPH_TO_MS / 2.

    self.angle_offset = FirstOrderFilter(None, 60.0, DT_CTRL, initialized=False)

    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0
    self.buttonReduce = 0
    self.iacc_pressed_prev = False
    self.plus_pressed_prev = False
    self.minus_pressed_prev = False
    self.iacc_button_counter = 0
    self.plus_button_counter = 0
    self.minus_button_counter = 0

    self.steeringPressed = False
    self.steeringPressedMax = 6
    self.steeringPressedMin = 1

    # Storage for snapshots and counters
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

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # Door / Seatbelt
    ret.doorOpen = any([cp.vl.get("GW_28B", {}).get("BCM_DriverDoorStatus", 0)])
    ret.seatbeltUnlatched = cp.vl.get("GW_50", {}).get("SRS_DriverBuckleSwitchStatus", 0) == 1
    ret.parkingBrake = False

    # Vehicle Speed
    carspd = cp.vl.get("GW_187", {}).get("ESP_VehicleSpeed", 0)
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 0.1

    # Gas, Brake, Gear
    ret.brakePressed = cp.vl.get("GW_196", {}).get("EMS_BrakePedalStatus", 0) != 0
    ret.gasPressed = cp.vl.get("GW_196", {}).get("EMS_RealAccPedal", 0) != 0

    can_gear = cp.vl.get("GW_338", {}).get("TCU_GearForDisplay", 0)
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    # Lights
    ret.leftBlinker = cp.vl.get("GW_28B", {}).get("BCM_TurnIndicatorLeft", 0) == 1
    ret.rightBlinker = cp.vl.get("GW_28B", {}).get("BCM_TurnIndicatorRight", 0) == 1

    # Steering
    ret.steeringAngleOffsetDeg = 0
    ret.steeringAngleDeg = cp.vl.get("GW_180", {}).get("SAS_SteeringAngle", 0)
    ret.steeringRateDeg = cp.vl.get("GW_180", {}).get("SAS_SteeringAngleSpeed", 0)
    ret.steeringTorque = cp.vl.get("GW_17E", {}).get("EPS_MeasuredTorsionBarTorque", 0)
    ret.steeringTorqueEps = (cp.vl.get("GW_170", {}).get("EPS_ActualTorsionBarTorq", 0) - 5533) * self.eps_torque_scale

    # Steering Pressed Logic
    if cp_cam.vl.get("GW_31A", {}).get("STEER_PRESSED", 0) == 1:
      self.steeringPressed = True
    elif abs(ret.steeringTorque) > self.steeringPressedMax:
      self.steeringPressed = True
    elif abs(ret.steeringTorque) < self.steeringPressedMin:
      self.steeringPressed = False
    ret.steeringPressed = self.steeringPressed

    # Cruise Control Logic (GW_28C) - Debounced
    buttons = cp.vl.get("GW_28C", {})
    iacc_button = buttons.get("GW_MFS_IACCenable_switch_signal", 0)
    plus_button = buttons.get("GW_MFS_RESPlus_switch_signal", 0)
    minus_button = buttons.get("GW_MFS_SETReduce_switch_signal", 0)

    # Debounce counters
    self.iacc_button_counter = self.iacc_button_counter + 1 if iacc_button == 1 else 0
    self.plus_button_counter = self.plus_button_counter + 1 if plus_button == 1 else 0
    self.minus_button_counter = self.minus_button_counter + 1 if minus_button == 1 else 0

    # Current debounced states
    iacc_pressed = self.iacc_button_counter >= 2
    plus_pressed = self.plus_button_counter >= 2
    minus_pressed = self.minus_button_counter >= 2

    # Rising edge detection
    iacc_rising_edge = iacc_pressed and not self.iacc_pressed_prev
    plus_rising_edge = plus_pressed and not self.plus_pressed_prev
    minus_rising_edge = minus_pressed and not self.minus_pressed_prev

    if self.cruiseEnable and (iacc_rising_edge or ret.brakePressed):
      self.cruiseEnable = False
    elif not self.cruiseEnable and iacc_rising_edge:
      self.cruiseEnable = True

    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = max(speed, 30.0) if self.cruiseSpeed == 0 else self.cruiseSpeed

    if self.cruiseEnable:
      if plus_rising_edge:
        self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
      if minus_rising_edge:
        self.cruiseSpeed = max(((self.cruiseSpeed // 5) - 1) * 5, 0)

    self.iacc_pressed_prev = iacc_pressed
    self.plus_pressed_prev = plus_pressed
    self.minus_pressed_prev = minus_pressed
    self.cruiseEnablePrev = self.cruiseEnable

    # Cruise State Output
    acc_enable = cp_cam.vl.get("GW_244", {}).get("ACC_ACCEnable", 0)
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.available = acc_enable == 0
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # Lead Vehicle Data from HUD Message
    #ret.radarDistance = cp_cam.vl.get("GW_31A", {}).get("Lead_Distance", 0)

    # Faults
    # ACC_ACCMode is 3-bit in DBC (0: Off, 1: Ready, 2: Active, 7: Fault)
    ret.accFaulted = cp_cam.vl.get("GW_244", {}).get("ACC_ACCMode", 0) == 7 or \
                     cp_cam.vl.get("GW_31A", {}).get("ACC_IACCHWAMode", 0) == 7
    ret.steerFaultTemporary = False # As per reference: "去除方向机故障提示"

    ret.stockFcw = cp_cam.vl.get("GW_244", {}).get("ACC_FCWPreWarning", 0) == 1
    ret.stockAeb = cp_cam.vl.get("GW_244", {}).get("ACC_AEBCtrlType", 0) > 0

    # Snapshots for Controller
    for msg in ["GW_1BA", "GW_244", "GW_307", "GW_31A"]:
      if msg in cp_cam.vl:
        self.sigs[msg] = copy.copy(cp_cam.vl[msg])
    if "GW_17E" in cp.vl:
      self.sigs["GW_17E"] = copy.copy(cp.vl["GW_17E"])

    # Rolling Counters
    self.counter_1ba = cp_cam.vl.get("GW_1BA", {}).get("ACC_RollingCounter_1BA", 0)
    self.counter_244 = cp_cam.vl.get("GW_244", {}).get("ACC_RollingCounter_24E", 0)
    self.counter_17e = cp.vl.get("GW_17E", {}).get("EPS_RollingCounter_17E", 0)
    self.counter_307 = cp_cam.vl.get("GW_307", {}).get("ACC_RollingCounter_35E", 0)
    self.counter_31a = cp_cam.vl.get("GW_31A", {}).get("ACC_RollingCounter_36D", 0)

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_50", 2),
      ("GW_28B", 25),
      ("GW_17E", 100),
      ("GW_180", 100),
      ("GW_187", 100),
      ("GW_196", 100),
      ("GW_28C", 25),
      ("GW_338", 10),
      ("GW_170", 100),
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
