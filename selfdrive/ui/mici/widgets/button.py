import math
import time
import pyray as rl
from typing import Union
from enum import Enum
from collections.abc import Callable
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import MiciLabel
from openpilot.system.ui.widgets.scroller import DO_ZOOM
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.common.filter_simple import BounceFilter

try:
  from openpilot.common.params import Params
except ImportError:
  Params = None

try:
  from openpilot.selfdrive.ui.iqpilot.theme import NeonTheme
except ImportError:
  # Fallback theme if iqpilot layer not available
  class _FallbackTheme:
    def glow(self, alpha=255): return rl.Color(0, 255, 245, alpha)
    def glow_mid(self, alpha=130): return rl.Color(0, 255, 245, alpha)
    def glow_outer(self, alpha=45): return rl.Color(0, 255, 245, alpha)
    def bg(self): return rl.Color(0, 26, 25, 255)
    def bg_pressed(self): return rl.Color(0, 33, 32, 255)
  NeonTheme = _FallbackTheme()

SCROLLING_SPEED_PX_S = 50
COMPLICATION_SIZE    = 36
LABEL_COLOR          = rl.Color(255, 255, 255, int(255 * 0.9))
LABEL_HORIZONTAL_PADDING = 40
COMPLICATION_GREY    = rl.Color(0xAA, 0xAA, 0xAA, 255)
PRESSED_SCALE = 1.15 if DO_ZOOM else 1.07


class ScrollState(Enum):
  PRE_SCROLL = 0
  SCROLLING = 1
  POST_SCROLL = 2


class BigCircleButton(Widget):
  def __init__(self, icon: str, red: bool = False, icon_size: tuple[int, int] = (64, 53), icon_offset: tuple[int, int] = (0, 0)):
    super().__init__()
    self._red = red
    self._icon_offset = icon_offset

    # State
    self.set_rect(rl.Rectangle(0, 0, 180, 180))
    self._press_state_enabled = True
    self._scale_filter = BounceFilter(1.0, 0.1, 1 / gui_app.target_fps)

    # Icons
    self._txt_icon = gui_app.texture(icon, *icon_size)
    self._txt_btn_disabled_bg = gui_app.texture("icons_mici/buttons/button_circle_disabled.png", 180, 180)

    self._txt_btn_bg = gui_app.texture("icons_mici/buttons/button_circle.png", 180, 180)
    self._txt_btn_pressed_bg = gui_app.texture("icons_mici/buttons/button_circle_hover.png", 180, 180)

    self._txt_btn_red_bg = gui_app.texture("icons_mici/buttons/button_circle_red.png", 180, 180)
    self._txt_btn_red_pressed_bg = gui_app.texture("icons_mici/buttons/button_circle_red_hover.png", 180, 180)

  def set_enable_pressed_state(self, pressed: bool):
    self._press_state_enabled = pressed

  def _render(self, _):
    # draw background
    txt_bg = self._txt_btn_bg if not self._red else self._txt_btn_red_bg
    if not self.enabled:
      txt_bg = self._txt_btn_disabled_bg
    elif self.is_pressed and self._press_state_enabled:
      txt_bg = self._txt_btn_pressed_bg if not self._red else self._txt_btn_red_pressed_bg

    scale = self._scale_filter.update(PRESSED_SCALE if self.is_pressed and self._press_state_enabled else 1.0)
    btn_x = self._rect.x + (self._rect.width * (1 - scale)) / 2
    btn_y = self._rect.y + (self._rect.height * (1 - scale)) / 2
    rl.draw_texture_ex(txt_bg, (btn_x, btn_y), 0, scale, rl.WHITE)

    # draw icon
    icon_color = rl.WHITE if self.enabled else rl.Color(255, 255, 255, int(255 * 0.35))
    rl.draw_texture(self._txt_icon, int(self._rect.x + (self._rect.width - self._txt_icon.width) / 2 + self._icon_offset[0]),
                    int(self._rect.y + (self._rect.height - self._txt_icon.height) / 2 + self._icon_offset[1]), icon_color)


class BigCircleToggle(BigCircleButton):
  def __init__(self, icon: str, toggle_callback: Callable | None = None, icon_size: tuple[int, int] = (64, 53), icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, False, icon_size=icon_size, icon_offset=icon_offset)
    self._toggle_callback = toggle_callback

    # State
    self._checked = False

    # Icons
    self._txt_toggle_enabled = gui_app.texture("icons_mici/buttons/toggle_dot_enabled.png", 66, 66)
    self._txt_toggle_disabled = gui_app.texture("icons_mici/buttons/toggle_dot_disabled.png", 66, 66)

  def set_checked(self, checked: bool):
    self._checked = checked

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    self._checked = not self._checked
    if self._toggle_callback:
      self._toggle_callback(self._checked)

  def _render(self, _):
    super()._render(_)

    # draw status icon
    rl.draw_texture(self._txt_toggle_enabled if self._checked else self._txt_toggle_disabled,
                    int(self._rect.x + (self._rect.width - self._txt_toggle_enabled.width) / 2),
                    int(self._rect.y + 5), rl.WHITE)


class BigButton(Widget):
  """A lightweight stand-in for the Qt BigButton, drawn & updated each frame."""

  def __init__(self, text: str, value: str = "", icon: Union[str, rl.Texture] = "", icon_size: tuple[int, int] = (64, 64)):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 402, 180))
    self.text = text
    self.value = value
    self._icon_size = icon_size
    self.set_icon(icon)

    self._scale_filter = BounceFilter(1.0, 0.1, 1 / gui_app.target_fps)

    self._rotate_icon_t: float | None = None

    self._label_font = gui_app.font(FontWeight.DISPLAY)
    self._value_font = gui_app.font(FontWeight.ROMAN)

    self._label = MiciLabel(text, font_size=self._get_label_font_size(), width=int(self._rect.width - LABEL_HORIZONTAL_PADDING * 2),
                            font_weight=FontWeight.DISPLAY, color=LABEL_COLOR,
                            alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM, wrap_text=True)
    self._sub_label = MiciLabel(value, font_size=COMPLICATION_SIZE, width=int(self._rect.width - LABEL_HORIZONTAL_PADDING * 2),
                                font_weight=FontWeight.ROMAN, color=COMPLICATION_GREY,
                                alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM, wrap_text=True)

    self._load_images()

    # internal state
    self._scroll_offset = 0       # in pixels
    self._needs_scroll = measure_text_cached(self._label_font, text, self._get_label_font_size()).x + 25 > self._rect.width
    self._scroll_timer = 0
    self._scroll_state = ScrollState.PRE_SCROLL

  def set_icon(self, icon: Union[str, rl.Texture]):
    self._txt_icon = gui_app.texture(icon, *self._icon_size) if isinstance(icon, str) and len(icon) else icon

  def set_rotate_icon(self, rotate: bool):
    if rotate and self._rotate_icon_t is not None:
      return
    self._rotate_icon_t = rl.get_time() if rotate else None

  def _load_images(self):
    self._txt_default_bg = gui_app.texture("icons_mici/buttons/button_rectangle.png", 402, 180)
    self._txt_pressed_bg = gui_app.texture("icons_mici/buttons/button_rectangle_pressed.png", 402, 180)
    self._txt_disabled_bg = gui_app.texture("icons_mici/buttons/button_rectangle_disabled.png", 402, 180)
    self._txt_hover_bg = gui_app.texture("icons_mici/buttons/button_rectangle_hover.png", 402, 180)

  def _get_label_font_size(self):
    if len(self.text) < 12:
      font_size = 64
    elif len(self.text) < 17:
      font_size = 48
    elif len(self.text) < 20:
      font_size = 42
    else:
      font_size = 36

    if self.value:
      font_size -= 20

    return font_size

  def set_text(self, text: str):
    self.text = text
    self._label.set_text(text)

  def set_value(self, value: str):
    self.value = value
    self._sub_label.set_text(value)

  def get_value(self) -> str:
    return self.value

  def get_text(self):
    return self.text

  def _update_state(self):
    # hold on text for a bit, scroll, hold again, reset
    if self._needs_scroll:
      """`dt` should be seconds since last frame (rl.get_frame_time())."""
      # TODO: this comment is generated by GPT, prob wrong and misused
      dt = rl.get_frame_time()

      self._scroll_timer += dt
      if self._scroll_state == ScrollState.PRE_SCROLL:
        if self._scroll_timer < 0.5:
          return
        self._scroll_state = ScrollState.SCROLLING
        self._scroll_timer = 0

      elif self._scroll_state == ScrollState.SCROLLING:
        self._scroll_offset -= SCROLLING_SPEED_PX_S * dt
        # reset when text has completely left the button + 50 px gap
        # TODO: use global constant for 30+30 px gap
        # TODO: add std Widget padding option integrated into the self._rect
        full_len = measure_text_cached(self._label_font, self.text, self._get_label_font_size()).x + 30 + 30
        if self._scroll_offset < (self._rect.width - full_len):
          self._scroll_state = ScrollState.POST_SCROLL
          self._scroll_timer = 0

      elif self._scroll_state == ScrollState.POST_SCROLL:
        # wait for a bit before starting to scroll again
        if self._scroll_timer < 0.75:
          return
        self._scroll_state = ScrollState.PRE_SCROLL
        self._scroll_timer = 0
        self._scroll_offset = 0

  def _render(self, _):
    # draw _txt_default_bg
    txt_bg = self._txt_default_bg
    if not self.enabled:
      txt_bg = self._txt_disabled_bg
    elif self.is_pressed:
      txt_bg = self._txt_hover_bg

    scale = self._scale_filter.update(PRESSED_SCALE if self.is_pressed else 1.0)
    btn_x = self._rect.x + (self._rect.width * (1 - scale)) / 2
    btn_y = self._rect.y + (self._rect.height * (1 - scale)) / 2
    rl.draw_texture_ex(txt_bg, (btn_x, btn_y), 0, scale, rl.WHITE)

    # LABEL ------------------------------------------------------------------
    lx = self._rect.x + LABEL_HORIZONTAL_PADDING
    ly = btn_y + self._rect.height - 33  # - 40# - self._get_label_font_size() / 2

    if self.value:
      self._sub_label.set_position(lx, ly)
      ly -= self._sub_label.font_size + 9
      self._sub_label.render()

    label_color = LABEL_COLOR if self.enabled else rl.Color(255, 255, 255, int(255 * 0.35))
    self._label.set_color(label_color)
    self._label.set_position(lx, ly)
    self._label.render()

    # ICON -------------------------------------------------------------------
    if self._txt_icon:
      rotation = 0
      if self._rotate_icon_t is not None:
        rotation = (rl.get_time() - self._rotate_icon_t) * 180

      # drop top right with 30px padding
      x = self._rect.x + self._rect.width - 30 - self._txt_icon.width / 2
      y = self._rect.y + 30 + self._txt_icon.height / 2
      source_rec = rl.Rectangle(0, 0, self._txt_icon.width, self._txt_icon.height)
      dest_rec = rl.Rectangle(int(x), int(y), self._txt_icon.width, self._txt_icon.height)
      origin = rl.Vector2(self._txt_icon.width / 2, self._txt_icon.height / 2)
      rl.draw_texture_pro(self._txt_icon, source_rec, dest_rec, origin, rotation, rl.WHITE)


class BigToggle(BigButton):
  def __init__(self, text: str, value: str = "", initial_state: bool = False, toggle_callback: Callable | None = None):
    super().__init__(text, value, "")
    self._checked = initial_state
    self._toggle_callback = toggle_callback

    self._label.set_font_size(48)

  def _load_images(self):
    super()._load_images()
    self._txt_enabled_toggle = gui_app.texture("icons_mici/buttons/toggle_pill_enabled.png", 84, 66)
    self._txt_disabled_toggle = gui_app.texture("icons_mici/buttons/toggle_pill_disabled.png", 84, 66)

  def set_checked(self, checked: bool):
    self._checked = checked

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self._checked = not self._checked
    if self._toggle_callback:
      self._toggle_callback(self._checked)

  def _draw_pill(self, x: float, y: float, checked: bool):
    # draw toggle icon top right
    if checked:
      rl.draw_texture(self._txt_enabled_toggle, int(x), int(y), rl.WHITE)
    else:
      rl.draw_texture(self._txt_disabled_toggle, int(x), int(y), rl.WHITE)

  def _render(self, _):
    super()._render(_)

    x = self._rect.x + self._rect.width - self._txt_enabled_toggle.width
    y = self._rect.y
    self._draw_pill(x, y, self._checked)


class BigMultiToggle(BigToggle):
  def __init__(self, text: str, options: list[str], toggle_callback: Callable | None = None,
               select_callback: Callable | None = None):
    super().__init__(text, "", toggle_callback=toggle_callback)
    assert len(options) > 0
    self._options = options
    self._select_callback = select_callback

    self._label.set_width(int(self._rect.width - LABEL_HORIZONTAL_PADDING * 2 - self._txt_enabled_toggle.width))
    # TODO: why isn't this automatic?
    self._label.set_font_size(self._get_label_font_size())

    self.set_value(self._options[0])

  def _get_label_font_size(self):
    font_size = super()._get_label_font_size()
    return font_size - 6

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    cur_idx = self._options.index(self.value)
    new_idx = (cur_idx + 1) % len(self._options)
    self.set_value(self._options[new_idx])
    if self._select_callback:
      self._select_callback(self.value)

  def _render(self, _):
    BigButton._render(self, _)

    checked_idx = self._options.index(self.value)

    x = self._rect.x + self._rect.width - self._txt_enabled_toggle.width
    y = self._rect.y

    for i in range(len(self._options)):
      self._draw_pill(x, y, checked_idx == i)
      y += 35


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
    self._params.put_nonblocking(self._param, new_idx)


class BigParamControl(BigToggle):
  def __init__(self, text: str, param: str, toggle_callback: Callable | None = None):
    super().__init__(text, "", toggle_callback=toggle_callback)
    self.param = param
    self.params = Params()
    self.set_checked(self.params.get_bool(self.param, False))

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self.params.put_bool(self.param, self._checked)

  def refresh(self):
    self.set_checked(self.params.get_bool(self.param, False))


# TODO: param control base class
class BigCircleParamControl(BigCircleToggle):
  def __init__(self, icon: str, param: str, toggle_callback: Callable | None = None, icon_size: tuple[int, int] = (64, 53),
               icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, toggle_callback, icon_size=icon_size, icon_offset=icon_offset)
    self._param = param
    self.params = Params()
    self.set_checked(self.params.get_bool(self._param, False))

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self.params.put_bool(self._param, self._checked)

  def refresh(self):
    self.set_checked(self.params.get_bool(self._param, False))


_CHIP_BG         = rl.Color(0x30, 0x30, 0x30, 230)
_CHIP_TEXT_COLOR = rl.Color(0xDD, 0xDD, 0xDD, 255)
_CHIP_H          = 28
_CHIP_FONT_SIZE  = 18
_CHIP_H_PAD      = 10
_CHIP_V_PAD      = 5
_CHIP_RADIUS     = 0.5
_CHIP_SPACING    = 8
_NEON_CORNER_ROUND = 0.28
_NEON_CARD_PAD     = 18


def _draw_neon_glow_halo(rect: rl.Rectangle, intensity: float = 1.0):
  segs      = 8
  roundness = _NEON_CORNER_ROUND
  for expand, alpha in [
    (14, int(18  * intensity)),
    (12, int(28  * intensity)),
    (10, int(40  * intensity)),
    (8,  int(55  * intensity)),
    (6,  int(72  * intensity)),
    (4,  int(95  * intensity)),
    (2,  int(120 * intensity)),
  ]:
    ex = rl.Rectangle(
      rect.x - expand, rect.y - expand,
      rect.width + expand * 2, rect.height + expand * 2,
    )
    rl.draw_rectangle_rounded(ex, roundness, segs, NeonTheme.glow_outer(alpha))


def _draw_neon_glow_border(rect: rl.Rectangle, intensity: float = 1.0):
  segs      = 8
  roundness = _NEON_CORNER_ROUND
  rl.draw_rectangle_rounded_lines_ex(rect, roundness, segs, 2.5,
                                     NeonTheme.glow(int(255 * intensity)))
  rl.draw_rectangle_rounded_lines_ex(rect, roundness, segs, 1.0,
                                     rl.Color(255, 255, 255, int(180 * intensity)))


def _neon_title_font_size(text: str, has_chips: bool) -> int:
  if len(text) < 10:
    size = 52
  elif len(text) < 14:
    size = 42
  elif len(text) < 18:
    size = 36
  else:
    size = 30
  if has_chips:
    size = min(size, 36)
  return size


class NeonBigButton(Widget):

  CARD_W = 310
  CARD_H = 160

  def __init__(self, title: str, chips: list[str] | None = None,
               click_callback: Callable | None = None):
    super().__init__()
    self._title_text       = title
    self._chips: list[str] = chips or []
    self._click_callback   = click_callback
    self._born: float      = time.monotonic()

    self.set_rect(rl.Rectangle(0, 0, self.CARD_W, self.CARD_H))

    self._label = MiciLabel(
      title,
      font_size=_neon_title_font_size(title, bool(chips)),
      width=self.CARD_W - _NEON_CARD_PAD * 2,
      font_weight=FontWeight.DISPLAY,
      color=LABEL_COLOR,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
      wrap_text=True,
      elide_right=False,
    )
    self._chip_font = gui_app.font(FontWeight.MEDIUM)

  def set_chips(self, chips: list[str]):
    self._chips = chips
    # Re-size title now that we know if chips are present
    self._label.set_font_size(_neon_title_font_size(self._title_text, bool(chips)))

  def set_click_callback(self, cb: Callable | None):
    self._click_callback = cb

  def _glow_intensity(self) -> float:
    t = time.monotonic() - self._born
    return 0.65 + 0.35 * (0.5 + 0.5 * math.sin(t * 5.0))

  def _render_chips(self, start_x: float, start_y: float):
    x = start_x
    for chip in self._chips:
      text_w = int(measure_text_cached(self._chip_font, chip, _CHIP_FONT_SIZE).x)
      w      = text_w + _CHIP_H_PAD * 2
      rl.draw_rectangle_rounded(rl.Rectangle(x, start_y, w, _CHIP_H),
                                 _CHIP_RADIUS, 4, _CHIP_BG)
      text_y = start_y + (_CHIP_H - _CHIP_FONT_SIZE) // 2
      rl.draw_text_ex(
        self._chip_font,
        chip,
        rl.Vector2(x + _CHIP_H_PAD, text_y),
        _CHIP_FONT_SIZE,
        0,
        _CHIP_TEXT_COLOR,
      )
      x += w + _CHIP_SPACING

  def _render(self, rect: rl.Rectangle) -> None:
    intensity = self._glow_intensity()
    _draw_neon_glow_halo(rect, intensity)
    bg = NeonTheme.bg_pressed() if self.is_pressed else NeonTheme.bg()
    rl.draw_rectangle_rounded(rect, _NEON_CORNER_ROUND, 6, bg)
    _draw_neon_glow_border(rect, intensity)
    chips_h  = (_CHIP_H + 6) if self._chips else 0
    title_rect = rl.Rectangle(
      rect.x + _NEON_CARD_PAD,
      rect.y + _NEON_CARD_PAD,
      rect.width - _NEON_CARD_PAD * 2,
      rect.height - _NEON_CARD_PAD - chips_h,
    )
    label_color = LABEL_COLOR if self.enabled else rl.Color(255, 255, 255, int(255 * 0.35))
    self._label.set_color(label_color)
    self._label.render(title_rect)
    if self._chips:
      chip_y = rect.y + rect.height - _CHIP_H - _NEON_CARD_PAD // 2
      self._render_chips(rect.x + _NEON_CARD_PAD, chip_y)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._click_callback:
      self._click_callback()


class NeonBigParamToggle(NeonBigButton):
  def __init__(self, title: str, param: str,
               sub_chips: list[str] | None = None,
               toggle_callback: Callable | None = None):
    super().__init__(title, chips=["disabled"])  # pre-set so layout reserves chip space
    self._param                = param
    self._params               = Params() if Params else None
    self._sub_chips: list[str] = sub_chips or []
    self._toggle_callback      = toggle_callback
    self._checked: bool        = False

    self._load_value()
    self._rebuild_chips()

  def set_sub_chips(self, sub_chips: list[str]):
    self._sub_chips = sub_chips
    self._rebuild_chips()

  def _load_value(self):
    if self._params:
      self._checked = self._params.get_bool(self._param, False)

  def _rebuild_chips(self):
    state = "enabled" if self._checked else "disabled"
    self.set_chips([state] + self._sub_chips)

  def _glow_intensity(self) -> float:
    return super()._glow_intensity() if self._checked else 0.25

  def _render(self, rect: rl.Rectangle) -> None:
    super()._render(rect)
    if not self._checked:
      rl.draw_rectangle_rounded(rect, _NEON_CORNER_ROUND, 6, rl.Color(0, 0, 0, 120))

  def _handle_mouse_release(self, mouse_pos: MousePos):
    self._checked = not self._checked
    if self._params:
      self._params.put_bool(self._param, self._checked)
    self._rebuild_chips()
    if self._toggle_callback:
      self._toggle_callback(self._checked)

  def refresh(self):
    self._load_value()
    self._rebuild_chips()


class NeonBigCircleParamControl(BigCircleParamControl):
  def __init__(self, icon: str, param: str,
               toggle_callback: Callable | None = None,
               icon_size: tuple[int, int] = (64, 53),
               icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, param, toggle_callback=toggle_callback,
                     icon_size=icon_size, icon_offset=icon_offset)
    self._born = time.monotonic()

  def _glow_intensity(self) -> float:
    if not self._checked:
      return 0.25
    t = time.monotonic() - self._born
    return 0.65 + 0.35 * (0.5 + 0.5 * math.sin(t * 5.0))

  def _render(self, rect: rl.Rectangle):
    intensity = self._glow_intensity()
    roundness = 1.0
    segs      = 12

    for expand, alpha in [
      (12, int(14  * intensity)),
      (10, int(22  * intensity)),
      (8,  int(35  * intensity)),
      (6,  int(50  * intensity)),
      (4,  int(70  * intensity)),
      (2,  int(95  * intensity)),
    ]:
      ex = rl.Rectangle(rect.x - expand, rect.y - expand,
                        rect.width + expand * 2, rect.height + expand * 2)
      rl.draw_rectangle_rounded(ex, roundness, segs, NeonTheme.glow_outer(alpha))
    super()._render(rect)
    rl.draw_rectangle_rounded_lines_ex(rect, roundness, segs, 2.5,
                                       NeonTheme.glow(int(255 * intensity)))
    rl.draw_rectangle_rounded_lines_ex(rect, roundness, segs, 1.0,
                                       rl.Color(255, 255, 255, int(160 * intensity)))

class NeonBigMultiToggle(NeonBigButton):
  def __init__(self, title: str, options: list[str],
               select_callback: Callable | None = None):
    assert len(options) > 0
    super().__init__(title, chips=[options[0]])
    self._options         = options
    self._value           = options[0]
    self._select_callback = select_callback

  def set_value(self, value: str):
    if value in self._options:
      self._value = value
    else:
      self._value = self._options[0]
    self.set_chips([self._value])

  def get_value(self) -> str:
    return self._value

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    idx = self._options.index(self._value)
    self._value = self._options[(idx + 1) % len(self._options)]
    self.set_chips([self._value])
    if self._select_callback:
      self._select_callback(self._value)


class NeonBigMultiParamToggle(NeonBigMultiToggle):

  def __init__(self, title: str, param: str, options: list[str],
               select_callback: Callable | None = None):
    super().__init__(title, options, select_callback)
    self._param  = param
    self._params = Params() if Params else None
    self._load_value()

  def _load_value(self):
    if self._params:
      try:
        idx = int(self._params.get(self._param) or 0)
        idx = max(0, min(idx, len(self._options) - 1))
      except (TypeError, ValueError):
        idx = 0
      self.set_value(self._options[idx])

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    idx = self._options.index(self._value)
    if self._params:
      self._params.put_nonblocking(self._param, idx)

  def refresh(self):
    self._load_value()


class NeonMappedParamToggle(NeonBigMultiToggle):
  def __init__(self, title: str, param: str, options: list[str], values: list[int],
               select_callback: Callable | None = None):
    super().__init__(title, options, select_callback)
    assert len(options) == len(values)
    self._param  = param
    self._values = values
    self._params = Params() if Params else None
    self._load_value()

  def _load_value(self):
    if self._params:
      try:
        current = int(self._params.get(self._param, return_default=True) or 0)
        idx = self._values.index(current)
      except (TypeError, ValueError):
        idx = 0
      self.set_value(self._options[idx])

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    idx = self._options.index(self._value)
    if self._params:
      self._params.put_nonblocking(self._param, self._values[idx])

  def refresh(self):
    self._load_value()


class NeonFloatMappedParamToggle(NeonBigMultiToggle):

  def __init__(self, title: str, param: str, options: list[str], values: list[float],
               select_callback: Callable | None = None):
    super().__init__(title, options, select_callback)
    assert len(options) == len(values)
    self._param  = param
    self._values = values
    self._params = Params() if Params else None
    self._load_value()

  def _load_value(self):
    if self._params:
      try:
        current_val = float(self._params.get(self._param, return_default=True) or 0)
        idx = min(range(len(self._values)), key=lambda i: abs(self._values[i] - current_val))
      except (TypeError, ValueError):
        idx = 1 if len(self._values) > 1 else 0
      self.set_value(self._options[idx])

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    idx = self._options.index(self._value)
    if self._params:
      self._params.put_nonblocking(self._param, str(self._values[idx]))

  def refresh(self):
    self._load_value()



class DrumPickerButton(NeonBigButton):
  def __init__(self, title: str, options: list[str]):
    super().__init__(title, chips=[""])
    self._options = options

  def _read_current(self) -> str:
    raise NotImplementedError

  def _write_value(self, value: str):
    raise NotImplementedError

  def refresh(self):
    self.set_chips([self._read_current()])

  def _on_picked(self, value: str):
    self._write_value(value)
    self.set_chips([value])

  def _handle_mouse_release(self, mouse_pos: MousePos):
    # Bypass NeonBigButton cycle — open drum picker instead
    Widget._handle_mouse_release(self, mouse_pos)
    if getattr(self, '_swiping_away', False):
      return
    from openpilot.selfdrive.ui.mici.widgets.drum_picker import DrumPickerDialog
    from openpilot.system.ui.lib.application import gui_app as _app
    dlg = DrumPickerDialog(
      title=self._title_text.lower(),
      options=self._options,
      current=self._read_current(),
      confirm_callback=self._on_picked,
    )
    _app.set_modal_overlay(dlg)


class DrumParamButton(DrumPickerButton):
  def __init__(self, title: str, param: str, options: list[str]):
    self._param  = param
    self._params = Params() if Params else None
    super().__init__(title, options)
    self.refresh()

  def _read_current(self) -> str:
    try:
      idx = int(self._params.get(self._param, return_default=True) or 0)
      idx = max(0, min(idx, len(self._options) - 1))
    except (TypeError, ValueError):
      idx = 0
    return self._options[idx]

  def _write_value(self, value: str):
    if value in self._options and self._params:
      self._params.put_nonblocking(self._param, self._options.index(value))


class DrumMappedParamButton(DrumPickerButton):
  def __init__(self, title: str, param: str, options: list[str], values: list[int]):
    assert len(options) == len(values)
    self._param  = param
    self._values = values
    self._params = Params() if Params else None
    super().__init__(title, options)
    self.refresh()

  def _read_current(self) -> str:
    try:
      raw = int(self._params.get(self._param, return_default=True) or 0)
      idx = min(range(len(self._values)), key=lambda i: abs(self._values[i] - raw))
    except (TypeError, ValueError):
      idx = 0
    return self._options[idx]

  def _write_value(self, value: str):
    if value in self._options and self._params:
      idx = self._options.index(value)
      self._params.put_nonblocking(self._param, int(self._values[idx]))


class DrumFloatMappedParamButton(DrumPickerButton):
  def __init__(self, title: str, param: str, options: list[str], values: list[float]):
    assert len(options) == len(values)
    self._param  = param
    self._values = values
    self._params = Params() if Params else None
    super().__init__(title, options)
    self.refresh()

  def _read_current(self) -> str:
    try:
      raw = float(self._params.get(self._param, return_default=True) or 0)
      idx = min(range(len(self._values)), key=lambda i: abs(self._values[i] - raw))
    except (TypeError, ValueError):
      idx = 0
    return self._options[idx]

  def _write_value(self, value: str):
    if value in self._options and self._params:
      idx = self._options.index(value)
      self._params.put_nonblocking(self._param, float(self._values[idx]))
