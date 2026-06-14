#!/usr/bin/env python3
import json
import os
import time
from math import atan2, cos, radians, sqrt
from pathlib import Path

from cereal import car, custom, log, messaging
from cereal.messaging import PubMaster
from openpilot.common.params import Params
from openpilot.system.hardware import HARDWARE
from openpilot.system.updated.updated import parse_release_notes
from openpilot.system.version import terms_version, training_version
from openpilot.common.basedir import BASEDIR

DEFAULT_DEMO_FIXTURE_PATH = Path(__file__).with_name("nav_demo_fixture_bolingbrook_mapbox.json")
DEMO_ROUTE_STEP_M_MIN = 12.0
TARGET_TIMELINE_SCENES = 180


def _load_demo_fixture() -> dict:
  fixture_path = Path(os.getenv("IQPILOT_NAV_DEMO_FIXTURE", str(DEFAULT_DEMO_FIXTURE_PATH)))
  return json.loads(fixture_path.read_text())


def _lerp(a: float, b: float, t: float) -> float:
  return a + (b - a) * t


def _segment_length_m(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat_scale = 111_320.0
  lon_scale = 111_320.0 * cos(radians((a[0] + b[0]) * 0.5))
  dx = (b[1] - a[1]) * lon_scale
  dy = (b[0] - a[0]) * lat_scale
  return sqrt(dx * dx + dy * dy)


def _route_length_m(points: list[tuple[float, float]]) -> float:
  return sum(_segment_length_m(points[idx], points[idx + 1]) for idx in range(len(points) - 1))


def _cumulative_distances(points: list[tuple[float, float]]) -> list[float]:
  out = [0.0]
  for idx in range(len(points) - 1):
    out.append(out[-1] + _segment_length_m(points[idx], points[idx + 1]))
  return out


def _interpolate_along(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
  if len(points) < 2:
    return points[0]

  remaining = max(distance_m, 0.0)
  for idx in range(len(points) - 1):
    a, b = points[idx], points[idx + 1]
    seg_len = _segment_length_m(a, b)
    if remaining <= seg_len:
      t = 0.0 if seg_len < 1e-3 else remaining / seg_len
      return _lerp(a[0], b[0], t), _lerp(a[1], b[1], t)
    remaining -= seg_len

  return points[-1]


def _bearing_between(a: tuple[float, float], b: tuple[float, float]) -> float:
  lon_scale = cos(radians((a[0] + b[0]) * 0.5))
  dx = (b[1] - a[1]) * lon_scale
  dy = b[0] - a[0]
  return (90.0 - (180.0 / 3.141592653589793) * atan2(dy, dx)) % 360.0


def _slice_route_ahead(points: list[tuple[float, float]], current_idx: int, lookbehind: int = 1) -> list[tuple[float, float]]:
  start = max(current_idx - lookbehind, 0)
  return points[start:]


def _decode_polyline6(polyline: str) -> list[tuple[float, float]]:
  if not polyline:
    return []

  points = []
  index = 0
  lat = 0
  lon = 0

  while index < len(polyline):
    result = 0
    shift = 0
    while True:
      byte = ord(polyline[index]) - 63
      index += 1
      result |= (byte & 0x1F) << shift
      shift += 5
      if byte < 0x20:
        break
    lat += ~(result >> 1) if result & 1 else (result >> 1)

    result = 0
    shift = 0
    while True:
      byte = ord(polyline[index]) - 63
      index += 1
      result |= (byte & 0x1F) << shift
      shift += 5
      if byte < 0x20:
        break
    lon += ~(result >> 1) if result & 1 else (result >> 1)
    points.append((lat / 1_000_000.0, lon / 1_000_000.0))

  return points

def _modifier_to_direction(modifier: str | None) -> int:
  modifier = (modifier or "").lower()
  if "left" in modifier:
    return custom.NavDirection.left
  if "right" in modifier:
    return custom.NavDirection.right
  return custom.NavDirection.none


def _modifier_to_turn_direction(modifier: str | None) -> int:
  modifier = (modifier or "").lower()
  if "left" in modifier:
    return custom.IQModelDataV2.TurnDirection.turnLeft
  if "right" in modifier:
    return custom.IQModelDataV2.TurnDirection.turnRight
  return custom.IQModelDataV2.TurnDirection.none


def _valhalla_modifier_from_type(type_code: int) -> str:
  mapping = {
    9: "slight_right",
    10: "right",
    11: "sharp_right",
    12: "uturn_right",
    13: "uturn_left",
    14: "sharp_left",
    15: "left",
    16: "slight_left",
    17: "straight",
    18: "right",
    19: "left",
    20: "straight",
    21: "roundabout",
    22: "roundabout",
    24: "right",
    25: "left",
    26: "straight",
    27: "straight",
    31: "straight",
    32: "right",
    33: "left",
    36: "straight",
  }
  return mapping.get(type_code, "straight")


def _normalize_mapbox_fixture(data: dict) -> dict:
  route = data["routes"][0]
  leg = route["legs"][0]
  points = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
  waypoint_entries = data.get("waypoints", [{}, {}])
  start_waypoint = waypoint_entries[0] if waypoint_entries else {}
  destination_location = data.get("waypoints", [{}, {}])[-1].get("location", route["geometry"]["coordinates"][-1])
  destination = (float(destination_location[1]), float(destination_location[0]))
  steps = []
  previous_name = os.getenv("IQPILOT_NAV_DEMO_START_NAME", "185 Brandon Ct")
  for step in leg["steps"]:
    maneuver = step["maneuver"]
    name = step["name"] or previous_name
    if step["name"]:
      previous_name = step["name"]
    steps.append({
      "name": name,
      "banner_name": step["name"],
      "location": (float(maneuver["location"][1]), float(maneuver["location"][0])),
      "raw_type": maneuver.get("type", "none"),
      "modifier": maneuver.get("modifier", "straight") or "straight",
      "description": maneuver.get("instruction") or name or "Continue",
      "distance": float(step["distance"]),
      "duration": float(step["duration"]),
    })
  return {
    "provider": "mapbox",
    "route_points": points,
    "duration_s": float(route["duration"]),
    "distance_m": float(route["distance"]),
    "steps": steps,
    "start_name": os.getenv("IQPILOT_NAV_DEMO_START_NAME", start_waypoint.get("name") or "Start"),
    "destination_name": os.getenv("IQPILOT_NAV_DEMO_DESTINATION_NAME", waypoint_entries[-1].get("name") or "Destination"),
    "destination": destination,
  }


def _normalize_valhalla_fixture(data: dict) -> dict:
  trip = data["trip"]
  leg = trip["legs"][0]
  points = _decode_polyline6(leg["shape"])
  start_loc = trip["locations"][0]
  destination_loc = trip["locations"][-1]
  destination = (float(destination_loc["lat"]), float(destination_loc["lon"]))
  steps = []
  previous_name = os.getenv("IQPILOT_NAV_DEMO_START_NAME", "185 Brandon Ct")
  for maneuver in leg["maneuvers"]:
    type_code = int(maneuver.get("type", 8) or 8)
    modifier = _valhalla_modifier_from_type(type_code)
    begin_idx = min(max(int(maneuver.get("begin_shape_index", 0) or 0), 0), len(points) - 1)
    street_names = maneuver.get("street_names") or []
    banner_name = street_names[0] if street_names else ""
    name = banner_name or previous_name
    if banner_name:
      previous_name = banner_name
    steps.append({
      "name": name,
      "banner_name": banner_name,
      "location": points[begin_idx],
      "raw_type": f"valhalla:{type_code}",
      "modifier": modifier,
      "description": maneuver.get("instruction") or name or "Continue",
      "distance": float(maneuver.get("length", 0.0) or 0.0) * 1000.0,
      "duration": float(maneuver.get("time", 0.0) or 0.0),
      "type_code": type_code,
    })
  return {
    "provider": "valhalla",
    "route_points": points,
    "duration_s": float(trip["summary"]["time"]),
    "distance_m": float(trip["summary"]["length"]) * 1000.0,
    "steps": steps,
    "start_name": os.getenv("IQPILOT_NAV_DEMO_START_NAME", start_loc.get("name") or "Start"),
    "destination_name": os.getenv("IQPILOT_NAV_DEMO_DESTINATION_NAME", destination_loc.get("name") or "Destination"),
    "destination": destination,
  }


def _normalize_demo_fixture(data: dict) -> dict:
  if "routes" in data:
    return _normalize_mapbox_fixture(data)
  if "trip" in data:
    return _normalize_valhalla_fixture(data)
  raise ValueError("Unsupported nav demo fixture format")


def _map_step_type(step_type: str, modifier: str | None, type_code: int | None = None) -> int:
  if type_code is not None:
    if type_code in {4, 5, 6}:
      return custom.IQNavState.ManeuverType.arrive
    if type_code in {21, 22, 23, 37}:
      return custom.IQNavState.ManeuverType.roundabout
    if type_code in {18, 19, 24, 25}:
      return custom.IQNavState.ManeuverType.exit
    if type_code in {17, 20, 26, 27}:
      return custom.IQNavState.ManeuverType.merge
    if type_code in {1, 2, 3, 7, 8, 31, 36}:
      return custom.IQNavState.ManeuverType.continueStraight
    return custom.IQNavState.ManeuverType.turn
  step_type = step_type or "none"
  modifier = (modifier or "").lower()
  if step_type == "arrive":
    return custom.IQNavState.ManeuverType.arrive
  if step_type in {"off ramp"}:
    return custom.IQNavState.ManeuverType.exit
  if step_type in {"merge", "on ramp"}:
    return custom.IQNavState.ManeuverType.merge
  if step_type in {"fork"}:
    return custom.IQNavState.ManeuverType.fork
  if step_type in {"roundabout", "rotary", "roundabout turn"}:
    return custom.IQNavState.ManeuverType.roundabout
  if step_type in {"continue", "new name", "depart", "notification"}:
    return custom.IQNavState.ManeuverType.continueStraight
  if step_type in {"turn", "end of road"}:
    return custom.IQNavState.ManeuverType.turn
  if modifier == "straight":
    return custom.IQNavState.ManeuverType.continueStraight
  return custom.IQNavState.ManeuverType.turn


def _nearest_route_index(points: list[tuple[float, float]], target: tuple[float, float]) -> int:
  best_idx = 0
  best_distance = None
  for idx, point in enumerate(points):
    d = _segment_length_m(point, target)
    if best_distance is None or d < best_distance:
      best_distance = d
      best_idx = idx
  return best_idx


DEMO_FIXTURE = _load_demo_fixture()
DEMO_CONTEXT = _normalize_demo_fixture(DEMO_FIXTURE)
DEMO_START_NAME = DEMO_CONTEXT["start_name"]
DEMO_DESTINATION_NAME = DEMO_CONTEXT["destination_name"]
DEMO_DESTINATION = DEMO_CONTEXT["destination"]
DEMO_ROUTE_POINTS = DEMO_CONTEXT["route_points"]
ROUTE_DISTANCES = _cumulative_distances(DEMO_ROUTE_POINTS)
ROUTE_TOTAL_DISTANCE_M = ROUTE_DISTANCES[-1]
DEMO_DURATION_S = float(DEMO_CONTEXT["duration_s"])
DEMO_ROUTE_STEP_M = max(DEMO_ROUTE_STEP_M_MIN, ROUTE_TOTAL_DISTANCE_M / TARGET_TIMELINE_SCENES)

DEMO_STEPS = []
previous_name = DEMO_START_NAME
for idx, step in enumerate(DEMO_CONTEXT["steps"]):
  maneuver_location = step["location"]
  route_index = _nearest_route_index(DEMO_ROUTE_POINTS, maneuver_location)
  route_distance = ROUTE_DISTANCES[route_index]
  step_name = step["name"] or previous_name
  if step["name"]:
    previous_name = step["name"]
  step_type = _map_step_type(step.get("raw_type", "none"), step.get("modifier"), step.get("type_code"))
  direction = _modifier_to_direction(step.get("modifier"))
  step_speed = max(float(step["distance"]) / max(float(step["duration"]), 1.0), 3.5)
  DEMO_STEPS.append({
    "index": idx,
    "name": step_name,
    "banner_name": step.get("banner_name", ""),
    "route_index": route_index,
    "route_distance": route_distance,
    "type": step_type,
    "raw_type": step.get("raw_type", "none"),
    "modifier": step.get("modifier", "straight") or "straight",
    "direction": direction,
    "description": step.get("description") or step_name or "Continue",
    "distance": float(step["distance"]),
    "duration": float(step["duration"]),
    "speed": step_speed,
    "location": maneuver_location,
  })

DEMO_NAV_STEPS = tuple(step for step in DEMO_STEPS if step["raw_type"] not in {"depart", "valhalla:1"})
DEMO_DESTINATION_ROUTE_POINT = DEMO_STEPS[-1]["location"]


def _find_route_index_for_distance(distance_m: float) -> int:
  for idx, route_distance in enumerate(ROUTE_DISTANCES):
    if route_distance >= distance_m:
      return idx
  return len(ROUTE_DISTANCES) - 1


def _find_upcoming_steps(distance_m: float) -> tuple[dict | None, dict | None]:
  upcoming = [step for step in DEMO_NAV_STEPS if step["route_distance"] > distance_m + 1e-3]
  first = upcoming[0] if upcoming else None
  second = upcoming[1] if len(upcoming) > 1 else None
  return first, second


def _current_road_name(distance_m: float) -> str:
  current = DEMO_START_NAME
  for step in DEMO_STEPS:
    if step["route_distance"] <= distance_m and step["banner_name"]:
      current = step["banner_name"]
  return current


def _phase_for_step(step: dict | None, distance_to_next: float) -> int:
  if step is None or step["type"] == custom.IQNavState.ManeuverType.arrive:
    return custom.IQNavState.ManeuverPhase.none
  if step["type"] in (custom.IQNavState.ManeuverType.exit, custom.IQNavState.ManeuverType.merge, custom.IQNavState.ManeuverType.fork):
    if distance_to_next <= 90.0:
      return custom.IQNavState.ManeuverPhase.highwayCommit
    if distance_to_next <= 260.0:
      return custom.IQNavState.ManeuverPhase.highwayPrepare
    return custom.IQNavState.ManeuverPhase.none
  if distance_to_next <= 45.0:
    return custom.IQNavState.ManeuverPhase.turnActive
  if distance_to_next <= 180.0:
    return custom.IQNavState.ManeuverPhase.turnPrepare
  return custom.IQNavState.ManeuverPhase.none


def _zoom_for_distance(distance_to_next: float, maneuver_type: int) -> float:
  if maneuver_type == custom.IQNavState.ManeuverType.arrive:
    return 17.2
  if maneuver_type in (custom.IQNavState.ManeuverType.exit, custom.IQNavState.ManeuverType.merge, custom.IQNavState.ManeuverType.fork):
    if distance_to_next <= 120.0:
      return 16.9
    return 16.3
  if distance_to_next <= 70.0:
    return 17.1
  if distance_to_next <= 160.0:
    return 16.8
  return 16.4


def _speed_target_for_step(current_step: dict | None, next_step: dict | None, distance_to_next: float) -> float:
  current_speed = current_step["speed"] if current_step is not None else 12.0
  next_speed = next_step["speed"] if next_step is not None else current_speed
  if next_step is not None and next_step["type"] == custom.IQNavState.ManeuverType.arrive:
    if distance_to_next <= 25.0:
      return 3.0
    if distance_to_next <= 80.0:
      return 4.5
  if distance_to_next <= 35.0:
    return max(next_speed * 0.85, 4.5)
  if distance_to_next <= 140.0:
    return max(min(current_speed, next_speed + 1.5), 6.0)
  return max(current_speed, 7.0)


def _capture_distance_targets() -> dict[str, float]:
  captures = {}
  selected_steps = [step for step in DEMO_NAV_STEPS if step["type"] != custom.IQNavState.ManeuverType.continueStraight]
  for idx, step in enumerate(selected_steps[:4], start=1):
    captures[f"nav_step_{idx:02d}"] = max(step["route_distance"] - min(120.0, max(step["distance"] * 0.35, 45.0)), 0.0)
  captures["nav_arrival"] = max(DEMO_NAV_STEPS[-1]["route_distance"] - 35.0, 0.0)
  return captures


def _timeline_distances() -> list[float]:
  base = [idx * DEMO_ROUTE_STEP_M for idx in range(int(ROUTE_TOTAL_DISTANCE_M // DEMO_ROUTE_STEP_M) + 1)]
  points = set(base)
  for step in DEMO_NAV_STEPS:
    for offset in (260.0, 180.0, 120.0, 80.0, 50.0, 25.0):
      if step["type"] == custom.IQNavState.ManeuverType.arrive and offset > 120.0:
        continue
      points.add(max(step["route_distance"] - offset, 0.0))
  points.add(ROUTE_TOTAL_DISTANCE_M - 15.0)
  points.add(ROUTE_TOTAL_DISTANCE_M - 5.0)
  return sorted(d for d in points if 0.0 <= d <= ROUTE_TOTAL_DISTANCE_M)


def _make_timeline_scene(distance_m: float) -> dict:
  current_lat, current_lon = _interpolate_along(DEMO_ROUTE_POINTS, distance_m)
  next_lat, next_lon = _interpolate_along(DEMO_ROUTE_POINTS, min(distance_m + 18.0, ROUTE_TOTAL_DISTANCE_M))
  route_idx = _find_route_index_for_distance(distance_m)
  bearing = _bearing_between((current_lat, current_lon), (next_lat, next_lon))

  current_step_idx = max(0, max((idx for idx, step in enumerate(DEMO_STEPS) if step["route_distance"] <= distance_m), default=0))
  current_step = DEMO_STEPS[current_step_idx]
  next_step, second_step = _find_upcoming_steps(distance_m)
  if next_step is None:
    next_step = DEMO_NAV_STEPS[-1]

  next_distance = max(next_step["route_distance"] - distance_m, 0.0)
  remaining_distance = max(ROUTE_TOTAL_DISTANCE_M - distance_m, 0.0)
  remaining_time = max(DEMO_DURATION_S * (remaining_distance / max(ROUTE_TOTAL_DISTANCE_M, 1.0)), 10.0)

  scene = {
    "name": f"nav_timeline_{int(distance_m):04d}",
    "capture_name": "",
    "road_name": _current_road_name(distance_m),
    "distance_m": next_distance,
    "time_remaining": remaining_time,
    "distance_remaining": remaining_distance,
    "speed_limit": max(current_step["speed"], 8.0),
    "speed_limit_ahead": max(next_step["speed"], 6.0),
    "speed_limit_ahead_distance": max(min(next_distance, 220.0), 0.0),
    "phase": _phase_for_step(next_step, next_distance),
    "direction": next_step["direction"],
    "next_type": next_step["type"],
    "next_modifier": next_step["modifier"],
    "next_description": next_step["description"],
    "second_type": second_step["type"] if second_step is not None else custom.IQNavState.ManeuverType.arrive,
    "second_direction": second_step["direction"] if second_step is not None else custom.NavDirection.none,
    "second_modifier": second_step["modifier"] if second_step is not None else "straight",
    "second_distance": max(second_step["route_distance"] - distance_m, 0.0) if second_step is not None else 0.0,
    "second_valid": second_step is not None,
    "provider": custom.IQNavState.LongitudinalProvider.route,
    "route_speed_target": _speed_target_for_step(current_step, next_step, next_distance),
    "current_latitude": current_lat,
    "current_longitude": current_lon,
    "bearing_deg": bearing,
    "zoom_hint": _zoom_for_distance(next_distance, next_step["type"]),
    "destination_latitude": DEMO_DESTINATION[0],
    "destination_longitude": DEMO_DESTINATION[1],
    "destination_name": DEMO_DESTINATION_NAME,
    "route_points": _slice_route_ahead(DEMO_ROUTE_POINTS, route_idx, lookbehind=1),
    "next_maneuver_latitude": next_step["location"][0],
    "next_maneuver_longitude": next_step["location"][1],
  }
  return scene


CAPTURE_TARGETS = _capture_distance_targets()
_timeline_scenes = [_make_timeline_scene(distance_m) for distance_m in _timeline_distances()]
for capture_name, target_distance in CAPTURE_TARGETS.items():
  best_scene = min(
    _timeline_scenes,
    key=lambda scene: abs((ROUTE_TOTAL_DISTANCE_M - scene["distance_remaining"]) - target_distance),
  )
  best_scene["capture_name"] = capture_name
NAV_TIMELINE = tuple(_timeline_scenes)
NAV_SCENES = tuple(scene for scene in NAV_TIMELINE if scene.get("capture_name"))


def seed_ui_test_params(params: Params, version: str, mapbox_token: str = "") -> None:
  params.put("DongleId", "123456789012345")
  params.put("UpdaterCurrentDescription", version)
  params.put("UpdaterNewDescription", version)
  params.put("UpdaterCurrentReleaseNotes", parse_release_notes(BASEDIR))
  params.put("UpdaterNewReleaseNotes", parse_release_notes(BASEDIR))
  params.put("HasAcceptedTerms", terms_version)
  params.put("CompletedTrainingVersion", training_version)
  params.put_bool("OnScreenNavigation", True)

  cp = car.CarParams(notCar=True, wheelbase=2.7, steerRatio=15.0)
  cp.openpilotLongitudinalControl = True
  cp_bytes = cp.to_bytes()
  params.put("CarParamsPersistent", cp_bytes)
  params.put("CarParams", cp_bytes)

  token = mapbox_token or os.getenv("MAPBOX_TOKEN", "")
  if token:
    params.put("MapboxToken", token)


def build_ui_pubmaster() -> PubMaster:
  return PubMaster([
    "deviceState",
    "pandaStates",
    "driverStateV2",
    "selfdriveState",
    "carState",
    "carControl",
    "controlsState",
    "iqPlan",
    "iqLiveData",
    "iqNavState",
    "iqNavRenderState",
    "gpsLocationExternal",
  ])


def publish_onroad_seed(pm: PubMaster, repeats: int = 8, delay: float = 0.05) -> None:
  device_state = messaging.new_message("deviceState")
  device_state.deviceState.started = True
  device_state.deviceState.networkType = log.DeviceState.NetworkType.wifi
  device_state.deviceState.deviceType = HARDWARE.get_device_type()

  panda_states = messaging.new_message("pandaStates", 1)
  panda_states.pandaStates[0].pandaType = log.PandaState.PandaType.dos
  panda_states.pandaStates[0].ignitionLine = True

  driver_state = messaging.new_message("driverStateV2")
  driver_state.driverStateV2.leftDriverData.faceOrientation = [0.0, 0.0, 0.0]

  selfdrive_state = messaging.new_message("selfdriveState")
  selfdrive_state.selfdriveState.enabled = True
  selfdrive_state.selfdriveState.state = log.SelfdriveState.OpenpilotState.enabled

  car_state = messaging.new_message("carState")
  car_state.carState.vEgo = 22.0
  car_state.carState.aEgo = -0.2
  car_state.carState.vCruise = 72.0
  car_state.carState.vCruiseCluster = 72.0

  car_control = messaging.new_message("carControl")
  car_control.carControl.enabled = True
  car_control.carControl.latActive = True
  car_control.carControl.cruiseControl.override = False

  controls_state = messaging.new_message("controlsState")
  controls_state.controlsState.vCruiseDEPRECATED = 72.0
  controls_state.controlsState.vCruiseClusterDEPRECATED = 72.0
  controls_state.controlsState.curvature = 0.0

  gps = messaging.new_message("gpsLocationExternal")
  gps.gpsLocationExternal.flags = 1
  gps.gpsLocationExternal.hasFix = True
  gps.gpsLocationExternal.verticalAccuracy = 1.0
  gps.gpsLocationExternal.speedAccuracy = 0.5
  gps.gpsLocationExternal.bearingAccuracyDeg = 1.0
  gps.gpsLocationExternal.vNED = [0.0, 0.0, 0.0]
  gps.gpsLocationExternal.latitude = DEMO_ROUTE_POINTS[0][0]
  gps.gpsLocationExternal.longitude = DEMO_ROUTE_POINTS[0][1]
  gps.gpsLocationExternal.altitude = 181.0
  gps.gpsLocationExternal.speed = 22.0
  gps.gpsLocationExternal.bearingDeg = _bearing_between(DEMO_ROUTE_POINTS[0], DEMO_ROUTE_POINTS[1])
  gps.gpsLocationExternal.unixTimestampMillis = int(time.time() * 1000)

  for _ in range(repeats):
    pm.send("deviceState", device_state)
    pm.send("pandaStates", panda_states)
    pm.send("driverStateV2", driver_state)
    pm.send("selfdriveState", selfdrive_state)
    pm.send("carState", car_state)
    pm.send("carControl", car_control)
    pm.send("controlsState", controls_state)
    pm.send("gpsLocationExternal", gps)
    time.sleep(delay)


def publish_nav_scene(pm: PubMaster, scene: dict, repeats: int = 6, delay: float = 0.05) -> None:
  iq_plan = messaging.new_message("iqPlan")
  iq_plan.iqPlan.longitudinalPlanSource = custom.IQPlan.LongitudinalPlanSource.nav
  iq_plan.iqPlan.vTarget = float(scene["route_speed_target"])
  iq_plan.iqPlan.aTarget = -0.7
  resolver = iq_plan.iqPlan.speedLimit.resolver
  resolver.speedLimit = float(scene["speed_limit"])
  resolver.speedLimitLast = float(scene["speed_limit"])
  resolver.speedLimitFinal = float(scene["speed_limit"])
  resolver.speedLimitFinalLast = float(scene["speed_limit"])
  resolver.speedLimitValid = True
  resolver.speedLimitLastValid = True
  resolver.speedLimitOffset = 0.0
  resolver.distToSpeedLimit = 0.0
  resolver.source = custom.IQPlan.SpeedLimit.Source.map
  assist = iq_plan.iqPlan.speedLimit.assist
  assist.enabled = False
  assist.active = False
  assist.state = custom.IQPlan.SpeedLimit.AssistState.disabled
  assist.vTarget = 255.0
  assist.aTarget = 0.0
  nav_summary = iq_plan.iqPlan.iqNavState.nav
  nav_summary.engaged = True
  nav_summary.provider = scene["provider"]
  nav_summary.state = custom.IQNavState.LongitudinalState.active
  nav_summary.speedTarget = float(scene["route_speed_target"])
  nav_summary.accelTarget = -0.7
  nav_summary.valid = True

  iq_live_data = messaging.new_message("iqLiveData")
  iq_live_data.iqLiveData.speedLimitValid = True
  iq_live_data.iqLiveData.speedLimit = float(scene["speed_limit"])
  iq_live_data.iqLiveData.speedLimitAheadValid = True
  iq_live_data.iqLiveData.speedLimitAhead = float(scene["speed_limit_ahead"])
  iq_live_data.iqLiveData.speedLimitAheadDistance = float(scene["speed_limit_ahead_distance"])
  iq_live_data.iqLiveData.roadName = scene["road_name"]

  iq_nav_state = messaging.new_message("iqNavState")
  nav_state = iq_nav_state.iqNavState
  nav_state.active = True
  nav_state.destinationValid = True
  nav_state.destinationLatitude = float(scene["destination_latitude"])
  nav_state.destinationLongitude = float(scene["destination_longitude"])
  nav_state.destinationName = scene.get("destination_name", "Navigation destination")
  nav_state.distanceRemaining = float(scene["distance_remaining"])
  nav_state.timeRemaining = float(scene["time_remaining"])
  nav_state.nextManeuverValid = True
  nav_state.nextManeuverDistance = float(scene["distance_m"])
  nav_state.nextManeuverType = scene["next_type"]
  nav_state.nextManeuverDirection = scene["direction"]
  nav_state.nextManeuverModifier = scene["next_modifier"]
  nav_state.nextManeuverDescription = scene["next_description"]
  nav_state.secondNextManeuverValid = scene.get("second_valid", True)
  nav_state.secondNextManeuverType = scene["second_type"]
  nav_state.secondNextManeuverDirection = scene["second_direction"]
  nav_state.secondNextManeuverDistance = float(scene["second_distance"])
  nav_state.secondNextManeuverModifier = scene.get("second_modifier", "")
  nav_state.longitudinalProvider = scene["provider"]
  nav_state.longitudinalState = custom.IQNavState.LongitudinalState.active
  nav_state.longitudinalEngaged = True
  nav_state.speedTarget = float(scene["route_speed_target"])
  nav_state.accelTarget = -0.7
  nav_state.valid = True
  nav_state.targetSpeed = float(scene["route_speed_target"])
  nav_state.targetSpeedValid = True
  nav_state.maneuverPhase = scene["phase"]
  nav_state.maneuverDirection = scene["direction"]
  nav_state.navSpeedTargetActive = True

  if scene["phase"] in (custom.IQNavState.ManeuverPhase.highwayPrepare, custom.IQNavState.ManeuverPhase.highwayCommit):
    nav_state.shouldSendLanePositioning = True
    nav_state.lanePositioningDirection = custom.IQModelDataV2.TurnDirection.turnRight if scene["direction"] == custom.NavDirection.right else custom.IQModelDataV2.TurnDirection.turnLeft
    nav_state.command = custom.IQNavState.Command.laneChange
    nav_state.commandDirection = scene["direction"]
    nav_state.commandIndex = 1
  elif scene["phase"] in (custom.IQNavState.ManeuverPhase.turnPrepare, custom.IQNavState.ManeuverPhase.turnActive):
    nav_state.shouldSendTurnDesire = True
    nav_state.turnDesireDirection = custom.IQModelDataV2.TurnDirection.turnLeft if scene["direction"] == custom.NavDirection.left else custom.IQModelDataV2.TurnDirection.turnRight

  iq_nav_render = messaging.new_message("iqNavRenderState")
  render_state = iq_nav_render.iqNavRenderState
  render_state.active = True
  render_state.currentLatitude = float(scene["current_latitude"])
  render_state.currentLongitude = float(scene["current_longitude"])
  render_state.bearingDeg = float(scene["bearing_deg"])
  render_state.zoomHint = float(scene["zoom_hint"])
  route_points = scene["route_points"]
  render_state.init("routePolyline", len(route_points))
  render_state.init("routePolylineSimplified", len(route_points))
  for idx, (lat, lon) in enumerate(route_points):
    render_state.routePolyline[idx].latitude = lat
    render_state.routePolyline[idx].longitude = lon
    render_state.routePolylineSimplified[idx].latitude = lat
    render_state.routePolylineSimplified[idx].longitude = lon
  render_state.nextManeuverLatitude = float(scene["next_maneuver_latitude"])
  render_state.nextManeuverLongitude = float(scene["next_maneuver_longitude"])
  render_state.nextManeuverType = scene["next_type"]
  render_state.nextManeuverDirection = scene["direction"]
  render_state.nextManeuverDistance = float(scene["distance_m"])
  render_state.destinationLatitude = float(scene["destination_latitude"])
  render_state.destinationLongitude = float(scene["destination_longitude"])

  gps = messaging.new_message("gpsLocationExternal")
  gps.gpsLocationExternal.flags = 1
  gps.gpsLocationExternal.hasFix = True
  gps.gpsLocationExternal.verticalAccuracy = 1.0
  gps.gpsLocationExternal.speedAccuracy = 0.5
  gps.gpsLocationExternal.bearingAccuracyDeg = 1.0
  gps.gpsLocationExternal.vNED = [0.0, 0.0, 0.0]
  gps.gpsLocationExternal.latitude = float(scene["current_latitude"])
  gps.gpsLocationExternal.longitude = float(scene["current_longitude"])
  gps.gpsLocationExternal.altitude = 181.0
  gps.gpsLocationExternal.speed = max(float(scene["route_speed_target"]), 4.5)
  gps.gpsLocationExternal.bearingDeg = float(scene["bearing_deg"])
  gps.gpsLocationExternal.unixTimestampMillis = int(time.time() * 1000)

  for _ in range(repeats):
    pm.send("iqPlan", iq_plan)
    pm.send("iqLiveData", iq_live_data)
    pm.send("iqNavState", iq_nav_state)
    pm.send("iqNavRenderState", iq_nav_render)
    pm.send("gpsLocationExternal", gps)
    time.sleep(delay)
