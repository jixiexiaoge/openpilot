import json

from openpilot.common.params import Params
from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position, resolve_mapbox_token


def test_resolve_mapbox_token_reads_param(tmp_path):
  params = Params(tmp_path.as_posix())
  params.put("MapboxToken", "pk.test-token")

  assert resolve_mapbox_token(params) == "pk.test-token"


def test_resolve_mapbox_token_missing_returns_empty(tmp_path):
  params = Params(tmp_path.as_posix())

  assert resolve_mapbox_token(params) == ""


def test_current_or_last_gps_position_uses_last_position_param(tmp_path):
  params = Params(tmp_path.as_posix())
  params.put("LastGPSPosition", json.dumps({
    "latitude": 37.7749,
    "longitude": -122.4194,
    "bearing": 91.5,
  }))

  lat, lon, bearing, valid = current_or_last_gps_position(params)

  assert valid
  assert lat == 37.7749
  assert lon == -122.4194
  assert bearing == 91.5


def test_current_or_last_gps_position_uses_iqloc_position_param(tmp_path):
  params = Params(tmp_path.as_posix())
  params.put("LastGPSPositionIQLoc", json.dumps({
    "latitude": 34.0522,
    "longitude": -118.2437,
    "bearingDeg": 12.0,
  }))

  lat, lon, bearing, valid = current_or_last_gps_position(params)

  assert valid
  assert lat == 34.0522
  assert lon == -118.2437
  assert bearing == 12.0


def test_current_or_last_gps_position_accepts_lat_lon_aliases(tmp_path):
  params = Params(tmp_path.as_posix())
  params.put("LastGPSPosition", json.dumps({
    "lat": 40.7128,
    "lng": -74.006,
  }))

  lat, lon, bearing, valid = current_or_last_gps_position(params)

  assert valid
  assert lat == 40.7128
  assert lon == -74.006
  assert bearing == 0.0


def test_current_or_last_gps_position_rejects_zero_position(tmp_path):
  params = Params(tmp_path.as_posix())
  params.put("LastGPSPosition", "{}")

  assert current_or_last_gps_position(params) == (0.0, 0.0, 0.0, False)
