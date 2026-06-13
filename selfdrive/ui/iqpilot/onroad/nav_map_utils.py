import math
from urllib.parse import quote

EARTH_RADIUS_M = 6378137.0
TILE_SIZE = 256.0


def _mercator_normalized(latitude: float, longitude: float) -> tuple[float, float]:
  x = (longitude + 180.0) / 360.0
  siny = min(max(math.sin(math.radians(latitude)), -0.9999), 0.9999)
  y = 0.5 - math.log((1.0 + siny) / (1.0 - siny)) / (4.0 * math.pi)
  return x, y


def mercator_world_px(latitude: float, longitude: float, zoom: float) -> tuple[float, float]:
  world_size = TILE_SIZE * (2.0 ** zoom)
  nx, ny = _mercator_normalized(latitude, longitude)
  x = nx * world_size
  y = ny * world_size
  return x, y


def destination_point(latitude: float, longitude: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
  if abs(distance_m) < 1e-3:
    return latitude, longitude

  angular_distance = distance_m / EARTH_RADIUS_M
  bearing = math.radians(bearing_deg)
  lat1 = math.radians(latitude)
  lon1 = math.radians(longitude)

  sin_lat1 = math.sin(lat1)
  cos_lat1 = math.cos(lat1)
  sin_ad = math.sin(angular_distance)
  cos_ad = math.cos(angular_distance)

  lat2 = math.asin(sin_lat1 * cos_ad + cos_lat1 * sin_ad * math.cos(bearing))
  lon2 = lon1 + math.atan2(
    math.sin(bearing) * sin_ad * cos_lat1,
    cos_ad - sin_lat1 * math.sin(lat2),
  )
  return math.degrees(lat2), math.degrees(lon2)


def fit_zoom_for_points(points, width: float, height: float, max_zoom: float = 17.6,
                        min_zoom: float = 12.8, padding: float = 56.0) -> float:
  coords = [(float(point.latitude), float(point.longitude)) for point in points if point is not None]
  if len(coords) < 2:
    return max_zoom

  xs, ys = zip(*[_mercator_normalized(lat, lon) for lat, lon in coords])
  span_x = max(max(xs) - min(xs), 1e-6)
  span_y = max(max(ys) - min(ys), 1e-6)

  usable_width = max(width - 2.0 * padding, 32.0)
  usable_height = max(height - 2.0 * padding, 32.0)
  zoom_x = math.log2(usable_width / (TILE_SIZE * span_x))
  zoom_y = math.log2(usable_height / (TILE_SIZE * span_y))
  return max(min(min(zoom_x, zoom_y), max_zoom), min_zoom)


def choose_nav_camera(current_latitude: float, current_longitude: float, bearing_deg: float, points,
                      width: float, height: float, preferred_zoom: float) -> tuple[float, float, float]:
  zoom = preferred_zoom
  if points:
    zoom = fit_zoom_for_points(points, width, height * 0.78, max_zoom=preferred_zoom + 0.6)
    zoom = min(max(zoom, preferred_zoom - 1.2), preferred_zoom + 0.6)

  meters_per_pixel = 156543.03392 * math.cos(math.radians(current_latitude)) / (2.0 ** zoom)
  lookahead_pixels = height * 0.16
  lookahead_m = max(lookahead_pixels * meters_per_pixel, 12.0)
  center_latitude, center_longitude = destination_point(current_latitude, current_longitude, bearing_deg, lookahead_m)
  return center_latitude, center_longitude, zoom


def build_mapbox_static_url(latitude: float, longitude: float, zoom: float, bearing: float,
                            width: int, height: int, points=None) -> str:
  overlay = ""
  if points:
    overlay = f"path-7+34d17a-0.85({encode_polyline(points)})/"

  return (
    f"https://api.mapbox.com/styles/v1/mapbox/navigation-night-v1/static/"
    f"{overlay}{longitude:.6f},{latitude:.6f},{zoom:.2f},{bearing:.1f},0/{width}x{height}@2x"
  )


def build_mapbox_tile_url(z: int, x: int, y: int, tile_size: int = 256, scale: int = 2) -> str:
  suffix = f"@{scale}x" if scale > 1 else ""
  return (
    f"https://api.mapbox.com/styles/v1/mapbox/navigation-night-v1/tiles/"
    f"{tile_size}/{z}/{x}/{y}{suffix}"
  )


def tile_world_size(z: int, tile_size: int = 256) -> int:
  return tile_size * (2 ** z)


def mercator_world_px_at_zoom(latitude: float, longitude: float, z: int, tile_size: int = 256) -> tuple[float, float]:
  world_size = tile_world_size(z, tile_size)
  nx, ny = _mercator_normalized(latitude, longitude)
  return nx * world_size, ny * world_size


def encode_polyline(points) -> str:
  result = []
  last_lat = 0
  last_lon = 0

  for point in points:
    lat = int(round(float(point.latitude if hasattr(point, "latitude") else point[0]) * 1e5))
    lon = int(round(float(point.longitude if hasattr(point, "longitude") else point[1]) * 1e5))

    for value in (lat - last_lat, lon - last_lon):
      shifted = ~(value << 1) if value < 0 else (value << 1)
      while shifted >= 0x20:
        result.append(chr((0x20 | (shifted & 0x1f)) + 63))
        shifted >>= 5
      result.append(chr(shifted + 63))

    last_lat = lat
    last_lon = lon

  return quote("".join(result), safe="")


def project_nav_point(latitude: float, longitude: float, center_latitude: float, center_longitude: float,
                      zoom: float, bearing_deg: float, width: float, height: float,
                      anchor_x: float = 0.5, anchor_y: float = 0.5) -> tuple[float, float]:
  px, py = mercator_world_px(latitude, longitude, zoom)
  cx, cy = mercator_world_px(center_latitude, center_longitude, zoom)
  dx = px - cx
  dy = py - cy

  theta = math.radians(bearing_deg)
  cos_theta = math.cos(theta)
  sin_theta = math.sin(theta)
  rx = dx * cos_theta + dy * sin_theta
  ry = -dx * sin_theta + dy * cos_theta
  return width * anchor_x + rx, height * anchor_y + ry


def project_nav_polyline(points, center_latitude: float, center_longitude: float, zoom: float, bearing_deg: float,
                         width: float, height: float, anchor_x: float = 0.5, anchor_y: float = 0.5) -> list[tuple[float, float]]:
  projected = []
  for point in points:
    projected.append(
      project_nav_point(
        float(point.latitude),
        float(point.longitude),
        center_latitude,
        center_longitude,
        zoom,
        bearing_deg,
        width,
        height,
        anchor_x=anchor_x,
        anchor_y=anchor_y,
      )
    )
  return projected
