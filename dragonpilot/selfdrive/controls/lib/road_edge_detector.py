#!/usr/bin/env python3
"""
Copyright (c) 2019, rav4kumar, Rick Lan, dragonpilot community, and a number of other of contributors.

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

import numpy as np

NEARSIDE_PROB = 0.2
EDGE_PROB = 0.35

class RoadEdgeDetector:
  def __init__(self, enabled = False):
    self._is_enabled = enabled
    self.left_edge_detected = False
    self.right_edge_detected = False

  def update(self, road_edge_stds, lane_line_probs):
    if not self._is_enabled:
      return

    left_road_edge_prob = np.clip(1.0 - road_edge_stds[0], 0.0, 1.0)
    left_lane_nearside_prob = lane_line_probs[0]

    right_road_edge_prob = np.clip(1.0 - road_edge_stds[1], 0.0, 1.0)
    right_lane_nearside_prob = lane_line_probs[3]

    self.left_edge_detected = bool(
      left_road_edge_prob > EDGE_PROB and
      left_lane_nearside_prob < NEARSIDE_PROB and
      right_lane_nearside_prob >= left_lane_nearside_prob
    )

    self.right_edge_detected = bool(
      right_road_edge_prob > EDGE_PROB and
      right_lane_nearside_prob < NEARSIDE_PROB and
      left_lane_nearside_prob >= right_lane_nearside_prob
    )

  def set_enabled(self, enabled):
    self._is_enabled = enabled

  def is_enabled(self):
    return self._is_enabled
