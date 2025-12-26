"""
Copyright (c) 2025, Rick Lan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, and/or sublicense,
for non-commercial purposes only, subject to the following conditions:

- The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
- Commercial use (e.g. use in a product, service, or activity intended to
  generate revenue) is prohibited without explicit written permission from
  the copyright holder.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.can.parser import CANParser
from opendbc.car.structs import RadarData
from typing import List, Tuple

# car head to radar
DREL_OFFSET = -1.52


# typically max lane width is 3.7m
LANE_WIDTH = 3.8
LANE_WIDTH_HALF = LANE_WIDTH/2

LANE_CENTER_MIN_LAT = 0.
LANE_CENTER_MAX_LAT = LANE_WIDTH_HALF
LANE_CENTER_MIN_DIST = 5.

LANE_SIDE_MIN_LAT = LANE_WIDTH_HALF
LANE_SIDE_MAX_LAT = LANE_WIDTH_HALF + LANE_WIDTH
LANE_SIDE_MIN_DIST = 10.


# lat distance, typically max lane width is 3.7m
MAX_LAT_DIST = 6.

# objects to ignore thats really close to the vehicle (after DREL_OFFSET applied)
MIN_DIST = 5.

# ignore oncoming objects
IGNORE_OBJ_STATE = 2

# ignore objects that we haven't seen for 5 secs
NOT_SEEN_INIT = 33

def _create_radar_parser():
  return CANParser('u_radar', [("Status", float('nan')), ("ObjectData", float('nan'))], 1)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)

    self.updated_messages = set()

    self.rcp = _create_radar_parser()

    self._pts_cache = dict()
    self._pts_not_seen = {key: 0 for key in range(255)}
    self._should_clear_cache = False

  # called by card.py, 100hz
  def update(self, can_strings):
    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)

    if 1546 in self.updated_messages:
      self._should_clear_cache = True

    if 1547 in self.updated_messages:
      all_objects = zip(
        self.rcp.vl_all['ObjectData']['ID'],
        self.rcp.vl_all['ObjectData']['DistLong'],
        self.rcp.vl_all['ObjectData']['DistLat'],
        self.rcp.vl_all['ObjectData']['VRelLong'],
        self.rcp.vl_all['ObjectData']['VRelLat'],
        self.rcp.vl_all['ObjectData']['DynProp'],
        self.rcp.vl_all['ObjectData']['Class'],
        self.rcp.vl_all['ObjectData']['RCS'],
      )

      # clean cache when we see a 0x60a then a 0x60b
      if self._should_clear_cache:
        self._pts_cache.clear()
        self._should_clear_cache = False

      for track_id, dist_long, dist_lat, vrel_long, vrel_lat, dyn_prop, obj_class, rcs in all_objects:

        d_rel = dist_long + DREL_OFFSET
        y_rel = -dist_lat

        should_ignore = False

        # ignore point (obj_class = 0)
        if not should_ignore and int(obj_class) == 0:
          should_ignore = True

        # ignore oncoming objects
        # @todo remove this because it's always 0 ?
        if not should_ignore and int(dyn_prop) == IGNORE_OBJ_STATE:
          should_ignore = True

        # far away lane object, ignore
        if not should_ignore and abs(y_rel) > LANE_SIDE_MAX_LAT:
          should_ignore = True

        # close object, ignore, use vision
        if not should_ignore and LANE_CENTER_MIN_LAT > abs(y_rel) > LANE_CENTER_MAX_LAT and d_rel < LANE_CENTER_MIN_DIST:
          should_ignore = True

        # close object, ignore, use vision
        if not should_ignore and LANE_SIDE_MIN_LAT > abs(y_rel) > LANE_SIDE_MAX_LAT and d_rel < LANE_SIDE_MIN_DIST:
          should_ignore = True

        if not should_ignore and track_id not in self._pts_cache:
          self._pts_cache[track_id] = RadarData.RadarPoint()
          self._pts_cache[track_id].trackId = track_id

        if should_ignore:
          self._pts_not_seen[track_id] = -1
        else:
          self._pts_not_seen[track_id] = NOT_SEEN_INIT

          # init cache
          if track_id not in self._pts_cache:
            self._pts_cache[track_id] = RadarData.RadarPoint()
            self._pts_cache[track_id].trackId = track_id

          # add/update to cache
          self._pts_cache[track_id].dRel = d_rel
          self._pts_cache[track_id].yRel = y_rel
          self._pts_cache[track_id].vRel = float(vrel_long)
          self._pts_cache[track_id].yvRel = float('nan')
          self._pts_cache[track_id].aRel = float('nan')
          self._pts_cache[track_id].measured = True

    self.updated_messages.clear()

    # publish to cereal
    if self.frame % 3 == 0:
      keys_to_remove = [key for key in self.pts if key not in self._pts_cache]
      for key in keys_to_remove:
        self._pts_not_seen[key] -= 1
        if self._pts_not_seen[key] <= 0:
          del self.pts[key]

      self.pts.update(self._pts_cache)

      ret = RadarData()
      if not self.rcp.can_valid:
        ret.errors.canError = True

      ret.points = list(self.pts.values())
      return ret

    return None
