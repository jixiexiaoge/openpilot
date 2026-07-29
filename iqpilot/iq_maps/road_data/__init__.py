"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Shared tunables and a small debug logger for the offline road-name / turn-speed path.
"""
from openpilot.common.swaglog import cloudlog

# seconds of road ahead we scan for upcoming turn-speed zones published on iqLiveData
LOOK_AHEAD_HORIZON_TIME = 15.0
# clear the on-screen road name once it has gone this long without a refresh (s)
ROAD_NAME_TIMEOUT = 30

R = 6373000.0            # mean Earth radius in metres (great-circle distance math)
QUERY_RADIUS = 3000      # online OSM query reach, metres
QUERY_RADIUS_OFFLINE = 2250  # offline-tile OSM query reach, metres

_DEBUG = False
_CLOUDLOG_DEBUG = False


def debug_road_data(msg, log_to_cloud=True):
  if _CLOUDLOG_DEBUG and log_to_cloud:
    cloudlog.debug(msg)
  if _DEBUG:
    print(msg)
