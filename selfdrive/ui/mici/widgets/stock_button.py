"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import math
import pyray as rl
from typing import Union
from enum import Enum
from collections.abc import Callable
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import DO_ZOOM
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.common.filter_simple import BounceFilter
from openpilot.iqpilot.ui.theme import NeonTheme

try:
  from openpilot.common.params import Params, UnknownKeyName
except ImportError:
  Params = None
  class UnknownKeyName(Exception):
    pass

SCROLLING_SPEED_PX_S = 50
COMPLICATION_SIZE    = 36
LABEL_COLOR          = rl.Color(255, 255, 255, int(255 * 0.9))
COMPLICATION_GREY    = rl.Color(0xAA, 0xAA, 0xAA, 255)
PRESSED_SCALE = 1.15 if DO_ZOOM else 1.07

_FORCE_ACCENT_RGB = None

_ACCENT_ROUND = 0.34
_ACCENT_INSET = 6
_GLOW_OUT = 3
_GLOW_IN = 12
_GLOW_IN_IDLE = 4
_GLOW_OUT_ALPHA = 32
_GLOW_IN_ALPHA = 80
_RIM_ALPHA = 200
_GLOW_SEGS = 16
_GLOW_CORNER_SEGS = 16


def _accent_rgb() -> tuple[int, int, int]:
  if _FORCE_ACCENT_RGB is not None:
    return _FORCE_ACCENT_RGB
  c = NeonTheme.glow(255)
  return (c.r, c.g, c.b)


def _inset(rect: rl.Rectangle, px: float) -> rl.Rectangle:
  return rl.Rectangle(rect.x + px, rect.y + px, rect.width - 2 * px, rect.height - 2 * px)


_BOX_BG = rl.Color(0x08, 0x09, 0x0A, 255)
_BOX_BG_PRESSED = rl.Color(0x16, 0x18, 0x1A, 255)
_BOX_BG_DISABLED = rl.Color(0x05, 0x06, 0x07, 255)


def _draw_accent_box(rect: rl.Rectangle, enabled: bool, pressed: bool):
  """Clean dark rounded box + smooth teal glow (matches the concept). Same roundness
  for box and glow → no seam. `rect` is the final box rect."""
  base = 1.0 if enabled else 0.4
  r, g, b = _accent_rgb()

  # keep every concentric ring's corner radius offset by exactly its inset, so the
  # rings stay parallel at the corners too (a fixed roundness fraction would shrink
  # the corner radius unevenly and leave a dark seam in each corner)
  shorter = min(rect.width, rect.height)
  base_radius = _ACCENT_ROUND * shorter / 2.0

  def _round_for(short_side: float, radius: float) -> float:
    return max(0.0, min(1.0, 2.0 * radius / short_side)) if short_side > 0 else 0.0

  for px in range(_GLOW_OUT, 0, -1):
    f = px / _GLOW_OUT
    a = int(_GLOW_OUT_ALPHA * base * (1.0 - f) ** 2.0)
    if a <= 0:
      continue
    ex = rl.Rectangle(rect.x - px, rect.y - px, rect.width + 2 * px, rect.height + 2 * px)
    rl.draw_rectangle_rounded(ex, _round_for(shorter + 2 * px, base_radius + px), _GLOW_SEGS, rl.Color(r, g, b, a))

  bg = _BOX_BG_PRESSED if pressed else (_BOX_BG if enabled else _BOX_BG_DISABLED)
  rl.draw_rectangle_rounded(rect, _round_for(shorter, base_radius), _GLOW_SEGS, bg)

  for px in range(_GLOW_IN, 0, -1):
    f = px / _GLOW_IN
    a = int(_GLOW_IN_ALPHA * base * (1.0 - f) ** 1.8)
    if a <= 0:
      continue
    rl.draw_rectangle_rounded_lines_ex(_inset(rect, px), _round_for(shorter - 2 * px, base_radius - px),
                                       _GLOW_CORNER_SEGS, 3, rl.Color(r, g, b, a))

  rl.draw_rectangle_rounded_lines_ex(rect, _round_for(shorter, base_radius), _GLOW_CORNER_SEGS, 2,
                                     rl.Color(r, g, b, int(_RIM_ALPHA * base)))


_CIRCLE_RED_RGB = (0xE0, 0x3A, 0x3A)


def _draw_accent_circle(cx: float, cy: float, radius: float, enabled: bool, red: bool = False, pressed: bool = False):
  """Circular version of the box accent: teal (or red) rim + inward glow, matching the boxes."""
  base = 1.0 if enabled else 0.4
  r, g, b = _CIRCLE_RED_RGB if red else _accent_rgb()
  c = rl.Vector2(cx, cy)
  segs = _GLOW_CORNER_SEGS * 2
  for px in range(_GLOW_OUT, 0, -1):
    a = int(_GLOW_OUT_ALPHA * base * (1.0 - px / _GLOW_OUT) ** 2.0)
    if a > 0:
      rl.draw_ring(c, radius + px - 1.0, radius + px + 1.0, 0, 360, segs, rl.Color(r, g, b, a))
  glow_in = _GLOW_IN if pressed else _GLOW_IN_IDLE
  for px in range(glow_in, 0, -1):
    a = int(_GLOW_IN_ALPHA * base * (1.0 - px / glow_in) ** 1.8)
    if a > 0:
      rl.draw_ring(c, radius - px - 1.5, radius - px + 1.5, 0, 360, segs, rl.Color(r, g, b, a))
  rl.draw_ring(c, radius - 1.5, radius + 1.5, 0, 360, segs, rl.Color(r, g, b, int(_RIM_ALPHA * base)))


class ScrollState(Enum):
  PRE_SCROLL = 0
  SCROLLING = 1
  POST_SCROLL = 2


class BigCircleButton(Widget):
  def __init__(self, icon: rl.Texture, red: bool = False, icon_offset: tuple[int, int] = (0, 0)):
    super().__init__()
    self._red = red
    self._icon_offset = icon_offset

    self.set_rect(rl.Rectangle(0, 0, 180, 180))
    self._scale_filter = BounceFilter(1.0, 0.1, 1 / gui_app.target_fps)
    self._click_delay = 0.075

    self._txt_icon = icon
    self._txt_btn_disabled_bg = gui_app.texture("icons_mici/buttons/button_circle_disabled.png", 180, 180)

    self._txt_btn_bg = gui_app.texture("icons_mici/buttons/button_circle.png", 180, 180)
    self._txt_btn_pressed_bg = gui_app.texture("icons_mici/buttons/button_circle_pressed.png", 180, 180)

    self._txt_btn_red_bg = gui_app.texture("icons_mici/buttons/button_circle_red.png", 180, 180)
    self._txt_btn_red_pressed_bg = gui_app.texture("icons_mici/buttons/button_circle_red_pressed.png", 180, 180)

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    icon_color = rl.Color(255, 255, 255, int(255 * 0.9)) if self.enabled else rl.Color(255, 255, 255, int(255 * 0.35))
    rl.draw_texture_ex(self._txt_icon, (btn_x + (btn_width - self._txt_icon.width) / 2 + self._icon_offset[0],
                                        btn_y + (btn_height - self._txt_icon.height) / 2 + self._icon_offset[1]), 0, 1.0, icon_color)

  def _render(self, _):
    txt_bg = self._txt_btn_bg if not self._red else self._txt_btn_red_bg
    if not self.enabled:
      txt_bg = self._txt_btn_disabled_bg
    elif self.is_pressed:
      txt_bg = self._txt_btn_pressed_bg if not self._red else self._txt_btn_red_pressed_bg

    scale = self._scale_filter.update(PRESSED_SCALE if self.is_pressed else 1.0)
    btn_x = self._rect.x + (self._rect.width * (1 - scale)) / 2
    btn_y = self._rect.y + (self._rect.height * (1 - scale)) / 2
    rl.draw_texture_ex(txt_bg, (btn_x, btn_y), 0, scale, rl.WHITE)

    cx = btn_x + self._rect.width * scale / 2.0
    cy = btn_y + self._rect.height * scale / 2.0
    _draw_accent_circle(cx, cy, self._rect.width * scale / 2.0 - _ACCENT_INSET, self.enabled, self._red, self.is_pressed)

    self._draw_content(btn_x, btn_y, self._rect.width * scale, self._rect.height * scale)


class BigCircleToggle(BigCircleButton):
  def __init__(self, icon: rl.Texture, toggle_callback: Callable | None = None, icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, False, icon_offset=icon_offset)
    self._toggle_callback = toggle_callback

    self._checked = False

    self._txt_toggle_enabled = gui_app.texture("icons_mici/buttons/toggle_dot_enabled.png", 66, 66)
    self._txt_toggle_disabled = gui_app.texture("icons_mici/buttons/toggle_dot_disabled.png", 66, 66)

  def set_checked(self, checked: bool):
    self._checked = checked

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    self._checked = not self._checked
    if self._toggle_callback:
      self._toggle_callback(self._checked)

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    super()._draw_content(btn_x, btn_y, btn_width, btn_height)

    rl.draw_texture_ex(self._txt_toggle_enabled if self._checked else self._txt_toggle_disabled,
                       (btn_x + (btn_width - self._txt_toggle_enabled.width) / 2, btn_y + 5),
                       0, 1.0, rl.WHITE)


class BigButton(Widget):
  LABEL_HORIZONTAL_PADDING = 40
  LABEL_VERTICAL_PADDING = 23

  """A lightweight stand-in for the Qt BigButton, drawn & updated each frame."""

  def __init__(self, text: str, value: str = "", icon: Union[rl.Texture, None] = None, scroll: bool = False):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 180))
    self.text = text
    self.value = value
    self._txt_icon = icon
    self._scroll = scroll
    self._press_effect_enabled = True

    self._scale_filter = BounceFilter(1.0, 0.1, 1 / gui_app.target_fps)
    self._click_delay = 0.075
    self._shake_start: float | None = None
    self._grow_animation_until: float | None = None

    self._rotate_icon_t: float | None = None

    self._label = UnifiedLabel(text, font_size=self._get_label_font_size(), font_weight=FontWeight.BOLD,
                               text_color=LABEL_COLOR, alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM, scroll=scroll,
                               line_height=0.9)
    self._sub_label = UnifiedLabel(value, font_size=COMPLICATION_SIZE, font_weight=FontWeight.ROMAN,
                                   text_color=COMPLICATION_GREY,
                                   alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM,
                                   wrap_text=False, scroll=True)
    self._update_label_layout()

    self._load_images()

  def set_icon(self, icon: Union[rl.Texture, None]):
    self._txt_icon = icon

  def set_rotate_icon(self, rotate: bool):
    if rotate and self._rotate_icon_t is not None:
      return
    self._rotate_icon_t = rl.get_time() if rotate else None

  def set_press_effect_enabled(self, enabled: bool) -> None:
    self._press_effect_enabled = enabled

  def set_scroll_active(self, active: bool) -> None:
    self._label.set_scroll_active(active)

  def _load_images(self):
    self._txt_default_bg = gui_app.texture("icons_mici/buttons/button_rectangle.png", 402, 180)
    self._txt_pressed_bg = gui_app.texture("icons_mici/buttons/button_rectangle_pressed.png", 402, 180)
    self._txt_disabled_bg = gui_app.texture("icons_mici/buttons/button_rectangle_disabled.png", 402, 180)

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(lambda: touch_callback() and self._grow_animation_until is None)

  def _width_hint(self) -> int:
    icon_size = self._txt_icon.width if self._txt_icon and self._scroll and self.value else 0
    return int(self._rect.width - self.LABEL_HORIZONTAL_PADDING * 2 - icon_size)

  def _get_label_font_size(self):
    if len(self.text) <= 18:
      return 48
    else:
      return 42

  def _update_label_layout(self):
    self._label.set_font_size(self._get_label_font_size())
    if self.value:
      self._label.set_alignment_vertical(rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP)
    else:
      self._label.set_alignment_vertical(rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM)

  def set_text(self, text: str):
    self.text = text
    self._label.set_text(text)
    self._update_label_layout()

  def set_value(self, value: str):
    self.value = value
    self._sub_label.set_text(value)
    self._update_label_layout()

  def get_value(self) -> str:
    return self.value

  def get_text(self):
    return self.text

  def trigger_shake(self):
    self._shake_start = rl.get_time()

  def trigger_grow_animation(self, duration: float = 0.65):
    self._grow_animation_until = rl.get_time() + duration

  @property
  def _shake_offset(self) -> float:
    SHAKE_DURATION = 0.5
    SHAKE_AMPLITUDE = 24.0
    SHAKE_FREQUENCY = 32.0
    if self._shake_start is None:
      return 0.0
    t = rl.get_time() - self._shake_start
    if t > SHAKE_DURATION:
      return 0.0
    decay = 1.0 - t / SHAKE_DURATION
    return decay * SHAKE_AMPLITUDE * math.sin(t * SHAKE_FREQUENCY)

  def set_position(self, x: float, y: float) -> None:
    super().set_position(x + self._shake_offset, y)

  def _handle_background(self) -> tuple[rl.Texture, float, float, float]:
    if self._grow_animation_until is not None:
      if rl.get_time() >= self._grow_animation_until:
        self._grow_animation_until = None

    txt_bg = self._txt_default_bg
    if not self.enabled:
      txt_bg = self._txt_disabled_bg
    elif self.is_pressed and self._press_effect_enabled:
      txt_bg = self._txt_pressed_bg

    pressed_scale = self.is_pressed and self._press_effect_enabled
    animate_scale = pressed_scale or self._grow_animation_until is not None
    scale = self._scale_filter.update(PRESSED_SCALE if animate_scale else 1.0)
    btn_x = self._rect.x + (self._rect.width * (1 - scale)) / 2
    btn_y = self._rect.y + (self._rect.height * (1 - scale)) / 2
    return txt_bg, btn_x, btn_y, scale

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    label_x = btn_x + self.LABEL_HORIZONTAL_PADDING

    label_color = LABEL_COLOR if self.enabled else rl.Color(255, 255, 255, int(255 * 0.35))
    self._label.set_color(label_color)
    label_rect = rl.Rectangle(label_x, btn_y + self.LABEL_VERTICAL_PADDING, self._width_hint(),
                              btn_height - self.LABEL_VERTICAL_PADDING * 2)
    self._label.render(label_rect)

    if self.value:
      label_y = btn_y + self.LABEL_VERTICAL_PADDING + self._label.get_content_height(self._width_hint())
      sub_label_height = btn_y + btn_height - self.LABEL_VERTICAL_PADDING - label_y
      sub_label_rect = rl.Rectangle(label_x, label_y, self._width_hint(), sub_label_height)
      self._sub_label.render(sub_label_rect)

    if self._txt_icon:
      rotation = 0
      if self._rotate_icon_t is not None:
        rotation = (rl.get_time() - self._rotate_icon_t) * 180

      x = btn_x + btn_width - 30 - self._txt_icon.width / 2
      y = btn_y + 30 + self._txt_icon.height / 2
      source_rec = rl.Rectangle(0, 0, self._txt_icon.width, self._txt_icon.height)
      dest_rec = rl.Rectangle(x, y, self._txt_icon.width, self._txt_icon.height)
      origin = rl.Vector2(self._txt_icon.width / 2, self._txt_icon.height / 2)
      rl.draw_texture_pro(self._txt_icon, source_rec, dest_rec, origin, rotation, rl.Color(255, 255, 255, int(255 * 0.9)))

  def _render(self, _):
    txt_bg, btn_x, btn_y, scale = self._handle_background()

    cell = rl.Rectangle(btn_x, btn_y, self._rect.width * scale, self._rect.height * scale)
    box_rect = _inset(cell, _ACCENT_INSET)
    _draw_accent_box(box_rect, self.enabled, self.is_pressed)

    # Clip each card's content to its own bounds so long/scrolling labels from one
    # tile cannot bleed into neighboring tiles in the horizontal scroller.
    content_rect = _inset(box_rect, 2)
    rl.begin_scissor_mode(int(content_rect.x), int(content_rect.y), int(content_rect.width), int(content_rect.height))
    self._draw_content(btn_x, btn_y, cell.width, cell.height)
    rl.end_scissor_mode()


class BigToggle(BigButton):
  def __init__(self, text: str, value: str = "", initial_state: bool = False, toggle_callback: Callable | None = None):
    super().__init__(text, value, "")
    self._checked = initial_state
    self._toggle_callback = toggle_callback

  def _load_images(self):
    super()._load_images()
    self._txt_enabled_toggle = gui_app.texture("icons_mici/buttons/toggle_pill_enabled.png", 84, 66)
    self._txt_disabled_toggle = gui_app.texture("icons_mici/buttons/toggle_pill_disabled.png", 84, 66)

  def set_checked(self, checked: bool):
    self._checked = checked

  def _width_hint(self) -> int:
    return int(self._rect.width - self.LABEL_HORIZONTAL_PADDING * 2 - self._txt_enabled_toggle.width)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self._checked = not self._checked
    if self._toggle_callback:
      self._toggle_callback(self._checked)

  def _draw_pill(self, x: float, y: float, checked: bool):
    if checked:
      rl.draw_texture_ex(self._txt_enabled_toggle, (x, y), 0, 1.0, rl.WHITE)
    else:
      rl.draw_texture_ex(self._txt_disabled_toggle, (x, y), 0, 1.0, rl.WHITE)

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    super()._draw_content(btn_x, btn_y, btn_width, btn_height)

    x = btn_x + btn_width - self._txt_enabled_toggle.width
    y = btn_y
    self._draw_pill(x, y, self._checked)


class BigMultiToggle(BigToggle):
  def __init__(self, text: str, options: list[str], toggle_callback: Callable | None = None,
               select_callback: Callable | None = None):
    super().__init__(text, "", toggle_callback=toggle_callback)
    assert len(options) > 0
    self._options = options
    self._select_callback = select_callback

    self.set_value(self._options[0])

  def _width_hint(self) -> int:
    return int(self._rect.width - self.LABEL_HORIZONTAL_PADDING * 2 - self._txt_enabled_toggle.width)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    cur_idx = self._options.index(self.value)
    new_idx = (cur_idx + 1) % len(self._options)
    self.set_value(self._options[new_idx])
    if self._select_callback:
      self._select_callback(self.value)

  def _draw_content(self, btn_x: float, btn_y: float, btn_width: float, btn_height: float):
    BigButton._draw_content(self, btn_x, btn_y, btn_width, btn_height)

    checked_idx = self._options.index(self.value)

    x = btn_x + btn_width - self._txt_enabled_toggle.width
    y = btn_y

    for i in range(len(self._options)):
      self._draw_pill(x, y, checked_idx == i)
      y += 35


class GreyBigButton(BigButton):
  """Users should manage newlines with this class themselves"""

  LABEL_HORIZONTAL_PADDING = 30

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.set_touch_valid_callback(lambda: False)

    self._rect.width = 476

    self._label.set_font_size(36)
    self._label.set_font_weight(FontWeight.BOLD)
    self._label.set_line_height(1.0)

    self._sub_label.set_font_size(36)
    self._sub_label.set_text_color(rl.Color(255, 255, 255, int(255 * 0.9)))
    self._sub_label.set_font_weight(FontWeight.DISPLAY_REGULAR)
    self._sub_label.set_alignment_vertical(rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE if not self._label.text else
                                           rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM)
    self._sub_label.set_line_height(0.95)

  @property
  def LABEL_VERTICAL_PADDING(self):
    return BigButton.LABEL_VERTICAL_PADDING if self._label.text else 18

  def _width_hint(self) -> int:
    return int(self._rect.width - self.LABEL_HORIZONTAL_PADDING * 2)

  def _get_label_font_size(self):
    return 36

  def _render(self, _):
    rl.draw_rectangle_rounded(self._rect, 0.4, 10, rl.Color(255, 255, 255, int(255 * 0.15)))
    self._draw_content(self._rect.x, self._rect.y, self._rect.width, self._rect.height)


class BigMultiParamToggle(BigMultiToggle):
  def __init__(self, text: str, param: str, options: list[str], toggle_callback: Callable | None = None,
               select_callback: Callable | None = None):
    super().__init__(text, options, toggle_callback, select_callback)
    self._param = param

    self._params = Params()
    self._load_value()

  def _load_value(self):
    self.set_value(self._options[self._params.get(self._param) or 0])

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    new_idx = self._options.index(self.value)
    self._params.put(self._param, new_idx)


class BigParamControl(BigToggle):
  def __init__(self, text: str, param: str, toggle_callback: Callable | None = None):
    super().__init__(text, "", toggle_callback=toggle_callback)
    self.param = param
    self.params = Params()
    self.set_checked(self._read_bool())

  def _read_bool(self) -> bool:
    try:
      return self.params.get_bool(self.param)
    except UnknownKeyName:
      return False

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    try:
      self.params.put_bool(self.param, self._checked)
    except UnknownKeyName:
      pass

  def refresh(self):
    self.set_checked(self._read_bool())


class BigCircleParamControl(BigCircleToggle):
  def __init__(self, icon: rl.Texture, param: str, toggle_callback: Callable | None = None,
               icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, toggle_callback, icon_offset=icon_offset)
    self._param = param
    self.params = Params()
    self.set_checked(self._read_bool())

  def _read_bool(self) -> bool:
    try:
      return self.params.get_bool(self._param)
    except UnknownKeyName:
      return False

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    try:
      self.params.put_bool(self._param, self._checked)
    except UnknownKeyName:
      pass

  def refresh(self):
    self.set_checked(self._read_bool())
