import copy
from opendbc.can import CANDefine, CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.carlog import carlog
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.tesla.teslacan import get_steer_ctrl_type
from opendbc.car.tesla.values import DBC, CANBUS, GEAR_MAP, STEER_THRESHOLD, TeslaFlags

from opendbc.iqpilot.car.tesla.carstate_ext import CarStateExt
from opendbc.iqpilot.car.tesla.values import TeslaFlagsIQ

ButtonType = structs.CarState.ButtonEvent.Type


class CarState(CarStateBase, CarStateExt):
  def __init__(self, CP, CP_IQ):
    CarStateBase.__init__(self, CP, CP_IQ)
    CarStateExt.__init__(self, CP, CP_IQ)
    self.can_define = CANDefine(DBC[CP.carFingerprint][Bus.party])
    self.shifter_values = self.can_define.dv["DI_systemStatus"]["DI_gear"]

    self.summon = False
    self.summon_prev = False
    self.cruise_enabled_prev = False
    self.fsd14_error_logged = False
    self.suspected_fsd14 = False
    self.suspected_fsd14_clear_frames = 0

    self.hands_on_level = 0
    self.acc_state_last = 0
    self.das_control = None
    self.das_body_controls_dat = b""
    self.cruise_override = False

  def update_summon_state(self, summon_state: str, cruise_enabled: bool):
    summon_now = summon_state in ("ACTIVE", "COMPLETE", "SELFPARK_STARTED")
    if summon_now and not self.summon_prev and not self.cruise_enabled_prev:
      self.summon = True
    if not summon_now:
      self.summon = False
    self.summon_prev = summon_now
    self.cruise_enabled_prev = cruise_enabled

  def update(self, can_parsers) -> tuple[structs.CarState, structs.IQCarState]:
    cp_party = can_parsers[Bus.party]
    cp_ap_party = can_parsers[Bus.ap_party]
    ret = structs.CarState()
    ret_iq = structs.IQCarState()
    scale_speed = 1.01
    length = 0.11

  # Vehicle speed
    ret.vEgoRaw = cp_party.vl["DI_speed"]["DI_vehicleSpeed"] * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)

    # Displayed speed
    ui_speed_units = self.can_define.dv["DI_speed"]["DI_uiSpeedUnits"].get(int(cp_party.vl["DI_speed"]["DI_uiSpeedUnits"]), None)
    if ui_speed_units == "DI_SPEED_KPH":
      ret.vEgoCluster = cp_party.vl["DI_speed"]["DI_uiSpeed"] * CV.KPH_TO_MS
    elif ui_speed_units == "DI_SPEED_MPH":
      ret.vEgoCluster = cp_party.vl["DI_speed"]["DI_uiSpeed"] * CV.MPH_TO_MS

    # Gas pedal
    ret.gasPressed = cp_party.vl["DI_systemStatus"]["DI_accelPedalPos"] > 0

    # Brake pedal
    ret.brake = 0
    ret.brakePressed = cp_party.vl["ESP_status"]["ESP_driverBrakeApply"] == 2

    # Steering wheel
    epas_status = cp_party.vl["EPAS3S_sysStatus"]
    self.hands_on_level = epas_status["EPAS3S_handsOnLevel"]
    ret.steeringAngleDeg = -epas_status["EPAS3S_internalSAS"]
    ret.steeringRateDeg = -cp_ap_party.vl["SCCM_steeringAngleSensor"]["SCCM_steeringAngleSpeed"]
    ret.steeringTorque = -epas_status["EPAS3S_torsionBarTorque"]
    ret.steeringTorqueEps = -epas_status["EPAS3S_steeringRackForce"] * length / self.CP.steerRatio

    # stock handsOnLevel uses >0.5 for 0.25s, but is too slow
    ret.steeringPressed = self.update_steering_pressed(abs(ret.steeringTorque) > STEER_THRESHOLD, 5)

    eac_status = self.can_define.dv["EPAS3S_sysStatus"]["EPAS3S_eacStatus"].get(int(epas_status["EPAS3S_eacStatus"]), None)
    ret.steerFaultPermanent = eac_status == "EAC_FAULT"
    ret.steerFaultTemporary = eac_status == "EAC_INHIBITED"

    # FSD disengages using union of handsOnLevel (slow overrides) and high angle rate faults (fast overrides, high speed)
    eac_error_code = self.can_define.dv["EPAS3S_sysStatus"]["EPAS3S_eacErrorCode"].get(int(epas_status["EPAS3S_eacErrorCode"]), None)
    ret.steeringDisengage = self.hands_on_level >= 3 or (eac_status == "EAC_INHIBITED" and
                                                         eac_error_code == "EAC_ERROR_HIGH_ANGLE_RATE_SAFETY")

    # Cruise state
    cruise_state = self.can_define.dv["DI_state"]["DI_cruiseState"].get(int(cp_party.vl["DI_state"]["DI_cruiseState"]), None)
    speed_units = self.can_define.dv["DI_state"]["DI_speedUnits"].get(int(cp_party.vl["DI_state"]["DI_speedUnits"]), None)
    acc_state = cp_ap_party.vl["DAS_control"]["DAS_accState"]
    # Respect all stock DAS cancel states, not just ACC_CANCEL_GENERIC_SILENT(13).
    # ELDA/ELK triggers ACC_CANCEL_GENERIC(0) which must also be forwarded.
    self.das_accCancel = acc_state in (0, 1, 2, 12, 13, 14, 15)

    summon_state = self.can_define.dv["DI_state"]["DI_autoparkState"].get(int(cp_party.vl["DI_state"]["DI_autoparkState"]), None)
    cruise_enabled = cruise_state in ("ENABLED", "STANDSTILL", "OVERRIDE", "PRE_FAULT", "PRE_CANCEL")
    self.cruise_override = cruise_state in ("OVERRIDE")
    self.update_summon_state(summon_state, cruise_enabled)

    # Match panda safety cruise engaged logic
    ret.cruiseState.enabled = cruise_enabled and not self.summon
    if speed_units == "KPH":
      ret.cruiseState.speedCluster = cp_party.vl["DI_state"]["DI_digitalSpeed"] * CV.KPH_TO_MS
    elif speed_units == "MPH":
      ret.cruiseState.speedCluster = cp_party.vl["DI_state"]["DI_digitalSpeed"] * CV.MPH_TO_MS
    ret.cruiseState.speed = max(ret.cruiseState.speedCluster / scale_speed, 1e-3)
    ret.cruiseState.available = cruise_state == "STANDBY" or ret.cruiseState.enabled
    ret.cruiseState.standstill = False  # This needs to be false, since we can resume from stop without sending anything special
    ret.standstill = cp_party.vl["ESP_B"]["ESP_vehicleStandstillSts"] == 1
    ret.accFaulted = cruise_state == "FAULT"

    ret.buttonEvents = [*create_button_events(acc_state, self.acc_state_last, {0: ButtonType.cancel, 13: ButtonType.cancel})]
    self.acc_state_last = acc_state


    # Gear
    ret.gearShifter = GEAR_MAP[self.can_define.dv["DI_systemStatus"]["DI_gear"].get(int(cp_party.vl["DI_systemStatus"]["DI_gear"]), "DI_GEAR_INVALID")]

    # Doors
    ret.doorOpen = cp_party.vl["UI_warning"]["anyDoorOpen"] == 1

    # Blinkers
    ret.leftBlinker = cp_party.vl["UI_warning"]["leftBlinkerBlinking"] in (1, 2)
    ret.rightBlinker = cp_party.vl["UI_warning"]["rightBlinkerBlinking"] in (1, 2)

    # Seatbelt
    ret.seatbeltUnlatched = cp_party.vl["UI_warning"]["buckleStatus"] != 1

    # Blindspot
    ret.leftBlindspot = cp_ap_party.vl["DAS_status"]["DAS_blindSpotRearLeft"] != 0
    ret.rightBlindspot = cp_ap_party.vl["DAS_status"]["DAS_blindSpotRearRight"] != 0

    # AEB
    ret.stockAeb = cp_ap_party.vl["DAS_control"]["DAS_aebEvent"] == 1

    # LKAS
    # On FSD 14+, ANGLE_CONTROL behavior changed to allow user winddown while actuating.
    # FSD switched from using ANGLE_CONTROL to LANE_KEEP_ASSIST to likely keep the old steering override disengage logic.
    # LKAS switched from LANE_KEEP_ASSIST to ANGLE_CONTROL to likely allow overriding LKAS events smoothly
    lkas_ctrl_type = get_steer_ctrl_type(self.CP.flags, 2)
    ret.stockLkas = cp_ap_party.vl["DAS_steeringControl"]["DAS_steeringControlType"] == lkas_ctrl_type  # LANE_KEEP_ASSIST

    if not (self.CP.flags & TeslaFlags.MISSING_DAS_SETTINGS):
      ret.invalidLkasSetting = cp_ap_party.vl["DAS_status"]["DAS_autopilotState"] not in (0, 1, 2)  # DISABLED, UNAVAILABLE, AVAILABLE

      # Because we don't have FSD 14 detection outside of a set of FW, we should check if this FW is accidentally missing from FSD_14_FW
      # 1. If in Autosteer or FSD, already caught by invalidLkasSetting
      # 2. If in TACC and DAS ever sends ANGLE_CONTROL (1), we can infer it's trying to do LKAS on FSD 14+
      # NOTE: Tesla's latest firmware changed ELDA (Emergency Lane Departure Assist) to use ANGLE_CONTROL (1)
      # instead of EMERGENCY_LANE_KEEP (3). Exclude ELDA by checking eac_status so it doesn't latch suspected_fsd14.
      eac_is_emergency = eac_status == "EMERGENCY_LANE_KEEP"
      angle_control = cp_ap_party.vl["DAS_steeringControl"]["DAS_steeringControlType"] == 1 and not eac_is_emergency  # ANGLE_CONTROL, excluding ELDA
      if not ret.invalidLkasSetting and angle_control and not self.CP.flags & TeslaFlags.FSD_14:
        self.suspected_fsd14 = True
        self.suspected_fsd14_clear_frames = 0

      if self.suspected_fsd14:
        ret.invalidLkasSetting = True
        if not self.fsd14_error_logged:
          carlog.error("FSD 14 detected, but FW not in FSD_14_FW set")
          self.fsd14_error_logged = True
        # Un-latch if ANGLE_CONTROL has been absent for ~3 s (100 frames @ ~33 Hz).
        # This allows re-engagement after transient triggers (e.g. if ELDA slips through on new FW variants).
        if not angle_control:
          self.suspected_fsd14_clear_frames += 1
          if self.suspected_fsd14_clear_frames >= 100:
            self.suspected_fsd14 = False
            self.suspected_fsd14_clear_frames = 0
        else:
          self.suspected_fsd14_clear_frames = 0

    # Buttons # ToDo: add Gap adjust button

    # Messages needed by carcontroller
    self.das_control = copy.copy(cp_ap_party.vl["DAS_control"])

    # Raw stock DAS_bodyControls bytes (bus 2), used to ride the blinker on the vehicle bus.
    if Bus.cam in can_parsers:
      self.das_body_controls_dat = bytes(can_parsers[Bus.cam].dat.get(0x3E9, b""))

    CarStateExt.update(self, ret, ret_iq, can_parsers)

    return ret, ret_iq

  @staticmethod
  def get_can_parsers(CP, CP_IQ):
    parsers = {
      Bus.party: CANParser(DBC[CP.carFingerprint][Bus.party], [], CANBUS.party),
      Bus.ap_party: CANParser(DBC[CP.carFingerprint][Bus.party], [], CANBUS.autopilot_party),
      **CarStateExt.get_parser(CP, CP_IQ),
    }
    # Stock DAS_bodyControls from the AP bus (bus 2) for the nav blinker.
    if CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS and Bus.adas in DBC[CP.carFingerprint]:
      parsers[Bus.cam] = CANParser(DBC[CP.carFingerprint][Bus.adas], [("DAS_bodyControls", 2)], CANBUS.autopilot_party)
    return parsers
