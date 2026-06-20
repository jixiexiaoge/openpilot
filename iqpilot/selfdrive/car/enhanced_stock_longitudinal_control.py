"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from __future__ import annotations

from openpilot.common.constants import CV
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX

from opendbc.car import structs

ENHANCED_STOCK_LONGITUDINAL_CONTROL_SET_SPEED_KPH_KEY = "enhancedStockLongitudinalControl.setSpeedKph"


def _float_param(key: str, value: float) -> dict[str, object]:
  return {"key": key, "type": "float", "value": f"{float(value):.3f}".encode("utf-8")}


def _clamp_set_speed_kph(value: float) -> float:
  return max(0.0, min(V_CRUISE_MAX, float(value)))


def build_iq_control_params_from_plan(CP: structs.CarParams, iq_plan, selfdrive_enabled: bool,
                                      current_set_speed_kph: float, previous_sync_limit_kph: float | None,
                                      pending_sync_limit_kph: float | None) -> tuple[list[dict[str, object]], float | None, float | None]:
  if not CP.openpilotLongitudinalControl or not selfdrive_enabled:
    return [], None, None

  resolver = getattr(getattr(iq_plan, "speedLimit", None), "resolver", None)
  assist = getattr(getattr(iq_plan, "speedLimit", None), "assist", None)
  if resolver is None or assist is None:
    return [], None, None

  speed_limit_final_last = float(getattr(resolver, "speedLimitFinalLast", 0.0) or 0.0)
  assist_enabled = bool(getattr(assist, "enabled", False))
  if not assist_enabled or speed_limit_final_last <= 0.0:
    return [], None, None

  resolved_limit_kph = _clamp_set_speed_kph(speed_limit_final_last * CV.MS_TO_KPH)
  limit_changed = previous_sync_limit_kph is None or abs(resolved_limit_kph - previous_sync_limit_kph) > 0.05
  if limit_changed:
    pending_sync_limit_kph = resolved_limit_kph

  if pending_sync_limit_kph is not None:
    if abs(current_set_speed_kph - pending_sync_limit_kph) <= 0.25:
      pending_sync_limit_kph = None
      set_speed_kph = _clamp_set_speed_kph(current_set_speed_kph or resolved_limit_kph)
    else:
      set_speed_kph = pending_sync_limit_kph
  else:
    set_speed_kph = _clamp_set_speed_kph(current_set_speed_kph or resolved_limit_kph)

  return [_float_param(ENHANCED_STOCK_LONGITUDINAL_CONTROL_SET_SPEED_KPH_KEY, set_speed_kph)], resolved_limit_kph, pending_sync_limit_kph


def get_set_speed_kph_from_params(params) -> float | None:
  for param in params:
    key = param.key if hasattr(param, "key") else param.get("key")
    if key != ENHANCED_STOCK_LONGITUDINAL_CONTROL_SET_SPEED_KPH_KEY:
      continue
    raw_value = param.value if hasattr(param, "value") else param.get("value")
    try:
      raw = raw_value.decode("utf-8") if isinstance(raw_value, (bytes, bytearray)) else str(raw_value)
      value = float(raw)
    except (AttributeError, TypeError, ValueError):
      return None
    return _clamp_set_speed_kph(value)
  return None
