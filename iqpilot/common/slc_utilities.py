import math
import numpy as np

try:
  import requests
except ImportError:
  requests = None

from openpilot.iqpilot.common.slc_variables import EARTH_RADIUS


def calculate_bearing_offset(latitude, longitude, current_bearing, distance):
  """
  Calculate new GPS coordinates given a starting point, bearing, and distance.
  Used for Mapbox API lookahead calculations.

  Args:
    latitude: Starting latitude in degrees
    longitude: Starting longitude in degrees
    current_bearing: Bearing in degrees (0-360)
    distance: Distance to project in meters

  Returns:
    Tuple of (new_latitude, new_longitude) in degrees
  """
  bearing = math.radians(current_bearing)
  lat_rad = math.radians(latitude)
  lon_rad = math.radians(longitude)

  delta = distance / EARTH_RADIUS

  new_lat = math.asin(math.sin(lat_rad) * math.cos(delta) + math.cos(lat_rad) * math.sin(delta) * math.cos(bearing))
  new_lon = lon_rad + math.atan2(math.sin(bearing) * math.sin(delta) * math.cos(lat_rad), math.cos(delta) - math.sin(lat_rad) * math.sin(new_lat))
  return math.degrees(new_lat), math.degrees(new_lon)


def calculate_distance_to_point(lat1, lon1, lat2, lon2):
  """
  Calculate the great circle distance between two GPS points using the Haversine formula.

  Args:
    lat1, lon1: First point coordinates in degrees
    lat2, lon2: Second point coordinates in degrees

  Returns:
    Distance in meters
  """
  lat1_rad = math.radians(lat1)
  lon1_rad = math.radians(lon1)
  lat2_rad = math.radians(lat2)
  lon2_rad = math.radians(lon2)

  delta_lat = lat2_rad - lat1_rad
  delta_lon = lon2_rad - lon1_rad

  a = (math.sin(delta_lat / 2) ** 2) + math.cos(lat1_rad) * math.cos(lat2_rad) * (math.sin(delta_lon / 2) ** 2)
  c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

  return EARTH_RADIUS * c


def calculate_lane_width(lane_line1, lane_line2, road_edge=None):
  """
  Calculate the width of a lane based on lane line positions.
  Used for speed limit filler to determine road width.

  Args:
    lane_line1: First lane line object with x, y coordinates
    lane_line2: Second lane line object with x, y coordinates
    road_edge: Optional road edge object with x, y coordinates

  Returns:
    Lane width in meters
  """
  lane_line1_x = np.asarray(lane_line1.x)
  lane_line1_y = np.asarray(lane_line1.y)

  lane_line2_x = np.asarray(lane_line2.x)
  lane_line2_y = np.asarray(lane_line2.y)

  lane_y_interp = np.interp(lane_line2_x, lane_line1_x, lane_line1_y)
  distance_to_lane = np.median(np.abs(lane_line2_y - lane_y_interp))

  if road_edge is None:
    return distance_to_lane

  road_edge_x = np.asarray(road_edge.x)
  road_edge_y = np.asarray(road_edge.y)

  edge_y_interp = np.interp(lane_line2_x, road_edge_x, road_edge_y)
  distance_to_edge = np.median(np.abs(lane_line2_y - edge_y_interp))

  return max(distance_to_lane, distance_to_edge)


def is_url_pingable(url):
  """
  Check if a URL is accessible and responding.
  Used to verify Mapbox/Overpass API availability before making requests.

  Args:
    url: URL to ping

  Returns:
    Boolean indicating if URL is accessible
  """
  if not url:
    return False

  if requests is None:
    return False

  if not hasattr(is_url_pingable, "session"):
    is_url_pingable.session = requests.Session()
    is_url_pingable.session.headers.update({"User-Agent": "iqpilot-ping-test/1.0"})

  try:
    response = is_url_pingable.session.head(url, timeout=10, allow_redirects=True)
    if response.status_code in (405, 501):
      response = is_url_pingable.session.get(url, timeout=10, allow_redirects=True, stream=True)

    is_accessible = response.ok
    response.close()
    return is_accessible
  except Exception:
    return False
