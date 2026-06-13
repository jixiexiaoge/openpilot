"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from enum import StrEnum

from opendbc.car import Bus, create_button_events, structs
from opendbc.can.parser import CANParser
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla.values import DBC, CANBUS
from opendbc.iqpilot.car.tesla.values import TeslaFlagsIQ

ButtonType = structs.CarState.ButtonEvent.Type


class CarStateExt:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.infotainment_3_finger_press = 0

  def update(self, ret: structs.CarState, ret_iq: structs.IQCarState, can_parsers: dict[StrEnum, CANParser]) -> None:
    if self.CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS:
      cp_adas = can_parsers[Bus.adas]

      prev_infotainment_3_finger_press = self.infotainment_3_finger_press
      self.infotainment_3_finger_press = int(cp_adas.vl["UI_status2"]["UI_activeTouchPoints"])

      ret.buttonEvents = [*create_button_events(self.infotainment_3_finger_press, prev_infotainment_3_finger_press,
                                                {3: ButtonType.lkas})]

      bms_soc_ui = float(cp_adas.vl["ID292BMS_SOC"].get("SOCUI292", 0.0))
      ui_range_mi = float(cp_adas.vl["ID33AUI_rangeSOC"].get("UI_Range", 0.0))
      hv_batt_voltage_v = float(cp_adas.vl["ID132HVBattAmpVolt"].get("BattVoltage132", 0.0))
      battery_details = None
      try:
        battery_details = ret.batteryDetails
      except Exception:
        battery_details = None

      soc_ui = bms_soc_ui if 0.0 <= bms_soc_ui <= 102.3 else None
      if soc_ui is not None:
        ret.fuelGauge = min(100.0, soc_ui) / 100.0
        if battery_details is not None:
          battery_details.soc = soc_ui
          battery_details.charge = soc_ui
      if 0.0 <= ui_range_mi <= 1023.0 and battery_details is not None:
        battery_details.capacity = ui_range_mi
      if 0.0 < hv_batt_voltage_v <= 800.0 and battery_details is not None:
        battery_details.voltage = hv_batt_voltage_v

    cp_party = can_parsers[Bus.party]
    cp_ap_party = can_parsers[Bus.ap_party]

    speed_units = self.can_define.dv["DI_state"]["DI_speedUnits"].get(int(cp_party.vl["DI_state"]["DI_speedUnits"]), None)
    speed_limit = cp_ap_party.vl["DAS_status"]["DAS_fusedSpeedLimit"]
    if self.can_define.dv["DAS_status"]["DAS_fusedSpeedLimit"].get(int(speed_limit), None) in ["NONE", "UNKNOWN_SNA"]:
      ret_iq.speedLimit = 0
    else:
      if speed_units == "KPH":
        ret_iq.speedLimit = speed_limit * CV.KPH_TO_MS
      elif speed_units == "MPH":
        ret_iq.speedLimit = speed_limit * CV.MPH_TO_MS

  @staticmethod
  def get_parser(CP: structs.CarParams, CP_IQ: structs.IQCarParams) -> dict[StrEnum, CANParser]:
    messages = {}

    if CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS:
      messages[Bus.adas] = CANParser(DBC[CP.carFingerprint][Bus.adas], [], CANBUS.vehicle)

    return messages
