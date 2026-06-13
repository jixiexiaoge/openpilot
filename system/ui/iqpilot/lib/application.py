"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os

import pyray as rl

SHOW_MOUSE_COORDS = os.getenv("SHOW_MOUSE_COORDS") == "1"
IQPILOT_UI = os.getenv("IQPILOT_UI", "1") == "1"


class GuiApplicationExt:
  def __init__(self):
    self._show_mouse_coords = SHOW_MOUSE_COORDS

  @staticmethod
  def iqpilot_ui() -> bool:
    return IQPILOT_UI

  def _draw_mouse_coordinates(self, font):
    coords_text = f"X:{int(rl.get_mouse_x())}, Y:{int(rl.get_mouse_y())}"

    green_color = rl.Color(0x12, 0x97, 0x91, 0xFF)

    # Calculate text width to position it at the right edge; estimate width based on text length
    # Each character is approximately 10-12 pixels wide at font size 20
    estimated_text_width = len(coords_text) * 11

    # Position text at the top right corner, 10px from the top
    screen_width = self._scaled_width if self._scale != 1.0 else self._width
    text_pos = rl.Vector2(screen_width - estimated_text_width - 10, 6)

    # Draw the text
    rl.draw_text_ex(font, coords_text, text_pos, 20, 0, green_color)

  def set_show_mouse_coords(self, show: bool):
    self._show_mouse_coords = show
