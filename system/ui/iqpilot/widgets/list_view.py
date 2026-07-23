"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl
from openpilot.system.ui.iqpilot.lib.styles import ink, metrics
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.iqpilot.lib import canvas
from openpilot.system.ui.widgets.scroller_tici import LineSeparator, LINE_COLOR, LINE_PADDING
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.toggle import Toggle
import unicodedata
from openpilot.common.params import Params, UnknownKeyName
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.lib.application import gui_app, MousePos, FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import (ListItem, ToggleAction, ItemAction, MultipleButtonAction,
                                                   ButtonAction, _resolve_value, DualButtonAction)

_Dyn = str | Callable[[], str]      # a literal or a late-bound provider
_Pred = Callable[[], bool]

LABEL_WIDTH = 350  # hoisted: used as a default arg in option_item before the option-control section
_SPINNER_TEAL = rl.Color(16, 185, 169, 255)
_SPINNER_HALO = rl.Color(255, 255, 255, 26)


class Spacer(Widget):
  def __init__(self, height: int = 1):
    super().__init__()
    self._rect = rl.Rectangle(0, 0, 0, height)

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _render(self, _):
    pass


class IQLineSeparator(LineSeparator):
  def __init__(self, height: int = 1):
    super().__init__()
    self._rect = rl.Rectangle(0, 0, 0, height)

  def _render(self, _):
    mid_y = int(self._rect.y + self._rect.height // 2)
    rl.draw_line(int(self._rect.x) + LINE_PADDING, mid_y,
                 int(self._rect.x + self._rect.width) - LINE_PADDING, mid_y, LINE_COLOR)


class IQToggleAction(ToggleAction):
  def __init__(self, initial_state: bool = False, width: int = metrics.TOGGLE_W, enabled: bool | _Pred = True,
               callback: Callable[[bool], None] | None = None, param: str | None = None):
    super().__init__(initial_state, width, enabled, callback)
    self.toggle = IQToggle(initial_state=initial_state, callback=callback, param=param)


class SafeIQToggleAction(IQToggleAction):
  """Toggle bound to a param that may be missing from the build's registry.

  IQToggle's ParamSlot already degrades reads/writes on unknown keys; this
  adds the caller-chosen fallback state and skips the callback on dead keys.
  """

  def __init__(self, param: str, default_on: bool = True, width: int = metrics.TOGGLE_W,
               enabled: bool | _Pred = True, callback: Callable[[bool], None] | None = None):
    slot = ParamSlot(param)

    def _guarded(state: bool):
      if slot.write(state) and callback:
        callback(state)

    super().__init__(initial_state=slot.read_bool(default_on), width=width, enabled=enabled,
                     callback=_guarded, param=param)
    self.toggle._slot = slot  # share one slot; IQToggle re-syncs from it every frame


class IQButton(Button):
  def _update_state(self):
    super()._update_state()
    self._background_color, label_color = self._palette()
    if label_color is not None:
      self._label.set_text_color(label_color)

  def _palette(self) -> tuple[rl.Color, rl.Color | None]:
    if not self.enabled:
      return ink.PUSH_DISABLED, ink.PUSH_TEXT_DISABLED
    if self._button_style == ButtonStyle.PRIMARY:
      # honor the "on"/active style (e.g. Onroad Uploads, Always Offroad, Force On-Road) — otherwise
      # set_button_style(PRIMARY) was ignored and toggles stayed grey with no visual feedback
      c = ink.KEY_ACTION
      if self.is_pressed:
        return rl.Color(min(255, c.r + 22), min(255, c.g + 22), min(255, c.b + 22), 255), None
      return c, None
    return (ink.PUSH_PRESSED if self.is_pressed else ink.PUSH), None


class NavSectionButton(IQButton):
  """A clean navigable section row: icon (left) + label + chevron (right), full width."""

  def __init__(self, text, icon_path: str | None = None, click_callback: Callable | None = None):
    super().__init__(text, click_callback=click_callback, button_style=ButtonStyle.NORMAL, text_padding=0)
    self._label_src = text
    self._icon = gui_app.texture(icon_path, 64, 64, keep_aspect_ratio=True) if icon_path else None
    self._chevron = gui_app.texture("icons/iq/chevron_right.png", 50, 50, keep_aspect_ratio=True)
    self._border_radius = 40

  def _render(self, _):
    rect = self._rect
    roundness = self._border_radius / (min(rect.width, rect.height) / 2)
    canvas.panel(rect, roundness, 10, self._background_color)

    cy = rect.y + rect.height / 2
    x = rect.x + 44
    if self._icon:
      rl.draw_texture(self._icon, int(x), int(cy - self._icon.height / 2), rl.WHITE)
      x += self._icon.width + 30

    text = self._label_src() if callable(self._label_src) else self._label_src
    font = gui_app.font(FontWeight.MEDIUM)
    fs = 58
    ts = measure_text_cached(font, text, fs)
    canvas.glyphs(font, text, rl.Vector2(int(x), int(cy - ts.y / 2)), fs, rl.WHITE)

    rl.draw_texture(self._chevron, int(rect.x + rect.width - 44 - self._chevron.width),
                    int(cy - self._chevron.height / 2), rl.Color(170, 172, 178, 255))


class IQSimpleButtonAction(ItemAction):
  """A single wide standalone button occupying the row."""

  def __init__(self, button_text: _Dyn, callback: Callable | None = None,
               enabled: bool | _Pred = True, button_width: int = metrics.WIDE_BTN_W):
    super().__init__(width=button_width, enabled=enabled)
    self.button_action = IQButton(button_text, click_callback=callback, button_style=ButtonStyle.NORMAL,
                                  border_radius=48)

  def set_touch_valid_callback(self, touch_callback: _Pred) -> None:
    super().set_touch_valid_callback(touch_callback)
    self.button_action.set_touch_valid_callback(touch_callback)

  def _render(self, rect: rl.Rectangle) -> bool | int | None:
    self.button_action.set_enabled(self.enabled)
    return self.button_action.render(rect)


class IQButtonAction(ButtonAction):
  """Stock button action plus a colourable readout and an in-progress spinner."""

  def __init__(self, text: _Dyn, width: int = metrics.ACTION_W, enabled: bool | _Pred = True):
    super().__init__(text=text, width=width, enabled=enabled)
    self._readout_tint: rl.Color = ink.READOUT
    self._loading = False

  def set_value(self, value: _Dyn, color: rl.Color = ink.READOUT):
    self._value_source = value
    self._readout_tint = color

  def set_loading(self, loading: bool):
    self._loading = loading

  def _button_only(self, rect: rl.Rectangle) -> bool:
    """Let the base draw just the trailing button by hiding the value for one pass."""
    stash, self._value_source = self._value_source, None
    try:
      return super()._render(rect)
    finally:
      self._value_source = stash

  @staticmethod
  def _draw_spinner(cx: float, cy: float):
    ang = (rl.get_time() * 280) % 360
    canvas.annulus(rl.Vector2(cx, cy), 16, 24, 0, 360, 40, _SPINNER_HALO)
    canvas.annulus(rl.Vector2(cx, cy), 16, 24, ang, ang + 100, 28, _SPINNER_TEAL)

  def _render(self, rect: rl.Rectangle) -> bool:
    from openpilot.system.ui.widgets.list_view import BUTTON_WIDTH, TEXT_PADDING

    if self._loading:
      pressed = self._button_only(rect)
      # teal spinner sits in the readout slot, next to the button
      self._draw_spinner(rect.x + rect.width - BUTTON_WIDTH - TEXT_PADDING - 28, rect.y + rect.height / 2)
      return pressed

    value = self.value
    if not value:
      return super()._render(rect)

    pressed = self._button_only(rect)
    body = rl.Rectangle(rect.x, rect.y, rect.width - BUTTON_WIDTH - TEXT_PADDING, rect.height)
    if measure_text_cached(self._font, value, metrics.TITLE_FS).x > body.width:
      self._value_label.set_text(value)
      self._value_label.set_font_size(metrics.TITLE_FS)
      self._value_label.set_text_color(self._readout_tint)
      self._value_label.render(body)
    else:
      gui_label(body, value, font_size=metrics.TITLE_FS, color=self._readout_tint,
                font_weight=FontWeight.NORMAL, alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)
    return pressed


class IQDualButtonAction(DualButtonAction):
  BUTTON_GAP = 20
  BUTTON_H = 150

  def __init__(self, left_text: _Dyn, right_text: _Dyn, left_callback: Callable | None = None,
               right_callback: Callable | None = None, enabled: bool | _Pred = True, border_radius: int = 40):
    super().__init__(left_text, right_text, left_callback, right_callback, enabled)
    # Neutral left action uses IQButton (lighter grey + IQ press states); right keeps its style (e.g. DANGER).
    self.left_button = IQButton(left_text, click_callback=left_callback, button_style=ButtonStyle.NORMAL, text_padding=0)
    self.left_button._border_radius = self.right_button._border_radius = border_radius

  def _pair_rects(self, rect: rl.Rectangle) -> tuple[rl.Rectangle, rl.Rectangle]:
    w = (rect.width - self.BUTTON_GAP) / 2
    y = rect.y + (rect.height - self.BUTTON_H) / 2
    left = rl.Rectangle(rect.x, y, w, self.BUTTON_H)
    right = rl.Rectangle(rect.x + w + self.BUTTON_GAP, y, w, self.BUTTON_H)
    if not self.left_button.is_visible:
      right = rl.Rectangle(rect.x, y, rect.width, self.BUTTON_H)
    elif not self.right_button.is_visible:
      left = rl.Rectangle(rect.x, y, rect.width, self.BUTTON_H)
    return left, right

  def _render(self, rect: rl.Rectangle):
    left, right = self._pair_rects(rect)
    self.left_button.render(left)
    self.right_button.render(right)


# Segmented (multi-button) control — dark container with a teal "active" pill + soft glow
SEG_CONTAINER_BG = rl.Color(42, 45, 52, 255)
SEG_CONTAINER_BORDER = rl.Color(255, 255, 255, 22)
SEG_ACTIVE = rl.Color(18, 191, 173, 255)
SEG_TEXT_SELECTED = rl.Color(8, 16, 16, 255)
SEG_H_PAD = 8
SEG_V_PAD = 9
SEG_TEXT_PAD = 16
_DOUBLE_CLICK_S = 0.5


class IQMultipleButtonAction(MultipleButtonAction):
  def __init__(self, buttons: list[_Dyn], button_width: int, selected_index: int = 0, callback: Callable | None = None,
               param: str | None = None):
    super().__init__(buttons, button_width, selected_index, callback)
    self._slot = ParamSlot(param)
    if self._slot.bound:
      self.selected_button = self._slot.read_int(selected_index)
    self._anim_x: float | None = None
    self._double_click_callbacks: dict[int, Callable] = {}
    self._last_click: tuple[int, float] = (-1, 0.0)

  @property
  def param_key(self):
    return self._slot.key

  def set_double_click_callback(self, button_index: int, callback: Callable) -> None:
    self._double_click_callbacks[button_index] = callback

  def _track_rect(self) -> rl.Rectangle:
    y = self._rect.y + (self._rect.height - metrics.ROW_BTN_H) / 2
    return rl.Rectangle(self._rect.x, y, self._rect.width, metrics.ROW_BTN_H)

  def _segment_at(self, mouse_pos: MousePos) -> int:
    track = self._track_rect()
    if not rl.check_collision_point_rec(mouse_pos, track):
      return -1
    return min(len(self.buttons) - 1, int((mouse_pos.x - track.x) / (track.width / len(self.buttons))))

  def _render(self, rect: rl.Rectangle):
    track = rl.Rectangle(rect.x, rect.y + (rect.height - metrics.ROW_BTN_H) / 2, rect.width, metrics.ROW_BTN_H)
    seg_w = track.width / len(self.buttons)
    selected_enabled = self._is_button_enabled(self.selected_button)

    # Dark container
    canvas.panel(track, 0.35, 20, SEG_CONTAINER_BG)
    canvas.panel_outline(track, 0.35, 20, 2, SEG_CONTAINER_BORDER if self.enabled else ink.FAINT)

    # Animated active pill
    target_x = track.x + self.selected_button * seg_w
    self._anim_x = target_x if self._anim_x is None else self._anim_x + (target_x - self._anim_x) * 0.2
    pill = rl.Rectangle(self._anim_x + SEG_H_PAD, track.y + SEG_V_PAD, seg_w - 2 * SEG_H_PAD, track.height - 2 * SEG_V_PAD)

    if selected_enabled:
      # Soft teal glow behind the active pill
      for grow, alpha in ((16, 16), (10, 28), (5, 44)):
        halo = rl.Rectangle(pill.x - grow, pill.y - grow, pill.width + 2 * grow, pill.height + 2 * grow)
        canvas.panel(halo, 0.6, 20, rl.Color(SEG_ACTIVE.r, SEG_ACTIVE.g, SEG_ACTIVE.b, alpha))
      canvas.panel(pill, 0.6, 20, SEG_ACTIVE)
    else:
      canvas.panel(pill, 0.6, 20, ink.FAINT)

    # Labels, shrunk to fit their segment
    for i, source in enumerate(self.buttons):
      text = _resolve_value(source, "")
      fs = 40
      limit = max(1, seg_w - SEG_TEXT_PAD * 2)
      ts = measure_text_cached(self._font, text, fs)
      while ts.x > limit and fs > 30:
        fs -= 2
        ts = measure_text_cached(self._font, text, fs)

      if i == self.selected_button and selected_enabled:
        color = SEG_TEXT_SELECTED
      elif self._is_button_enabled(i):
        color = ink.TITLE
      else:
        color = ink.FAINT
      rl.draw_text_ex(self._font, text,
                      rl.Vector2(track.x + i * seg_w + (seg_w - ts.x) / 2, track.y + (track.height - ts.y) / 2),
                      fs, 0, color)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    hit = self._segment_at(mouse_pos)

    if self.enabled and hit >= 0 and self._is_button_enabled(hit):
      self.selected_button = hit
      if self.callback:
        self.callback(hit)
    self._slot.write(self.selected_button)

    if hit < 0 or not self._double_click_callbacks:
      return
    prev_hit, prev_time = self._last_click
    now = time.monotonic()
    if hit == prev_hit and (now - prev_time) < _DOUBLE_CLICK_S:
      self._last_click = (-1, 0.0)
      if hit in self._double_click_callbacks:
        self._double_click_callbacks[hit]()
    else:
      self._last_click = (hit, now)


class IQListItem(ListItem):
  """Settings row with IQ extensions: leading toggles/buttons, title badge chips,
  right-aligned readouts, and a stacked (non-inline) action layout."""

  STACKED_EXTRA = metrics.ROW / 1.75

  def __init__(self, title: _Dyn = "", icon: str | None = None, description: _Dyn | None = None,
               description_visible: bool = False, callback: Callable | None = None,
               action_item: ItemAction | None = None, inline: bool = True, title_color: rl.Color = ink.TITLE):
    super().__init__(title, icon, description, description_visible, callback, action_item)
    self.title_color = title_color
    self.inline = inline
    if not self.inline:
      self._rect.height += self.STACKED_EXTRA
    self.title_badge: tuple[str, rl.Color] | None = None
    self._ro_val: _Dyn | None = None
    self._ro_font = gui_app.font(FontWeight.NORMAL)
    self._ro_tint: rl.Color = ink.READOUT

  # -- value/badge API ------------------------------------------------------
  def set_title(self, title: _Dyn = ""):
    self._title = title

  def set_right_value(self, value: _Dyn, color: rl.Color = ink.READOUT):
    self._ro_val = value
    self._ro_tint = color

  @property
  def right_value(self) -> str:
    if self._ro_val is None:
      return ""
    return str(_resolve_value(self._ro_val, ""))

  def show_description(self, show: bool):
    self._set_description_visible(show)

  # -- geometry -------------------------------------------------------------
  def _leading_action(self) -> bool:
    return isinstance(self.action_item, ToggleAction) or isinstance(self.action_item, IQSimpleButtonAction)

  def _update_state(self):
    prev_desc = self._prev_description
    super()._update_state()
    if self.description_visible and self._prev_description != prev_desc:
      self._rect.height = self.get_item_height(self._font, int(self._rect.width - metrics.GUTTER * 2))

  def get_item_height(self, font: rl.Font, max_width: int) -> float:
    extra = 0.0
    if self.description_visible:
      extra += metrics.GUTTER * 1.5
    if not self.inline:
      extra += self.STACKED_EXTRA
    return super().get_item_height(font, max_width) + extra

  def get_right_item_rect(self, item_rect: rl.Rectangle) -> rl.Rectangle:
    if not self.action_item:
      return rl.Rectangle(0, 0, 0, 0)

    pad = metrics.GUTTER
    inset_x = item_rect.x + pad
    inner_w = item_rect.width - pad * 2
    top = item_rect.y

    if not self.inline:
      # stacked: the action spans the row width, below the title
      title_h = measure_text_cached(self._font, self.title, metrics.TITLE_FS).y
      return rl.Rectangle(inset_x, top + title_h + pad * 3, inner_w, metrics.ROW_BTN_H)

    hint = self.action_item.get_width_hint()
    if hint == 0:
      return rl.Rectangle(inset_x, top, inner_w, metrics.ROW)

    title_w = measure_text_cached(self._font, self.title, metrics.TITLE_FS).x
    hint = min(inner_w - title_w, hint)
    x = item_rect.x if self._leading_action() else item_rect.x + item_rect.width - hint
    return rl.Rectangle(x, top, hint, metrics.ROW)

  # -- drawing --------------------------------------------------------------
  def _draw_title_badge(self, x: float, cy: float):
    """Rounded status chip just after the title text."""
    label, color = self.title_badge
    font = gui_app.font(FontWeight.MEDIUM)
    fs = 30
    ts = measure_text_cached(font, label, fs)
    pad_x = 18
    chip = rl.Rectangle(x, cy - (ts.y + 16) / 2, ts.x + pad_x * 2, ts.y + 16)
    canvas.panel(chip, 0.5, 12, color)
    lum = 0.299 * color.r + 0.587 * color.g + 0.114 * color.b
    txt_color = rl.Color(10, 14, 16, 255) if lum > 140 else rl.WHITE
    canvas.glyphs(font, label, rl.Vector2(chip.x + pad_x, cy - ts.y / 2), fs, txt_color)

  def _draw_title(self, x: float, with_badge: bool) -> None:
    self._text_size = measure_text_cached(self._font, self.title, metrics.TITLE_FS)
    y = self._rect.y + (metrics.ROW - self._text_size.y) // 2 if self.inline else self._rect.y + metrics.GUTTER * 1.5
    canvas.glyphs(self._font, self.title, rl.Vector2(x, y), metrics.TITLE_FS, self.title_color)
    if with_badge and self.title_badge:
      self._draw_title_badge(x + self._text_size.x + 24, y + self._text_size.y / 2)

  def _draw_right_value(self, from_x: float) -> None:
    span = rl.Rectangle(from_x, self._rect.y, self._rect.width - (from_x - self._rect.x) - metrics.GUTTER, metrics.ROW)
    if span.width > 0:
      gui_label(span, self.right_value, font_size=metrics.TITLE_FS, color=self._ro_tint,
                font_weight=FontWeight.NORMAL, alignment=rl.GuiTextAlignment.TEXT_ALIGN_RIGHT,
                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)

  def _draw_caption(self) -> None:
    content_w = int(self._rect.width - metrics.GUTTER * 2)
    y = self._rect.y + metrics.CAPTION_DY
    if not self.inline and self.action_item:
      y = self.action_item.rect.y + metrics.CAPTION_DY - metrics.GUTTER * 0.5
    self._html_renderer.render(rl.Rectangle(self._rect.x + metrics.GUTTER, y, content_w,
                                            self._html_renderer.get_total_height(content_w)))

  def _fire_action(self, action_rect: rl.Rectangle) -> None:
    if self.action_item.render(action_rect) and self.action_item.enabled and self.callback:
      self.callback()

  def _render(self, _):
    if not self.is_visible:
      return
    if (self._rect.y + self.rect.height) <= self._parent_rect.y or self._rect.y >= (self._parent_rect.y + self._parent_rect.height):
      return

    content_x = self._rect.x + metrics.GUTTER

    if self._leading_action():
      slot_h = metrics.WIDE_BTN_H if isinstance(self.action_item, IQSimpleButtonAction) else metrics.TOGGLE_H
      lead = rl.Rectangle(content_x, self._rect.y + (metrics.ROW - slot_h) // 2, self.action_item.rect.width, slot_h)
      text_x = lead.x + lead.width + metrics.GUTTER * 1.5
      if self.title:
        self._draw_title(text_x, with_badge=False)
      if self.right_value:
        self._draw_right_value(text_x)
      self._fire_action(lead)
    else:
      if self.title:
        self._draw_title(content_x, with_badge=True)
      if self.action_item:
        self._fire_action(self.get_right_item_rect(self._rect))

    if self.description_visible:
      self._draw_caption()


def simple_button_item_iq(button_text: _Dyn, callback: Callable | None = None,
                          enabled: bool | _Pred = True, button_width: int = metrics.WIDE_BTN_W) -> IQListItem:
  action = IQSimpleButtonAction(button_text=button_text, enabled=enabled, callback=callback, button_width=button_width)
  return IQListItem(title="", callback=callback, description="", action_item=action)


def toggle_item_iq(title: _Dyn, description: _Dyn | None = None, initial_state: bool = False,
                   callback: Callable | None = None, icon: str = "", enabled: bool | _Pred = True, param: str | None = None) -> IQListItem:
  action = IQToggleAction(initial_state=initial_state, enabled=enabled, callback=callback, param=param)
  return IQListItem(title=title, description=description, action_item=action, icon=icon, callback=callback)


def multiple_button_item_iq(title: _Dyn, description: _Dyn, buttons: list[_Dyn],
                            selected_index: int = 0, button_width: int = metrics.ACTION_W, callback: Callable | None = None,
                            icon: str = "", param: str | None = None, inline: bool = False) -> IQListItem:
  action = IQMultipleButtonAction(buttons, button_width, selected_index, callback=callback, param=param)
  return IQListItem(title=title, description=description, icon=icon, action_item=action, inline=inline)


def option_item_iq(title: _Dyn, param: str,
                   min_value: int, max_value: int, description: _Dyn | None = None,
                   value_change_step: int = 1, on_value_changed: Callable[[int], None] | None = None,
                   enabled: bool | _Pred = True,
                   icon: str = "", label_width: int = LABEL_WIDTH, value_map: dict[int, int] | None = None,
                   use_float_scaling: bool = False, label_callback: Callable[[int], str] | None = None, inline: bool = False) -> IQListItem:
  action = IQOptionControl(
    param, min_value, max_value, value_change_step,
    enabled, on_value_changed, value_map, label_width, use_float_scaling, label_callback
  )
  return IQListItem(title=title, description=description, action_item=action, icon=icon, inline=inline)


def button_item_iq(title: _Dyn, button_text: _Dyn, description: _Dyn | None = None,
                   callback: Callable | None = None, enabled: bool | _Pred = True) -> IQListItem:
  action = IQButtonAction(text=button_text, enabled=enabled)
  return IQListItem(title=title, description=description, action_item=action, callback=callback)


def dual_button_item_iq(left_text: _Dyn, right_text: _Dyn, left_callback: Callable | None = None,
                        right_callback: Callable | None = None, description: _Dyn | None = None,
                        enabled: bool | _Pred = True, border_radius: int = 40) -> IQListItem:
  action = IQDualButtonAction(left_text, right_text, left_callback, right_callback, enabled, border_radius)
  return IQListItem(title="", description=description, action_item=action)


# Preferred IQ helper names.
simple_button_item = simple_button_item_iq
toggle_item = toggle_item_iq
multiple_button_item = multiple_button_item_iq
option_item = option_item_iq
button_item = button_item_iq
dual_button_item = dual_button_item_iq


# ===== toggle =====

KNOB_PADDING = 10
KNOB_RADIUS = metrics.TOGGLE_TRACK_H / 2 - KNOB_PADDING

# Track colors: grey when off, teal gradient (left -> right) when on.
OFF_COLOR = rl.Color(58, 61, 68, 255)
ON_START = rl.Color(52, 231, 200, 255)    # #34E7C8
ON_END = rl.Color(4, 140, 155, 255)       # #048C9B
OFF_DISABLED = rl.Color(45, 47, 52, 255)
ON_START_DISABLED = rl.Color(40, 110, 100, 255)
ON_END_DISABLED = rl.Color(18, 78, 86, 255)
KNOB_ON = rl.WHITE
KNOB_DISABLED = rl.Color(150, 150, 150, 255)
TRACK_BORDER = rl.Color(0, 0, 0, 45)


class IQToggle(Toggle):
  def __init__(self, initial_state=False, callback: Callable[[bool], None] | None = None, param: str | None = None):
    self._slot = ParamSlot(param)
    if self._slot.bound:
      initial_state = self._slot.read_bool(initial_state)
    super().__init__(initial_state, callback)

  @property
  def param_key(self):
    return self._slot.key

  def set_rect(self, rect: rl.Rectangle):
    self._rect = rl.Rectangle(rect.x, rect.y, metrics.TOGGLE_W, metrics.TOGGLE_H)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._enabled:
      self._slot.write(self._state)

  def update(self):
    # Framerate-independent exponential ease-out (springy settle) instead of the base class's
    # constant-velocity linear slide, which read as robotic.
    if abs(self._progress - self._target) > 0.001:
      self._progress += (self._target - self._progress) * min(1.0, rl.get_frame_time() * 16.0)
    else:
      self._progress = self._target

  def _sync_from_param(self):
    if self._slot.bound:
      stored = self._slot.read_bool(self._state)
      if stored != self._state:
        self.set_state(stored)

  def _render(self, rect: rl.Rectangle):
    self._sync_from_param()
    self.update()
    self._rect.y -= metrics.GUTTER / 2

    # Track color blends grey -> teal gradient as the toggle animates on.
    if self._enabled:
      c_start = self._blend_color(OFF_COLOR, ON_START, self._progress)
      c_end = self._blend_color(OFF_COLOR, ON_END, self._progress)
      knob_color = KNOB_ON
    else:
      c_start = self._blend_color(OFF_DISABLED, ON_START_DISABLED, self._progress)
      c_end = self._blend_color(OFF_DISABLED, ON_END_DISABLED, self._progress)
      knob_color = KNOB_DISABLED

    x = self._rect.x
    y = self._rect.y
    w = metrics.TOGGLE_W
    h = metrics.TOGGLE_TRACK_H
    r = h / 2

    # Gradient pill: rounded end caps + horizontal gradient body
    rl.draw_circle(int(x + r), int(y + r), r, c_start)
    rl.draw_circle(int(x + w - r), int(y + r), r, c_end)
    canvas.h_sweep(int(x + r), int(y), int(w - 2 * r), int(h), c_start, c_end)

    # Subtle outline for definition
    canvas.panel_outline(rl.Rectangle(x, y, w, h), 1.0, 16, 2, TRACK_BORDER)

    # Knob position
    p = self._progress
    left_edge = x + KNOB_PADDING
    right_edge = x + w - KNOB_PADDING
    knob_travel_distance = right_edge - left_edge - 2 * KNOB_RADIUS
    knob_x = left_edge + KNOB_RADIUS + knob_travel_distance * p
    knob_y = y + h / 2

    # Subtle squish: the knob stretches along its travel and rounds back out at the ends — a tactile,
    # liquid feel. m peaks (1.0) at mid-travel and is 0 at rest, so a settled knob is a clean circle.
    m = 4.0 * p * (1.0 - p)
    rh = KNOB_RADIUS * (1.0 + 0.22 * m)
    rv = KNOB_RADIUS * (1.0 - 0.12 * m)

    # Soft drop shadow under the knob for depth
    rl.draw_ellipse(int(knob_x), int(knob_y + 4), rh + 1, rv + 1, rl.Color(0, 0, 0, 38))
    rl.draw_ellipse(int(knob_x), int(knob_y + 2), rh, rv, rl.Color(0, 0, 0, 30))
    rl.draw_ellipse(int(knob_x), int(knob_y), rh, rv, knob_color)


# ===== option_control =====

# Dimensions and styling constants
BUTTON_WIDTH = 150
BUTTON_HEIGHT = 150
LABEL_WIDTH = 350
BUTTON_SPACING = 25
VALUE_FONT_SIZE = 50
BUTTON_FONT_SIZE = 60
CONTAINER_PADDING = 20

# Circular +/- button styling
BTN_INSET = 24                                   # gap between circle and container edge
GLYPH_THICK = 9                                  # +/- stroke thickness
CONTAINER_ROUNDNESS = 0.5
BTN_BG = rl.Color(64, 67, 75, 255)               # idle circle (lifted off the container)
BTN_BG_DISABLED = rl.Color(40, 42, 48, 255)
BTN_BG_PRESSED = rl.Color(16, 185, 169, 255)     # teal on press
GLYPH_COLOR = rl.Color(52, 231, 200, 255)        # teal +/-
GLYPH_PRESSED = rl.Color(10, 14, 16, 255)        # dark glyph on teal
GLYPH_DISABLED = rl.Color(110, 112, 118, 255)


class _ValueCodec:
  """Maps between the stepper's internal integer position and the stored/displayed value."""

  def __init__(self, value_map: dict[int, int] | None, float_scaled: bool,
               label_fn: Callable[[float | int], str] | None):
    self._map = value_map
    self._scaled = float_scaled
    self._label_fn = label_fn

  def external(self, position: int):
    if self._map:
      return self._map[position]
    return position / 100.0 if self._scaled else position

  def position_of(self, stored, fallback: int) -> int:
    if self._map:
      for pos, mapped in self._map.items():
        if mapped == stored:
          return int(pos)
      return fallback
    try:
      return int(round(float(stored) * 100.0)) if self._scaled else int(stored)
    except (TypeError, ValueError):
      return fallback

  def label(self, position: int) -> str:
    if self._label_fn:
      return self._label_fn(self.external(position))
    if self._map:
      return str(self._map.get(position, position))
    if self._scaled:
      return f"{position / 100.0:.2f}"
    return str(position)


class IQOptionControl(ItemAction):
  def __init__(self, param: str, min_value: int, max_value: int,
               value_change_step: int = 1, enabled: bool | _Pred = True,
               on_value_changed: Callable[[int], None] | None = None,
               value_map: dict[int, int] | None = None,
               label_width: int = LABEL_WIDTH,
               use_float_scaling: bool = False, label_callback: Callable[[float | int], str] | None = None):
    super().__init__(enabled=enabled)
    self.param_key = param
    self.min_value = min_value
    self.max_value = max_value
    self.value_change_step = value_change_step
    self.on_value_changed = on_value_changed
    self.label_width = label_width
    # kept for callers introspecting the control
    self.value_map = value_map
    self.use_float_scaling = use_float_scaling
    self.label_callback = label_callback

    self._slot = ParamSlot(param)
    self._codec = _ValueCodec(value_map, use_float_scaling, label_callback)
    self.current_value = self._clamp(self._codec.position_of(self._slot.read_raw(), min_value))

    self._font = gui_app.font(FontWeight.MEDIUM)
    self._zones: dict[int, rl.Rectangle] = {}   # step delta sign -> hit rect
    self.label_rect = rl.Rectangle(0, 0, 0, 0)

  def _clamp(self, position: int) -> int:
    return max(self.min_value, min(self.max_value, position))

  def get_value(self) -> int:
    return self.current_value

  def set_value(self, value: int):
    if not (self.min_value <= value <= self.max_value):
      return
    self.current_value = value
    self._slot.write(self._codec.external(value))
    if self.on_value_changed:
      self.on_value_changed(value)

  def get_displayed_value(self) -> str:
    return self._codec.label(self.current_value)

  def _place(self, rect: rl.Rectangle):
    control_w = BUTTON_WIDTH * 2 + self.label_width + BUTTON_SPACING * 2
    total_w = control_w + CONTAINER_PADDING * 2
    self._rect.width = total_w
    x0 = self._rect.x + self._rect.width - total_w
    y0 = rect.y + (rect.height - BUTTON_HEIGHT) / 2

    self.container_rect = rl.Rectangle(x0, y0, total_w, BUTTON_HEIGHT)
    self._zones = {
      -1: rl.Rectangle(x0, y0, BUTTON_WIDTH + CONTAINER_PADDING, BUTTON_HEIGHT),
      +1: rl.Rectangle(x0 + CONTAINER_PADDING + BUTTON_WIDTH + BUTTON_SPACING + self.label_width + BUTTON_SPACING,
                       y0, BUTTON_WIDTH + CONTAINER_PADDING, BUTTON_HEIGHT),
    }
    self.label_rect = rl.Rectangle(x0 + CONTAINER_PADDING + BUTTON_WIDTH + BUTTON_SPACING, y0,
                                   self.label_width, BUTTON_HEIGHT)

  def _step_allowed(self, direction: int) -> bool:
    if not self.enabled:
      return False
    return self.current_value > self.min_value if direction < 0 else self.current_value < self.max_value

  def _render(self, rect: rl.Rectangle):
    if self._rect.width == 0 or self._rect.height == 0 or not self.is_visible:
      return

    self._place(rect)
    canvas.panel(self.container_rect, CONTAINER_ROUNDNESS, 20, ink.PANEL)

    for direction, zone in self._zones.items():
      self._draw_stepper(zone, direction, self._step_allowed(direction))

    label = self.get_displayed_value()
    size = measure_text_cached(self._font, label, VALUE_FONT_SIZE)
    origin = rl.Vector2(self.label_rect.x + (self.label_rect.width - size.x) / 2,
                        self.label_rect.y + (self.label_rect.height - size.y) / 2)
    canvas.glyphs(self._font, label, origin, VALUE_FONT_SIZE, ink.TITLE if self.enabled else ink.DISABLED)

  def _draw_stepper(self, zone: rl.Rectangle, direction: int, allowed: bool):
    pressed = (allowed and self._touch_valid()
               and rl.check_collision_point_rec(rl.get_mouse_position(), zone)
               and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT))

    if not allowed:
      circle, glyph = BTN_BG_DISABLED, GLYPH_DISABLED
    elif pressed:
      circle, glyph = BTN_BG_PRESSED, GLYPH_PRESSED
    else:
      circle, glyph = BTN_BG, GLYPH_COLOR

    cx = zone.x + zone.width / 2
    cy = zone.y + zone.height / 2
    radius = (BUTTON_HEIGHT - 2 * BTN_INSET) / 2
    rl.draw_circle(int(cx), int(cy), radius, circle)

    # Crisp drawn glyph (rounded bars) instead of a font character
    arm = radius * 0.46
    canvas.panel(rl.Rectangle(cx - arm, cy - GLYPH_THICK / 2, arm * 2, GLYPH_THICK), 1.0, 6, glyph)
    if direction > 0:
      canvas.panel(rl.Rectangle(cx - GLYPH_THICK / 2, cy - arm, GLYPH_THICK, arm * 2), 1.0, 6, glyph)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    for direction, zone in self._zones.items():
      if self._step_allowed(direction) and rl.check_collision_point_rec(mouse_pos, zone):
        self.set_value(self._clamp(self.current_value + direction * self.value_change_step))
        return
    self.set_value(self.current_value)


# Preferred IQ-compatible generic alias.
OptionControl = IQOptionControl


# ===== progress_bar =====

# Download progress fill: gradient from 09A3AB (left) to E30985 (right).
FILL_START = rl.Color(0x09, 0xA3, 0xAB, 255)
FILL_END = rl.Color(0xE3, 0x09, 0x85, 255)

_FONT_SIZE = 40
_BAR_H = 60
_PAD = 30
_INSET = 4
_SWEEP_FRACTION = 0.35
_SWEEP_HZ = 0.7


def _mix(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  t = max(0.0, min(1.0, t))
  return rl.Color(int(a.r + (b.r - a.r) * t), int(a.g + (b.g - a.g) * t), int(a.b + (b.b - a.b) * t), 255)


class ProgressBarAction(ItemAction):
  def __init__(self, width=600):
    super().__init__(width=width)
    self.progress = 0.0
    self.text = ""
    self.show_progress = False
    self.indeterminate = False
    self.text_color = rl.GRAY
    self._font = gui_app.font(FontWeight.NORMAL)

  def update(self, progress, text, show_progress=False, text_color=rl.GRAY, indeterminate=False):
    self.progress = progress
    self.text = text
    self.show_progress = show_progress
    self.text_color = text_color
    self.indeterminate = indeterminate

  def _bar_geometry(self, rect: rl.Rectangle) -> tuple[rl.Rectangle, float]:
    """Right-aligned bar sized to the text; a "NN% - detail" label reserves the
    width of a full "100%" prefix so the bar doesn't jitter as digits change."""
    label_w = measure_text_cached(self._font, self.text, _FONT_SIZE).x
    text_dx = _PAD

    prefix, sep, _ = self.text.partition(" - ")
    if self.show_progress and sep:
      widest_prefix = measure_text_cached(self._font, "100%", _FONT_SIZE).x
      prefix_w = measure_text_cached(self._font, prefix, _FONT_SIZE).x
      slack = widest_prefix - prefix_w
      bar_w = label_w + slack + 2 * _PAD
      text_dx = _PAD + slack
    else:
      bar_w = label_w + 2 * _PAD
      text_dx = (bar_w - label_w) / 2

    bar = rl.Rectangle(rect.x + rect.width - bar_w, rect.y + (rect.height - _BAR_H) / 2, bar_w, _BAR_H)
    return bar, text_dx

  @staticmethod
  def _fill_span(track: rl.Rectangle, lo: float, hi: float):
    """Paint the [lo, hi] fraction of the track with the gradient section that
    belongs to that span, so partial fills stay colour-consistent."""
    lo, hi = max(0.0, lo), min(1.0, hi)
    if hi <= lo:
      return
    x0 = track.x + track.width * lo
    x1 = track.x + track.width * hi
    canvas.h_sweep(int(x0), int(track.y), int(x1 - x0), int(track.height),
                                 _mix(FILL_START, FILL_END, lo), _mix(FILL_START, FILL_END, hi))

  def _render(self, rect: rl.Rectangle):
    bar, text_dx = self._bar_geometry(rect)

    if self.show_progress:
      track = rl.Rectangle(bar.x + _INSET, bar.y + _INSET, bar.width - 2 * _INSET, bar.height - 2 * _INSET)
      if track.width > 0:
        if self.indeterminate:
          # no known percentage (host didn't expose a size) — sweep a gradient window across
          phase = (rl.get_time() * _SWEEP_HZ) % 1.0
          head = phase * (1.0 + _SWEEP_FRACTION)
          self._fill_span(track, head - _SWEEP_FRACTION, head)
        else:
          self._fill_span(track, 0.0, self.progress / 100.0)

    label_h = measure_text_cached(self._font, self.text, _FONT_SIZE).y
    rl.draw_text_ex(self._font, self.text, rl.Vector2(bar.x + text_dx, bar.y + (_BAR_H - label_h) / 2),
                    _FONT_SIZE, 0, self.text_color)


def progress_item(title):
  return ListItem(title=title, action_item=ProgressBarAction())

from dataclasses import dataclass, field
from openpilot.common.params import Params
from openpilot.system.ui.iqpilot.lib.styles import ink
from openpilot.system.ui.iqpilot.widgets.helpers.glyphs import draw_star
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle, BUTTON_PRESSED_BACKGROUND_COLORS
from openpilot.system.ui.widgets.html_render import HtmlModal
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog


# ===== tree_dialog =====

TREE_TEAL = rl.Color(16, 185, 169, 255)
TREE_FOLDER_COLOR = rl.Color(48, 51, 58, 255)        # brand header rows (lighter)
TREE_SEARCH_FILL = rl.Color(42, 45, 52, 255)
TREE_SEARCH_PRESSED = rl.Color(58, 62, 70, 255)
TREE_SEARCH_BORDER = rl.Color(255, 255, 255, 38)

_STAR_SLOT = 90          # right-edge inset reserved for the favourite star
_ROW_H = 120
_FRAME_PAD = 50


@dataclass
class TreeNode:
  ref: str
  data: dict = field(default_factory=dict)


@dataclass
class TreeFolder:
  folder: str
  nodes: list


class _TreeRow(Button):
  """One rendered row: a brand/folder header, or a selectable leaf with an optional star."""

  def __init__(self, text, ref, is_folder=False, indent_level=0, click_callback=None,
               favorite_callback=None, is_favorite=False, is_expanded=False):
    super().__init__(text, click_callback, button_style=ButtonStyle.NORMAL,
                     text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                     text_padding=20 + indent_level * 30, elide_right=True)
    self.text = text
    self.ref = ref
    self.is_folder = is_folder
    self.indent_level = indent_level
    self.is_favorite = is_favorite
    self.selected = False
    self.is_expanded = is_expanded
    self._favorite_callback = favorite_callback
    self.text_padding = 20 + indent_level * 30
    self.border_radius = 10

  def _fill_color(self):
    if self.is_pressed:
      return BUTTON_PRESSED_BACKGROUND_COLORS[self._button_style]
    if self.selected and self.ref != "search_bar":
      return TREE_TEAL
    return TREE_FOLDER_COLOR if self.is_folder else ink.KEY_SUNKEN

  def _star_hitbox(self) -> rl.Rectangle:
    return rl.Rectangle(self._rect.x + self._rect.width - _STAR_SLOT - 40,
                        self._rect.y + self._rect.height / 2 - 40, 80, 80)

  def _render(self, rect):
    indent = 60 * self.indent_level
    self._rect = rl.Rectangle(rect.x + indent, rect.y, rect.width - indent, rect.height)
    roundness = self.border_radius / (min(self._rect.width, self._rect.height) / 2)
    rl.draw_rectangle_rounded(self._rect, roundness, 10, self._fill_color())

    cy = self._rect.y + self._rect.height / 2
    text_offset = self.text_padding + 20

    if self.is_folder:
      # chevron: down when expanded, right when collapsed
      chev = gui_app.texture("icons/iq/chevron_down.png" if self.is_expanded else "icons/iq/chevron_right.png",
                             40, 40, keep_aspect_ratio=True)
      rl.draw_texture(chev, int(self._rect.x + self.text_padding + 6), int(cy - chev.height / 2), rl.Color(205, 205, 210, 255))
      text_offset = self.text_padding + 6 + 40 + 22
    elif self.indent_level > 0 and not self.selected:
      # teal accent marking a model under the expanded brand
      rl.draw_rectangle_rounded(rl.Rectangle(self._rect.x + 16, cy - 24, 6, 48), 1.0, 4, TREE_TEAL)

    self._label.render(rl.Rectangle(self._rect.x + text_offset, self._rect.y,
                                    self._rect.width - text_offset - _STAR_SLOT, self._rect.height))

    if not self.is_folder and self._favorite_callback:
      draw_star(self._rect.x + self._rect.width - _STAR_SLOT, cy, 40, self.is_favorite,
                ink.ACCENT if self.is_favorite else rl.GRAY)

  def _handle_mouse_release(self, mouse_pos):
    if not self.is_folder and self._favorite_callback and rl.check_collision_point_rec(mouse_pos, self._star_hitbox()):
      self._favorite_callback()
      return True
    return super()._handle_mouse_release(mouse_pos)


class TreeOptionDialog(MultiOptionDialog):
  """Folder/leaf picker with search, favourites, and a pinned current selection."""

  def __init__(self, title, folders, current_ref="", fav_param="", option_font_weight=FontWeight.MEDIUM, search_prompt=None,
               get_folders_fn=None, on_exit=None, display_func=None, search_funcs=None, search_title=None, search_subtitle=None):
    super().__init__(title, [], current_ref, option_font_weight)
    self.folders = folders
    self.selection_ref = current_ref
    self.fav_param = fav_param
    self.expanded = set()
    self._fav_slot = ParamSlot(fav_param or None)
    stored = self._fav_slot.read_raw()
    self.favorites = set(stored.split(';')) if stored else set()
    self.query = ""
    self.search_prompt = search_prompt or tr("Search")
    self.get_folders_fn = get_folders_fn
    self.on_exit = on_exit
    self.display_func = display_func or (lambda node: node.data.get('display_name', node.ref))
    self.search_funcs = search_funcs or [lambda node: node.data.get('display_name', ''), lambda node: node.data.get('short_name', '')]
    self.search_title = search_title or tr("Enter search query")
    self.search_subtitle = search_subtitle
    self._search_rect: rl.Rectangle | None = None
    self._search_pressed = False

    self.selection_node = self._locate_current(current_ref)
    if self.selection_node is not None:
      self.selection = self.current = self.display_func(self.selection_node)

    self._build_visible_items()

  # -- model ----------------------------------------------------------------
  def _locate_current(self, current_ref):
    """Match by ref, by display text, or fall back to "Default" when no ref is set."""
    for folder in self.folders:
      for node in folder.nodes:
        display = self.display_func(node)
        if node.ref == current_ref or display == current_ref or (not current_ref and node.ref == "Default"):
          return node
    return None

  def _node_matches(self, node) -> bool:
    if not self.query:
      return True
    haystacks = [fn(node) for fn in self.search_funcs]
    return bool(rank_matches(self.query, [h for h in haystacks if h]))

  def _leaf_row(self, node, depth: int, expanded: bool = False) -> _TreeRow:
    fav_cb = None
    if self.fav_param and node.ref != "Default":
      fav_cb = lambda n=node: self._toggle_favorite(n)  # noqa: E731
    return _TreeRow(self.display_func(node), node.ref, False, depth,
                    lambda n=node: self._select_node(n),
                    fav_cb, node.ref in self.favorites, is_expanded=expanded)

  def _build_visible_items(self, reset_scroll=True):
    rows: list[_TreeRow] = []

    # Pinned selected item at the very top (if any)
    pinned = getattr(self, "selection_node", None)
    if pinned is not None:
      self.selection = self.current = self.display_func(pinned)
      rows.append(self._leaf_row(pinned, 0, expanded=True))

    for folder in self.folders:
      visible_nodes = [n for n in folder.nodes if self._node_matches(n)]
      if not visible_nodes and self.query:
        continue
      expanded = folder.folder in self.expanded or not folder.folder or bool(self.query)
      if folder.folder:
        rows.append(_TreeRow(folder.folder, "", True, 0,
                             lambda f=folder: self._toggle_folder(f), is_expanded=expanded))
      if expanded:
        for node in visible_nodes:
          if pinned is not None and node.ref == pinned.ref and not folder.folder:
            continue  # already pinned at the top
          rows.append(self._leaf_row(node, 1 if folder.folder else 0, expanded=expanded))

    self.visible_items = rows
    self.option_buttons = rows
    self.options = [row.text for row in rows]
    self.scroller._items = rows
    if reset_scroll:
      self.scroller.scroll_panel.set_offset(0)

  # -- interactions ---------------------------------------------------------
  def _select_node(self, node):
    self.selection = self.display_func(node)
    self.selection_ref = node.ref

  def _toggle_folder(self, folder):
    if not folder.folder:
      return
    self.expanded.symmetric_difference_update({folder.folder})
    if folder is self.folders[-1] and folder.folder in self.expanded:
      self.scroller.scroll_panel.set_offset(self.scroller.scroll_panel.offset - 200)
    self._build_visible_items(reset_scroll=False)

  def _toggle_favorite(self, node):
    self.favorites.symmetric_difference_update({node.ref})
    self._fav_slot.write(';'.join(self.favorites))
    if self.get_folders_fn:
      self.folders = self.get_folders_fn(self.favorites)
    self._build_visible_items(reset_scroll=False)

  def _open_search(self):
    def _apply(result, text):
      if result == DialogResult.CONFIRM:
        self.query = text
        self._build_visible_items()
      gui_app.set_modal_overlay(self, callback=self.on_exit)

    open_text_prompt(self.search_title, self.search_subtitle, initial=self.query, on_done=_apply)

  # -- drawing --------------------------------------------------------------
  def _render(self, rect):
    frame = rl.Rectangle(rect.x + _FRAME_PAD, rect.y + _FRAME_PAD, rect.width - 2 * _FRAME_PAD, rect.height - 2 * _FRAME_PAD)
    rl.draw_rectangle_rounded(frame, 0.02, 20, rl.BLACK)

    title_rect = rl.Rectangle(frame.x + _FRAME_PAD, frame.y + _FRAME_PAD, frame.width * 0.5, 70)
    gui_label(title_rect, self.title, 70, font_weight=FontWeight.BOLD)

    search_bottom = self._draw_search_field(frame, title_rect.y + title_rect.height + 36)
    self._draw_choice_list(frame, search_bottom + 36)
    self._draw_footer(frame)
    return self._result

  def _draw_search_field(self, frame: rl.Rectangle, top: float) -> float:
    self._search_rect = rl.Rectangle(frame.x + _FRAME_PAD, top, frame.width - 2 * _FRAME_PAD, 100)
    rl.draw_rectangle_rounded(self._search_rect, 0.4, 16, TREE_SEARCH_PRESSED if self._search_pressed else TREE_SEARCH_FILL)
    rl.draw_rectangle_rounded_lines_ex(self._search_rect, 0.4, 16, 2, TREE_SEARCH_BORDER)

    # Magnifying glass icon
    icon_color = rl.Color(190, 190, 195, 255)
    cx = self._search_rect.x + 54
    cy = self._search_rect.y + self._search_rect.height / 2 - 2
    radius = 24
    for i in range(4):
      rl.draw_circle_lines(int(cx), int(cy), radius - i, icon_color)
    rl.draw_line_ex(rl.Vector2(cx + radius * 0.65, cy + radius * 0.65),
                    rl.Vector2(cx + radius * 1.4, cy + radius * 1.4), 5, icon_color)

    # Query text, or muted placeholder
    text_x = cx + radius * 1.4 + 34
    text_rect = rl.Rectangle(text_x, self._search_rect.y,
                             self._search_rect.x + self._search_rect.width - text_x - 24, self._search_rect.height)
    if self.query:
      gui_label(text_rect, self.query, 56, font_weight=FontWeight.MEDIUM)
    else:
      gui_label(text_rect, self.search_prompt, 56, color=rl.Color(150, 150, 155, 255), font_weight=FontWeight.NORMAL)

    return self._search_rect.y + self._search_rect.height

  def _draw_choice_list(self, frame: rl.Rectangle, top: float):
    area = rl.Rectangle(frame.x + _FRAME_PAD, top, frame.width - 2 * _FRAME_PAD,
                        frame.height - (top - frame.y) - 210)
    for row in self.option_buttons:
      row.selected = (row.text == self.selection)
      row.set_button_style(ButtonStyle.PRIMARY if row.selected else ButtonStyle.NORMAL)
      row.set_rect(rl.Rectangle(0, 0, area.width, _ROW_H))
    self.scroller.render(area)

  def _draw_footer(self, frame: rl.Rectangle):
    btn_w = (frame.width - 3 * _FRAME_PAD) / 2
    btn_y = frame.y + frame.height - 160

    self.cancel_button._border_radius = self.select_button._border_radius = 44
    self.cancel_button.render(rl.Rectangle(frame.x + _FRAME_PAD, btn_y, btn_w, 160))

    select_rect = rl.Rectangle(frame.x + 2 * _FRAME_PAD + btn_w, btn_y, btn_w, 160)
    can_select = self.selection != self.current
    self.select_button.set_enabled(can_select)
    if can_select:
      rl.draw_rectangle_rounded(select_rect, 44 / (min(select_rect.width, select_rect.height) / 2), 10, TREE_TEAL)
      self.select_button.set_button_style(ButtonStyle.TRANSPARENT_WHITE_TEXT)
    else:
      self.select_button.set_button_style(ButtonStyle.NORMAL)
    self.select_button.render(select_rect)

  # -- input ----------------------------------------------------------------
  def _handle_mouse_press(self, mouse_pos):
    if self._search_rect and rl.check_collision_point_rec(mouse_pos, self._search_rect):
      self._search_pressed = True
      return True
    return super()._handle_mouse_press(mouse_pos)

  def _handle_mouse_release(self, mouse_pos):
    tapped_search = (self._search_pressed and self._search_rect
                     and rl.check_collision_point_rec(mouse_pos, self._search_rect))
    self._search_pressed = False
    if tapped_search:
      self._open_search()
      return True
    return super()._handle_mouse_release(mouse_pos)


# ===== text_prompt =====

def open_text_prompt(title: str, subtitle: str | None = None, initial: str = "",
                     param_key: str | None = None,
                     on_done: Callable[[DialogResult, str], None] | None = None,
                     min_len: int = 0, password: bool = False) -> Keyboard:
  """Open the on-screen keyboard as a modal text prompt.

  On confirm, the entered text is optionally persisted to `param_key` and
  passed to `on_done`; a cancel reports an empty string.
  """
  pad = Keyboard(max_text_size=255, min_text_size=min_len, password_mode=password)
  pad.set_title(title, subtitle) if subtitle else pad.set_title(title)
  pad.set_text(initial)

  def _finish(result: DialogResult):
    entered = pad.text if result == DialogResult.CONFIRM else ""
    if entered and result == DialogResult.CONFIRM and param_key:
      Params().put(param_key, entered)
    if on_done:
      on_done(result, entered)

  gui_app.set_modal_overlay(pad, _finish)
  return pad


# ===== notice_modal =====

class NoticeModal(HtmlModal):
  """HTML notice dialog whose OK press closes the overlay and reports CONFIRM."""

  def __init__(self, file_path=None, text=None, callback=None):
    super().__init__(file_path=file_path, text=text)
    self.result = DialogResult.NO_ACTION

    def _dismiss():
      self.result = DialogResult.CONFIRM
      gui_app.set_modal_overlay(None)
      if callback:
        callback(self.result)

    self._ok_button._click_callback = _dismiss

  def reset(self):
    self.result = DialogResult.NO_ACTION


# ===== param binding (typed per-key params handle for IQ settings widgets) =====

class ParamSlot:
  """Typed read/write handle for one params key, shared by IQ settings widgets.

  A widget owns a slot instead of talking to Params directly; missing keys
  (params compiled out of a build) degrade to the fallback instead of raising.
  """

  _store = Params()

  def __init__(self, key: str | None):
    self.key = key

  @property
  def bound(self) -> bool:
    return bool(self.key)

  def read_bool(self, fallback: bool = False) -> bool:
    if not self.key:
      return fallback
    try:
      return self._store.get_bool(self.key)
    except UnknownKeyName:
      return fallback

  def read_raw(self, fallback=None):
    if not self.key:
      return fallback
    try:
      value = self._store.get(self.key, return_default=True)
    except UnknownKeyName:
      return fallback
    return fallback if value is None else value

  def read_int(self, fallback: int = 0) -> int:
    try:
      return int(self.read_raw(fallback))
    except (TypeError, ValueError):
      return fallback

  def write(self, value) -> bool:
    if not self.key:
      return False
    try:
      if isinstance(value, bool):
        self._store.put_bool(self.key, value)
      else:
        self._store.put(self.key, value)
    except UnknownKeyName:
      return False
    return True


# ===== fuzzy match ranking (folder/search filtering for tree pickers) =====

def _fold(text: str) -> str:
  return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def _words_of(text: str) -> list[str]:
  out, cur = [], []
  for ch in _fold(text):
    if ch.isalnum():
      cur.append(ch)
    elif cur:
      out.append("".join(cur))
      cur = []
  if cur:
    out.append("".join(cur))
  return out


def _is_subsequence(needle: str, haystack: str) -> bool:
  it = iter(haystack)
  return all(ch in it for ch in needle)


def _token_score(token: str, words: list[str], joined: str) -> int:
  best = 0
  for w in words:
    if w == token:
      best = max(best, 100)
    elif w.startswith(token):
      best = max(best, 75)
    elif token in w:
      best = max(best, 40)
  if not best and _is_subsequence(token, joined):
    best = 10
  return best


def rank_matches(query: str, items: list[str]) -> list[str]:
  tokens = _words_of(query)
  if not tokens:
    return list(items)
  ranked = []
  for item in items:
    words = _words_of(item)
    joined = "".join(words)
    total = 0
    for tok in tokens:
      s = _token_score(tok, words, joined)
      if s == 0:
        total = 0
        break
      total += s
    if total:
      ranked.append((total, item))
  ranked.sort(key=lambda pair: (-pair[0], items.index(pair[1])))
  return [item for _, item in ranked]
