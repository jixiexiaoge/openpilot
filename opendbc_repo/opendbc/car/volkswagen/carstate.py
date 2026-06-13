"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import sys
import os
import math
import time
import calendar
from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.interfaces import CarStateBase
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.volkswagen.values import CAR, DBC, CanBus, NetworkLocation, RADAR_DISABLE_STATE, TransmissionType, GearShifter, \
                                                      CarControllerParams, VolkswagenFlags, VolkswagenFlagsIQ
from opendbc.car.volkswagen.speed_limit_manager import SpeedLimitManager
from openpilot.iqpilot.konn3kt.iqlvbs import alc as iq_lvbs_alc

iqpilot_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, iqpilot_path)
try:
  from openpilot.common.params import Params
except ImportError:
  pass

ButtonType = structs.CarState.ButtonEvent.Type


class CarState(CarStateBase):
  CRUISE_FAULT_LATERAL_ENABLE_FRAMES = 5
  CRUISE_FAULT_LATERAL_DISABLE_FRAMES = 20
  MEB_TEMP_CRUISE_FAULT = 6
  MEB_TOLERANCE_MAX = 100

  def __init__(self, CP, CP_IQ):
    super().__init__(CP, CP_IQ)
    self._params = Params()
    self.frame = 0
    self.eps_init_complete = False
    self.CCP = CarControllerParams(CP)
    self.button_states = {button.event_type: False for button in self.CCP.BUTTONS}
    self.esp_hold_confirmation = False
    self.upscale_lead_car_signal = False
    self.eps_stock_values = False
    self.curvature = 0.
    self.klr_stock_values = {}
    self.ea_hud_stock_values = {}
    self.ea_control_stock_values = {}
    self.acc_type = 0
    self.acc_stock_counters: dict[str, int] = {}
    self.esp_stopping = False
    self.tsk_brake_torque = 0.0
    self.last_cruiseActive = False
    self.cruise_faulted_frames = 0
    self.cruise_fault_clear_frames = 0
    self.cruise_fault_lateral_active = False
    self.cruise_faulted = False
    self.grade = 0.0
    self.rolling_backward = False
    self.rolling_forward = False
    self.sum_wegimpulse = 0
    self.speed_limit_mgr = SpeedLimitManager(CP)
    self.enable_predicative_speed_limit = False
    self.enable_speed_limit_predicative = False
    self.enable_pred_react_to_speed_limits = False
    self.enable_pred_react_to_curves = False
    self.speed_limit_predicative_type = 0
    self.force_rhd_for_bsm = False
    self.grade = 0.0
    self.rolling_backward = False
    self.rolling_forward = False
    self.sum_wegimpulse = 0
    self.travel_assist_available = False
    self.left_blinker_active = False
    self.right_blinker_active = False
    self._param_update_time = 0.0
    self.cruise_recovery_timer = 0
    self.tolerance_counter = self.MEB_TOLERANCE_MAX
    self.lkas_button = 0
    self.prev_lkas_button = 0
    self.vw_iq_lvbs_alc_available = False
    self.vw_iq_lvbs_alc_entering = False
    self.vw_iq_lvbs_alc_active = False
    self.vw_iq_lvbs_alc_key_slot = 0
    self.EPS_ALC_Status = 0
    self.EPS_ALC_Abbruch = 0
    self.PQ_ALC_Status_raw = 0
    self.alcOverrideAlert = False
    self.bremse8_stock = None
    self.cruise_main_switch = False

  def _apply_iq_private_flags(self, ret_iq: structs.IQCarState) -> None:
    ret_iq.alcOverrideAlert = bool(self.alcOverrideAlert)

  def update_button_enable(self, buttonEvents: list[structs.CarState.ButtonEvent]):
    if not self.CP.pcmCruise:
      if self.cruise_fault_lateral_active and self.cruise_faulted:
        return False
      for b in buttonEvents:
        # Enable OP long on falling edge of enable buttons
        if b.type in (ButtonType.setCruise, ButtonType.resumeCruise) and not b.pressed:
          return True
    return False

  def create_button_events(self, pt_cp, buttons):
    button_events = []

    for button in buttons:
      state = pt_cp.vl[button.can_addr][button.can_msg] in button.values
      if self.button_states[button.event_type] != state:
        event = structs.CarState.ButtonEvent()
        event.type = button.event_type
        event.pressed = state
        button_events.append(event)
      self.button_states[button.event_type] = state

    return button_events

  def _update_mqb_iq_alc_state(self, pt_cp):
    iq_lvbs_alc.update_mqb_carstate_alc_state(self, pt_cp)

  def _update_pq_iq_alc_state(self, pt_cp):
    iq_lvbs_alc.update_pq_carstate_alc_state(self, pt_cp)

  def update(self, can_parsers) -> tuple[structs.CarState, structs.IQCarState]:
    pt_cp = can_parsers[Bus.pt]
    cam_cp = can_parsers[Bus.cam]
    ext_cp = pt_cp if self.CP.networkLocation == NetworkLocation.fwdCamera else cam_cp

    if self.CP.flags & VolkswagenFlags.PQ:
      aux_cp = can_parsers.get(Bus.aux)
      return self.update_pq(pt_cp, cam_cp, ext_cp, aux_cp)
    elif self.CP.flags & VolkswagenFlags.MLB:
      br_cp = can_parsers[Bus.aux]
      return self.update_mlb(pt_cp, br_cp, cam_cp, ext_cp)
    elif self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      main_cp = can_parsers[Bus.main]
      return self.update_meb(pt_cp, main_cp, cam_cp, ext_cp)

    ret = structs.CarState()
    ret_iq = structs.IQCarState()

    if self.CP.transmissionType == TransmissionType.direct:
      ret.gearShifter = self.parse_gear_shifter(self.CCP.shifter_values.get(pt_cp.vl["Motor_EV_01"]["MO_Waehlpos"], None))
    elif self.CP.transmissionType == TransmissionType.manual:
      if bool(pt_cp.vl["Gateway_72"]["BCM1_Rueckfahrlicht_Schalter"]):
        ret.gearShifter = GearShifter.reverse
      else:
        ret.gearShifter = GearShifter.drive
    else:
      ret.gearShifter = self.parse_gear_shifter(self.CCP.shifter_values.get(pt_cp.vl["Gateway_73"]["GE_Fahrstufe"], None))

    if True:
      # MQB-specific
      if self.CP.flags & VolkswagenFlags.KOMBI_PRESENT:
        self.upscale_lead_car_signal = bool(pt_cp.vl["Kombi_03"]["KBI_Variante"])  # Analog v digital instrument cluster

      self.parse_wheel_speeds(ret,
        pt_cp.vl["ESP_19"]["ESP_VL_Radgeschw_02"],
        pt_cp.vl["ESP_19"]["ESP_VR_Radgeschw_02"],
        pt_cp.vl["ESP_19"]["ESP_HL_Radgeschw_02"],
        pt_cp.vl["ESP_19"]["ESP_HR_Radgeschw_02"],
      )

      self.rolling_backward = (
        pt_cp.vl["ESP_10"]["ESP_HR_Fahrtrichtung"] == 1 or
        pt_cp.vl["ESP_10"]["ESP_HL_Fahrtrichtung"] == 1 or
        pt_cp.vl["ESP_10"]["ESP_VR_Fahrtrichtung"] == 1 or
        pt_cp.vl["ESP_10"]["ESP_VL_Fahrtrichtung"] == 1
      )
      self.rolling_forward = (
        pt_cp.vl["ESP_10"]["ESP_HR_Fahrtrichtung"] == 0 or
        pt_cp.vl["ESP_10"]["ESP_HL_Fahrtrichtung"] == 0 or
        pt_cp.vl["ESP_10"]["ESP_VR_Fahrtrichtung"] == 0 or
        pt_cp.vl["ESP_10"]["ESP_VL_Fahrtrichtung"] == 0
      )
      self.sum_wegimpulse = int(
        pt_cp.vl["ESP_10"]["ESP_Wegimpuls_VL"] +
        pt_cp.vl["ESP_10"]["ESP_Wegimpuls_VR"] +
        pt_cp.vl["ESP_10"]["ESP_Wegimpuls_HL"] +
        pt_cp.vl["ESP_10"]["ESP_Wegimpuls_HR"]
      )

      if self.CP.flags & VolkswagenFlags.STOCK_HCA_PRESENT:
        ret.carFaultedNonCritical = bool(cam_cp.vl["HCA_01"]["EA_Ruckfreigabe"]) or cam_cp.vl["HCA_01"]["EA_ACC_Sollstatus"] > 0  # EA

      ret.brake = pt_cp.vl["ESP_05"]["ESP_Bremsdruck"] / 250.0  # FIXME: this is pressure in Bar, not sure what OP expects
      brake_pedal_pressed = bool(pt_cp.vl["Motor_14"]["MO_Fahrer_bremst"])
      brake_pressure_detected = bool(pt_cp.vl["ESP_05"]["ESP_Fahrer_bremst"])
      ret.brakePressed = brake_pedal_pressed or brake_pressure_detected
      ret.parkingBrake = bool(pt_cp.vl["Kombi_01"]["KBI_Handbremse"])  # FIXME: need to include an EPB check as well

      ret.doorOpen = any([pt_cp.vl["Gateway_72"]["ZV_FT_offen"],
                          pt_cp.vl["Gateway_72"]["ZV_BT_offen"],
                          pt_cp.vl["Gateway_72"]["ZV_HFS_offen"],
                          pt_cp.vl["Gateway_72"]["ZV_HBFS_offen"],
                          pt_cp.vl["Gateway_72"]["ZV_HD_offen"]])

      if self.CP.enableBsm:
        # Infostufe: BSM LED on, Warnung: BSM LED flashing
        ret.leftBlindspot = bool(ext_cp.vl["SWA_01"]["SWA_Infostufe_SWA_li"]) or bool(ext_cp.vl["SWA_01"]["SWA_Warnung_SWA_li"])
        ret.rightBlindspot = bool(ext_cp.vl["SWA_01"]["SWA_Infostufe_SWA_re"]) or bool(ext_cp.vl["SWA_01"]["SWA_Warnung_SWA_re"])

      if not (self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR):
        ret.stockFcw = bool(ext_cp.vl["ACC_10"]["AWV2_Freigabe"])
        ret.stockAeb = bool(ext_cp.vl["ACC_10"]["ANB_Teilbremsung_Freigabe"]) or bool(ext_cp.vl["ACC_10"]["ANB_Zielbremsung_Freigabe"])
      else:
        ret.stockFcw = False
        ret.stockAeb = False

      cc_only = self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY or self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR
      self.acc_type = 0 if cc_only else ext_cp.vl["ACC_06"]["ACC_Typ"]
      if not cc_only:
        self.acc_stock_counters["ACC_02"] = int(ext_cp.vl["ACC_02"]["COUNTER"])
        self.acc_stock_counters["ACC_06"] = int(ext_cp.vl["ACC_06"]["COUNTER"])
        self.acc_stock_counters["ACC_07"] = int(ext_cp.vl["ACC_07"]["COUNTER"])
        self.acc_stock_counters["ACC_10"] = int(ext_cp.vl["ACC_10"]["COUNTER"])
      self.esp_stopping = bool(pt_cp.vl["ESP_21"]["ESP_Anhaltevorgang_ACC_aktiv"])
      self.esp_hold_confirmation = bool(pt_cp.vl["ESP_21"]["ESP_Haltebestaetigung"])
      self.tsk_brake_torque = pt_cp.vl["TSK_06"]["TSK_Radbremsmom"] if pt_cp.vl["TSK_06"]["TSK_Freig_Verzoeg_Anf"] else 0.0
      self.grade = pt_cp.vl["Motor_16"]["TSK_Steigung"]
      acc_limiter_mode = False if cc_only else ext_cp.vl["ACC_02"]["ACC_Gesetzte_Zeitluecke"] == 0
      speed_limiter_mode = bool(pt_cp.vl["TSK_06"]["TSK_Limiter_ausgewaehlt"])

      self._update_mqb_iq_alc_state(pt_cp)

      ret.cruiseState.available = pt_cp.vl["TSK_06"]["TSK_Status"] in (2, 3, 4, 5)
      ret.cruiseState.enabled = pt_cp.vl["TSK_06"]["TSK_Status"] in (3, 4, 5)
      ret.cruiseState.speed = 0 if cc_only else ext_cp.vl["ACC_02"]["ACC_Wunschgeschw_02"] * CV.KPH_TO_MS if self.CP.pcmCruise else 0
      ret.accFaulted = pt_cp.vl["TSK_06"]["TSK_Status"] in (6, 7)

      ret.leftBlinker = bool(pt_cp.vl["Blinkmodi_02"]["Comfort_Signal_Left"])
      ret.rightBlinker = bool(pt_cp.vl["Blinkmodi_02"]["Comfort_Signal_Right"])

    # Shared logic
    ret.vEgoCluster = pt_cp.vl["Kombi_01"]["KBI_angez_Geschw"] * CV.KPH_TO_MS

    if ret.cruiseState.speed > 0 and ret.vEgo > 1.0:
      cluster_ratio = ret.vEgoCluster / ret.vEgo
      ret.cruiseState.speedCluster = ret.cruiseState.speed * cluster_ratio

    self.parse_mlb_mqb_steering_state(ret, pt_cp)

    ret.gasPressed = pt_cp.vl["Motor_20"]["MO_Fahrpedalrohwert_01"] > 0
    ret.espActive = bool(pt_cp.vl["ESP_21"]["ESP_Eingriff"])
    ret.espDisabled = pt_cp.vl["ESP_21"]["ESP_Tastung_passiv"] != 0
    ret.seatbeltUnlatched = pt_cp.vl["Airbag_02"]["AB_Gurtschloss_FA"] != 3

    ret.standstill = ret.vEgoRaw == 0
    ret.cruiseState.standstill = self.CP.pcmCruise and self.esp_hold_confirmation
    ret.cruiseState.nonAdaptive = acc_limiter_mode or speed_limiter_mode
    if ret.cruiseState.speed > 90:
      ret.cruiseState.speed = 0

    self.eps_stock_values = pt_cp.vl["LH_EPS_03"]
    self.ldw_stock_values = cam_cp.vl["LDW_02"] if self.CP.networkLocation == NetworkLocation.fwdCamera else {}
    self.gra_stock_values = pt_cp.vl["GRA_ACC_01"]

    ret.buttonEvents = self.create_button_events(pt_cp, self.CCP.BUTTONS)

    ret.lowSpeedAlert = self.update_low_speed_alert(ret.vEgo)
    ret.cruiseFaultLateralMode = False
    ret.lateralAvailable = ret.cruiseState.available
    ret.blockPcmEnable = False

    ret.fuelGauge = pt_cp.vl["Kombi_02"]["KBI_Inhalt_Tank"] / 55.0
    ret.fuelTankLevelL = pt_cp.vl["Kombi_02"]["KBI_Inhalt_Tank"]  # raw liters for konn3kt

    self.cruise_faulted = ret.accFaulted
    self._apply_iq_private_flags(ret_iq)
    self.frame += 1
    return ret, ret_iq

  def update_meb(self, pt_cp, main_cp, cam_cp, ext_cp) -> tuple[structs.CarState, structs.IQCarState]:
    ret = structs.CarState()
    ret_iq = structs.IQCarState()

    if time.monotonic() - self._param_update_time > 2.0:
      self.enable_speed_limit_predicative = self._params.get_bool("EnableSpeedLimitPredicative")
      self.enable_pred_react_to_speed_limits = self._params.get_bool("EnableSLPredReactToSL")
      self.enable_pred_react_to_curves = self._params.get_bool("EnableSLPredReactToCurves")
      self._param_update_time = time.monotonic()

    self.parse_wheel_speeds(ret,
      pt_cp.vl["ESC_51"]["VL_Radgeschw"],
      pt_cp.vl["ESC_51"]["VR_Radgeschw"],
      pt_cp.vl["ESC_51"]["HL_Radgeschw"],
      pt_cp.vl["ESC_51"]["HR_Radgeschw"],
    )

    if self.CP.flags & VolkswagenFlags.KOMBI_PRESENT:
      ret.vEgoCluster = pt_cp.vl["Kombi_01"]["KBI_angez_Geschw"] * CV.KPH_TO_MS
    ret.standstill = ret.vEgoRaw == 0

    ret.steeringAngleDeg = pt_cp.vl["LWI_01"]["LWI_Lenkradwinkel"] * (1, -1)[int(pt_cp.vl["LWI_01"]["LWI_VZ_Lenkradwinkel"])]
    ret.steeringRateDeg = pt_cp.vl["LWI_01"]["LWI_Lenkradw_Geschw"] * (1, -1)[int(pt_cp.vl["LWI_01"]["LWI_VZ_Lenkradw_Geschw"])]
    ret.steeringTorque = pt_cp.vl["LH_EPS_03"]["EPS_Lenkmoment"] * (1, -1)[int(pt_cp.vl["LH_EPS_03"]["EPS_VZ_Lenkmoment"])]
    ret.steeringPressed = abs(ret.steeringTorque) > self.CCP.STEER_DRIVER_ALLOWANCE

    self.curvature = -pt_cp.vl["QFK_01"]["Curvature"] * (1, -1)[int(pt_cp.vl["QFK_01"]["Curvature_VZ"])]
    ret.steeringCurvature = self.curvature
    ret.yawRate = -pt_cp.vl["ESC_50"]["Yaw_Rate"] * (1, -1)[int(pt_cp.vl["ESC_50"]["Yaw_Rate_Sign"])] * CV.DEG_TO_RAD

    if self.CP.flags & VolkswagenFlags.ALT_GEAR:
      gear_raw = pt_cp.vl["Gateway_73"]["GE_Fahrstufe"]
    else:
      gear_raw = pt_cp.vl["Getriebe_11"]["GE_Fahrstufe"]
    ret.gearShifter = self.parse_gear_shifter(self.CCP.shifter_values.get(gear_raw, None))
    drive_mode = ret.gearShifter == GearShifter.drive

    hca_status = self.CCP.hca_status_values.get(pt_cp.vl["QFK_01"]["LatCon_HCA_Status"])
    ret.steerFaultTemporary, ret.steerFaultPermanent = self.update_hca_state(hca_status, drive_mode=drive_mode)

    self.eps_stock_values = pt_cp.vl["LH_EPS_03"]
    self.klr_stock_values = pt_cp.vl["KLR_01"] if self.CP.flags & VolkswagenFlags.STOCK_KLR_PRESENT else {}
    self.ea_hud_stock_values = cam_cp.vl["EA_02"]
    self.ea_control_stock_values = cam_cp.vl["EA_01"]
    ret.carFaultedNonCritical = cam_cp.vl["EA_01"]["EA_Funktionsstatus"] in (3, 4, 5, 6)

    ret.gasPressed = pt_cp.vl["Motor_51"]["Accel_Pedal_Pressure"] > 0  # Motor_54 has unreliable offset on MQBevo
    ret.brakePressed = bool(pt_cp.vl["Motor_14"]["MO_Fahrer_bremst"])
    ret.brake = pt_cp.vl["ESC_51"]["Brake_Pressure"]

    ret.parkingBrake = pt_cp.vl["ESC_50"]["EPB_Status"] in (1, 4)

    doors = pt_cp.vl["ZV_02"] if bool(pt_cp.vl["Gateway_72"]["ZV_02_alt"]) else pt_cp.vl["Gateway_72"]
    ret.doorOpen = any([doors["ZV_FT_offen"],
                        doors["ZV_BT_offen"],
                        doors["ZV_HFS_offen"],
                        doors["ZV_HBFS_offen"],
                        doors["ZV_HD_offen"]])

    ret.seatbeltUnlatched = pt_cp.vl["Airbag_02"]["AB_Gurtschloss_FA"] != 3

    if self.CP.enableBsm:
      bsm_bus = pt_cp if self.CP.flags & (VolkswagenFlags.MEB_GEN2 | VolkswagenFlags.MQB_EVO) else ext_cp
      blindspot_driver = bool(bsm_bus.vl["MEB_Side_Assist_01"]["Blind_Spot_Info_Driver"]) or bool(bsm_bus.vl["MEB_Side_Assist_01"]["Blind_Spot_Warn_Driver"])
      blindspot_passenger = bool(bsm_bus.vl["MEB_Side_Assist_01"]["Blind_Spot_Info_Passenger"]) or bool(bsm_bus.vl["MEB_Side_Assist_01"]["Blind_Spot_Warn_Passenger"])
      force_rhd = self.force_rhd_for_bsm or self._params.get_bool("ForceRHDForBSM")
      car_is_lhd = not force_rhd
      ret.leftBlindspot = blindspot_driver if car_is_lhd else blindspot_passenger
      ret.rightBlindspot = blindspot_passenger if car_is_lhd else blindspot_driver

    self.ldw_stock_values = cam_cp.vl["LDW_02"]

    awv_values = ext_cp.vl.get("AWV_03", ext_cp.vl.get("ACC_10", {}))
    ret.stockFcw = bool(awv_values.get("FCW_Active", 0)) or bool(awv_values.get("AWV2_Freigabe", 0))
    ret.stockAeb = False

    self.acc_type = ext_cp.vl["ACC_18"]["ACC_Typ"]
    self.travel_assist_available = bool(pt_cp.vl.get("TA_01", {}).get("Travel_Assist_Available", 0))

    ret.cruiseState.available = pt_cp.vl["Motor_51"]["TSK_Status"] in (2, 3, 4, 5)
    ret.cruiseState.enabled = pt_cp.vl["Motor_51"]["TSK_Status"] in (3, 4, 5)
    acc_values = ext_cp.vl.get("MEB_ACC_01", ext_cp.vl.get("ACC_19", {}))
    ret.cruiseState.nonAdaptive = bool(acc_values.get("ACC_Limiter_Mode", 0)) if self.CP.pcmCruise else bool(pt_cp.vl["Motor_51"]["TSK_Limiter_ausgewaehlt"])

    acc_faulted = pt_cp.vl["Motor_51"]["TSK_Status"] in (6, 7)
    ret.accFaulted = self.update_acc_fault(acc_faulted, parking_brake=ret.parkingBrake, drive_mode=drive_mode)

    if self.CP.flags & VolkswagenFlags.MQB_EVO:
      self.esp_hold_confirmation = bool(pt_cp.vl["ESP_21"]["ESP_Haltebestaetigung"])
    else:
      self.esp_hold_confirmation = pt_cp.vl["ESC_50"]["Motion_State"] == 3
    ret.cruiseState.standstill = self.CP.pcmCruise and self.esp_hold_confirmation

    if self.CP.pcmCruise:
      ret.cruiseState.speed = float(int(round(acc_values.get("ACC_Wunschgeschw_02", 0)))) * CV.KPH_TO_MS
      if ret.cruiseState.speed > 90:
        ret.cruiseState.speed = 0

    if ret.cruiseState.speed > 0 and ret.vEgo > 1.0 and ret.vEgoCluster > 0:
      cluster_ratio = ret.vEgoCluster / ret.vEgo
      ret.cruiseState.speedCluster = ret.cruiseState.speed * cluster_ratio

    raining = pt_cp.vl["RLS_01"]["RS_Regenmenge"] > 0
    vze_01_values = cam_cp.vl.get("MEB_VZE_01", cam_cp.vl.get("VZE_04", {}))
    psd_04_values = main_cp.vl["PSD_04"] if self.CP.flags & VolkswagenFlags.STOCK_PSD_PRESENT else {}
    psd_05_values = main_cp.vl["PSD_05"] if self.CP.flags & VolkswagenFlags.STOCK_PSD_PRESENT else {}
    psd_06_values = main_cp.vl["PSD_06"] if self.CP.flags & VolkswagenFlags.STOCK_PSD_PRESENT else {}
    psd_06_values = pt_cp.vl["PSD_06"] if not psd_06_values and self.CP.flags & VolkswagenFlags.STOCK_PSD_06_PRESENT else psd_06_values
    diagnose_01_values = pt_cp.vl["Diagnose_01"] if self.CP.flags & VolkswagenFlags.STOCK_DIAGNOSE_01_PRESENT else {}

    if self.enable_speed_limit_predicative and not self.enable_predicative_speed_limit:
      self.enable_predicative_speed_limit = True
    self.speed_limit_mgr.enable_predicative_speed_limit(self.enable_predicative_speed_limit, self.enable_pred_react_to_speed_limits, self.enable_pred_react_to_curves)
    self.speed_limit_mgr.update(ret.vEgo, psd_04_values, psd_05_values, psd_06_values, vze_01_values, raining, diagnose_01_values)
    ret.cruiseState.speedLimit = self.speed_limit_mgr.get_speed_limit()
    ret.cruiseState.speedLimitPredicative = self.speed_limit_mgr.get_speed_limit_predicative()
    self.speed_limit_predicative_type = self.speed_limit_mgr.get_speed_limit_predicative_type()
    ret_iq.speedLimit = ret.cruiseState.speedLimit

    self.left_blinker_active = bool(pt_cp.vl["Blinkmodi_02"]["BM_links"])
    self.right_blinker_active = bool(pt_cp.vl["Blinkmodi_02"]["BM_rechts"])
    stalk_values = pt_cp.vl.get("SMLS_01", {})
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(240, stalk_values.get("BH_Blinker_li", 0), stalk_values.get("BH_Blinker_re", 0))

    main_cruise_latching = not bool(pt_cp.vl["GRA_ACC_01"]["GRA_Typ_Hauptschalter"])
    buttons = getattr(self.CCP, "BUTTONS_ALT", self.CCP.BUTTONS) if main_cruise_latching else self.CCP.BUTTONS
    ret.buttonEvents = self.create_button_events(pt_cp, buttons)

    self.gra_stock_values = pt_cp.vl["GRA_ACC_01"]

    ret.espDisabled = bool(pt_cp.vl["ESP_21"]["ESP_Tastung_passiv"])
    ret.espActive = bool(pt_cp.vl["ESP_21"]["ESP_Eingriff"])

    allow_lat_only = self._params.get_bool("AllowLateralWhenLongUnavailable")
    cruise_main_switch = bool(pt_cp.vl["GRA_ACC_01"]["GRA_Hauptschalter"])
    cruise_fault_candidate = allow_lat_only and ret.accFaulted and cruise_main_switch

    if cruise_fault_candidate:
      self.cruise_faulted_frames += 1
      self.cruise_fault_clear_frames = 0
      if self.cruise_faulted_frames >= self.CRUISE_FAULT_LATERAL_ENABLE_FRAMES:
        self.cruise_fault_lateral_active = True
    else:
      self.cruise_faulted_frames = 0
      if self.cruise_fault_lateral_active:
        self.cruise_fault_clear_frames += 1
        if self.cruise_fault_clear_frames >= self.CRUISE_FAULT_LATERAL_DISABLE_FRAMES:
          self.cruise_fault_lateral_active = False
      else:
        self.cruise_fault_clear_frames = 0

    if not allow_lat_only:
      self.cruise_fault_lateral_active = False
      self.cruise_faulted_frames = 0
      self.cruise_fault_clear_frames = 0

    ret.cruiseFaultLateralMode = self.cruise_fault_lateral_active
    ret.lateralAvailable = ret.cruiseState.available or ret.cruiseFaultLateralMode
    ret.blockPcmEnable = ret.cruiseFaultLateralMode

    if self.CP.flags & VolkswagenFlags.MEB:
      ret.batteryDetails.charge = pt_cp.vl["Motor_16"]["MO_Energieinhalt_BMS"]
      if self.CP.networkLocation == NetworkLocation.gateway:
        ret.batteryDetails.heaterActive = bool(main_cp.vl["MEB_HVEM_03"]["PTC_ON"])
        ret.batteryDetails.voltage = main_cp.vl["MEB_HVEM_01"]["Battery_Voltage"]
        ret.batteryDetails.capacity = main_cp.vl["BMS_04"]["BMS_Kapazitaet_02"] * ret.batteryDetails.voltage
        ret.batteryDetails.soc = ret.batteryDetails.charge / ret.batteryDetails.capacity * 100.0 if ret.batteryDetails.capacity > 0 else 0.0
        ret.batteryDetails.power = main_cp.vl["MEB_HVEM_01"]["Engine_Power"]
        ret.batteryDetails.temperature = main_cp.vl["DCDC_03"]["DC_Temperatur"]
        ret.batteryDetails.chargingMode = int(main_cp.vl["BMS_04"]["BMS_IstModus"])
        ret.fuelGauge = ret.batteryDetails.soc / 100.0

    self.update_meb_virtual_lkas(ret, pt_cp, hca_status)

    ret.lowSpeedAlert = self.update_low_speed_alert(ret.vEgo)

    # Propagate radar disable failure state so carcontroller can skip ACC sends
    if self.CP.flags & VolkswagenFlags.DISABLE_RADAR:
      ret.radarDisableFailed = RADAR_DISABLE_STATE["error"]

    self.cruise_faulted = ret.accFaulted
    self.frame += 1
    self._apply_iq_private_flags(ret_iq)
    return ret, ret_iq

  @staticmethod
  def _pq_cluster_clock(aux_cp) -> int:
    """Decode the VW PQ gateway clock (Diagnose_1 / 0x7D0) to a UTC unix timestamp.
    Returns 0 if the parser is absent, the time is stale, or a field is out of range."""
    if aux_cp is None:
      return 0
    try:
      d = aux_cp.vl["Diagnose_1"]
    except KeyError:
      return 0
    if int(d["DI1_Zeit_alt"]):  # time is stale (gateway hasn't seen the cluster recently)
      return 0
    year = int(d["DI1_Jahr"])      # DBC applies the +2000 offset
    month = int(d["DI1_Monat"])
    day = int(d["DI1_Tag"])
    hour = int(d["DI1_Stunde"])
    minute = int(d["DI1_Minute"])
    second = int(d["DI1_Sekunde"])
    # Month 13/14/15 and 0 mean "invalid / no radio clock"; reject any out-of-range field.
    if not (2024 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31
            and hour <= 23 and minute <= 59 and second <= 59):
      return 0
    try:
      return int(calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)))
    except (ValueError, OverflowError):
      return 0

  def update_pq(self, pt_cp, cam_cp, ext_cp, aux_cp=None) -> tuple[structs.CarState, structs.IQCarState]:
    ret = structs.CarState()
    ret_iq = structs.IQCarState()

    # Gateway cluster (radio) clock — used to seed the system time on RTC-less
    # devices until GPS/NTP arrives. 0 when unknown or stale. See vw_pq.dbc Diagnose_1.
    ret.vehicleClockSeconds = self._pq_cluster_clock(aux_cp)

    # vEgo obtained from Bremse_1 vehicle speed rather than Bremse_3 wheel speeds because Bremse_3 isn't present on NSF
    ret.vEgoRaw = pt_cp.vl["Bremse_1"]["BR1_Rad_kmh"] * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = ret.vEgoRaw == 0

    # Update EPS position and state info. For signed values, VW sends the sign in a separate signal.
    ret.steeringAngleDeg = pt_cp.vl["Lenkhilfe_3"]["LH3_BLW"] * (1, -1)[int(pt_cp.vl["Lenkhilfe_3"]["LH3_BLWSign"])]
    ret.steeringRateDeg = pt_cp.vl["Lenkwinkel_1"]["LW1_Lenk_Gesch"] * (1, -1)[int(pt_cp.vl["Lenkwinkel_1"]["LW1_Gesch_Sign"])]
    ret.steeringTorque = pt_cp.vl["Lenkhilfe_3"]["LH3_LM"] * (1, -1)[int(pt_cp.vl["Lenkhilfe_3"]["LH3_LMSign"])]
    ret.steeringPressed = abs(ret.steeringTorque) > self.CCP.STEER_DRIVER_ALLOWANCE
    hca_status = self.CCP.hca_status_values.get(pt_cp.vl["Lenkhilfe_2"]["LH2_Sta_HCA"])
    ret.steerFaultTemporary, ret.steerFaultPermanent = self.update_hca_state(hca_status)

    # Update gas, brakes, and gearshift.
    ret.gasPressed = pt_cp.vl["Motor_3"]["MO3_Pedalwert"] > 0
    ret.brake = pt_cp.vl["Bremse_5"]["BR5_Bremsdruck"] / 250.0  # FIXME: this is pressure in Bar, not sure what OP expects
    ret.brakePressed = bool(pt_cp.vl["Motor_2"]["MO2_BLS"])
    ret.parkingBrake = bool(pt_cp.vl["Kombi_1"]["Bremsinfo"])

    # Update gear and/or clutch position data.
    if self.CP.transmissionType == TransmissionType.automatic:
      ret.gearShifter = self.parse_gear_shifter(self.CCP.shifter_values.get(pt_cp.vl["Getriebe_1"]["GE1_Wahl_Pos"], None))
    elif self.CP.transmissionType == TransmissionType.manual:
      reverse_light = bool(pt_cp.vl["Gate_Komf_1"]["GK1_Rueckfahr"])
      if reverse_light:
        ret.gearShifter = GearShifter.reverse
      else:
        ret.gearShifter = GearShifter.drive

    # Update door and trunk/hatch lid open status.
    ret.doorOpen = any([pt_cp.vl["Gate_Komf_1"]["GK1_Fa_Tuerkont"],
                        pt_cp.vl["Gate_Komf_1"]["BSK_BT_geoeffnet"],
                        pt_cp.vl["Gate_Komf_1"]["BSK_HL_geoeffnet"],
                        pt_cp.vl["Gate_Komf_1"]["BSK_HR_geoeffnet"],
                        pt_cp.vl["Gate_Komf_1"]["BSK_HD_Hauptraste"]])

    # Update seatbelt fastened status.
    ret.seatbeltUnlatched = not bool(pt_cp.vl["Airbag_1"]["Gurtschalter_Fahrer"])

    self.LH_3_Sign = pt_cp.vl["Lenkhilfe_3"]["LH3_BLWSign"]
    self.LH2_steeringState = pt_cp.vl["Lenkhilfe_2"]["LH2_aktLenkeingriff"]
    self._update_pq_iq_alc_state(pt_cp)

    # Consume blind-spot monitoring info/warning LED states, if available.
    # Infostufe: BSM LED on, Warnung: BSM LED flashing
    if self.CP.enableBsm:
      ret.leftBlindspot = bool(ext_cp.vl["SWA_1"]["SWA_Infostufe_SWA_li"]) or bool(ext_cp.vl["SWA_1"]["SWA_Warnung_SWA_li"])
      ret.rightBlindspot = bool(ext_cp.vl["SWA_1"]["SWA_Infostufe_SWA_re"]) or bool(ext_cp.vl["SWA_1"]["SWA_Warnung_SWA_re"])

    # Consume factory LDW data relevant for factory SWA (Lane Change Assist)
    # and capture it for forwarding to the blind spot radar controller
    self.ldw_stock_values = cam_cp.vl["LDW_Status"] if self.CP.networkLocation == NetworkLocation.fwdCamera else {}

    cc_only = self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY or self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR

    if not (self.CP.flags & VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR):
      ret.stockFcw = bool(ext_cp.vl["AWV"]["AWV_2_Freigabe"])
      ret.stockAeb = bool(ext_cp.vl["AWV"]["ANB_Teilbremsung_Freigabe"]) or bool(ext_cp.vl["AWV"]["ANB_Zielbremsung_Freigabe"])
    else:
      ret.stockFcw = False
      ret.stockAeb = False

    ret.espActive = bool(pt_cp.vl["Bremse_1"]["BR1_Lampe_ASR"])

    # Update ACC radar status.
    self.acc_type = 0 if cc_only else ext_cp.vl["ACC_System"]["ACS_Typ_ACC"]
    cruise_main_switch = bool(pt_cp.vl["Motor_5"]["MO5_GRA_Hauptsch"])
    cruise_tsk_status = bool(pt_cp.vl["Motor_2"]["MO2_Status_TSK"])
    self.cruise_main_switch = cruise_main_switch or cruise_tsk_status
    MO2_StaGRA = pt_cp.vl["Motor_2"]["MO2_Sta_GRA"] in (1, 2)
    ACS_StaADR = False if cc_only else ext_cp.vl["ACC_System"]["ACS_Sta_ADR"] == 1
    cruiseActive = MO2_StaGRA or ACS_StaADR
    if cruiseActive:
      self.last_cruiseActive = True
    elif not MO2_StaGRA and not ACS_StaADR:
      self.last_cruiseActive = False
    ret.cruiseState.enabled = self.last_cruiseActive

    if self.CP.pcmCruise:
      if cc_only:
        cruise_faulted = pt_cp.vl["Motor_2"]["MO2_Sta_GRA"] == 3
      else:
        cruise_faulted = ext_cp.vl["ACC_GRA_Anzeige"]["ACA_StaACC"] in (6, 7) or ext_cp.vl["ACC_System"]["ACS_Sta_ADR"] == 3 or pt_cp.vl["Motor_2"]["MO2_Sta_GRA"] == 3
    else:
      cruise_faulted = pt_cp.vl["Motor_2"]["MO2_Sta_GRA"] == 3

    ret.accFaulted = cruise_faulted
    ret.cruiseState.available = (cruise_main_switch or cruise_tsk_status) and not cruise_faulted
    allow_lat_only = self._params.get_bool("AllowLateralWhenLongUnavailable") and self._params.get_bool("AolEnabled")
    cruise_main_available = cruise_main_switch or cruise_tsk_status
    ret.cruiseFaultLateralMode = allow_lat_only and cruise_faulted and cruise_main_available
    ret.lateralAvailable = ret.cruiseState.available or ret.cruiseFaultLateralMode
    ret.blockPcmEnable = ret.cruiseFaultLateralMode

    # Update ACC setpoint. When the setpoint reads as 255, the driver has not
    # yet established an ACC setpoint, so treat it as zero.
    if cc_only:
      ret.cruiseState.speed = pt_cp.vl["Motor_2"]["MO2_GRA_Soll"] * CV.KPH_TO_MS
    elif self.CP.pcmCruise:
      ret.cruiseState.speed = ext_cp.vl["ACC_GRA_Anzeige"]["ACA_V_Wunsch"] * CV.KPH_TO_MS
    else:
      ret.cruiseState.speed = 0
    if ret.cruiseState.speed > 70:  # 255 kph in m/s == no current setpoint
      ret.cruiseState.speed = 0

    self.motor2_stock = pt_cp.vl["Motor_2"]

    # Update button states for turn signals and ACC controls, capture all ACC button state/config for passthrough
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(300, pt_cp.vl["Gate_Komf_1"]["GK1_Blinker_li"],
                                                                            pt_cp.vl["Gate_Komf_1"]["GK1_Blinker_re"])
    self.leftBlinkerUpdate = pt_cp.vl["Gate_Komf_1"]["GK1_Blinker_li"]
    self.rightBlinkerUpdate = pt_cp.vl["Gate_Komf_1"]["GK1_Blinker_re"]
    ret.buttonEvents = self.create_button_events(pt_cp, self.CCP.BUTTONS)
    self.gra_stock_values = pt_cp.vl["GRA_Neu"]

    # Additional safety checks performed in CarInterface.
    ret.espDisabled = bool(pt_cp.vl["Bremse_1"]["BR1_ESPASR_passive"])

    ret.lowSpeedAlert = self.update_low_speed_alert(ret.vEgo)

    ret.fuelGauge = pt_cp.vl["Kombi_1"]["Tankinhalt"] / 55.0
    ret.fuelTankLevelL = pt_cp.vl["Kombi_1"]["Tankinhalt"]  # raw liters for konn3kt

    self.cruise_faulted = ret.accFaulted
    self.frame += 1
    self._apply_iq_private_flags(ret_iq)
    return ret, ret_iq

  def update_mlb(self, pt_cp, br_cp, cam_cp, ext_cp) -> structs.CarState:
    ret = structs.CarState()
    ret_iq = structs.IQCarState()

    self.parse_wheel_speeds(ret,
      pt_cp.vl["ESP_03"]["ESP_VL_Radgeschw"],
      pt_cp.vl["ESP_03"]["ESP_VR_Radgeschw"],
      pt_cp.vl["ESP_03"]["ESP_HL_Radgeschw"],
      pt_cp.vl["ESP_03"]["ESP_HR_Radgeschw"],
    )

    ret.gasPressed = pt_cp.vl["Motor_03"]["MO_Fahrpedalrohwert_01"] > 0
    if self.CP.carFingerprint == CAR.PORSCHE_MACAN_MK1:
      ret.gearShifter = self.parse_gear_shifter(self.CCP.shifter_values.get(pt_cp.vl["Getriebe_03"]["GE_Waehlhebel"], None))
    else:
      ret.gearShifter = GearShifter.drive

    # ACC okay but disabled (1), ACC ready (2), a radar visibility or other fault/disruption (6 or 7)
    # currently regulating speed (3), driver accel override (4), brake only (5)
    if self.CP.carFingerprint == CAR.PORSCHE_MACAN_MK1:
      ret.cruiseState.available = ext_cp.vl["ACC_05"]["ACC_Status_ACC"] in (2, 3, 4, 5)
      ret.cruiseState.enabled = ext_cp.vl["ACC_05"]["ACC_Status_ACC"] in (3, 4, 5)
      ret.accFaulted = ext_cp.vl["ACC_05"]["ACC_Status_ACC"] in (6, 7)
    else:
      ret.cruiseState.available = pt_cp.vl["TSK_02"]["TSK_Status"] in (0, 1, 2)
      ret.cruiseState.enabled = pt_cp.vl["TSK_02"]["TSK_Status"] in (1, 2)
      ret.cruiseState.speed = ext_cp.vl["ACC_02"]["ACC_Wunschgeschw_02"] * CV.KPH_TO_MS
      ret.accFaulted = pt_cp.vl["TSK_02"]["TSK_Status"] in (3,)

    self.parse_mlb_mqb_steering_state(ret, pt_cp)

    ret.brake = pt_cp.vl["ESP_05"]["ESP_Bremsdruck"] / 250.0
    brake_pedal_pressed = bool(pt_cp.vl["Motor_03"]["MO_Fahrer_bremst"])
    brake_pressure_detected = bool(pt_cp.vl["ESP_05"]["ESP_Fahrer_bremst"])
    ret.brakePressed = brake_pedal_pressed or brake_pressure_detected
    ret.parkingBrake = bool(pt_cp.vl["Kombi_01"]["KBI_Handbremse"])
    ret.espDisabled = pt_cp.vl["ESP_01"]["ESP_Tastung_passiv"] != 0

    if self.CP.carFingerprint == CAR.PORSCHE_MACAN_MK1:
      ret.leftBlinker = bool(pt_cp.vl["Gateway_11"]["BH_Blinker_li"])
      ret.rightBlinker = bool(pt_cp.vl["Gateway_11"]["BH_Blinker_re"])

      ret.seatbeltUnlatched = pt_cp.vl["Gateway_06"]["AB_Gurtschloss_FA"] != 3
      ret.doorOpen = any([pt_cp.vl["Gateway_05"]["FT_Tuer_geoeffnet"],
                          pt_cp.vl["Gateway_05"]["BT_Tuer_geoeffnet"],
                          pt_cp.vl["Gateway_05"]["HL_Tuer_geoeffnet"],
                          pt_cp.vl["Gateway_05"]["HR_Tuer_geoeffnet"]])
    else:
      ret.leftBlinker = bool(pt_cp.vl["Blinkmodi_01"]["BM_links"])
      ret.rightBlinker = bool(pt_cp.vl["Blinkmodi_01"]["BM_rechts"])
      ret.seatbeltUnlatched = pt_cp.vl["Airbag_02"]["AB_Gurtschloss_FA"] != 3

    # Consume blind-spot monitoring info/warning LED states, if available.
    # Infostufe: BSM LED on, Warnung: BSM LED flashing
    if self.CP.enableBsm:
      ret.leftBlindspot = bool(ext_cp.vl["SWA_01"]["SWA_Infostufe_SWA_li"]) or bool(ext_cp.vl["SWA_01"]["SWA_Warnung_SWA_li"])
      ret.rightBlindspot = bool(ext_cp.vl["SWA_01"]["SWA_Infostufe_SWA_re"]) or bool(ext_cp.vl["SWA_01"]["SWA_Warnung_SWA_re"])

    self.ldw_stock_values = cam_cp.vl["LDW_02"] if self.CP.networkLocation == NetworkLocation.fwdCamera else {}
    self.gra_stock_values = pt_cp.vl["LS_01"]

    ret.fuelGauge = br_cp.vl["Kombi_02"]["KBI_Inhalt_Tank"] / 55.0
    ret.fuelTankLevelL = br_cp.vl["Kombi_02"]["KBI_Inhalt_Tank"]  # raw liters for konn3kt

    ret.buttonEvents = self.create_button_events(pt_cp, self.CCP.BUTTONS)

    ret.cruiseState.standstill = self.CP.pcmCruise and self.esp_hold_confirmation
    ret.standstill = ret.vEgoRaw == 0
    ret.cruiseFaultLateralMode = False
    ret.lateralAvailable = ret.cruiseState.available
    ret.blockPcmEnable = False

    self.cruise_faulted = ret.accFaulted
    self.frame += 1
    self._apply_iq_private_flags(ret_iq)
    return ret, ret_iq

  def update_low_speed_alert(self, v_ego: float) -> bool:
    # Low speed steer alert hysteresis logic
    if (self.CP.minSteerSpeed - 1e-3) > CarControllerParams.DEFAULT_MIN_STEER_SPEED and v_ego < (self.CP.minSteerSpeed + 1.):
      self.low_speed_alert = True
    elif v_ego > (self.CP.minSteerSpeed + 2.):
      self.low_speed_alert = False
    return self.low_speed_alert

  def parse_mlb_mqb_steering_state(self, ret, pt_cp, drive_mode=True):
    ret.steeringAngleDeg = pt_cp.vl["LWI_01"]["LWI_Lenkradwinkel"] * (1, -1)[int(pt_cp.vl["LWI_01"]["LWI_VZ_Lenkradwinkel"])]
    ret.steeringRateDeg = pt_cp.vl["LWI_01"]["LWI_Lenkradw_Geschw"] * (1, -1)[int(pt_cp.vl["LWI_01"]["LWI_VZ_Lenkradw_Geschw"])]
    ret.steeringTorque = pt_cp.vl["LH_EPS_03"]["EPS_Lenkmoment"] * (1, -1)[int(pt_cp.vl["LH_EPS_03"]["EPS_VZ_Lenkmoment"])]
    ret.steeringPressed = abs(ret.steeringTorque) > self.CCP.STEER_DRIVER_ALLOWANCE

    hca_status = self.CCP.hca_status_values.get(pt_cp.vl["LH_EPS_03"]["EPS_HCA_Status"])
    ret.steerFaultTemporary, ret.steerFaultPermanent = self.update_hca_state(hca_status, drive_mode)
    return

  def update_hca_state(self, hca_status, drive_mode=True):
    # Treat FAULT as temporary for worst likely EPS recovery time, for cars without factory Lane Assist
    # DISABLED means the EPS hasn't been configured to support Lane Assist
    self.eps_init_complete = self.eps_init_complete or (hca_status in ("DISABLED", "READY", "ACTIVE") or self.frame > 600)
    perm_fault = drive_mode and hca_status == "DISABLED" or (self.eps_init_complete and hca_status == "FAULT")
    temp_fault = drive_mode and hca_status in ("REJECTED", "PREEMPTED") or not self.eps_init_complete
    return temp_fault, perm_fault

  def update_acc_fault(self, acc_fault, parking_brake=False, drive_mode=True, recovery_frames_max=100):
    fault = acc_fault
    if parking_brake and not drive_mode:
      fault = False
      self.cruise_recovery_timer = self.frame
    elif self.frame - self.cruise_recovery_timer < recovery_frames_max:
      fault = False
    return fault

  def update_meb_virtual_lkas(self, ret, pt_cp, hca_status):
    temp_cruise_fault = pt_cp.vl["Motor_51"]["TSK_Status"] == self.MEB_TEMP_CRUISE_FAULT
    drive_mode = ret.gearShifter == GearShifter.drive
    if temp_cruise_fault and ret.parkingBrake and not drive_mode:
      ret.cruiseState.available = True
      self.tolerance_counter = 0
    elif self.tolerance_counter < self.MEB_TOLERANCE_MAX:
      ret.cruiseState.available = True
      self.tolerance_counter = min(self.tolerance_counter + 1, self.MEB_TOLERANCE_MAX)

    self.prev_lkas_button = self.lkas_button
    user_disable = any(b.type == ButtonType.cancel and b.pressed for b in ret.buttonEvents)
    steering_enabled = hca_status == "ACTIVE"
    cruise_standby = not ret.cruiseState.enabled
    self.lkas_button = steering_enabled and user_disable and cruise_standby

    if self.prev_lkas_button != self.lkas_button:
      event = structs.CarState.ButtonEvent()
      event.type = ButtonType.lkas
      event.pressed = self.lkas_button
      ret.buttonEvents = list(ret.buttonEvents) + [event]

  @staticmethod
  def get_can_parsers(CP, CP_IQ):
    if CP.flags & VolkswagenFlags.PQ:
      return CarState.get_can_parsers_pq(CP)
    if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      return CarState.get_can_parsers_meb(CP)

    # manually configure some optional and variable-rate/edge-triggered messages
    pt_messages, cam_messages = [], []

    if not CP.flags & VolkswagenFlags.MLB:
      pt_messages += [
        ("Blinkmodi_02", 1)  # From J519 BCM (sent at 1Hz when no lights active, 50Hz when active)
      ]
    if CP.flags & VolkswagenFlags.MLB:
      pt_messages += [
        ("Blinkmodi_01", math.nan)  # From J519 BCM (is inactive when no lights active, 50Hz when active)
      ]
    if CP.flags & VolkswagenFlags.STOCK_HCA_PRESENT:
      cam_messages += [
        ("HCA_01", 1),  # From R242 Driver assistance camera, 50Hz if steering/1Hz if not
      ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, CanBus(CP).pt),
      Bus.aux: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, CanBus(CP).aux),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, CanBus(CP).cam),
    }

  @staticmethod
  def get_can_parsers_pq(CP):
    # Gateway cluster clock (Diagnose_1 / 0x7D0) lives on the comfort/ACAN bus (bus 1).
    # freq 0 disables the alive/rate check so cars that don't forward it never drop can_valid.
    aux_messages = [("Diagnose_1", 0)]
    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], [], CanBus(CP).pt),
      Bus.aux: CANParser(DBC[CP.carFingerprint][Bus.pt], aux_messages, CanBus(CP).aux),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], [], CanBus(CP).cam),
    }

  @staticmethod
  def get_can_parsers_meb(CP):
    pt_messages = [
      ("Blinkmodi_02", 1),
      ("SMLS_01", 1),
      # TA_01 lives on bus 0 (car ECU / OP-generated when long is active).
      # math.nan → ignore_alive=True so it never contributes to can_valid.
      ("TA_01", math.nan),
    ]
    if CP.networkLocation == NetworkLocation.fwdCamera:
      pt_messages.append(("AWV_03", 1))

    cam_messages = []
    if CP.networkLocation == NetworkLocation.gateway:
      cam_messages.append(("AWV_03", 1))

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, CanBus(CP).pt),
      Bus.main: CANParser(DBC[CP.carFingerprint][Bus.pt], [], CanBus(CP).main),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, CanBus(CP).cam),
    }
