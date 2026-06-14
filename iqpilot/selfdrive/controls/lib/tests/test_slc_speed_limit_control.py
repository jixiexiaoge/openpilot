"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from types import SimpleNamespace

from openpilot.common.constants import CV
from openpilot.iqpilot.selfdrive.controls.lib.slc_vcruise import SLCVCruise, CRUISING_SPEED
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit_controller import SpeedLimitController, POLICY_MAP_DATA_PRIORITY, POLICY_COMBINED


class FakeParams:
  def __init__(self):
    self.values = {}

  def get(self, key, encoding=None):
    _ = encoding
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_nonblocking(self, key, value):
    self.values[key] = value

  def put(self, key, value):
    self.values[key] = value


def _build_sm(v_cruise_cluster=100.0, v_ego_cluster=27.8, gas=False, enabled=True, iq_limit=0.0):
  # vCruiseCluster is in kph in carState.
  return {
    "carState": SimpleNamespace(vCruiseCluster=v_cruise_cluster, vEgoCluster=v_ego_cluster, gasPressed=gas,
                                steeringAngleDeg=0.0, buttonEvents=[]),
    "iqCarState": SimpleNamespace(speedLimit=iq_limit, accelPressed=False, decelPressed=False),
    "selfdriveState": SimpleNamespace(enabled=enabled),
    "liveParameters": SimpleNamespace(angleOffsetDeg=0.0),
  }


class _FakeSLC:
  def __init__(self):
    self.target = 0.0
    self.source = "None"
    self.active_target = 0.0
    self.active_source = "None"
    self.unconfirmed_speed_limit = 0.0
    self.overridden_speed = 0.0
    self.pending_events = []
    self.assist_state = None
    self.output_a_target = 0.0
    self.update_limits_calls = 0
    self.update_override_calls = 0
    self._offset = 0.0

  def update_limits(self, *_args, **_kwargs):
    self.update_limits_calls += 1

  def update_override(self, *_args, **_kwargs):
    self.update_override_calls += 1

  def get_offset(self, _is_metric):
    return self._offset


def _base_slc_params_controller():
  return {
    "slc_policy": POLICY_MAP_DATA_PRIORITY,
    "slc_auto_confirm": False,
    "slc_fallback_previous_speed_limit": False,
    "slc_fallback_set_speed": False,
    "speed_limit_confirmation_higher": False,
    "speed_limit_confirmation_lower": False,
    "slc_mapbox_filler": True,
    "map_speed_lookahead_higher": 5.0,
    "map_speed_lookahead_lower": 5.0,
  }


def test_speed_limit_controller_resolves_source_by_priority():
  params = FakeParams()
  controller = SpeedLimitController(params)
  controller.update_gps = lambda _sm: None
  controller._resolver.update_map_data = lambda *_args, **_kwargs: None
  controller.get_mapbox_speed_limit = lambda *_args, **_kwargs: None
  controller.mapbox_requests["total_requests"] = 0
  controller.mapbox_requests["max_requests"] = 999999
  controller.mapbox_limit = 22.0
  controller._resolver.map_speed_limit = 18.0  # map data wins in map_data_priority policy

  sm = _build_sm(iq_limit=25.0)
  slc_params = _base_slc_params_controller()
  slc_params["slc_policy"] = POLICY_MAP_DATA_PRIORITY

  controller.update_limits(25.0, None, True, 30.0, 27.0, sm, slc_params)
  assert controller.active_source == "Map Data"
  assert controller.active_target == 18.0


def test_speed_limit_controller_combined_mode_prefers_smallest_limit():
  params = FakeParams()
  controller = SpeedLimitController(params)
  controller.update_gps = lambda _sm: None
  controller._resolver.update_map_data = lambda *_args, **_kwargs: None
  controller.get_mapbox_speed_limit = lambda *_args, **_kwargs: None
  controller.mapbox_requests["total_requests"] = 0
  controller.mapbox_requests["max_requests"] = 999999
  controller.mapbox_limit = 24.0
  controller._resolver.map_speed_limit = 16.0  # smallest of: dashboard=28, mapbox=24, map_data=16

  sm = _build_sm(iq_limit=28.0)
  slc_params = _base_slc_params_controller()
  slc_params["slc_policy"] = POLICY_COMBINED

  controller.update_limits(28.0, None, True, 31.0, 27.0, sm, slc_params)
  assert controller.active_source == "Map Data"
  assert controller.active_target == 16.0


def test_slc_vcruise_applies_target_without_increasing_cruise():
  slc = SLCVCruise()
  slc.slc = _FakeSLC()
  slc.slc.target = 23.0
  slc.slc.source = "Dashboard"
  slc.slc.active_target = 23.0
  slc.slc.active_source = "Dashboard"
  slc.slc._offset = 1.0

  slc._get_slc_params = lambda: {
    "speed_limit_controller": True,
    "show_speed_limits": False,
    "is_metric": True,
    "slc_policy": POLICY_MAP_DATA_PRIORITY,
    "slc_auto_confirm": False,
    "speed_limit_confirmation_higher": False,
    "speed_limit_confirmation_lower": False,
    "map_speed_lookahead_higher": 5.0,
    "map_speed_lookahead_lower": 5.0,
    "slc_fallback_experimental_mode": False,
    "slc_fallback_set_speed": False,
    "slc_fallback_previous_speed_limit": False,
    "speed_limit_controller_override_manual": True,
    "speed_limit_controller_override_set_speed": False,
    "slc_mapbox_filler": False,
  }

  v_cruise = 30.0
  sm = _build_sm(v_cruise_cluster=v_cruise * CV.MS_TO_KPH, v_ego_cluster=27.0, iq_limit=23.0)
  out = slc.update(apply_enabled=True, now=None, time_validated=True, v_cruise=v_cruise, v_ego=27.0, sm=sm)

  assert slc.slc.update_limits_calls == 1
  assert slc.slc.update_override_calls == 1
  assert out <= v_cruise
  assert out >= CRUISING_SPEED


def test_slc_vcruise_show_only_does_not_modify_cruise():
  slc = SLCVCruise()
  slc.slc = _FakeSLC()
  slc.slc.target = 21.0
  slc.slc.source = "Map Data"
  slc.slc.active_target = 21.0
  slc.slc.active_source = "Map Data"
  slc._get_slc_params = lambda: {
    "speed_limit_controller": False,
    "show_speed_limits": True,
    "is_metric": True,
    "slc_policy": POLICY_MAP_DATA_PRIORITY,
    "slc_auto_confirm": False,
    "speed_limit_confirmation_higher": False,
    "speed_limit_confirmation_lower": False,
    "map_speed_lookahead_higher": 5.0,
    "map_speed_lookahead_lower": 5.0,
    "slc_fallback_experimental_mode": False,
    "slc_fallback_set_speed": False,
    "slc_fallback_previous_speed_limit": False,
    "speed_limit_controller_override_manual": True,
    "speed_limit_controller_override_set_speed": False,
    "slc_mapbox_filler": False,
  }

  v_cruise = 29.0
  sm = _build_sm(v_cruise_cluster=v_cruise * CV.MS_TO_KPH, v_ego_cluster=26.0, iq_limit=21.0)
  out = slc.update(apply_enabled=True, now=None, time_validated=True, v_cruise=v_cruise, v_ego=26.0, sm=sm)

  assert slc.slc.update_limits_calls == 1
  assert slc.slc.update_override_calls == 0
  assert out == v_cruise
