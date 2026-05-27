"""
Copyright (c) 2026, Rick Lan

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

from cereal import log

# Hysteresis thresholds (km/h -> m/s)
APM_ACTIVATE_SPEED = 30 * 1000 / 3600    # 30 km/h ~8.33 m/s — switch to aggressive below this
APM_DEACTIVATE_SPEED = 40 * 1000 / 3600  # 40 km/h ~11.11 m/s — restore user personality above this


class APM:

  def __init__(self):
    self._active = False

  def get_personality(self, v_ego, personality):
    if self._active:
      if v_ego > APM_DEACTIVATE_SPEED:
        self._active = False
    else:
      if v_ego < APM_ACTIVATE_SPEED:
        self._active = True

    if self._active:
      return log.LongitudinalPersonality.aggressive
    return personality
