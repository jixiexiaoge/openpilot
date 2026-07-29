"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from abc import abstractmethod, ABC

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.constants import CV
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.iqpilot.navd.helpers import coordinate_from_param

ROAD_SPEED_CEILING = V_CRUISE_UNSET * CV.KPH_TO_MS


class RoadSignalBridge(ABC):
  def __init__(self):
    self.params = Params()

    self.location_sub = messaging.SubMaster(['iqLiveLocation'])
    self.output_pub = messaging.PubMaster(['iqLiveData'])

    self.fix_ready = False
    self.heading_deg = None
    self.last_coordinate = coordinate_from_param("LastGPSPositionIQLoc", self.params)

  @abstractmethod
  def refresh_position(self) -> None:
    pass

  @abstractmethod
  def read_current_limit(self) -> float:
    pass

  @abstractmethod
  def read_upcoming_limit(self) -> tuple[float, float]:
    pass

  @abstractmethod
  def read_current_road(self) -> str:
    pass

  def publish_snapshot(self) -> None:
    active_limit = self.read_current_limit()
    next_limit, next_limit_distance = self.read_upcoming_limit()

    outbound = messaging.new_message('iqLiveData')
    outbound.valid = self.location_sub['iqLiveLocation'].gpsHealthy
    live_data = outbound.iqLiveData

    live_data.speedLimitValid = bool(ROAD_SPEED_CEILING > active_limit > 0)
    live_data.speedLimit = active_limit
    live_data.speedLimitAheadValid = bool(ROAD_SPEED_CEILING > next_limit > 0)
    live_data.speedLimitAhead = next_limit
    live_data.speedLimitAheadDistance = next_limit_distance
    live_data.roadName = self.read_current_road()

    self.output_pub.send('iqLiveData', outbound)

  def step(self) -> None:
    self.location_sub.update(0)
    self.refresh_position()
    self.publish_snapshot()
