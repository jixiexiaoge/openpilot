import json
import platform
from pathlib import Path

from openpilot.common.params import Params

_MAPBOX_DEFAULT_HELPER_UNAVAILABLE = False
_GPS_SERVICES = ("gpsLocationExternal", "gpsLocation")
_POSITION_PARAM_KEYS = ("LastGPSPosition", "LastGPSPositionIQLoc")


def _decode_param(value) -> str:
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="ignore").strip()
  if isinstance(value, str):
    return value.strip()
  return ""


def resolve_mapbox_token(params: Params | None = None) -> str:
  global _MAPBOX_DEFAULT_HELPER_UNAVAILABLE

  params = params or Params()
  token = _decode_param(params.get("MapboxToken"))
  if token:
    return token

  if _MAPBOX_DEFAULT_HELPER_UNAVAILABLE:
    return ""

  try:
    from openpilot.iqpilot.navd.runtime_common import ensure_default_mapbox_token
  except Exception:
    _MAPBOX_DEFAULT_HELPER_UNAVAILABLE = True
    return ""

  for args in ((params,), ()):
    try:
      token = _decode_param(ensure_default_mapbox_token(*args))
    except TypeError:
      continue
    except Exception:
      token = ""

    if not token:
      token = _decode_param(params.get("MapboxToken"))
    if token:
      return token

  return _decode_param(params.get("MapboxToken"))


def has_mapbox_token(params: Params | None = None) -> bool:
  return bool(resolve_mapbox_token(params))


def _valid_lat_lon(lat: float, lon: float) -> bool:
  return abs(lat) <= 90.0 and abs(lon) <= 180.0 and (abs(lat) > 1e-4 or abs(lon) > 1e-4)


def _float_field(data: dict, *names: str) -> float:
  for name in names:
    if name in data:
      return float(data.get(name) or 0.0)
  return 0.0


def _position_from_json(raw) -> tuple[float, float, float, bool]:
  text = _decode_param(raw)
  if not text:
    return 0.0, 0.0, 0.0, False
  try:
    data = json.loads(text)
    if not isinstance(data, dict):
      return 0.0, 0.0, 0.0, False
    lat = _float_field(data, "latitude", "lat")
    lon = _float_field(data, "longitude", "lon", "lng")
    if _valid_lat_lon(lat, lon):
      return lat, lon, _float_field(data, "bearing", "bearingDeg"), True
  except (TypeError, ValueError, json.JSONDecodeError):
    pass
  return 0.0, 0.0, 0.0, False


def _position_from_msg(msg, lat_name: str = "latitude", lon_name: str = "longitude",
                       bearing_name: str = "bearingDeg") -> tuple[float, float, float, bool]:
  try:
    lat = float(getattr(msg, lat_name, 0.0))
    lon = float(getattr(msg, lon_name, 0.0))
    if _valid_lat_lon(lat, lon):
      return lat, lon, float(getattr(msg, bearing_name, 0.0)), True
  except Exception:
    pass
  return 0.0, 0.0, 0.0, False


def _position_from_params(params: Params) -> tuple[float, float, float, bool]:
  for key in _POSITION_PARAM_KEYS:
    lat, lon, bearing, valid = _position_from_json(params.get(key))
    if valid:
      return lat, lon, bearing, True
  return 0.0, 0.0, 0.0, False


def current_or_last_gps_position(params: Params | None = None) -> tuple[float, float, float, bool]:
  # ui_state is imported lazily AND guarded: night-mode init constructs the ui_state singleton,
  # which calls in here before the module finishes importing. In that window the import raises
  # (partially initialized module) — fall back to the params path (Night Mode passes self.params),
  # since there's no live GPS during boot anyway.
  try:
    from openpilot.selfdrive.ui.ui_state import ui_state
  except ImportError:
    ui_state = None

  if ui_state is not None:
    for service in _GPS_SERVICES:
      try:
        lat, lon, bearing, valid = _position_from_msg(ui_state.sm[service])
        if valid:
          return lat, lon, bearing, True
      except Exception:
        pass

    try:
      lat, lon, bearing, valid = _position_from_msg(
        ui_state.sm["iqNavRenderState"],
        lat_name="currentLatitude",
        lon_name="currentLongitude",
        bearing_name="bearingDeg",
      )
      if valid:
        return lat, lon, bearing, True
    except Exception:
      pass

  explicit_params = params is not None
  params = params or (ui_state.params if ui_state is not None else Params())
  lat, lon, bearing, valid = _position_from_params(params)
  if valid:
    return lat, lon, bearing, True

  if not explicit_params and platform.system() != "Darwin" and Path("/dev/shm/params/d").exists():
    try:
      lat, lon, bearing, valid = _position_from_params(Params("/dev/shm/params"))
      if valid:
        return lat, lon, bearing, True
    except Exception:
      pass

  return 0.0, 0.0, 0.0, False
