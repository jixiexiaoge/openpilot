import math
from datetime import UTC, datetime

_J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
SUNSET_ELEVATION_DEG = -0.833  # standard sunset/sunrise threshold, corrected for atmospheric refraction


def sun_elevation_deg(lat: float, lon: float, dt_utc: datetime | None = None) -> float:
  """Low-precision solar elevation angle (accurate to well under a degree), per the
  standard Meeus-derived approximation. lat/lon in degrees (lon positive east)."""
  dt_utc = dt_utc or datetime.now(UTC)
  n = (dt_utc - _J2000).total_seconds() / 86400.0

  mean_lon = math.radians((280.460 + 0.9856474 * n) % 360)
  mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
  ecliptic_lon = (mean_lon + math.radians(1.915) * math.sin(mean_anomaly)
                  + math.radians(0.020) * math.sin(2 * mean_anomaly))
  obliquity = math.radians(23.439 - 0.0000004 * n)

  declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_lon))
  right_ascension = math.atan2(math.cos(obliquity) * math.sin(ecliptic_lon), math.cos(ecliptic_lon))

  equation_of_time_deg = math.degrees(mean_lon - right_ascension)
  equation_of_time_deg = (equation_of_time_deg + 180) % 360 - 180

  utc_hours = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
  hour_angle = math.radians(15 * (utc_hours - 12) + lon + equation_of_time_deg)

  lat_rad = math.radians(lat)
  elevation = math.asin(math.sin(lat_rad) * math.sin(declination)
                         + math.cos(lat_rad) * math.cos(declination) * math.cos(hour_angle))
  return math.degrees(elevation)


def is_after_sunset(lat: float, lon: float, dt_utc: datetime | None = None) -> bool:
  return sun_elevation_deg(lat, lon, dt_utc) < SUNSET_ELEVATION_DEG
