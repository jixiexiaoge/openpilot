from opendbc.can import CANDefine, CANParser
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

    # 马自达车道线融合相关变量
    self.external_fusion_left_lane = -1
    self.external_fusion_right_lane = -1
    self.fusion_enabled = False

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
      # wait for LKAS_BLOCK signal to clear when going up since it lags behind the speed sometimes
      if speed_kph > LKAS_LIMITS.ENABLE_SPEED and not lkas_blocked:
        self.lkas_allowed_speed = True
      elif speed_kph < LKAS_LIMITS.DISABLE_SPEED:
        self.lkas_allowed_speed = False
    else:
      self.lkas_allowed_speed = True

    # TODO: the signal used for available seems to be the adaptive cruise signal, instead of the main on
    #       it should be used for carState.cruiseState.nonAdaptive instead
    ret.cruiseState.available = cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"] == 1
    ret.cruiseState.enabled = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1
    ret.cruiseState.standstill = cp.vl["PEDALS"]["STANDSTILL"] == 1
    ret.cruiseState.speed = cp.vl["CRZ_EVENTS"]["CRZ_SPEED"] * CV.KPH_TO_MS

    # stock lkas should be on
    # TODO: is this needed?
    ret.invalidLkasSetting = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0

        # 在 carstate.py 的 update 方法中
    lane_info = cp_cam.vl["CAM_LANEINFO"]

    # 马自达只有基本的车道线状态
    lane_lines_status = lane_info["LANE_LINES"]

    # 优先使用外部融合结果
    if self.fusion_enabled:
        ret.leftLaneLine = self.external_fusion_left_lane
        ret.rightLaneLine = self.external_fusion_right_lane
    else:
        # 如果没有外部融合，使用原始逻辑
        # 根据状态设置 leftLaneLine 和 rightLaneLine
        # 由于马自达没有类型和颜色信息,只能设置基本值
        if lane_lines_status == 2:  # 两条车道线
            ret.leftLaneLine = 0   # 假设为虚线白色
            ret.rightLaneLine = 0
        elif lane_lines_status == 3:  # 只有左车道线
            ret.leftLaneLine = 0
            ret.rightLaneLine = -1  # 无车道线
        elif lane_lines_status == 4:  # 只有右车道线
            ret.leftLaneLine = -1
            ret.rightLaneLine = 0
        else:  # 无车道线或LKAS禁用
            ret.leftLaneLine = -1
            ret.rightLaneLine = -1

    if ret.cruiseState.enabled:
      if not self.lkas_allowed_speed and self.acc_active_last:
        self.low_speed_alert = True
      else:
        self.low_speed_alert = False
    ret.lowSpeedAlert = self.low_speed_alert

    # Check if LKAS is disabled due to lack of driver torque when all other states indicate
    # it should be enabled (steer lockout). Don't warn until we actually get lkas active
    # and lose it again, i.e, after initial lkas activation
    ret.steerFaultTemporary = self.lkas_allowed_speed and lkas_blocked

    self.acc_active_last = ret.cruiseState.enabled

    self.crz_btns_counter = cp.vl["CRZ_BTNS"]["CTR"]

    # camera signals
    self.lkas_disabled = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0
    self.cam_lkas = cp_cam.vl["CAM_LKAS"]
    self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]
    ret.steerFaultPermanent = cp_cam.vl["CAM_LKAS"]["ERR_BIT_1"] == 1

    self.lkas_previously_enabled = self.lkas_enabled
    self.lkas_enabled = not self.lkas_disabled

    # TODO: add button types for inc and dec
    #ret.buttonEvents = create_button_events(self.distance_button, prev_distance_button, {1: ButtonType.gapAdjustCruise})
    ret.buttonEvents = [
      *create_button_events(self.cruise_buttons, self.prev_cruise_buttons, BUTTONS_DICT),
      *create_button_events(self.distance_button, self.prev_distance_button, {1: ButtonType.gapAdjustCruise}),
      #*create_button_events(self.lkas_enabled, self.lkas_previously_enabled, {1: ButtonType.lfaButton}),
    ]
    return ret

  def set_lane_fusion_result(self, left_lane, right_lane, enabled=False):
    """
    设置外部车道线融合结果
    由LanePlanner调用来更新融合后的车道线信息
    """
    self.external_fusion_left_lane = left_lane
    self.external_fusion_right_lane = right_lane
    self.fusion_enabled = enabled

  def get_lane_fusion_result(self):
    """
    获取当前的车道线融合结果
    供LanePlanner查询使用
    """
    return {
      'left_lane': self.external_fusion_left_lane,
      'right_lane': self.external_fusion_right_lane,
      'enabled': self.fusion_enabled
    }

  @staticmethod
  def get_can_parsers(CP):
    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], [], 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], [], 2),
    }
