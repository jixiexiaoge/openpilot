"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import pyray as rl
import numpy as np
from collections.abc import Callable

from openpilot.common.filter_simple import FirstOrderFilter, BounceFilter
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.scroll_panel2 import GuiScrollPanel2, ScrollState
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.nav_widget import NavWidget

ITEM_SPACING = 20
LINE_COLOR = rl.GRAY
LINE_PADDING = 40
ANIMATION_SCALE = 0.6
PAGE_SLIDER_MARGIN = 18
PAGE_SLIDER_GLOW_W = 360
PAGE_SLIDER_GLOW_H = 18
PAGE_SLIDER_PEAK = 220
PAGE_SLIDER_END_TAPER = 95
PAGE_EDGE_FADE_W = 55

MIN_ZOOM_ANIMATION_TIME = 0.075  # seconds
DO_ZOOM = False
DO_JELLO = False
SCROLL_BAR = False


class LineSeparator(Widget):
  def __init__(self, height: int = 1):
    super().__init__()
    self._rect = rl.Rectangle(0, 0, 0, height)

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, _):
    rl.draw_line(int(self._rect.x) + LINE_PADDING, int(self._rect.y),
                 int(self._rect.x + self._rect.width) - LINE_PADDING, int(self._rect.y),
                 LINE_COLOR)


class Scroller(Widget):
  def __init__(self, items: list[Widget], horizontal: bool = True, snap_items: bool = True, spacing: int = ITEM_SPACING,
               line_separator: bool = False, pad_start: int = ITEM_SPACING, pad_end: int = ITEM_SPACING):
    super().__init__()
    self._items: list[Widget] = []
    self._horizontal = horizontal
    self._snap_items = snap_items
    self._spacing = spacing
    self._line_separator = LineSeparator() if line_separator else None
    self._pad_start = pad_start
    self._pad_end = pad_end

    self._reset_scroll_at_show = True

    self._scrolling_to: float | None = None
    self._scroll_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self._zoom_filter = FirstOrderFilter(1.0, 0.2, 1 / gui_app.target_fps)
    self._zoom_out_t: float = 0.0

    # layout state
    self._visible_items: list[Widget] = []
    self._content_size: float = 0.0
    self._scroll_offset: float = 0.0

    self._item_pos_filter = BounceFilter(0.0, 0.05, 1 / gui_app.target_fps)

    # when not pressed, snap to closest item to be center
    self._scroll_snap_filter = FirstOrderFilter(0.0, 0.05, 1 / gui_app.target_fps)

    self.scroll_panel = GuiScrollPanel2(self._horizontal, handle_out_of_bounds=not self._snap_items)
    self._scroll_enabled: bool | Callable[[], bool] = True

    self._txt_scroll_indicator = gui_app.texture("icons_mici/settings/vertical_scroll_indicator.png", 40, 80)

    for item in items:
      self.add_widget(item)

  def set_reset_scroll_at_show(self, scroll: bool):
    self._reset_scroll_at_show = scroll

  def scroll_to(self, pos: float, smooth: bool = False):
    # already there
    if abs(pos) < 1:
      return

    # FIXME: the padding correction doesn't seem correct
    scroll_offset = self.scroll_panel.get_offset() - pos
    if smooth:
      self._scrolling_to = scroll_offset
    else:
      self.scroll_panel.set_offset(scroll_offset)

  @property
  def is_auto_scrolling(self) -> bool:
    return self._scrolling_to is not None

  def add_widget(self, item: Widget) -> None:
    self._items.append(item)
    item.set_touch_valid_callback(lambda: self.scroll_panel.is_touch_valid() and self.enabled)

  def add_widgets(self, items: list[Widget]) -> None:
    for item in items:
      self.add_widget(item)

  @property
  def items(self) -> list[Widget]:
    return self._items

  def move_item(self, from_idx: int, to_idx: int):
    if from_idx == to_idx or not (0 <= from_idx < len(self._items)):
      return
    self._items.insert(to_idx, self._items.pop(from_idx))

  def set_scrolling_enabled(self, enabled: bool | Callable[[], bool]) -> None:
    """Set whether scrolling is enabled (does not affect widget enabled state)."""
    self._scroll_enabled = enabled

  def _update_state(self):
    if DO_ZOOM:
      if self._scrolling_to is not None or self.scroll_panel.state != ScrollState.STEADY:
        self._zoom_out_t = rl.get_time() + MIN_ZOOM_ANIMATION_TIME
        self._zoom_filter.update(0.85)
      else:
        if self._zoom_out_t is not None:
          if rl.get_time() > self._zoom_out_t:
            self._zoom_filter.update(1.0)
          else:
            self._zoom_filter.update(0.85)

    # Cancel auto-scroll if user starts manually scrolling
    if self._scrolling_to is not None and (self.scroll_panel.state == ScrollState.PRESSED or self.scroll_panel.state == ScrollState.MANUAL_SCROLL):
      self._scrolling_to = None

    if self._scrolling_to is not None:
      self._scroll_filter.update(self._scrolling_to)
      self.scroll_panel.set_offset(self._scroll_filter.x)

      if abs(self._scroll_filter.x - self._scrolling_to) < 1:
        self.scroll_panel.set_offset(self._scrolling_to)
        self._scrolling_to = None
    else:
      # keep current scroll position up to date
      self._scroll_filter.x = self.scroll_panel.get_offset()

  def _get_scroll(self, visible_items: list[Widget], content_size: float) -> float:
    scroll_enabled = self._scroll_enabled() if callable(self._scroll_enabled) else self._scroll_enabled
    self.scroll_panel.set_enabled(scroll_enabled and self.enabled)
    self.scroll_panel.update(self._rect, content_size)
    if not self._snap_items:
      return round(self.scroll_panel.get_offset())

    # Snap closest item to center
    center_pos = self._rect.x + self._rect.width / 2 if self._horizontal else self._rect.y + self._rect.height / 2
    closest_delta_pos = float('inf')
    scroll_snap_idx: int | None = None
    for idx, item in enumerate(visible_items):
      if self._horizontal:
        delta_pos = (item.rect.x + item.rect.width / 2) - center_pos
      else:
        delta_pos = (item.rect.y + item.rect.height / 2) - center_pos
      if abs(delta_pos) < abs(closest_delta_pos):
        closest_delta_pos = delta_pos
        scroll_snap_idx = idx

    if scroll_snap_idx is not None:
      snap_item = visible_items[scroll_snap_idx]
      if self.is_pressed:
        # no snapping until released
        self._scroll_snap_filter.x = 0
      else:
        # TODO: this doesn't handle two small buttons at the edges well
        if self._horizontal:
          snap_delta_pos = (center_pos - (snap_item.rect.x + snap_item.rect.width / 2)) / 10
          snap_delta_pos = min(snap_delta_pos, -self.scroll_panel.get_offset() / 10)
          snap_delta_pos = max(snap_delta_pos, (self._rect.width - self.scroll_panel.get_offset() - content_size) / 10)
        else:
          snap_delta_pos = (center_pos - (snap_item.rect.y + snap_item.rect.height / 2)) / 10
          snap_delta_pos = min(snap_delta_pos, -self.scroll_panel.get_offset() / 10)
          snap_delta_pos = max(snap_delta_pos, (self._rect.height - self.scroll_panel.get_offset() - content_size) / 10)
        self._scroll_snap_filter.update(snap_delta_pos)

      self.scroll_panel.set_offset(self.scroll_panel.get_offset() + self._scroll_snap_filter.x)

    return self.scroll_panel.get_offset()

  def _layout(self):
    self._visible_items = [item for item in self._items if item.is_visible]

    # Add line separator between items
    if self._line_separator is not None:
      l = len(self._visible_items)
      for i in range(1, len(self._visible_items)):
        self._visible_items.insert(l - i, self._line_separator)

    self._content_size = sum(item.rect.width if self._horizontal else item.rect.height for item in self._visible_items)
    self._content_size += self._spacing * (len(self._visible_items) - 1)
    self._content_size += self._pad_start + self._pad_end

    self._scroll_offset = self._get_scroll(self._visible_items, self._content_size)

    rl.begin_scissor_mode(int(self._rect.x), int(self._rect.y),
                          int(self._rect.width), int(self._rect.height))

    self._item_pos_filter.update(self._scroll_offset)

    cur_pos = 0
    for idx, item in enumerate(self._visible_items):
      spacing = self._spacing if (idx > 0) else self._pad_start
      # Nicely lay out items horizontally/vertically
      if self._horizontal:
        x = self._rect.x + cur_pos + spacing
        y = self._rect.y + (self._rect.height - item.rect.height) / 2
        cur_pos += item.rect.width + spacing
      else:
        x = self._rect.x + (self._rect.width - item.rect.width) / 2
        y = self._rect.y + cur_pos + spacing
        cur_pos += item.rect.height + spacing

      # Consider scroll
      if self._horizontal:
        x += self._scroll_offset
      else:
        y += self._scroll_offset

      # Add some jello effect when scrolling
      if DO_JELLO:
        if self._horizontal:
          cx = self._rect.x + self._rect.width / 2
          jello_offset = self._scroll_offset - np.interp(x + item.rect.width / 2,
                                                         [self._rect.x, cx, self._rect.x + self._rect.width],
                                                         [self._item_pos_filter.x, self._scroll_offset, self._item_pos_filter.x])
          x -= np.clip(jello_offset, -20, 20)
        else:
          cy = self._rect.y + self._rect.height / 2
          jello_offset = self._scroll_offset - np.interp(y + item.rect.height / 2,
                                                         [self._rect.y, cy, self._rect.y + self._rect.height],
                                                         [self._item_pos_filter.x, self._scroll_offset, self._item_pos_filter.x])
          y -= np.clip(jello_offset, -20, 20)

      # Update item state
      item.set_position(round(x), round(y))  # round to prevent jumping when settling
      item.set_parent_rect(self._rect)

  def _render(self, _):
    for item in self._visible_items:
      item_visible = rl.check_collision_recs(item.rect, self._rect)
      if hasattr(item, "set_scroll_active"):
        item.set_scroll_active(item_visible)

      # Skip rendering if not in viewport
      if not item_visible:
        continue

      # Scale each element around its own origin when scrolling
      scale = self._zoom_filter.x
      if scale != 1.0:
        rl.rl_push_matrix()
        rl.rl_scalef(scale, scale, 1.0)
        rl.rl_translatef((1 - scale) * (item.rect.x + item.rect.width / 2) / scale,
                         (1 - scale) * (item.rect.y + item.rect.height / 2) / scale, 0)
        item.render()
        rl.rl_pop_matrix()
      else:
        item.render()

    # Draw scroll indicator
    if SCROLL_BAR and not self._horizontal and len(self._visible_items) > 0:
      _real_content_size = self._content_size - self._rect.height + self._txt_scroll_indicator.height
      scroll_bar_y = -self._scroll_offset / _real_content_size * self._rect.height
      scroll_bar_y = min(max(scroll_bar_y, self._rect.y), self._rect.y + self._rect.height - self._txt_scroll_indicator.height)
      rl.draw_texture_ex(self._txt_scroll_indicator, rl.Vector2(self._rect.x, scroll_bar_y), 0, 1.0, rl.WHITE)

    rl.end_scissor_mode()

  def show_event(self):
    super().show_event()
    if self._reset_scroll_at_show:
      self.scroll_panel.set_offset(0.0)

    for item in self._items:
      item.show_event()

  def hide_event(self):
    super().hide_event()
    for item in self._items:
      item.hide_event()


def draw_scroller_page_slider(scroller: Scroller, rect: rl.Rectangle) -> None:
  if not scroller._horizontal:
    return
  max_off = scroller._content_size - scroller.rect.width
  if max_off <= 1:
    return
  progress = max(0.0, min(1.0, (-scroller.scroll_panel.get_offset()) / max_off))

  from openpilot.iqpilot.ui.theme import NeonTheme
  c = NeonTheme.glow(255)
  r, g, b = c.r, c.g, c.b
  glow_w = PAGE_SLIDER_GLOW_W
  h = PAGE_SLIDER_GLOW_H
  end = PAGE_SLIDER_END_TAPER
  left = rect.x - end
  right = rect.x + rect.width - glow_w + end
  x = int(left + progress * (right - left))
  bottom = int(rect.y + rect.height)

  rl.draw_rectangle_gradient_v(x, bottom - h, glow_w, h, rl.Color(r, g, b, 0), rl.Color(r, g, b, PAGE_SLIDER_PEAK))
  black, blank = rl.Color(0, 0, 0, 255), rl.Color(0, 0, 0, 0)
  rl.draw_rectangle_gradient_h(x, bottom - h, end, h, black, blank)
  rl.draw_rectangle_gradient_h(x + glow_w - end, bottom - h, end, h, blank, black)


def draw_scroller_edge_fades(rect: rl.Rectangle) -> None:
  fw = PAGE_EDGE_FADE_W
  x, y = int(rect.x), int(rect.y)
  w, h = int(rect.width), int(rect.height)
  black = rl.Color(0, 0, 0, 255)
  blank = rl.Color(0, 0, 0, 0)
  rl.draw_rectangle_gradient_h(x, y, fw, h, black, blank)
  rl.draw_rectangle_gradient_h(x + w - fw, y, fw, h, blank, black)


class NavScroller(NavWidget):
  """Full screen Scroller that supports the nav stack with swipe-to-dismiss animations.

  Subclasses add their items via ``self._scroller.add_widgets([...])``. Built on the existing
  ``Scroller`` so old callers are unaffected.
  """
  def __init__(self, **kwargs):
    super().__init__()
    kwargs.setdefault('snap_items', False)
    self._scroller = Scroller([], **kwargs)
    self._scroller.set_enabled(lambda: self.enabled and not self.is_dismissing)

  PAGE_SLIDER_MARGIN = PAGE_SLIDER_MARGIN
  PAGE_SLIDER_GLOW_W = PAGE_SLIDER_GLOW_W
  PAGE_SLIDER_GLOW_H = PAGE_SLIDER_GLOW_H
  PAGE_SLIDER_PEAK = PAGE_SLIDER_PEAK
  PAGE_SLIDER_END_TAPER = PAGE_SLIDER_END_TAPER
  PAGE_SLIDER_RGB = (0x3A, 0xDD, 0xC6)

  PAGE_EDGE_FADE_W = PAGE_EDGE_FADE_W

  def _back_enabled(self) -> bool:
    return self._scroller._horizontal or self._scroller.scroll_panel.get_offset() >= -20

  def _draw_page_slider(self):
    draw_scroller_page_slider(self._scroller, self._rect)

  def _draw_edge_fades(self):
    draw_scroller_edge_fades(self._rect)

  def _render(self, _):
    self._scroller.render(self._rect)
    self._draw_edge_fades()
    self._draw_page_slider()

  def show_event(self):
    super().show_event()
    self._scroller.show_event()

  def hide_event(self):
    super().hide_event()
    self._scroller.hide_event()


class NavRawScrollPanel(NavWidget):
  BACK_TOUCH_AREA_PERCENTAGE = 1.0

  def __init__(self):
    super().__init__()
    self._scroll_panel = GuiScrollPanel2(horizontal=False)
    self._scroll_panel.set_enabled(lambda: self.enabled and not self.is_dismissing)

  def show_event(self):
    super().show_event()
    self._scroll_panel.set_offset(0)

  def _back_enabled(self) -> bool:
    return self._scroll_panel.get_offset() >= -20
