"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.iqpilot.car.hyundai.values import HyundaiFlagsIQ, HyundaiSafetyFlagsIQ


BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE = ("rivian", "tesla")


class BrakeInterventionMode:
  CONTINUE = 0
  SUSPEND = 1
  CANCEL = 2


def _forces_brake_cancel(brand: str, iq_flags: int) -> bool:
  if brand == "rivian":
    return True

  return False


def _supports_hyundai_main_cruise_toggle(brand: str) -> bool:
  return brand == "hyundai"

def _removes_main_cruise_toggle(brand: str) -> bool:
  return brand in BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE

def uses_forced_brake_cancel(CP: structs.CarParams, CP_IQ: structs.IQCarParams) -> bool:
  return _forces_brake_cancel(CP.brand, CP_IQ.flags)

def read_aol_enabled_pref(params: Params) -> bool:
  return params.get_bool("AolEnabled")

def read_main_cruise_pref(params: Params) -> bool:
  return params.get_bool("AolMainCruiseAllowed")

def read_joint_engagement_pref(params: Params) -> bool:
  return params.get_bool("AolUnifiedEngagementMode")

def resolve_brake_intervention_mode(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  forced_cancel = uses_forced_brake_cancel(CP, CP_IQ)
  if forced_cancel:
    return BrakeInterventionMode.CANCEL

  return params.get("AolSteeringMode", return_default=True)

def apply_aol_experience_flags(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  aol_enabled = read_aol_enabled_pref(params)
  brake_mode = resolve_brake_intervention_mode(CP, CP_IQ, params)
  if aol_enabled:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_AOL

    if brake_mode == BrakeInterventionMode.CANCEL:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.AOL_DISENGAGE_LATERAL_ON_BRAKE
    elif brake_mode == BrakeInterventionMode.SUSPEND:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.AOL_PAUSE_LATERAL_ON_BRAKE

def apply_aol_brand_overrides(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  hyundai_main_toggle_supported = _supports_hyundai_main_cruise_toggle(CP.brand)
  if hyundai_main_toggle_supported:
    CP_IQ.flags |= HyundaiFlagsIQ.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE.value
    CP_IQ.safetyParam |= HyundaiSafetyFlagsIQ.LONG_MAIN_CRUISE_TOGGLEABLE
  limited_brand_behavior = uses_forced_brake_cancel(CP, CP_IQ)
  if limited_brand_behavior:
    params.put("AolSteeringMode", 2)
    params.put_bool("AolUnifiedEngagementMode", True)
  if _removes_main_cruise_toggle(CP.brand):
    params.remove("AolMainCruiseAllowed")
