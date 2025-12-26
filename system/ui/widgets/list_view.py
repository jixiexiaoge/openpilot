import os
import pyray as rl
from collections.abc import Callable
from abc import ABC
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.toggle import Toggle, WIDTH as TOGGLE_WIDTH, HEIGHT as TOGGLE_HEIGHT
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.html_render import HtmlRenderer, ElementType

ITEM_BASE_WIDTH = 600
ITEM_BASE_HEIGHT = 170
ITEM_PADDING = 20
ITEM_TEXT_FONT_SIZE = 50
ITEM_TEXT_COLOR = rl.WHITE
ITEM_TEXT_VALUE_COLOR = rl.Color(170, 170, 170, 255)
ITEM_DESC_TEXT_COLOR = rl.Color(128, 128, 128, 255)
ITEM_DESC_FONT_SIZE = 40
ITEM_DESC_V_OFFSET = 140
RIGHT_ITEM_PADDING = 20
ICON_SIZE = 80
BUTTON_WIDTH = 250
BUTTON_HEIGHT = 100
BUTTON_BORDER_RADIUS = 50
BUTTON_FONT_SIZE = 35
BUTTON_FONT_WEIGHT = FontWeight.MEDIUM

TEXT_PADDING = 20


def _resolve_value(value, default=""):
  if callable(value):
    return value()
  return value if value is not None else default


# Abstract base class for right-side items
class ItemAction(Widget, ABC):
  def __init__(self, width: int = BUTTON_HEIGHT, enabled: bool | Callable[[], bool] = True):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, width, 0))
    self._enabled_source = enabled

  def get_width_hint(self) -> float:
    # Return's action ideal width, 0 means use full width
    return self._rect.width

  def set_enabled(self, enabled: bool | Callable[[], bool]):
    self._enabled_source = enabled

  @property
  def enabled(self):
    return _resolve_value(self._enabled_source, False)


class ToggleAction(ItemAction):
  def __init__(self, initial_state: bool = False, width: int = TOGGLE_WIDTH, enabled: bool | Callable[[], bool] = True,
               callback: Callable[[bool], None] | None = None):
    super().__init__(width, enabled)
    self.toggle = Toggle(initial_state=initial_state, callback=callback)

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self.toggle.set_touch_valid_callback(touch_callback)

  def _render(self, rect: rl.Rectangle) -> bool:
    self.toggle.set_enabled(self.enabled)
    clicked = self.toggle.render(rl.Rectangle(rect.x, rect.y + (rect.height - TOGGLE_HEIGHT) / 2, self._rect.width, TOGGLE_HEIGHT))
    return bool(clicked)

  def set_state(self, state: bool):
    self.toggle.set_state(state)

  def get_state(self) -> bool:
    return self.toggle.get_state()


class ButtonAction(ItemAction):
  def __init__(self, text: str | Callable[[], str], width: int = BUTTON_WIDTH, enabled: bool | Callable[[], bool] = True):
    super().__init__(width, enabled)
    self._text_source = text
    self._value_source: str | Callable[[], str] | None = None
    self._pressed = False
    self._font = gui_app.font(FontWeight.NORMAL)

    def pressed():
      self._pressed = True

    self._button = Button(
      self.text,
      font_size=BUTTON_FONT_SIZE,
      font_weight=BUTTON_FONT_WEIGHT,
      button_style=ButtonStyle.LIST_ACTION,
      border_radius=BUTTON_BORDER_RADIUS,
      click_callback=pressed,
      text_padding=0,
    )
    self.set_enabled(enabled)

  def get_width_hint(self) -> float:
    value_text = self.value
    if value_text:
      text_width = measure_text_cached(self._font, value_text, ITEM_TEXT_FONT_SIZE).x
      return text_width + BUTTON_WIDTH + TEXT_PADDING
    else:
      return BUTTON_WIDTH

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self._button.set_touch_valid_callback(touch_callback)

  def set_text(self, text: str | Callable[[], str]):
    self._text_source = text

  def set_value(self, value: str | Callable[[], str]):
    self._value_source = value

  @property
  def text(self):
    return _resolve_value(self._text_source, tr("Error"))

  @property
  def value(self):
    return _resolve_value(self._value_source, "")

  def _render(self, rect: rl.Rectangle) -> bool:
    self._button.set_text(self.text)
    self._button.set_enabled(_resolve_value(self.enabled))
    button_rect = rl.Rectangle(rect.x + rect.width - BUTTON_WIDTH, rect.y + (rect.height - BUTTON_HEIGHT) / 2, BUTTON_WIDTH, BUTTON_HEIGHT)
    self._button.render(button_rect)

    value_text = self.value
    if value_text:
      value_rect = rl.Rectangle(rect.x, rect.y, rect.width - BUTTON_WIDTH - TEXT_PADDING, rect.height)
      gui_label(value_rect, value_text, font_size=ITEM_TEXT_FONT_SIZE, color=ITEM_TEXT_VALUE_COLOR,
                font_weight=FontWeight.NORMAL, alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)

    # TODO: just use the generic Widget click callbacks everywhere, no returning from render
    pressed = self._pressed
    self._pressed = False
    return pressed


class TextAction(ItemAction):
  def __init__(self, text: str | Callable[[], str], color: rl.Color = ITEM_TEXT_COLOR, enabled: bool | Callable[[], bool] = True):
    self._text_source = text
    self.color = color

    self._font = gui_app.font(FontWeight.NORMAL)
    initial_text = _resolve_value(text, "")
    text_width = measure_text_cached(self._font, initial_text, ITEM_TEXT_FONT_SIZE).x
    super().__init__(int(text_width + TEXT_PADDING), enabled)

  @property
  def text(self):
    return _resolve_value(self._text_source, tr("Error"))

  def get_width_hint(self) -> float:
    text_width = measure_text_cached(self._font, self.text, ITEM_TEXT_FONT_SIZE).x
    return text_width + TEXT_PADDING

  def _render(self, rect: rl.Rectangle) -> bool:
    gui_label(self._rect, self.text, font_size=ITEM_TEXT_FONT_SIZE, color=self.color,
              font_weight=FontWeight.NORMAL, alignment=rl.GuiTextAlignment.TEXT_ALIGN_RIGHT,
              alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)
    return False

  def set_text(self, text: str | Callable[[], str]):
    self._text_source = text


class DualButtonAction(ItemAction):
  def __init__(self, left_text: str | Callable[[], str], right_text: str | Callable[[], str], left_callback: Callable = None,
               right_callback: Callable = None, enabled: bool | Callable[[], bool] = True):
    super().__init__(width=0, enabled=enabled)  # Width 0 means use full width
    self.left_button = Button(left_text, click_callback=left_callback, button_style=ButtonStyle.NORMAL, text_padding=0)
    self.right_button = Button(right_text, click_callback=right_callback, button_style=ButtonStyle.DANGER, text_padding=0)

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self.left_button.set_touch_valid_callback(touch_callback)
    self.right_button.set_touch_valid_callback(touch_callback)

  def _render(self, rect: rl.Rectangle):
    button_spacing = 30
    button_height = 120
    button_width = (rect.width - button_spacing) / 2
    button_y = rect.y + (rect.height - button_height) / 2

    left_rect = rl.Rectangle(rect.x, button_y, button_width, button_height)
    right_rect = rl.Rectangle(rect.x + button_width + button_spacing, button_y, button_width, button_height)

    # expand one to full width if other is not visible
    if not self.left_button.is_visible:
      right_rect.x = rect.x
      right_rect.width = rect.width
    elif not self.right_button.is_visible:
      left_rect.width = rect.width

    # Render buttons
    self.left_button.render(left_rect)
    self.right_button.render(right_rect)


class MultipleButtonAction(ItemAction):
  def __init__(self, buttons: list[str | Callable[[], str]], button_width: int, selected_index: int = 0, callback: Callable = None):
    super().__init__(width=len(buttons) * button_width + (len(buttons) - 1) * RIGHT_ITEM_PADDING, enabled=True)
    self.buttons = buttons
    self.button_width = button_width
    self.selected_button = selected_index
    self.callback = callback
    self._font = gui_app.font(FontWeight.MEDIUM)

  def set_selected_button(self, index: int):
    if 0 <= index < len(self.buttons):
      self.selected_button = index

  def get_selected_button(self) -> int:
    return self.selected_button

  def _render(self, rect: rl.Rectangle):
    spacing = RIGHT_ITEM_PADDING
    button_y = rect.y + (rect.height - BUTTON_HEIGHT) / 2

    for i, _text in enumerate(self.buttons):
      button_x = rect.x + i * (self.button_width + spacing)
      button_rect = rl.Rectangle(button_x, button_y, self.button_width, BUTTON_HEIGHT)

      # Check button state
      mouse_pos = rl.get_mouse_position()
      is_pressed = rl.check_collision_point_rec(mouse_pos, button_rect) and self.enabled and self.is_pressed
      is_selected = i == self.selected_button

      # Button colors
      if is_selected:
        bg_color = rl.Color(51, 171, 76, 255)  # Green
      elif is_pressed:
        bg_color = rl.Color(74, 74, 74, 255)  # Dark gray
      else:
        bg_color = rl.Color(57, 57, 57, 255)  # Gray

      if not self.enabled:
        bg_color = rl.Color(bg_color.r, bg_color.g, bg_color.b, 150)  # Dim

      # Draw button
      rl.draw_rectangle_rounded(button_rect, 1.0, 20, bg_color)

      # Draw text
      text = _resolve_value(_text, "")
      text_size = measure_text_cached(self._font, text, 40)
      text_x = button_x + (self.button_width - text_size.x) / 2
      text_y = button_y + (BUTTON_HEIGHT - text_size.y) / 2
      text_color = rl.Color(228, 228, 228, 255) if self.enabled else rl.Color(150, 150, 150, 255)
      rl.draw_text_ex(self._font, text, rl.Vector2(text_x, text_y), 40, 0, text_color)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    spacing = RIGHT_ITEM_PADDING
    button_y = self._rect.y + (self._rect.height - BUTTON_HEIGHT) / 2
    for i, _ in enumerate(self.buttons):
      button_x = self._rect.x + i * (self.button_width + spacing)
      button_rect = rl.Rectangle(button_x, button_y, self.button_width, BUTTON_HEIGHT)
      if rl.check_collision_point_rec(mouse_pos, button_rect):
        self.selected_button = i
        if self.callback:
          self.callback(i)


class ListItem(Widget):
  def __init__(self, title: str | Callable[[], str] = "", icon: str | None = None, description: str | Callable[[], str] | None = None,
               description_visible: bool = False, callback: Callable | None = None,
               action_item: ItemAction | None = None):
    super().__init__()
    self._title = title
    self.set_icon(icon)
    self._description = description
    self.description_visible = description_visible
    self.callback = callback
    self.description_opened_callback: Callable | None = None
    self.action_item = action_item

    self.set_rect(rl.Rectangle(0, 0, ITEM_BASE_WIDTH, ITEM_BASE_HEIGHT))
    self._font = gui_app.font(FontWeight.NORMAL)

    self._html_renderer = HtmlRenderer(text="", text_size={ElementType.P: ITEM_DESC_FONT_SIZE},
                                       text_color=ITEM_DESC_TEXT_COLOR)
    self._parse_description(self.description)

    # Cached properties for performance
    self._prev_description: str | None = self.description

  @property
  def enabled(self) -> bool:
    if self.action_item:
      return self.action_item.enabled
    return True

  def show_event(self):
    self._set_description_visible(False)

  def set_description_opened_callback(self, callback: Callable) -> None:
    self.description_opened_callback = callback

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    if self.action_item:
      self.action_item.set_touch_valid_callback(touch_callback)

  def set_parent_rect(self, parent_rect: rl.Rectangle):
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self.is_visible:
      return

    # Check not in action rect
    if self.action_item:
      action_rect = self.get_right_item_rect(self._rect)
      if rl.check_collision_point_rec(mouse_pos, action_rect):
        # Click was on right item, don't toggle description
        return

    self._set_description_visible(not self.description_visible)

  def _set_description_visible(self, visible: bool):
    if self.description and self.description_visible != visible:
      self.description_visible = visible
      # do callback first in case receiver changes description
      if self.description_visible and self.description_opened_callback is not None:
        self.description_opened_callback()
        # Call _update_state to catch any description changes
        self._update_state()

      content_width = int(self._rect.width - ITEM_PADDING * 2)
      self._rect.height = self.get_item_height(self._font, content_width)

  def _update_state(self):
    # Detect changes if description is callback
    new_description = self.description
    if new_description != self._prev_description:
      self._parse_description(new_description)

  def _render(self, _):
    if not self.is_visible:
      return

    # Don't draw items that are not in parent's viewport
    if ((self._rect.y + self.rect.height) <= self._parent_rect.y or
      self._rect.y >= (self._parent_rect.y + self._parent_rect.height)):
      return

    content_x = self._rect.x + ITEM_PADDING
    text_x = content_x

    color = ITEM_TEXT_COLOR if self.enabled else ITEM_TEXT_VALUE_COLOR
    icon_tint = rl.WHITE if self.enabled else ITEM_TEXT_VALUE_COLOR

    # Only draw title and icon for items that have them
    if self.title:
      # Draw icon if present
      if self.icon:
        rl.draw_texture(self._icon_texture, int(content_x), int(self._rect.y + (ITEM_BASE_HEIGHT - self._icon_texture.height) // 2), icon_tint)
        text_x += ICON_SIZE + ITEM_PADDING

      # Draw main text
      text_size = measure_text_cached(self._font, self.title, ITEM_TEXT_FONT_SIZE)
      item_y = self._rect.y + (ITEM_BASE_HEIGHT - text_size.y) // 2
      rl.draw_text_ex(self._font, self.title, rl.Vector2(text_x, item_y), ITEM_TEXT_FONT_SIZE, 0, color)

    # Draw description if visible
    if self.description_visible:
      content_width = int(self._rect.width - ITEM_PADDING * 2)
      description_height = self._html_renderer.get_total_height(content_width)
      description_rect = rl.Rectangle(
        self._rect.x + ITEM_PADDING,
        self._rect.y + ITEM_DESC_V_OFFSET,
        content_width,
        description_height
      )
      self._html_renderer.render(description_rect)

    # Draw right item if present
    if self.action_item:
      right_rect = self.get_right_item_rect(self._rect)
      right_rect.y = self._rect.y
      if self.action_item.render(right_rect) and self.action_item.enabled:
        # Right item was clicked/activated
        if self.callback:
          self.callback()

  def set_icon(self, icon: str | None):
    self.icon = icon
    self._icon_texture = gui_app.texture(os.path.join("icons", self.icon), ICON_SIZE, ICON_SIZE) if self.icon else None

  def set_description(self, description: str | Callable[[], str] | None):
    self._description = description

  def _parse_description(self, new_desc):
    self._html_renderer.parse_html_content(new_desc)
    self._prev_description = new_desc

  @property
  def title(self):
    return _resolve_value(self._title, "")

  @property
  def description(self):
    return _resolve_value(self._description, "")

  def get_item_height(self, font: rl.Font, max_width: int) -> float:
    if not self.is_visible:
      return 0

    height = float(ITEM_BASE_HEIGHT)
    if self.description_visible:
      description_height = self._html_renderer.get_total_height(max_width)
      height += description_height - (ITEM_BASE_HEIGHT - ITEM_DESC_V_OFFSET) + ITEM_PADDING
    return height

  def get_right_item_rect(self, item_rect: rl.Rectangle) -> rl.Rectangle:
    if not self.action_item:
      return rl.Rectangle(0, 0, 0, 0)

    right_width = self.action_item.get_width_hint()
    if right_width == 0:  # Full width action (like DualButtonAction)
      return rl.Rectangle(item_rect.x + ITEM_PADDING, item_rect.y,
                          item_rect.width - (ITEM_PADDING * 2), ITEM_BASE_HEIGHT)

    # Clip width to available space, never overlapping this Item's title
    content_width = item_rect.width - (ITEM_PADDING * 2)
    title_width = measure_text_cached(self._font, self.title, ITEM_TEXT_FONT_SIZE).x
    right_width = min(content_width - title_width, right_width)

    right_x = item_rect.x + item_rect.width - right_width
    right_y = item_rect.y
    return rl.Rectangle(right_x, right_y, right_width, ITEM_BASE_HEIGHT)


# Factory functions
def simple_item(title: str | Callable[[], str], callback: Callable | None = None) -> ListItem:
  return ListItem(title=title, callback=callback)


def toggle_item(title: str | Callable[[], str], description: str | Callable[[], str] | None = None, initial_state: bool = False,
                callback: Callable | None = None, icon: str = "", enabled: bool | Callable[[], bool] = True) -> ListItem:
  action = ToggleAction(initial_state=initial_state, enabled=enabled, callback=callback)
  return ListItem(title=title, description=description, action_item=action, icon=icon)


def button_item(title: str | Callable[[], str], button_text: str | Callable[[], str], description: str | Callable[[], str] | None = None,
                callback: Callable | None = None, enabled: bool | Callable[[], bool] = True) -> ListItem:
  action = ButtonAction(text=button_text, enabled=enabled)
  return ListItem(title=title, description=description, action_item=action, callback=callback)


def text_item(title: str | Callable[[], str], value: str | Callable[[], str], description: str | Callable[[], str] | None = None,
              callback: Callable | None = None, enabled: bool | Callable[[], bool] = True) -> ListItem:
  action = TextAction(text=value, color=ITEM_TEXT_VALUE_COLOR, enabled=enabled)
  return ListItem(title=title, description=description, action_item=action, callback=callback)


def dual_button_item(left_text: str | Callable[[], str], right_text: str | Callable[[], str], left_callback: Callable = None, right_callback: Callable = None,
                     description: str | Callable[[], str] | None = None, enabled: bool | Callable[[], bool] = True) -> ListItem:
  action = DualButtonAction(left_text, right_text, left_callback, right_callback, enabled)
  return ListItem(title="", description=description, action_item=action)


def multiple_button_item(title: str | Callable[[], str], description: str | Callable[[], str], buttons: list[str | Callable[[], str]], selected_index: int,
                         button_width: int = BUTTON_WIDTH, callback: Callable = None, icon: str = ""):
  action = MultipleButtonAction(buttons, button_width, selected_index, callback=callback)
  return ListItem(title=title, description=description, icon=icon, action_item=action)


# Copyright (c) 2019, Rick Lan
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, and/or sublicense,
# for non-commercial purposes only, subject to the following conditions:
#
# - The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
# - Commercial use (e.g. use in a product, service, or activity intended to
#   generate revenue) is prohibited without explicit written permission from
#   the copyright holder.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from abc import ABC, abstractmethod

class BaseSpinBoxAction(ItemAction, ABC):
  def __init__(self, callback: Callable | None, enabled: bool | Callable[[], bool], width: int):
    super().__init__(width=width, enabled=enabled)
    self._callback = callback

    icon_size = 60
    self._minus_icon = gui_app.texture("icons/minus.png", icon_size, icon_size)
    self._plus_icon = gui_app.texture("icons/plus.png", icon_size, icon_size)

    self._minus_button = Button("", self._on_minus, icon=self._minus_icon, button_style=ButtonStyle.LIST_ACTION, multi_touch=True)
    self._plus_button = Button("", self._on_plus, icon=self._plus_icon, button_style=ButtonStyle.LIST_ACTION, multi_touch=True)

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self._minus_button.set_touch_valid_callback(touch_callback)
    self._plus_button.set_touch_valid_callback(touch_callback)

  def _render(self, rect: rl.Rectangle) -> bool:
    is_enabled = _resolve_value(self._enabled_source, False)

    button_width = 110
    button_height = BUTTON_HEIGHT
    spacing = 10
    button_y = rect.y + (rect.height - button_height) / 2

    minus_rect = rl.Rectangle(rect.x, button_y, button_width, button_height)
    plus_rect = rl.Rectangle(rect.x + rect.width - button_width, button_y, button_width, button_height)

    label_x = rect.x + button_width + spacing
    label_width = (plus_rect.x) - (label_x) - spacing

    self._minus_button.set_enabled(is_enabled and self._get_minus_enabled())
    self._plus_button.set_enabled(is_enabled and self._get_plus_enabled())

    self._minus_button.render(minus_rect)
    self._plus_button.render(plus_rect)

    if label_width > 0:
      label_rect = rl.Rectangle(label_x, rect.y, label_width, rect.height)
      display_text = self._get_display_text()
      color = ITEM_TEXT_VALUE_COLOR if is_enabled else ITEM_DESC_TEXT_COLOR
      gui_label(label_rect, display_text, font_size=ITEM_TEXT_FONT_SIZE, color=color,
                font_weight=FontWeight.NORMAL, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)

    return False

  @abstractmethod
  def _on_minus(self):
    """Called when the minus button is pressed."""
    pass

  @abstractmethod
  def _on_plus(self):
    """Called when the plus button is pressed."""
    pass

  @abstractmethod
  def _get_minus_enabled(self) -> bool:
    """Return True if the minus button should be enabled."""
    pass

  @abstractmethod
  def _get_plus_enabled(self) -> bool:
    """Return True if the plus button should be enabled."""
    pass

  @abstractmethod
  def _get_display_text(self) -> str:
    """Return the string to display in the center."""
    pass


class SpinBoxAction(BaseSpinBoxAction):
  def __init__(self, initial_value: int, min_val: int, max_val: int, step: int = 1,
               suffix: str = "", special_value_text: str | None = None,
               callback: Callable[[int], None] | None = None, enabled: bool | Callable[[], bool] = True,
               width: int = 320):
    super().__init__(callback, enabled, width)
    self._value = initial_value
    self._min_val = min_val
    self._max_val = max_val
    self._step = step
    self._suffix = suffix
    self._special_value_text = special_value_text

  def set_value(self, value: int):
    self._value = max(self._min_val, min(self._max_val, value))

  def get_value(self) -> int:
    return self._value

  def _on_minus(self):
    new_val = max(self._min_val, self._value - self._step)
    if new_val != self._value:
      self._value = new_val
      if self._callback:
        self._callback(self._value)

  def _on_plus(self):
    new_val = min(self._max_val, self._value + self._step)
    if new_val != self._value:
      self._value = new_val
      if self._callback:
        self._callback(self._value)

  def _get_minus_enabled(self) -> bool:
    return self._value > self._min_val

  def _get_plus_enabled(self) -> bool:
    return self._value < self._max_val

  def _get_display_text(self) -> str:
    if self._special_value_text and self._value == self._min_val:
      return self._special_value_text
    return f"{self._value}{self._suffix}"


class DoubleSpinBoxAction(BaseSpinBoxAction):
  def __init__(self, initial_value: float, min_val: float, max_val: float, step: float = 0.1,
               decimals: int = 1, suffix: str = "", special_value_text: str | None = None, # <-- 1. This is correct
               callback: Callable[[float], None] | None = None, enabled: bool | Callable[[], bool] = True,
               width: int = 320):
    super().__init__(callback, enabled, width)
    self._value = initial_value
    self._min_val = min_val
    self._max_val = max_val
    self._step = step
    self._decimals = decimals
    self._suffix = suffix
    self._special_value_text = special_value_text  # <-- 2. Store the variable

  def set_value(self, value: float):
    self._value = max(self._min_val, min(self._max_val, value))

  def get_value(self) -> float:
    return self._value

  def _on_minus(self):
    new_val = max(self._min_val, self._value - self._step)
    if new_val < self._value:
      self._value = new_val
      if self._callback:
        self._callback(self._value)

  def _on_plus(self):
    new_val = min(self._max_val, self._value + self._step)
    if new_val > self._value:
      self._value = new_val
      if self._callback:
        self._callback(self._value)

  def _get_minus_enabled(self) -> bool:
    return self._value > self._min_val

  def _get_plus_enabled(self) -> bool:
    return self._value < self._max_val

  def _get_display_text(self) -> str:
    is_min_val = abs(self._value - self._min_val) < 1e-9
    if self._special_value_text and is_min_val:
      return self._special_value_text

    return f"{self._value:.{self._decimals}f}{self._suffix}"


class TextSpinBoxAction(BaseSpinBoxAction):
  def __init__(self, options: list[str], initial_index: int = 0,
               callback: Callable[[int], None] | None = None, enabled: bool | Callable[[], bool] = True,
               width: int = 320):
    super().__init__(callback, enabled, width)
    self._options = options if options else [""]
    self._current_index = max(0, min(len(self._options) - 1, initial_index))
    self._initial_index = initial_index

  def set_index(self, index: int):
    self._current_index = max(0, min(len(self._options) - 1, index))

  def get_index(self) -> int:
    return self._current_index

  def _on_minus(self):
    new_idx = max(0, self._current_index - 1)
    if new_idx != self._current_index:
      self._current_index = new_idx
      if self._callback:
        self._callback(self._current_index)

  def _on_plus(self):
    new_idx = min(len(self._options) - 1, self._current_index + 1)
    if new_idx != self._current_index:
      self._current_index = new_idx
      if self._callback:
        self._callback(self._current_index)

  def _get_minus_enabled(self) -> bool:
    return self._current_index > 0

  def _get_plus_enabled(self) -> bool:
    return self._current_index < len(self._options) - 1

  def _get_display_text(self) -> str:
    return self._options[self._current_index]


def spin_button_item(title: str | Callable[[], str], callback: Callable[[int], None] | None,
                       initial_value: int, min_val: int, max_val: int, step: int = 1,
                       suffix: str = "", special_value_text: str | None = None,
                       description: str | Callable[[], str] | None = None,
                       icon: str = "", enabled: bool | Callable[[], bool] = True,
                       width: int = 500) -> ListItem:
  """
  Creates a ListItem with a spinbox-style control (minus, value, plus).

  :param title: The main title of the list item.
  :param callback: Function to call with the new integer value when it changes.
  :param initial_value: The starting value.
  :param min_val: The minimum allowed value.
  :param max_val: The maximum allowed value.
  :param step: The increment/decrement amount on each button press.
  :param suffix: A string to append to the value (e.g., " s").
  :param special_value_text: Text to display when the value is at min_val (e.g., "Auto").
  :param description: Optional description text shown when the item is expanded.
  :param icon: Optional icon for the list item.
  :param enabled: Whether the control is enabled.
  :return: A ListItem widget.
  """
  action = SpinBoxAction(initial_value=initial_value, min_val=min_val, max_val=max_val, step=step,
                         suffix=suffix, special_value_text=special_value_text,
                         callback=callback, enabled=enabled, width=width)
  return ListItem(title=title, description=description, action_item=action, icon=icon)

def double_spin_button_item(title: str | Callable[[], str], callback: Callable[[float], None] | None,
                            initial_value: float, min_val: float, max_val: float, step: float = 0.1,
                            decimals: int = 1, suffix: str = "", special_value_text: str | None = None,
                            description: str | Callable[[], str] | None = None,
                            icon: str = "", enabled: bool | Callable[[], bool] = True,
                            width: int = 500) -> ListItem:
  """
  Creates a ListItem with a spinbox-style control for float values.

  :param decimals: Number of decimal places to display.
  :return: A ListItem widget.
  """
  action = DoubleSpinBoxAction(initial_value=initial_value, min_val=min_val, max_val=max_val, step=step,
                               decimals=decimals, suffix=suffix, special_value_text=special_value_text,
                               callback=callback, enabled=enabled, width=width)
  return ListItem(title=title, description=description, action_item=action, icon=icon)

def text_spin_button_item(title: str | Callable[[], str], callback: Callable[[int], None] | None,
                          options: list[str], initial_index: int = 0,
                          description: str | Callable[[], str] | None = None,
                          icon: str = "", enabled: bool | Callable[[], bool] = True,
                          width: int = 500) -> ListItem:
  """
  Creates a ListItem with a spinbox control for a list of text options.

  :param options: A list of strings to cycle through (e.g., ['Low', 'Mid', 'High']).
  :param initial_index: The starting index in the options list.
  :param callback: Function to call with the new *index* (int) when it changes.
  :return: A ListItem widget.
  """
  action = TextSpinBoxAction(options=options, initial_index=initial_index,
                             callback=callback, enabled=enabled, width=width)
  return ListItem(title=title, description=description, action_item=action, icon=icon)
