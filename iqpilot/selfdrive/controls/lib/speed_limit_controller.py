#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import calendar
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from cereal import car, custom
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.common.k3_slc_log import k3_slc_log
from openpilot.iqpilot.common.slc_utilities import calculate_bearing_offset, is_url_pingable
from openpilot.iqpilot.common.slc_variables import FREE_MAPBOX_REQUESTS, OFFSET_MAP_IMPERIAL, OFFSET_MAP_METRIC

try:
  import requests
except ImportError:
  requests = None

ButtonType = car.CarState.ButtonEvent.Type
SpeedLimitAssistState = custom.IQPlan.SpeedLimit.AssistState
EventNameIQ = custom.IQOnroadEvent.EventName

LIMIT_MIN_ACC = -1.5
LIMIT_MAX_ACC = 1.0
LIMIT_MIN_SPEED = 8.33
LIMIT_SPEED_OFFSET_TH = -1.0
LIMIT_ADAPT_ACC = -1.0
CONTROL_HORIZON = 10.0

AUTO_CONFIRM_PERIOD = 5.0
AUTO_DENY_PERIOD = 30.0

POLICY_MAP_DATA_ONLY = 0
POLICY_MAP_DATA_PRIORITY = 1
POLICY_COMBINED = 2

CONFIRM_LOWER_BUTTONS = frozenset({ButtonType.decelCruise, ButtonType.setCruise})
CONFIRM_HIGHER_BUTTONS = frozenset({ButtonType.accelCruise, ButtonType.resumeCruise})


class IQSpeedLimitResolver:
  def __init__(self):
    self.map_speed_limit = 0.0
    self.next_speed_limit = 0.0
    self.next_speed_distance = 0.0

  @staticmethod
  def _is_alive(sm, key):
    if hasattr(sm, "alive"):
      return bool(sm.alive.get(key, False))
    return False

  def update_map_data(self, v_ego, sm, lookahead_lower, lookahead_higher):
    if not self._is_alive(sm, "iqLiveData"):
      self.map_speed_limit = 0.0
      self.next_speed_limit = 0.0
      self.next_speed_distance = 0.0
      return

    map_data = sm["iqLiveData"]
    current_limit = float(getattr(map_data, "speedLimit", 0)) if getattr(map_data, "speedLimitValid", False) else 0.0
    ahead_limit = float(getattr(map_data, "speedLimitAhead", 0)) if getattr(map_data, "speedLimitAheadValid", False) else 0.0
    ahead_distance = float(getattr(map_data, "speedLimitAheadDistance", 0))

    self.next_speed_limit = ahead_limit
    self.next_speed_distance = ahead_distance

    if ahead_limit > 0 and ahead_distance > 0:
      if ahead_limit < v_ego:
        adapt_time = (ahead_limit - v_ego) / LIMIT_ADAPT_ACC  # positive (LIMIT_ADAPT_ACC negative)
        adapt_distance = v_ego * adapt_time + 0.5 * LIMIT_ADAPT_ACC * adapt_time**2
        comfort_distance = lookahead_lower * v_ego
        if ahead_distance <= max(adapt_distance, comfort_distance):
          self.map_speed_limit = ahead_limit
          return
      elif ahead_limit > current_limit:
        if ahead_distance <= lookahead_higher * v_ego:
          self.map_speed_limit = ahead_limit
          return

    self.map_speed_limit = current_limit

  def resolve(self, dashboard_limit, mapbox_limit, slc_params):
    policy = slc_params.get("slc_policy", POLICY_MAP_DATA_PRIORITY)

    sources = {}
    if dashboard_limit >= LIMIT_MIN_SPEED:
      sources["Dashboard"] = dashboard_limit
    if mapbox_limit >= LIMIT_MIN_SPEED:
      sources["Mapbox"] = mapbox_limit
    if self.map_speed_limit >= LIMIT_MIN_SPEED:
      sources["Map Data"] = self.map_speed_limit

    if policy == POLICY_MAP_DATA_ONLY:
      if "Map Data" in sources:
        return sources["Map Data"], "Map Data"
      return 0.0, "None"

    if policy == POLICY_MAP_DATA_PRIORITY:
      for src in ("Map Data", "Dashboard", "Mapbox"):
        if src in sources:
          return sources[src], src
      return 0.0, "None"

    if policy == POLICY_COMBINED:
      if sources:
        src = min(sources, key=sources.get)
        return sources[src], src
      return 0.0, "None"

    return 0.0, "None"


class IQSpeedLimitAssist:
  def __init__(self, params):
    self._params = params
    self._state = SpeedLimitAssistState.inactive
    self._prev_state = SpeedLimitAssistState.inactive

    self.target = 0.0
    self.source = "None"

    self.unconfirmed_limit = 0.0
    self.unconfirmed_source = "None"

    self.previous_target = 0.0
    self.previous_source = "None"
    self.denied_target = 0.0

    self._pre_active_timer = 0.0

    self.pending_events = []

    self.output_a_target = 0.0

    self.just_confirmed = False

  @property
  def state(self):
    return self._state

  def update(self, enabled, v_ego, resolved_limit, resolved_source, slc_params, sm):
    self.pending_events = []
    self.just_confirmed = False
    self._prev_state = self._state

    if not enabled:
      if self._state != SpeedLimitAssistState.disabled:
        self._state = SpeedLimitAssistState.disabled
        self._reset_confirmed()
        self._reset_unconfirmed()
      self.output_a_target = 0.0
      self._fire_transition_events()
      return

    if self._state == SpeedLimitAssistState.disabled:
      self._state = SpeedLimitAssistState.inactive

    has_limit = resolved_limit >= LIMIT_MIN_SPEED
    v_offset = self.target - v_ego if self.target > 0 else 0.0

    if self._state == SpeedLimitAssistState.inactive:
      if has_limit:
        if self._needs_confirmation(resolved_limit, slc_params):
          self._enter_pre_active(resolved_limit, resolved_source)
        else:
          self._apply_limit(resolved_limit, resolved_source, v_ego, fire_changed_event=True)

    elif self._state == SpeedLimitAssistState.preActive:
      self._pre_active_timer += DT_MDL
      confirmed, denied = self._check_confirmation(sm, slc_params)

      if denied:
        self.denied_target = self.unconfirmed_limit
        self.previous_source = self.unconfirmed_source
        self.previous_target = self.unconfirmed_limit
        self._reset_unconfirmed()
        self._state = SpeedLimitAssistState.inactive
      elif confirmed:
        self._confirm(v_ego)
      elif not has_limit:
        self._reset_unconfirmed()
        self._state = SpeedLimitAssistState.inactive

    elif self._state in (SpeedLimitAssistState.active, SpeedLimitAssistState.adapting):
      if not has_limit:
        if self.target > 0:
          self.previous_target = self.target
          self.previous_source = self.source
        self._reset_confirmed()
        self._state = SpeedLimitAssistState.inactive
      elif abs(resolved_limit - self.target) >= 1.0:
        if self._needs_confirmation(resolved_limit, slc_params):
          self._enter_pre_active(resolved_limit, resolved_source)
        else:
          self._apply_limit(resolved_limit, resolved_source, v_ego, fire_changed_event=True)
      elif self._state == SpeedLimitAssistState.adapting:
        if v_offset >= LIMIT_SPEED_OFFSET_TH:
          self._state = SpeedLimitAssistState.active
      elif self._state == SpeedLimitAssistState.active:
        if v_offset < LIMIT_SPEED_OFFSET_TH:
          self._state = SpeedLimitAssistState.adapting

    self._update_a_target(v_ego)
    self._fire_transition_events()

  def _enter_pre_active(self, limit, source):
    self.unconfirmed_limit = limit
    self.unconfirmed_source = source
    self._state = SpeedLimitAssistState.preActive
    self._pre_active_timer = 0.0

  def _confirm(self, v_ego):
    self.target = self.unconfirmed_limit
    self.source = self.unconfirmed_source
    self.previous_target = self.target
    self.previous_source = self.source
    self.denied_target = 0.0
    self._reset_unconfirmed()
    self._params.put_nonblocking("PreviousSpeedLimit", float(self.target))
    self.just_confirmed = True
    v_offset = self.target - v_ego
    self._state = SpeedLimitAssistState.adapting if v_offset < LIMIT_SPEED_OFFSET_TH else SpeedLimitAssistState.active

  def _apply_limit(self, limit, source, v_ego, fire_changed_event=False):
    self.target = limit
    self.source = source
    self.previous_target = self.target
    self.previous_source = self.source
    self._params.put_nonblocking("PreviousSpeedLimit", float(self.target))
    if fire_changed_event:
      self.pending_events.append(EventNameIQ.speedLimitChanged)
    v_offset = self.target - v_ego
    self._state = SpeedLimitAssistState.adapting if v_offset < LIMIT_SPEED_OFFSET_TH else SpeedLimitAssistState.active

  def _needs_confirmation(self, new_limit, slc_params):
    if new_limit < self.target:
      return slc_params.get("speed_limit_confirmation_lower", False)
    return slc_params.get("speed_limit_confirmation_higher", False)

  def _check_confirmation(self, sm, slc_params):
    confirmed = False
    denied = False

    if slc_params.get("slc_auto_confirm", False) and self._pre_active_timer >= AUTO_CONFIRM_PERIOD:
      return True, False

    if self._pre_active_timer >= AUTO_DENY_PERIOD:
      return False, True

    is_lower = (self.target <= 0) or (self.unconfirmed_limit <= self.target)
    try:
      for btn in sm["carState"].buttonEvents:
        if btn.pressed:
          continue
        if is_lower and btn.type in CONFIRM_LOWER_BUTTONS:
          confirmed = True
          break
        elif not is_lower and btn.type in CONFIRM_HIGHER_BUTTONS:
          confirmed = True
          break
    except (AttributeError, TypeError):
      pass

    return confirmed, denied

  def _update_a_target(self, v_ego):
    if self._state in (SpeedLimitAssistState.adapting, SpeedLimitAssistState.active) and self.target > 0:
      v_offset = self.target - v_ego
      self.output_a_target = float(np.clip(v_offset / CONTROL_HORIZON, LIMIT_MIN_ACC, LIMIT_MAX_ACC))
    else:
      self.output_a_target = 0.0

  def _fire_transition_events(self):
    prev = self._prev_state
    curr = self._state
    if prev == curr:
      return
    if curr == SpeedLimitAssistState.preActive:
      self.pending_events.append(EventNameIQ.speedLimitPreActive)
    elif curr in (SpeedLimitAssistState.adapting, SpeedLimitAssistState.active):
      if prev not in (SpeedLimitAssistState.adapting, SpeedLimitAssistState.active):
        self.pending_events.append(EventNameIQ.speedLimitActive)

  def _reset_confirmed(self):
    self.target = 0.0
    self.source = "None"

  def _reset_unconfirmed(self):
    self.unconfirmed_limit = 0.0
    self.unconfirmed_source = "None"


class SpeedLimitController:
  def __init__(self, params):
    self.params = params
    self._resolver = IQSpeedLimitResolver()
    self._assist = IQSpeedLimitAssist(params)

    self.calling_mapbox = False
    self.mapbox_limit = 0.0
    self.segment_distance = 0.0

    self.gps_valid = False
    self.gps_position = {"bearing": 0, "latitude": 0, "longitude": 0}

    self.override_slc = False
    self.overridden_speed = 0.0

    self._resolved_limit = 0.0
    self._resolved_source = "None"
    self._czone_was_limiting = False

    self.pending_events = []

    mapbox_requests_raw = self.params.get("MapBoxRequests")
    if isinstance(mapbox_requests_raw, dict):
      self.mapbox_requests = mapbox_requests_raw
    elif mapbox_requests_raw is not None:
      try:
        raw = mapbox_requests_raw
        if isinstance(raw, bytes):
          self.mapbox_requests = json.loads(raw.decode("utf-8"))
        elif isinstance(raw, str):
          self.mapbox_requests = json.loads(raw)
        else:
          self.mapbox_requests = {}
      except (json.JSONDecodeError, AttributeError, TypeError):
        self.mapbox_requests = {}
    else:
      self.mapbox_requests = {}
    self.mapbox_requests.setdefault("total_requests", 0)
    self.mapbox_requests.setdefault("max_requests", FREE_MAPBOX_REQUESTS - (28 * 100))

    self.mapbox_host = "https://api.mapbox.com"
    self.mapbox_token = self.params.get("MapboxToken")
    if self.mapbox_token is not None and isinstance(self.mapbox_token, bytes):
      self.mapbox_token = self.mapbox_token.decode("utf-8")

    previous_limit = self.params.get("PreviousSpeedLimit")
    if previous_limit is not None:
      try:
        val = previous_limit
        self._assist.previous_target = float(val.decode("utf-8") if isinstance(val, bytes) else val)
      except (ValueError, AttributeError):
        pass

    self.executor = ThreadPoolExecutor(max_workers=1)
    self._last_mapbox_log_t = 0.0
    self._last_mapbox_diag_t = 0.0
    self._last_mapbox_diag_message = None

    self.session = requests.Session() if requests is not None else None
    if self.session is not None:
      self.session.headers.update({"Accept-Language": "en"})
      self.session.headers.update({"User-Agent": "iqpilot-mapbox-speed-limit-retriever/1.0"})

    self.tomtom_host = "https://api.tomtom.com"
    self.tomtom_token = self._resolve_tomtom_token()
    self.tomtom_limit = 0.0
    self.tomtom_segment_distance = 0.0
    self.calling_tomtom = False
    self.tomtom_consecutive_failures = 0
    self.tomtom_backoff_until = 0.0

  def _resolve_tomtom_token(self) -> str:
    try:
      from openpilot.iqpilot.navd.runtime_common import resolve_tomtom_token
      return resolve_tomtom_token(self.params) or ""
    except Exception:
      tok = self.params.get("TomTomToken")
      return (tok.decode("utf-8") if isinstance(tok, bytes) else (tok or "")).strip()

  @property
  def target(self):
    return self._assist.target

  @property
  def source(self):
    return self._assist.source

  @property
  def active_target(self):
    return self._resolved_limit

  @property
  def active_source(self):
    return self._resolved_source

  @property
  def unconfirmed_speed_limit(self):
    return self._assist.unconfirmed_limit

  @property
  def map_speed_limit(self):
    return self._resolver.map_speed_limit

  @property
  def next_speed_limit(self):
    return self._resolver.next_speed_limit

  @property
  def assist_state(self):
    return self._assist.state

  @property
  def output_a_target(self):
    return self._assist.output_a_target

  def get_offset(self, is_metric):
    offset_map = OFFSET_MAP_METRIC if is_metric else OFFSET_MAP_IMPERIAL
    for low, high, offset_param in offset_map:
      if low < self._assist.target < high:
        offset_value = self.params.get(offset_param)
        if offset_value is not None:
          if isinstance(offset_value, bytes):
            return float(offset_value.decode("utf-8"))
          return float(offset_value)
        return 0.0
    return 0.0

  @staticmethod
  def _is_alive(sm, key):
    if hasattr(sm, "alive"):
      return bool(sm.alive.get(key, False))
    return False

  def update_gps(self, sm):
    iq_loc_valid = False
    iq_loc = None
    if self._is_alive(sm, "iqLiveLocation"):
      iq_loc = sm["iqLiveLocation"]
      iq_loc_valid = bool(getattr(iq_loc, "gpsHealthy", False))

    if self._is_alive(sm, "gpsLocationExternal"):
      gps_location = sm["gpsLocationExternal"]
    elif self._is_alive(sm, "gpsLocation"):
      gps_location = sm["gpsLocation"]
    else:
      gps_location = None

    gps_has_fix = False
    if gps_location is not None:
      gps_has_fix = bool(getattr(gps_location, "hasFix", False))
      gps_has_fix |= bool(getattr(gps_location, "flags", 0) > 0)

    if gps_location and (gps_has_fix or iq_loc_valid):
      self.gps_valid = True
      self.gps_position = {
        "bearing": getattr(gps_location, "bearingDeg", 0),
        "latitude": getattr(gps_location, "latitude", 0),
        "longitude": getattr(gps_location, "longitude", 0),
      }
    elif iq_loc_valid and iq_loc is not None and getattr(iq_loc, "geodeticPosition", None) and iq_loc.geodeticPosition.isValid:
      self.gps_valid = True
      self.gps_position = {
        "bearing": math.degrees(iq_loc.alignedOrientationNed.values[2]) if getattr(iq_loc, "alignedOrientationNed", None) else 0,
        "latitude": iq_loc.geodeticPosition.values[0],
        "longitude": iq_loc.geodeticPosition.values[1],
      }
    else:
      self.gps_valid = False

  def _log_mapbox_diag(self, message, force=False):
    now_mono = time.monotonic()
    if not force and message == self._last_mapbox_diag_message and now_mono - self._last_mapbox_diag_t < 5.0:
      return
    if not force and now_mono - self._last_mapbox_diag_t < 2.0:
      return
    self._last_mapbox_diag_t = now_mono
    self._last_mapbox_diag_message = message
    cloudlog.info(message)
    k3_slc_log(message)

  def get_mapbox_speed_limit(self, now, time_validated, v_ego, sm):
    if requests is None or self.session is None:
      self._log_mapbox_diag("SLC Mapbox skipped: requests session unavailable")
      self.mapbox_limit = 0.0
      self.segment_distance = 0.0
      return

    steer_angle = sm["carState"].steeringAngleDeg - sm["liveParameters"].angleOffsetDeg
    if not self.gps_valid or not self.mapbox_token or steer_angle >= 45:
      self._log_mapbox_diag(f"SLC Mapbox skipped: gps_valid={self.gps_valid} token={bool(self.mapbox_token)} steer_angle={round(float(steer_angle), 2)}")
      self.mapbox_limit = 0.0
      self.segment_distance = 0.0
      return

    if v_ego < 1:
      return

    if self.segment_distance > 0:
      self.segment_distance -= v_ego * DT_MDL
      return

    if self.calling_mapbox:
      self.segment_distance = v_ego
      return

    def make_request():
      try:
        self.calling_mapbox = True
        successful = False

        if not is_url_pingable(self.mapbox_host):
          self._log_mapbox_diag("SLC Mapbox skipped: host not pingable", force=True)
          self.segment_distance = 1000
          return None

        if time_validated:
          current_month = now.month
          if current_month != self.mapbox_requests.get("month"):
            self.mapbox_requests.update(
              {
                "month": current_month,
                "total_requests": 0,
                "max_requests": FREE_MAPBOX_REQUESTS - calendar.monthrange(now.year, current_month)[1] * 100,
              }
            )

        self.mapbox_requests["total_requests"] += 1
        self.params.put_nonblocking("MapBoxRequests", self.mapbox_requests)

        lat = self.gps_position.get("latitude")
        lon = self.gps_position.get("longitude")
        bearing = self.gps_position.get("bearing")
        future_lat, future_lon = calculate_bearing_offset(lat, lon, bearing, v_ego)

        self._log_mapbox_diag(
          f"SLC Mapbox request: lat={round(float(lat), 6)} lon={round(float(lon), 6)} bearing={round(float(bearing), 2)} v_ego={round(float(v_ego), 2)}",
          force=True,
        )

        url = f"{self.mapbox_host}/matching/v5/mapbox/driving/{lon},{lat};{future_lon},{future_lat}.json"
        mapbox_params = {
          "access_token": self.mapbox_token,
          "annotations": "maxspeed,distance",
          "geometries": "polyline6",
          "overview": "full",
          "steps": "false",
          "radiuses": "10;10",
          "tidy": "true",
        }

        response = self.session.get(url, params=mapbox_params, timeout=10)
        response.raise_for_status()
        successful = True
        return response.json()
      except Exception as exception:
        now_mono = time.monotonic()
        if now_mono - self._last_mapbox_log_t >= 5.0:
          self._last_mapbox_log_t = now_mono
          msg = f"SLC Mapbox request failed: {exception}"
          cloudlog.warning(msg)
          k3_slc_log(msg)
      finally:
        self.calling_mapbox = False
        if not successful:
          self.mapbox_limit = 0.0
          self.segment_distance = v_ego

    def complete_request(future):
      try:
        data = future.result()
        if data:
          matchings = data.get("matchings") or []
          if not matchings:
            self.mapbox_limit = 0.0
            self.segment_distance = v_ego
            return
          legs = (matchings[0] or {}).get("legs") or []
          if not legs:
            self.mapbox_limit = 0.0
            self.segment_distance = v_ego
            return
          annotation = legs[0].get("annotation") or {}
          distances = annotation.get("distance") or [v_ego]
          segment_distance = distances[0]
          speed_data = annotation.get("maxspeed", [])
          speed_limit_kph = 0
          if speed_data:
            first = speed_data[0]
            speed_limit_kph = (first.get("speed") if first.get("speed") != "none" else 0) or 0
          if speed_limit_kph > 0:
            self.mapbox_limit = speed_limit_kph * CV.KPH_TO_MS
            self.segment_distance = segment_distance
            self._log_mapbox_diag(
              f"SLC Mapbox callback: speed_limit_kph={round(float(speed_limit_kph), 2)} segment_distance={round(float(segment_distance), 2)}",
              force=True,
            )
            return
        self.mapbox_limit = 0.0
        self.segment_distance = v_ego
      except Exception as exception:
        now_mono = time.monotonic()
        if now_mono - self._last_mapbox_log_t >= 5.0:
          self._last_mapbox_log_t = now_mono
          msg = f"SLC Mapbox callback failed: {exception}"
          cloudlog.warning(msg)
          k3_slc_log(msg)
        self.mapbox_limit = 0.0
        self.segment_distance = v_ego

    future = self.executor.submit(make_request)
    future.add_done_callback(complete_request)

  def get_tomtom_speed_limit(self, now, time_validated, v_ego, sm):
    if requests is None or self.session is None or not self.tomtom_token:
      self.tomtom_limit = 0.0
      self.tomtom_segment_distance = 0.0
      return

    # backoff: an exhausted-quota key (HTTP 403 InsufficientFunds) otherwise gets
    # hammered every 250 m for the rest of the drive
    if time.monotonic() < self.tomtom_backoff_until:
      self.tomtom_limit = 0.0
      return

    steer_angle = sm["carState"].steeringAngleDeg - sm["liveParameters"].angleOffsetDeg
    if not self.gps_valid or steer_angle >= 45 or v_ego < 1:
      self.tomtom_limit = 0.0
      return

    # re-query at most once per ~250 m of travel
    if self.tomtom_segment_distance > 0:
      self.tomtom_segment_distance -= v_ego * DT_MDL
      return
    if self.calling_tomtom:
      self.tomtom_segment_distance = v_ego
      return

    lat = self.gps_position.get("latitude")
    lon = self.gps_position.get("longitude")
    bearing = self.gps_position.get("bearing")
    future_lat, future_lon = calculate_bearing_offset(lat, lon, bearing, max(v_ego, 12.0) * 12.0)

    def make_request():
      successful = False
      try:
        self.calling_tomtom = True
        url = f"{self.tomtom_host}/routing/1/calculateRoute/{lat},{lon}:{future_lat},{future_lon}/json"
        self._log_mapbox_diag(
          f"SLC TomTom request: lat={round(float(lat), 6)} lon={round(float(lon), 6)} bearing={round(float(bearing), 2)} v_ego={round(float(v_ego), 2)}",
          force=True,
        )
        response = self.session.get(url, params={"key": self.tomtom_token, "sectionType": "speedLimit", "traffic": "false"}, timeout=10)
        response.raise_for_status()
        successful = True
        self.tomtom_consecutive_failures = 0
        return response.json()
      except Exception as exception:
        status = getattr(getattr(exception, "response", None), "status_code", None)
        if status in (401, 403, 429):
          # dead/exhausted key: retry hourly in case credits refill, not every 250 m
          self.tomtom_backoff_until = time.monotonic() + 3600.0
        else:
          self.tomtom_consecutive_failures += 1
          self.tomtom_backoff_until = time.monotonic() + min(600.0, 10.0 * (2 ** min(self.tomtom_consecutive_failures, 6)))
        now_mono = time.monotonic()
        if now_mono - self._last_mapbox_log_t >= 5.0:
          self._last_mapbox_log_t = now_mono
          msg = f"SLC TomTom request failed (backoff {max(0.0, self.tomtom_backoff_until - now_mono):.0f}s): {exception}"
          cloudlog.warning(msg)
          k3_slc_log(msg)
      finally:
        self.calling_tomtom = False
        if not successful:
          self.tomtom_limit = 0.0
          self.tomtom_segment_distance = v_ego

    def complete_request(future):
      try:
        data = future.result()
        kmh = 0
        if data:
          sections = ((data.get("routes") or [{}])[0]).get("sections") or []
          speed_secs = [s for s in sections if s.get("sectionType") == "SPEED_LIMIT"]
          at_start = next((s for s in speed_secs if s.get("startPointIndex") == 0), None)
          chosen = at_start or (speed_secs[0] if speed_secs else None)
          if chosen:
            kmh = chosen.get("maxSpeedLimitInKmh") or 0
        if kmh and kmh > 0:
          self.tomtom_limit = float(kmh) * CV.KPH_TO_MS
          self._log_mapbox_diag(
            f"SLC TomTom callback: speed_limit_kph={round(float(kmh), 2)}",
            force=True,
          )
        else:
          self.tomtom_limit = 0.0
      except Exception as exception:
        now_mono = time.monotonic()
        if now_mono - self._last_mapbox_log_t >= 5.0:
          self._last_mapbox_log_t = now_mono
          cloudlog.warning(f"SLC TomTom callback failed: {exception}")
        self.tomtom_limit = 0.0
      finally:
        self.tomtom_segment_distance = 250.0

    future = self.executor.submit(make_request)
    future.add_done_callback(complete_request)

  def _construction_zone_limit(self, sm, slc_params):
    if not slc_params.get("construction_zone_assist", False):
      return 0.0
    if not self._is_alive(sm, "iqConstructionZone"):
      return 0.0
    if not bool(getattr(sm["iqConstructionZone"], "active", False)):
      return 0.0
    speed = slc_params.get("construction_zone_speed", 60.0)
    unit = CV.KPH_TO_MS if slc_params.get("is_metric", False) else CV.MPH_TO_MS
    return max(float(speed), 0.0) * unit

  def _maybe_reset_mapbox_quota(self, now, time_validated):
    if time_validated:
      current_month = now.month
      if current_month != self.mapbox_requests.get("month"):
        self.mapbox_requests.update(
          {
            "month": current_month,
            "total_requests": 0,
            "max_requests": FREE_MAPBOX_REQUESTS - calendar.monthrange(now.year, current_month)[1] * 100,
          }
        )
        self.params.put_nonblocking("MapBoxRequests", self.mapbox_requests)

  def update_limits(self, dashboard_speed_limit, now, time_validated, v_cruise, v_ego, sm, slc_params):
    self.update_gps(sm)

    lookahead_lower = slc_params.get("map_speed_lookahead_lower", 5.0)
    lookahead_higher = slc_params.get("map_speed_lookahead_higher", 5.0)
    self._resolver.update_map_data(v_ego, sm, lookahead_lower, lookahead_higher)

    use_online = slc_params.get("slc_online_filler", False)
    if use_online:
      self._maybe_reset_mapbox_quota(now, time_validated)
      if self.mapbox_requests["total_requests"] < self.mapbox_requests["max_requests"]:
        self.get_mapbox_speed_limit(now, time_validated, v_ego, sm)
      else:
        self.mapbox_limit = 0.0
        self.segment_distance = 0.0
      self.get_tomtom_speed_limit(now, time_validated, v_ego, sm)
    else:
      self.mapbox_limit = 0.0
      self.tomtom_limit = 0.0
      self.segment_distance = 0.0
      self.tomtom_segment_distance = 0.0

    online_limit = self.tomtom_limit if self.tomtom_limit > 0 else self.mapbox_limit

    dashboard_limit = float(dashboard_speed_limit) if dashboard_speed_limit else 0.0
    resolved_limit, resolved_source = self._resolver.resolve(dashboard_limit, online_limit, slc_params)

    enabled = bool(getattr(sm["selfdriveState"], "enabled", False))
    if resolved_limit <= 0:
      if self._assist.denied_target != self._assist.previous_target > 0 and slc_params.get("slc_fallback_previous_speed_limit", False):
        resolved_limit = self._assist.previous_target
        resolved_source = self._assist.previous_source
      elif enabled and slc_params.get("slc_fallback_set_speed", False):
        resolved_limit = v_cruise
        resolved_source = "None"

    # work-zone clamp: only ever lowers the resolved limit
    czone_limit = self._construction_zone_limit(sm, slc_params)
    if czone_limit > 0 and (resolved_limit <= 0 or resolved_limit > czone_limit):
      resolved_limit = czone_limit
      resolved_source = "Construction"

    self._resolved_limit = float(resolved_limit)
    self._resolved_source = resolved_source

    self._assist.update(enabled, v_ego, resolved_limit, resolved_source, slc_params, sm)

    if self._assist.just_confirmed:
      self.overridden_speed = 0.0

    self.pending_events = list(self._assist.pending_events)

    czone_limiting = resolved_source == "Construction"
    if czone_limiting and not self._czone_was_limiting:
      self.pending_events.append(EventNameIQ.constructionZoneDetected)
    self._czone_was_limiting = czone_limiting

  def update_override(self, v_cruise, v_cruise_diff, v_ego, v_ego_diff, sm, slc_params, is_metric):
    offset = self.get_offset(is_metric)
    target = self._assist.target

    self.override_slc = self.overridden_speed > target + offset > 0
    self.override_slc |= sm["carState"].gasPressed and v_ego > target + offset > 0
    self.override_slc &= bool(getattr(sm["selfdriveState"], "enabled", False))

    if self.override_slc:
      if slc_params.get("speed_limit_controller_override_manual", False):
        if sm["carState"].gasPressed:
          self.overridden_speed = max(v_ego + v_ego_diff, self.overridden_speed)
        self.overridden_speed = float(np.clip(self.overridden_speed, target + offset, v_cruise + v_cruise_diff))
      elif slc_params.get("speed_limit_controller_override_set_speed", False):
        self.overridden_speed = v_cruise + v_cruise_diff
    else:
      self.overridden_speed = 0.0
