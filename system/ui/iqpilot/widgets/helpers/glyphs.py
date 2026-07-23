"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import math

import pyray as rl

# Unit pentagram vertices, spike up, alternating outer/inner radius, clockwise
# from the top. Inner radius 0.5 keeps the classic star proportions.
_STAR_RING: list[tuple[float, float]] = []
for _k in range(10):
  _theta = math.radians(-90.0 + _k * 36.0)
  _r = 1.0 if _k % 2 == 0 else 0.5
  _STAR_RING.append((_r * math.cos(_theta), _r * math.sin(_theta)))


def draw_star(center_x: float, center_y: float, radius: float, is_filled: bool, color: rl.Color) -> None:
  pts = [rl.Vector2(center_x + ux * radius, center_y + uy * radius) for ux, uy in _STAR_RING]

  if is_filled:
    inner = [pts[k] for k in range(1, 10, 2)]
    # five spikes, each flanked by its two inner neighbours...
    for i in range(5):
      rl.draw_triangle(inner[i - 1], pts[2 * i], inner[i], color)
    # ...plus the inner pentagon, fanned from one vertex
    for i in range(1, 4):
      rl.draw_triangle(inner[0], inner[i], inner[i + 1], color)

  for k in range(10):
    rl.draw_line_ex(pts[k], pts[(k + 1) % 10], 2, color)
