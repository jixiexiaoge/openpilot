"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import custom, car
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode


def compare_cluster_target(v_cruise_cluster: float, target_set_speed: float, is_metric: bool) -> tuple[bool, bool]:
  speed_conv = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
  v_cruise_cluster_conv = round(v_cruise_cluster * speed_conv)
  target_set_speed_conv = round(target_set_speed * speed_conv)

  req_plus = v_cruise_cluster_conv < target_set_speed_conv
  req_minus = v_cruise_cluster_conv > target_set_speed_conv

  return req_plus, req_minus


def set_speed_limit_controller_availability(CP: car.CarParams, CP_IQ: custom.IQCarParams, params: Params = None) -> bool:
  if params is None:
    params = Params()

  is_release = params.get_bool("IsReleaseIqBranch")
  disallow_in_release = CP.brand == "tesla" and is_release
  always_disallow = CP.brand == "rivian"
  allowed = True

  if disallow_in_release or always_disallow:
    allowed = False

  if not CP.openpilotLongitudinalControl and CP_IQ.pcmCruiseSpeed:
    allowed = False

  if not allowed:
    if params.get("SpeedLimitMode", return_default=True) == SpeedLimitMode.control:
      params.put("SpeedLimitMode", int(SpeedLimitMode.warning))

  return allowed


def set_speed_limit_assist_availability(CP: car.CarParams, CP_IQ: custom.IQCarParams, params: Params = None) -> bool:
  return set_speed_limit_controller_availability(CP, CP_IQ, params)
