# Earth radius in meters (for GPS calculations)
EARTH_RADIUS = 6378137

# Mapbox API limits
FREE_MAPBOX_REQUESTS = 100_000

# Speed limit offset maps for different unit systems
# Each entry is (min_speed_ms, max_speed_ms, param_name)

OFFSET_MAP_IMPERIAL = [
  (0, 11.2, "speed_limit_offset1"),     # 0-24 mph
  (11.2, 15.2, "speed_limit_offset2"),  # 25-34 mph
  (15.2, 19.6, "speed_limit_offset3"),  # 35-44 mph
  (19.6, 24.1, "speed_limit_offset4"),  # 45-54 mph
  (24.1, 28.6, "speed_limit_offset5"),  # 55-64 mph
  (28.6, 33.1, "speed_limit_offset6"),  # 65-74 mph
  (33.1, 44.2, "speed_limit_offset7"),  # 75-99 mph
]

OFFSET_MAP_METRIC = [
  (0, 8.1, "speed_limit_offset1"),      # 0-29 km/h
  (8.1, 13.6, "speed_limit_offset2"),   # 30-49 km/h
  (13.6, 16.4, "speed_limit_offset3"),  # 50-59 km/h
  (16.4, 21.9, "speed_limit_offset4"),  # 60-79 km/h
  (21.9, 27.5, "speed_limit_offset5"),  # 80-99 km/h
  (27.5, 33.1, "speed_limit_offset6"),  # 100-119 km/h
  (33.1, 38.9, "speed_limit_offset7"),  # 120-140 km/h
]

# Speed limit filler constants
BOUNDING_BOX_RADIUS_DEGREE = 0.1
MAX_ENTRIES = 1_000_000
MAX_OVERPASS_DATA_BYTES = 1_073_741_824
MAX_OVERPASS_REQUESTS = 10_000
METERS_PER_DEG_LAT = 111_320
VETTING_INTERVAL_DAYS = 7

# Overpass API URLs
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_STATUS_URL = "https://overpass-api.de/api/status"
