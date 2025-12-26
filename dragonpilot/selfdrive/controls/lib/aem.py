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

import time
import numpy as np
from openpilot.selfdrive.modeld.constants import ModelConstants


AEM_COOLDOWN_TIME = 0.5  # seconds

SLOW_DOWN_BP = [0., 2.78, 5.56, 8.34, 11.12, 13.89, 15.28]
SLOW_DOWN_DIST = [10, 30., 50., 70., 80., 90., 120.]

# Allow throttle
# ALLOW_THROTTLE_THRESHOLD = 0.4
# MIN_ALLOW_THROTTLE_SPEED = 2.5


class AEM:

  def __init__(self):
    self._active = False
    self._cooldown_end_time = 0.0

  def _perform_experimental_mode(self):
    self._active = True
    self._cooldown_end_time = time.monotonic() + AEM_COOLDOWN_TIME

  def get_mode(self, mode):
    # override mode
    if time.monotonic() < self._cooldown_end_time:
      mode = 'blended'
    else:
      self._active = False
    return mode

  def update_states(self, model_msg, radar_msg, v_ego):

    # Stop sign/light detection
    if not self._active:
      if len(model_msg.orientation.x) == len(model_msg.position.x) == ModelConstants.IDX_N and \
        model_msg.position.x[ModelConstants.IDX_N - 1] < np.interp(v_ego, SLOW_DOWN_BP, SLOW_DOWN_DIST):
        self._perform_experimental_mode()

    # throttle prob is low and there is no lead ahead (prep for brake?)
    # if not self._active:
    #   if len(model_msg.meta.disengagePredictions.gasPressProbs) > 1:
    #     throttle_prob = model_msg.meta.disengagePredictions.gasPressProbs[1]
    #   else:
    #     throttle_prob = 1.0

    #   allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED
    #   if not allow_throttle and not radar_msg.leadOne.status:
    #     self._perform_experimental_mode()

