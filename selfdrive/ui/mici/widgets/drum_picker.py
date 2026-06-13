"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

DrumPickerDialog — iOS-style drum-roll value selector.

Layout (matches concept image):
  - Title label centred at top with a white underline
  - 5 visible values: [n-2]  [n-1]  [  N  ]  [n+1]  [n+2]
  - Centre value: large bold white, flanked by two thin vertical bars
  - Outer values fade with distance (alpha 0.35 → 0.22 → 0.10)
  - Optional unit label below centre
  - Drag left/right or tap arrows to change value; confirm on release / tap elsewhere
"""
import pyray as rl
from collections.abc import Callable

from openpilot.common.filter_simple import BounceFilter, FirstOrderFilter
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, MouseEvent
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import DialogResult
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialogBase

try:
  from openpilot.selfdrive.ui.iqpilot.theme import NeonTheme
except ImportError:
  class _FT:
    def glow(self, a=255): return rl.Color(0, 255, 245, a)
    def glow_outer(self, a=45): return rl.Color(0, 255, 245, a)
  NeonTheme = _FT()


# ── Visual constants ───────────────────────────────────────────────────────────
_CENTRE_FONT_SIZE  = 36     # fits comfortably inside the slot walls
_SIDE1_FONT_SIZE   = 30     # one step away
_SIDE2_FONT_SIZE   = 20     # two steps away
_UNIT_FONT_SIZE    = 18
_TITLE_FONT_SIZE   = 24

_CENTRE_ALPHA = 255
_SIDE1_ALPHA  = int(255 * 0.45)
_SIDE2_ALPHA  = int(255 * 0.18)

_BAR_W         = 2           # vertical separator bar width
_BAR_H_FRAC    = 0.55        # bar height as fraction of dialog height
_SLOT_W        = 90          # width of the centre slot (determines bar positions)
_SLOT_SPACING  = 115         # horizontal distance between adjacent value centres
# 1 index = 1 slot spacing in pixels — drag exactly one slot width to move one step
_DRAG_SCALE    = 1.0 / _SLOT_SPACING


class DrumPickerDialog(BigDialogBase):
  """
  Full-screen drum-roll value picker.
  Drag left/right to scroll values; releasing snaps and calls confirm_callback
  immediately (live preview) but keeps the dialog open.
  Swipe down (back gesture) to dismiss.
  """

  def __init__(self,
               title: str,
               options: list[str],
               current: str,
               unit: str = "",
               confirm_callback: Callable[[str], None] | None = None):
    super().__init__()
    assert len(options) > 0
    self._title            = title
    self._options          = options
    self._unit             = unit
    self._confirm_callback = confirm_callback

    # Current index with a smooth bounce filter for animation
    try:
      idx = options.index(current)
    except ValueError:
      idx = 0
    dt = 1 / gui_app.target_fps
    self._idx: float     = float(idx)
    self._idx_filter     = BounceFilter(float(idx), 0.06, dt, bounce=3)
    self._idx_filter.x   = float(idx)

    # Press/release zoom scale — smoothly goes 1.0 → 1.12 on touch-down,
    # back to 1.0 on release, giving a tactile "grab" feel.
    self._scale_target: float  = 1.0
    self._scale_filter         = FirstOrderFilter(1.0, 0.04, dt)

    # Drag state
    self._drag_start_x: float | None = None
    self._drag_start_idx: float      = float(idx)
    self._dragging: bool             = False

    # Pre-load fonts
    self._font_display = gui_app.font(FontWeight.DISPLAY)
    self._font_medium  = gui_app.font(FontWeight.MEDIUM)
    self._font_roman   = gui_app.font(FontWeight.ROMAN)

  # ── Helpers ────────────────────────────────────────────────────────────────

  def _current_idx(self) -> int:
    return max(0, min(round(self._idx_filter.x), len(self._options) - 1))

  def selected_value(self) -> str:
    return self._options[self._current_idx()]

  def _clamp_idx(self, v: float) -> float:
    return max(0.0, min(v, float(len(self._options) - 1)))

  # ── Input ──────────────────────────────────────────────────────────────────

  def _handle_mouse_press(self, mouse_pos: MousePos):
    super()._handle_mouse_press(mouse_pos)
    # Kill any in-progress bounce so the grab starts from exactly
    # where the value visually is right now — no jump on first drag.
    snapped = float(round(self._idx_filter.x))
    self._idx          = snapped
    self._idx_filter.x = snapped
    self._idx_filter.velocity.x = 0.0   # kill bounce velocity
    self._drag_start_x   = mouse_pos.x
    self._drag_start_idx = snapped
    self._dragging       = False
    self._scale_target   = 1.12   # zoom in on touch-down

  def _handle_mouse_event(self, mouse_event: MouseEvent):
    super()._handle_mouse_event(mouse_event)
    if self._drag_start_x is None:
      return
    delta = self._drag_start_x - mouse_event.pos.x   # drag left = higher idx
    if abs(delta) > 8:
      self._dragging = True
    if self._dragging:
      self._idx = self._clamp_idx(self._drag_start_idx + delta * _DRAG_SCALE)
      self._idx_filter.x = self._idx   # snap immediately while dragging

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    # Swipe-down = dismiss, calling callback with final value first
    if self._swiping_away:
      self._idx = float(round(self._idx_filter.x))
      if self._confirm_callback:
        self._confirm_callback(self.selected_value())
      self._drag_start_x = None
      self._dragging     = False
      self._ret = DialogResult.CONFIRM
      return
    # Normal release: set the snap target and let BounceFilter glide there.
    # Do NOT hard-set _idx_filter.x — that would teleport instead of animate.
    self._idx          = float(round(self._idx_filter.x))
    self._drag_start_x = None
    self._dragging     = False
    self._scale_target = 1.0   # zoom back out on release
    if self._confirm_callback:
      self._confirm_callback(self.selected_value())

  # ── Update ─────────────────────────────────────────────────────────────────

  def _update_state(self):
    super()._update_state()
    # While dragging, filter is slaved directly to _idx (instant follow).
    # On release, _dragging=False so filter animates toward _idx with bounce.
    if self._dragging:
      self._idx_filter.x = self._idx
      self._idx_filter.velocity.x = 0.0
    else:
      self._idx_filter.update(self._idx)
    self._scale_filter.update(self._scale_target)

  # ── Render ─────────────────────────────────────────────────────────────────

  def _render(self, _) -> DialogResult:
    rect   = self._rect
    cx     = rect.x + rect.width  / 2
    cy     = rect.y + rect.height / 2

    # ── Dark background ───────────────────────────────────────────────────────
    rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height),
                      rl.Color(0, 0, 0, 230))

    # ── Vertical separator bars (drawn first so title renders above) ──────────
    bar_h   = int(rect.height * _BAR_H_FRAC)
    bar_y   = int(cy - bar_h / 2)
    bar_col = NeonTheme.glow(60)
    rl.draw_rectangle(int(cx - _SLOT_W / 2), bar_y, _BAR_W, bar_h, bar_col)
    rl.draw_rectangle(int(cx + _SLOT_W / 2), bar_y, _BAR_W, bar_h, bar_col)

    # ── Title — centred above the bars, no underline ──────────────────────────
    title_w = int(measure_text_cached(self._font_medium, self._title, _TITLE_FONT_SIZE).x)
    tx = int(cx - title_w / 2)
    ty = int(rect.y + (bar_y - rect.y) / 2 - _TITLE_FONT_SIZE / 2)
    rl.draw_text_ex(self._font_medium, self._title,
                    rl.Vector2(tx, ty), _TITLE_FONT_SIZE, 0,
                    rl.Color(255, 255, 255, 220))

    # ── Value row ─────────────────────────────────────────────────────────────
    animated_idx = self._idx_filter.x
    n            = len(self._options)

    # centre_int is always the settled target — never flips mid-animation.
    # frac drives pixel offset only (how far filter still needs to travel).
    centre_int = int(self._idx)
    frac       = animated_idx - centre_int

    for offset in [-2, -1, 0, 1, 2]:
      # Which option index lives in this visual slot?
      opt_idx = centre_int + offset
      if opt_idx < 0 or opt_idx >= n:
        continue

      # Pixel offset from screen centre: slot position minus fractional drift
      draw_x_off = (offset - frac) * _SLOT_SPACING

      label      = self._options[opt_idx]
      abs_offset = abs(offset - frac)   # fractional distance from visual centre

      # Font size and alpha interpolated by distance
      if abs_offset < 0.5:
        font_sz = int(_SIDE1_FONT_SIZE + (_CENTRE_FONT_SIZE - _SIDE1_FONT_SIZE) * (1 - abs_offset * 2))
        alpha   = int(_SIDE1_ALPHA + (_CENTRE_ALPHA - _SIDE1_ALPHA) * (1 - abs_offset * 2))
        weight  = FontWeight.DISPLAY
      elif abs_offset < 1.5:
        t       = abs_offset - 0.5
        font_sz = int(_SIDE2_FONT_SIZE + (_SIDE1_FONT_SIZE - _SIDE2_FONT_SIZE) * (1 - t))
        alpha   = int(_SIDE2_ALPHA + (_SIDE1_ALPHA - _SIDE2_ALPHA) * (1 - t))
        weight  = FontWeight.DISPLAY
      else:
        font_sz = _SIDE2_FONT_SIZE
        alpha   = _SIDE2_ALPHA
        weight  = FontWeight.DISPLAY

      # Apply press-zoom scale to the centre value only
      scale  = 1.0 + (self._scale_filter.x - 1.0) * max(0.0, 1.0 - abs_offset * 2)
      font_sz = max(8, int(font_sz * scale))

      font   = gui_app.font(weight)
      tw     = int(measure_text_cached(font, label, font_sz).x)
      th     = font_sz
      draw_x = int(cx + draw_x_off - tw / 2)
      draw_y = int(cy - th / 2)

      rl.draw_text_ex(font, label,
                      rl.Vector2(draw_x, draw_y),
                      font_sz, 0,
                      rl.Color(255, 255, 255, alpha))

    # ── Unit label below centre ───────────────────────────────────────────────
    if self._unit:
      uw = int(measure_text_cached(self._font_roman, self._unit, _UNIT_FONT_SIZE).x)
      rl.draw_text_ex(self._font_roman, self._unit,
                      rl.Vector2(int(cx - uw / 2), int(cy + _CENTRE_FONT_SIZE / 2 + 8)),
                      _UNIT_FONT_SIZE, 0,
                      rl.Color(255, 255, 255, 140))

    # ── Subtle neon glow on centre slot ───────────────────────────────────────
    slot_rect = rl.Rectangle(cx - _SLOT_W / 2 - 1, bar_y, _SLOT_W + 2, bar_h)
    rl.draw_rectangle_gradient_h(
      int(slot_rect.x), int(slot_rect.y),
      int(slot_rect.width // 2), int(slot_rect.height),
      rl.BLANK, NeonTheme.glow_outer(40),
    )
    rl.draw_rectangle_gradient_h(
      int(slot_rect.x + slot_rect.width // 2), int(slot_rect.y),
      int(slot_rect.width // 2), int(slot_rect.height),
      NeonTheme.glow_outer(40), rl.BLANK,
    )

    return self._ret
