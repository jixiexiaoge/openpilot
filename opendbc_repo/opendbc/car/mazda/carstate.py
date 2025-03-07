from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.mazda.values import DBC, LKAS_LIMITS, MazdaFlags, Buttons

ButtonType = structs.CarState.ButtonEvent.Type
BUTTONS_DICT = {Buttons.SET_PLUS: ButtonType.accelCruise, Buttons.SET_MINUS: ButtonType.decelCruise,
                Buttons.RESUME: ButtonType.resumeCruise, Buttons.CANCEL: ButtonType.cancel}

class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)

    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR"]["GEAR"]

    self.crz_btns_counter = 0
    self.acc_active_last = False
    self.low_speed_alert = False
    self.lkas_allowed_speed = False
    self.lkas_disabled = False

    self.prev_distance_button = 0
    self.distance_button = 0
    self.pcmCruiseGap = 0 # copy from Hyundai

    # 巡航控制相关变量
    self.cruise_buttons = Buttons.NONE
    self.prev_cruise_buttons = Buttons.NONE
    self.cruise_setting = False
    self.is_metric = False  # 用于判断速度单位

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    ret = structs.CarState()

    self.prev_distance_button = self.distance_button
    self.distance_button = cp.vl["CRZ_BTNS"]["DISTANCE_LESS"]

    self.prev_cruise_buttons = self.cruise_buttons

    if bool(cp.vl["CRZ_BTNS"]["SET_P"]):
      self.cruise_buttons = Buttons.SET_PLUS
    elif bool(cp.vl["CRZ_BTNS"]["SET_M"]):
      self.cruise_buttons = Buttons.SET_MINUS
    elif bool(cp.vl["CRZ_BTNS"]["RES"]):
      self.cruise_buttons = Buttons.RESUME
    else:
      self.cruise_buttons = Buttons.NONE

    # 检测是否处于公制单位
    self.is_metric = not cp.vl["CRZ_BTNS"]["MPH_UNIT"]

    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["WHEEL_SPEEDS"]["FL"],
      cp.vl["WHEEL_SPEEDS"]["FR"],
      cp.vl["WHEEL_SPEEDS"]["RL"],
      cp.vl["WHEEL_SPEEDS"]["RR"],
    )
    ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

    # Match panda speed reading
    speed_kph = cp.vl["ENGINE_DATA"]["SPEED"]
    ret.standstill = speed_kph <= .1

    can_gear = int(cp.vl["GEAR"]["GEAR"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))
    ret.gearStep = cp.vl["GEAR"]["GEAR_BOX"]
    ret.engineRpm = cp.vl["ENGINE_DATA"]["RPM"] # for mazda RPM
    # 将CAN总线上的DISTANCE_SETTING值转换为与车辆显示一致的值
    can_distance_setting = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]
    # 假设最大值为4，使用5减去CAN值来获取正确的显示值
    ret.pcmCruiseGap = 5 - can_distance_setting if 1 <= can_distance_setting <= 4 else can_distance_setting

    ret.genericToggle = bool(cp.vl["BLINK_INFO"]["HIGH_BEAMS"])
    ret.leftBlindspot = cp.vl["BSM"]["LEFT_BS_STATUS"] != 0
    ret.rightBlindspot = cp.vl["BSM"]["RIGHT_BS_STATUS"] != 0
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40, cp.vl["BLINK_INFO"]["LEFT_BLINK"] == 1,
                                                                      cp.vl["BLINK_INFO"]["RIGHT_BLINK"] == 1)

    ret.steeringAngleDeg = cp.vl["STEER"]["STEER_ANGLE"]
    ret.steeringTorque = cp.vl["STEER_TORQUE"]["STEER_TORQUE_SENSOR"]
    ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD

    ret.steeringTorqueEps = cp.vl["STEER_TORQUE"]["STEER_TORQUE_MOTOR"]
    ret.steeringRateDeg = cp.vl["STEER_RATE"]["STEER_ANGLE_RATE"]

    # TODO: this should be from 0 - 1.
    ret.brakePressed = cp.vl["PEDALS"]["BRAKE_ON"] == 1
    ret.brake = cp.vl["BRAKE"]["BRAKE_PRESSURE"]

    ret.seatbeltUnlatched = cp.vl["SEATBELT"]["DRIVER_SEATBELT"] == 0
    ret.doorOpen = any([cp.vl["DOORS"]["FL"], cp.vl["DOORS"]["FR"],
                        cp.vl["DOORS"]["BL"], cp.vl["DOORS"]["BR"]])

    # TODO: this should be from 0 - 1.
    ret.gas = cp.vl["ENGINE_DATA"]["PEDAL_GAS"]
    ret.gasPressed = ret.gas > 0

    # Either due to low speed or hands off
    lkas_blocked = cp.vl["STEER_RATE"]["LKAS_BLOCK"] == 1

    if self.CP.minSteerSpeed > 0:
      # LKAS is enabled at 52kph going up and disabled at 45kph going down
      # If the car is going below 45kph, wait for the LKAS_BLOCK signal before disabling
      # to avoid disabling LKAS during a turn where the speed momentarily drops below 45kph...
      self.lkas_allowed_speed = ret.vEgo > (LKAS_LIMITS.ENABLE_SPEED * CV.KPH_TO_MS)
      if self.lkas_allowed_speed:
        self.lkas_disabled = False
      elif lkas_blocked:
        self.lkas_disabled = True
      # ...however, if the car is going below 40kph, disabling LKAS is correct behavior
      elif ret.vEgo < (LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS):
        self.lkas_disabled = True
    else:
      # If the car doesn't have a minimum steer speed, use the LKAS_BLOCK signal
      self.lkas_disabled = lkas_blocked
      self.lkas_allowed_speed = True

    if self.lkas_disabled:
      self.low_speed_alert = True
    else:
      self.low_speed_alert = False

    # The camera on Mazda (and other similar platforms) will continuously send LKAS messages
    # even when LKAS is disabled. We need to analyze the CRZ_CTRL message from the DSU to
    # determine if LKAS is actually enabled, which will tell us if we can send control messages
    # to the car.

    self.cruise_setting = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1 or cp.vl["CRZ_CTRL"]["RESUME_READY"] == 1

    # Check for Cruise active / available
    ret.cruiseState.available = self.cruise_setting or cp.vl["CRZ_CTRL"]["CRZ_READY"] == 1
    ret.cruiseState.enabled = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1
    ret.cruiseState.speed = cp.vl["CRZ_CTRL"]["CRUISE_SPEED"] * CV.KPH_TO_MS
    ret.cruiseState.nonAdaptive = False
    ret.cruiseState.standstill = False

    # Update ACC properties
    ret.cruiseState.speedCluster = cp.vl["CRZ_CTRL"]["CRUISE_SPEED"] * CV.KPH_TO_MS
    ret.cruiseGap = cp.vl["CRZ_CTRL"]["DISTANCE_SETTING"]

    # 通过按钮事件控制巡航功能
    ret.buttonEvents = []

    if self.cruise_buttons != self.prev_cruise_buttons:
      be = structs.CarState.ButtonEvent.new_message()
      be.type = BUTTONS_DICT.get(self.cruise_buttons, ButtonType.unknown)
      ret.buttonEvents.append(be)

    # Update ACC main button state
    ret.cruiseState.available = self.cruise_setting or cp.vl["CRZ_CTRL"]["CRZ_READY"] == 1

    # 保存摄像头相关信息，用于发送HUD警告
    self.cam_lkas = cp_cam.vl["CAM_LKAS"]
    self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]

    return ret

  @staticmethod
  def get_can_parsers(CP):
    signals = [
      # sig_name, sig_address
      ("LEFT_BLINK", "BLINK_INFO"),
      ("RIGHT_BLINK", "BLINK_INFO"),
      ("HIGH_BEAMS", "BLINK_INFO"),
      ("STEER_ANGLE", "STEER"),
      ("STEER_ANGLE_RATE", "STEER_RATE"),
      ("LKAS_BLOCK", "STEER_RATE"),
      ("STEER_TORQUE_SENSOR", "STEER_TORQUE"),
      ("STEER_TORQUE_MOTOR", "STEER_TORQUE"),
      ("FL", "WHEEL_SPEEDS"),
      ("FR", "WHEEL_SPEEDS"),
      ("RL", "WHEEL_SPEEDS"),
      ("RR", "WHEEL_SPEEDS"),
      ("BRAKE_ON", "PEDALS"),
      ("GEAR", "GEAR"),
      ("GEAR_BOX", "GEAR"),
      ("SPEED", "ENGINE_DATA"),
      ("PEDAL_GAS", "ENGINE_DATA"),
      ("RPM", "ENGINE_DATA"),
      ("DRIVER_SEATBELT", "SEATBELT"),
      ("FL", "DOORS"),
      ("FR", "DOORS"),
      ("BL", "DOORS"),
      ("BR", "DOORS"),
      ("BRAKE_PRESSURE", "BRAKE"),
      # Cruise state
      ("CRZ_ACTIVE", "CRZ_CTRL"),
      ("CRZ_READY", "CRZ_CTRL"),
      ("CRUISE_SPEED", "CRZ_CTRL"),
      ("RESUME_READY", "CRZ_CTRL"),
      ("SET_ALLOW", "CRZ_CTRL"),
      ("ACC_ACTIVE", "CRZ_CTRL"),
      ("DISTANCE_SETTING", "CRZ_CTRL"),
      # BSM
      ("LEFT_BS_STATUS", "BSM"),
      ("RIGHT_BS_STATUS", "BSM"),
      # Cruise buttons
      ("SET_P", "CRZ_BTNS"),
      ("SET_M", "CRZ_BTNS"),
      ("RES", "CRZ_BTNS"),
      ("CANCEL", "CRZ_BTNS"),
      ("DISTANCE_LESS", "CRZ_BTNS"),
      ("MPH_UNIT", "CRZ_BTNS"),  # 是否使用MPH单位
    ]

    checks = [
      # sig_address, frequency
      ("BLINK_INFO", 10),
      ("STEER", 80),
      ("STEER_RATE", 80),
      ("STEER_TORQUE", 80),
      ("WHEEL_SPEEDS", 80),
      ("PEDALS", 80),
      ("GEAR", 40),
      ("ENGINE_DATA", 100),
      ("SEATBELT", 10),
      ("DOORS", 10),
      ("BRAKE", 50),
      ("CRZ_CTRL", 50),
      ("BSM", 10),
      ("CRZ_BTNS", 10),
    ]

    # Camera measurements are at 60Hz
    cam_signals = [
      # sig_name, sig_address
      ("BIT_1", "CAM_LKAS"),
      ("ERR_BIT_1", "CAM_LKAS"),
      ("LINE_NOT_VISIBLE", "CAM_LKAS"),
      ("LDW", "CAM_LKAS"),
      ("ERR_BIT_2", "CAM_LKAS"),
      # Lane info
      ("LINE_VISIBLE", "CAM_LANEINFO"),
      ("LINE_NOT_VISIBLE", "CAM_LANEINFO"),
      ("LANE_LINES", "CAM_LANEINFO"),
      ("BIT1", "CAM_LANEINFO"),
      ("BIT2", "CAM_LANEINFO"),
      ("BIT3", "CAM_LANEINFO"),
      ("NO_ERR_BIT", "CAM_LANEINFO"),
      ("S1", "CAM_LANEINFO"),
      ("S1_HBEAM", "CAM_LANEINFO"),
      ("HANDS_WARN_3_BITS", "CAM_LANEINFO"),
      ("HANDS_ON_STEER_WARN", "CAM_LANEINFO"),
      ("HANDS_ON_STEER_WARN_2", "CAM_LANEINFO"),
      ("LDW_WARN_LL", "CAM_LANEINFO"),
      ("LDW_WARN_RL", "CAM_LANEINFO"),
    ]

    cam_checks = [
      # sig_address, frequency
      ("CAM_LKAS", 16),
      ("CAM_LANEINFO", 2),
    ]

    return [
      # pt = powertrain bus
      CANParser(DBC[CP.carFingerprint][Bus.pt], signals, checks, Bus.pt),
      # cam = camera bus
      CANParser(DBC[CP.carFingerprint][Bus.pt], cam_signals, cam_checks, Bus.cam),
      # body = radar bus
      None,
    ]
