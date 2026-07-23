"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import colorsys
import time

import pyray as rl
from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient

# Scrolling spectrum along the driving path: a fixed set of stops from the
# bottom (1.0) to the top (0.0) of the path, each a full-saturation swatch whose
# hue advances with time and whose opacity thins toward the horizon.
_SEGMENTS = 8
_SCROLL_DEG_PER_S = 50.0
_SATURATION = 0.9
_LIGHTNESS = 0.6
_ALPHA_NEAR = 0.8            # opacity at the bottom of the path
_ALPHA_HORIZON_FRACTION = 0.3   # how much of that opacity is shed by the top

# Stop offsets are constant, so resolve them once.
_STOP_OFFSETS = tuple(i / (_SEGMENTS - 1) for i in range(_SEGMENTS))


def _swatch(hue_turns: float, alpha: float) -> rl.Color:
  r, g, b = colorsys.hls_to_rgb(hue_turns, _LIGHTNESS, _SATURATION)
  return rl.Color(int(r * 255), int(g * 255), int(b * 255), int(alpha * 255))


def _spectrum_gradient() -> Gradient:
  scroll_deg = (time.monotonic() * _SCROLL_DEG_PER_S) % 360.0
  colors = []
  for offset in _STOP_OFFSETS:
    hue_deg = (scroll_deg + offset * 360.0) % 360.0
    alpha = _ALPHA_NEAR * (1.0 - offset * _ALPHA_HORIZON_FRACTION)
    colors.append(_swatch(hue_deg / 360.0, alpha))
  return Gradient(start=(0.0, 1.0), end=(0.0, 0.0), colors=colors, stops=list(_STOP_OFFSETS))


class RainbowPath:
  def draw_rainbow_path(self, rect, path):
    draw_polygon(rect, path.projected_points, gradient=_spectrum_gradient())
