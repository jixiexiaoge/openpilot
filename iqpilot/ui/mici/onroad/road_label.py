"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from openpilot.iqpilot.ui.onroad.hud_overlays import RoadNameBanner


class RoadNameRendererMici(RoadNameBanner):
  """Compact capsule tuned for the mici's small panel."""

  TYPE_SIZE = 28
  FLOOR_WIDTH = 120
  SIDE_PAD = 28
  MARGIN = 200
  DROP = 8
  BAR_H = TYPE_SIZE + 14
  CURVE = 0.35
  SEGS = 8
  BACKDROP_A = 140
  INK_A = 210
  INNER_PAD = 16
