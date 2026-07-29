"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os

import pyray as rl

_UI_MODE_IQ = os.getenv("IQPILOT_UI", "1") == "1"

_PROBE_FS = 20
_PROBE_MARGIN = 10
_PROBE_COLOR = rl.Color(0x12, 0x97, 0x91, 0xFF)


class IQAppHooks:
  """IQ hooks mixed into GuiApplication: UI-mode flag + pointer debug readout."""

  def __init__(self):
    self._pointer_probe = os.getenv("SHOW_MOUSE_COORDS") == "1"

  @staticmethod
  def iqpilot_ui() -> bool:
    return _UI_MODE_IQ

  def set_show_mouse_coords(self, show: bool):
    self._pointer_probe = show

  @property
  def pointer_probe_enabled(self) -> bool:
    return self._pointer_probe

  def draw_pointer_probe(self, font):
    readout = f"X:{rl.get_mouse_x()}, Y:{rl.get_mouse_y()}"
    width = rl.measure_text_ex(font, readout, _PROBE_FS, 0).x
    canvas_w = self._scaled_width if self._scale != 1.0 else self._width
    rl.draw_text_ex(font, readout, rl.Vector2(canvas_w - width - _PROBE_MARGIN, 6), _PROBE_FS, 0, _PROBE_COLOR)
