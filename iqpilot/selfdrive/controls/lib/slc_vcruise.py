#!/usr/bin/env python3
import time

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.common.k3_slc_log import k3_slc_log
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit_controller import SpeedLimitController

CRUISING_SPEED = 7


class SLCVCruise:

  def __init__(self):
    self.params = Params()

    self.slc = SpeedLimitController(self.params)
    self._last_debug_log_t = 0.0
    self._last_debug_signature = None

    # Exposed SLC state (for UI/logging)
    self.controller_enabled = False
    self.mode_assist = False
    self.slc_offset = 0
    self.slc_target = 0
    self.slc_source = "None"
    self.slc_unconfirmed = 0
    self.slc_overridden_speed = 0
    self.slc_active_target = 0
    self.slc_active_source = "None"
    self._user_max_speed = 0.0
    self.slc_experimental_mode = False
    self.pending_events = []

  @property
  def assist_state(self):
    return getattr(self.slc, 'assist_state', None)

  @property
  def slc_a_target(self):
    return float(getattr(self.slc, 'output_a_target', 0.0))

  def _maybe_log_debug(self, slc_params, apply_enabled, v_cruise, v_ego, dashboard_speed_limit, applied_target, returned_v_cruise):
    map_speed_limit = float(getattr(self.slc, "map_speed_limit", 0.0) or 0.0)
    mapbox_limit = float(getattr(self.slc, "mapbox_limit", 0.0) or 0.0)
    next_speed_limit = float(getattr(self.slc, "next_speed_limit", 0.0) or 0.0)
    gps_valid = bool(getattr(self.slc, "gps_valid", False))
    signature = (
      bool(slc_params["speed_limit_controller"]),
      bool(slc_params["show_speed_limits"]),
      self.slc.target,
      self.slc.source,
      self.slc.active_target,
      self.slc.active_source,
      map_speed_limit,
      mapbox_limit,
      next_speed_limit,
      self.slc.overridden_speed,
      bool(apply_enabled),
      float(applied_target),
      float(returned_v_cruise),
    )
    now_mono = time.monotonic()
    if signature == self._last_debug_signature and now_mono - self._last_debug_log_t < 5.0:
      return

    self._last_debug_signature = signature
    self._last_debug_log_t = now_mono

    message = (
      "SLC debug: "
      f"mode={int(self.params.get('IQSpeedAssistMode', return_default=True))} "
      f"controller={slc_params['speed_limit_controller']} "
      f"show={slc_params['show_speed_limits']} "
      f"apply_enabled={bool(apply_enabled)} "
      f"dashboard={round(float(dashboard_speed_limit), 2)} "
      f"map_data={round(map_speed_limit, 2)} "
      f"mapbox={round(mapbox_limit, 2)} "
      f"next_map={round(next_speed_limit, 2)} "
      f"selected_source={self.slc.source} "
      f"selected_target={round(float(self.slc.target), 2)} "
      f"active_source={self.slc.active_source} "
      f"active_target={round(float(self.slc.active_target), 2)} "
      f"offset={round(float(self.slc_offset), 2)} "
      f"override={round(float(self.slc.overridden_speed), 2)} "
      f"gps_valid={gps_valid} "
      f"applied_target={round(float(applied_target), 2)} "
      f"returned_v_cruise={round(float(returned_v_cruise), 2)} "
      f"v_cruise={round(float(v_cruise), 2)} "
      f"v_ego={round(float(v_ego), 2)}"
    )
    cloudlog.info(message)
    k3_slc_log(message)

  def _get_slc_params(self):
    """
    Load SLC parameters from Params.

    Returns:
      Dictionary of SLC configuration parameters
    """
    def get_param_bool(key, default=False):
      value = self.params.get_bool(key)
      return value if value is not None else default

    def get_param_float(key, default=0.0):
      value = self.params.get(key)
      if value is None:
        return default
      if isinstance(value, bytes):
        try:
          return float(value.decode('utf-8'))
        except (ValueError, AttributeError):
          return default
      return float(value)

    def get_param_str(key, default=""):
      value = self.params.get(key)
      if value is None:
        return default
      if isinstance(value, bytes):
        return value.decode('utf-8')
      return str(value)

    slc_policy = int(get_param_str("SLCPolicy", "1"))

    override_method = int(get_param_str("SLCOverrideMethod", "0"))
    override_manual = (override_method == 0)
    override_set_speed = (override_method == 1)

    speed_limit_mode = int(get_param_str("IQSpeedAssistMode", "1"))  # default: SpeedLimitMode.information
    speed_limit_controller = get_param_bool("SpeedLimitController")
    show_speed_limits = get_param_bool("ShowSpeedLimits")

    if speed_limit_mode == 0:  # SpeedLimitMode.off
      speed_limit_controller = False
      show_speed_limits = False
    elif speed_limit_mode == 3:  # SpeedLimitMode.control
      speed_limit_controller = True
      show_speed_limits = False
    else:
      speed_limit_controller = False
      show_speed_limits = True

    return {
      "speed_limit_controller": speed_limit_controller,
      "speed_limit_mode": speed_limit_mode,
      "show_speed_limits": show_speed_limits,
      "slc_policy": slc_policy,
      "slc_auto_confirm": get_param_bool("SLCAutoConfirm"),
      "speed_limit_confirmation_higher": get_param_bool("SpeedLimitConfirmationHigher"),
      "speed_limit_confirmation_lower": get_param_bool("SpeedLimitConfirmationLower"),
      "map_speed_lookahead_higher": get_param_float("MapSpeedLookaheadHigher", 5.0),
      "map_speed_lookahead_lower": get_param_float("MapSpeedLookaheadLower", 5.0),
      "slc_fallback_experimental_mode": get_param_bool("SLCFallbackExperimentalMode"),
      "slc_fallback_set_speed": get_param_bool("SLCFallbackSetSpeed"),
      "slc_fallback_previous_speed_limit": get_param_bool("SLCFallbackPreviousSpeedLimit"),
      "speed_limit_controller_override_manual": override_manual,
      "speed_limit_controller_override_set_speed": override_set_speed,
      "slc_online_filler": get_param_bool("SLCOnlineFiller"),
      "is_metric": get_param_bool("IsMetric"),
      "construction_zone_assist": get_param_bool("ConstructionZoneAssist"),
      "construction_zone_speed": get_param_float("ConstructionZoneSpeed", 60.0),
    }

  @staticmethod
  def _allow_auto_raise(slc_params):
    # Reuse the existing "confirm higher" toggle as the gate:
    # disabled confirm => allow SLC to raise cruise to a higher accepted limit.
    return not slc_params["speed_limit_confirmation_higher"]

  def update(self, apply_enabled, now, time_validated, v_cruise, v_ego, sm):
    slc_params = self._get_slc_params()
    self.controller_enabled = bool(slc_params["speed_limit_controller"])
    self.mode_assist = int(slc_params["speed_limit_mode"]) == 3  # SpeedLimitMode.control
    is_metric = slc_params["is_metric"]
    v_cruise_cluster = max(sm["carState"].vCruiseCluster * CV.KPH_TO_MS, v_cruise)
    v_cruise_diff = v_cruise_cluster - v_cruise

    v_ego_cluster = max(sm["carState"].vEgoCluster, v_ego)
    v_ego_diff = v_ego_cluster - v_ego
    car_state_iq = sm["iqCarState"]
    dashboard_speed_limit = car_state_iq.speedLimit if hasattr(car_state_iq, "speedLimit") else 0
    if apply_enabled:
      if self._user_max_speed <= 0.0:
        self._user_max_speed = v_cruise_cluster
      elif v_cruise_cluster > self._user_max_speed:
        self._user_max_speed = v_cruise_cluster
    else:
      self._user_max_speed = 0.0
    if slc_params["speed_limit_controller"]:
      self.slc.update_limits(dashboard_speed_limit, now, time_validated, v_cruise, v_ego, sm, slc_params)
      self.pending_events = list(getattr(self.slc, 'pending_events', []))
      self.slc.update_override(v_cruise, v_cruise_diff, v_ego, v_ego_diff, sm, slc_params, is_metric)

      self.slc_offset = 0 if self.slc.source == "Construction" else self.slc.get_offset(is_metric)
      self.slc_target = self.slc.target
      self.slc_source = self.slc.source
      self.slc_active_target = self.slc.active_target
      self.slc_active_source = self.slc.active_source
      self.slc_unconfirmed = self.slc.unconfirmed_speed_limit
      self.slc_overridden_speed = self.slc.overridden_speed

    elif slc_params["show_speed_limits"]:
      self.slc.update_limits(dashboard_speed_limit, now, time_validated, v_cruise, v_ego, sm, slc_params)
      self.pending_events = []

      self.slc_offset = 0
      self.slc_target = self.slc.target
      self.slc_source = self.slc.source
      self.slc_active_target = self.slc.active_target
      self.slc_active_source = self.slc.active_source
      self.slc_unconfirmed = self.slc.unconfirmed_speed_limit
      self.slc_overridden_speed = 0

    else:
      self.pending_events = []
      self.slc_offset = 0
      self.slc_target = 0
      self.slc_source = "None"
      self.slc_active_target = 0
      self.slc_active_source = "None"
      self.slc_unconfirmed = 0
      self.slc_overridden_speed = 0

    self.slc_experimental_mode = bool(
      slc_params["speed_limit_controller"] and
      slc_params["slc_fallback_experimental_mode"] and
      self.slc_target <= 0
    )

    applied_target = 0.0

    if slc_params["speed_limit_controller"] and apply_enabled:
      slc_target_with_offset = max(self.slc_overridden_speed, self.slc_target + self.slc_offset)
      allow_auto_raise = self._allow_auto_raise(slc_params)
      if self._user_max_speed > 0.0 and not allow_auto_raise:
        slc_target_with_offset = min(slc_target_with_offset, self._user_max_speed)
      slc_cruise_target = slc_target_with_offset - v_ego_diff

      if slc_cruise_target >= CRUISING_SPEED:
        applied_target = slc_cruise_target
        if allow_auto_raise and self.slc_source != "Construction":
          v_cruise = slc_cruise_target
        else:
          v_cruise = min(v_cruise, slc_cruise_target)

    self._maybe_log_debug(slc_params, apply_enabled, v_cruise, v_ego, dashboard_speed_limit, applied_target, v_cruise)

    return v_cruise
