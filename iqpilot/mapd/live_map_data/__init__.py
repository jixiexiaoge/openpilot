"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.common.swaglog import cloudlog

LOOK_AHEAD_HORIZON_TIME = 15.  # s. Time horizon for look ahead of turn speed sections to provide on iqLiveData msg.
_DEBUG = False
_CLOUDLOG_DEBUG = False
ROAD_NAME_TIMEOUT = 30  # secs
R = 6373000.0  # approximate radius of earth in mts
QUERY_RADIUS = 3000  # mts. Radius to use on OSM data queries.
QUERY_RADIUS_OFFLINE = 2250  # mts. Radius to use on offline OSM data queries.


def get_debug(msg, log_to_cloud=True):
  if _CLOUDLOG_DEBUG and log_to_cloud:
    cloudlog.debug(msg)
  if _DEBUG:
    print(msg)
