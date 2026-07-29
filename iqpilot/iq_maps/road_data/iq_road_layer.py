"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import math
import platform

from cereal import custom
from openpilot.common.params import Params
from openpilot.iqpilot.iq_maps.road_data.signal_bridge import RoadSignalBridge
from openpilot.iqpilot.navd.helpers import Coordinate


class IQRoadLayer(RoadSignalBridge):
  def __init__(self):
    super().__init__()
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params

  def refresh_position(self) -> None:
    location = self.location_sub['iqLiveLocation']
    self.fix_ready = (
      location.solutionState == custom.IQLiveLocation.SolutionState.ready
      and location.geodeticPosition.isValid
    )

    if self.fix_ready:
      self.heading_deg = math.degrees(location.alignedOrientationNed.values[2])
      self.last_coordinate = Coordinate(location.geodeticPosition.values[0], location.geodeticPosition.values[1])

    if self.last_coordinate is None:
      return

    payload = {
      "latitude": self.last_coordinate.latitude,
      "longitude": self.last_coordinate.longitude,
    }

    if self.heading_deg is not None:
      payload["bearing"] = self.heading_deg

    self.mem_params.put("LastGPSPosition", json.dumps(payload))

  def read_current_limit(self) -> float:
    return float(self.mem_params.get("MapSpeedLimit") or 0.0)

  def read_current_road(self) -> str:
    return str(self.mem_params.get("RoadName") or "")

  def read_upcoming_limit(self) -> tuple[float, float]:
    raw_segment = self.mem_params.get("NextMapSpeedLimit")
    if isinstance(raw_segment, bytes):
      raw_segment = raw_segment.decode("utf-8")
    try:
      upcoming_segment = json.loads(raw_segment) if isinstance(raw_segment, str) and raw_segment else (raw_segment or {})
    except json.JSONDecodeError:
      upcoming_segment = {}

    next_limit = float(upcoming_segment.get("speedlimit", 0.0) or 0.0)
    target_lat = upcoming_segment.get("latitude")
    target_lon = upcoming_segment.get("longitude")
    distance_to_limit = 0.0

    if target_lat is not None and target_lon is not None:
      limit_coordinate = Coordinate(float(target_lat), float(target_lon))
      distance_to_limit = (self.last_coordinate or Coordinate(0, 0)).distance_to(limit_coordinate)

    return next_limit, distance_to_limit
