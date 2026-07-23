import pyray as rl
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from openpilot.common.params import Params
from openpilot.iqpilot.ui.layouts.settings.iq_panels import IQSettingsLayout
from openpilot.selfdrive.ui.layouts.home import _format_updater_description
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets.screen_header import ScreenHeader, HEADER_HEIGHT, BACK_BTN_SIZE
from openpilot.system.ui.lib.application import gui_app, FontWeight, MouseEvent, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.label import UnifiedLabel

# iOS-style swipe-from-the-left-edge-to-go-back, for panel -> grid only (the one place
# this layout already has a from/to slide transition to reuse for the live drag).
EDGE_SWIPE_ZONE = 80           # px from the left edge a swipe-back touch must start within
EDGE_SWIPE_ARM_DISTANCE = 8    # px of rightward movement before we commit to "this is a swipe"
EDGE_SWIPE_BLOCK_VERTICAL = 60  # px of vertical movement (while still under arm distance) that cancels it
EDGE_SWIPE_COMPLETE_FRACTION = 0.3  # fraction of screen width dragged to complete the pop on release
SWIPE_SETTLE_SECONDS = 0.16         # glide from the release point to done/cancelled (no snap)

MARGIN = 40
SPACING = 25
COLUMNS = 3
PILL_GAP = 24
PILL_MIN_HEIGHT = 150
BUBBLE_SIZE = 86
BUBBLE_RED = rl.Color(226, 60, 52, 255)
BUBBLE_RED_PRESSED = rl.Color(245, 92, 82, 255)
BUBBLE_GREY = rl.Color(70, 72, 78, 255)
BUBBLE_GREY_PRESSED = rl.Color(95, 98, 106, 255)
BUBBLE_TEAL = rl.Color(16, 185, 169, 255)
BUBBLE_TEAL_PRESSED = rl.Color(22, 210, 192, 255)
SETTINGS_TRANSITION_SECONDS = 0.28
TRANSITION_SURFACE_OVERSCAN = 4
TRANSITION_SURFACE_BG = rl.Color(10, 10, 10, 255)


class MenuTransitionState(Enum):
  IDLE = auto()
  PUSHING = auto()
  POPPING = auto()


@dataclass
class MenuTransition:
  state: MenuTransitionState = MenuTransitionState.IDLE
  t: float = 0.0
  duration: float = SETTINGS_TRANSITION_SECONDS
  from_screen: object | None = None
  to_screen: object | None = None

  @property
  def active(self) -> bool:
    return self.state != MenuTransitionState.IDLE


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
  return max(lo, min(hi, x))


def _lerp(a: float, b: float, t: float) -> float:
  return a + (b - a) * t


def _ease_out_cubic(x: float) -> float:
  x = _clamp(x)
  return 1.0 - pow(1.0 - x, 3.0)


def _ease_emphasized(x: float) -> float:
  # ease-in-out-cubic: gentle acceleration into the slide, graceful deceleration into place
  x = _clamp(x)
  if x < 0.5:
    return 4.0 * x * x * x
  return 1.0 - pow(-2.0 * x + 2.0, 3.0) / 2.0


# Depth cues for the grid<->panel push/pop (see main.py for the same treatment).
TRANSITION_PARALLAX = 0.28
TRANSITION_MAX_DIM = 0.5
TRANSITION_SHADOW_W = 32


class SettingsPill(Widget):
  """A settings-grid button: icon + label on a rounded card, opens a sub-panel."""

  BG = rl.Color(38, 40, 46, 255)
  BG_PRESSED = rl.Color(54, 57, 65, 255)
  BORDER = rl.Color(255, 255, 255, 38)

  def __init__(self, icon_path: str, label: str, on_click: Callable[[], None]):
    super().__init__()
    self._label = label
    self._icon = gui_app.texture(icon_path, 80, 80, keep_aspect_ratio=True) if icon_path else None
    self.set_click_callback(on_click)

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rounded(rect, 0.25, 20, self.BG_PRESSED if self.is_pressed else self.BG)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.25, 20, 2, self.BORDER)

    font = gui_app.font(FontWeight.MEDIUM)
    label_size = 50
    ts = measure_text_cached(font, self._label, label_size)
    icon_w = self._icon.width if self._icon else 0
    gap = 24 if self._icon else 0
    group_w = icon_w + gap + ts.x
    x = rect.x + (rect.width - group_w) / 2
    cy = rect.y + rect.height / 2

    if self._icon:
      rl.draw_texture(self._icon, int(x), int(cy - self._icon.height / 2), rl.WHITE)
      x += icon_w + gap
    rl.draw_text_ex(font, self._label, rl.Vector2(int(x), int(cy - ts.y / 2)), label_size, 0, rl.WHITE)


class SettingsHubLayout(Widget):
  """Offroad Settings: a grid of pill buttons (the mockup look) that open the existing
  IQ settings sub-panels. Back from a panel returns to the grid; back from the grid goes home.
  """

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._settings = IQSettingsLayout()  # one instance: reuse its configured panels + wiring
    self._header = self._child(ScreenHeader(tr("Settings")))
    self._on_close: Callable[[], None] | None = None

    self._mode = "grid"           # "grid" | "panel"
    self._cur_panel = None

    # Edge-swipe-back drag state (panel -> grid only)
    self._swipe_start_pos: MousePos | None = None
    self._swipe_active = False       # past EDGE_SWIPE_ARM_DISTANCE, now tracking finger 1:1
    self._swipe_blocked = False      # vertical movement won out before we armed; ignore rest of this touch
    self._swipe_dx = 0.0
    # Release-settle animation (glide to grid/panel instead of snapping)
    self._swipe_settling = False
    self._swipe_settle_from = 0.0
    self._swipe_settle_to = 0.0
    self._swipe_settle_t = 0.0
    self._swipe_completing = False
    self._version_text = _format_updater_description(self._params.get("UpdaterCurrentDescription"))
    self._version_label = UnifiedLabel("", font_size=44, font_weight=FontWeight.MEDIUM,
                                       text_color=rl.Color(185, 185, 190, 255),
                                       alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE,
                                       wrap_text=False, scroll=True)
    self._transition = MenuTransition()

    # Restart / power-off / always-offroad / night-mode bubbles in the grid header
    self._restart_icon = gui_app.texture("icons/iq/restart.png", 48, 48, keep_aspect_ratio=True)
    self._power_icon = gui_app.texture("icons/iq/power.png", 48, 48, keep_aspect_ratio=True)
    self._offroad_icon = gui_app.texture("icons/iq/square-parking.png", 48, 48, keep_aspect_ratio=True)
    self._night_icon = gui_app.texture("icons/iq/moon.png", 48, 48, keep_aspect_ratio=True)
    self._bell_icon = gui_app.texture("icons/iq/bell.png", 48, 48, keep_aspect_ratio=True)
    self._bell_slash_icon = gui_app.texture("icons/iq/bell-slash.png", 48, 48, keep_aspect_ratio=True)
    self._restart_rect = rl.Rectangle(0, 0, 0, 0)
    self._power_rect = rl.Rectangle(0, 0, 0, 0)
    self._offroad_rect = rl.Rectangle(0, 0, 0, 0)
    self._night_rect = rl.Rectangle(0, 0, 0, 0)
    self._quiet_rect = rl.Rectangle(0, 0, 0, 0)

    # Build the grid from the settings panels, skipping ones hidden from navigation (e.g. Cruise).
    panels = self._settings._panels
    hidden = self._settings._hidden_from_sidebar
    self._grid_panels = [pt for pt in panels if pt not in hidden]
    self._pills = [
      SettingsPill(panels[pt].icon, tr(panels[pt].name), (lambda p=pt: self._open_panel(p)))
      for pt in self._grid_panels
    ]

    # Route the Toggles -> Cruise shortcut into this hub's panel view.
    cruise_pt = next((pt for pt in panels if pt.name == "CRUISE"), None)
    toggles_pt = next((pt for pt in panels if pt.name == "TOGGLES"), None)
    if cruise_pt is not None and toggles_pt is not None:
      toggles = panels[toggles_pt].instance
      if hasattr(toggles, "set_cruise_panel_callback"):
        toggles.set_cruise_panel_callback(lambda: self._open_panel(cruise_pt))

  def set_callbacks(self, on_close: Callable[[], None] | None = None):
    self._on_close = on_close

  def show_grid(self):
    self._mode = "grid"
    self._transition = MenuTransition()

  def set_current_panel(self, panel_type):
    self._open_panel(panel_type)

  def show_event(self):
    super().show_event()
    self._mode = "grid"
    self._transition = MenuTransition()
    self._version_text = _format_updater_description(self._params.get("UpdaterCurrentDescription"))

  def _open_panel(self, panel_type):
    if self._transition.active:
      return

    from_grid = self._mode == "grid"
    self._settings.set_current_panel(panel_type)
    self._cur_panel = panel_type
    if from_grid and not ui_state.started:
      self._start_transition("grid", "panel", MenuTransitionState.PUSHING)
    else:
      self._mode = "panel"

  def _back_to_grid(self):
    if self._mode == "panel" and not self._transition.active:
      self._start_transition("panel", "grid", MenuTransitionState.POPPING)

  def _reset_swipe(self):
    self._swipe_start_pos = None
    self._swipe_active = False
    self._swipe_blocked = False
    self._swipe_dx = 0.0

  def _handle_mouse_event(self, mouse_event: MouseEvent) -> None:
    super()._handle_mouse_event(mouse_event)

    if self._swipe_settling:
      return  # let the release animation finish before accepting a new gesture

    if mouse_event.slot != 0 or self._mode != "panel" or self._transition.active:
      self._reset_swipe()
      return

    if mouse_event.left_pressed:
      if mouse_event.pos.x - self._rect.x <= EDGE_SWIPE_ZONE:
        self._swipe_start_pos = mouse_event.pos
        self._swipe_active = False
        self._swipe_blocked = False
        self._swipe_dx = 0.0
      else:
        self._reset_swipe()

    elif self._swipe_start_pos is not None:
      if mouse_event.left_down:
        dx = mouse_event.pos.x - self._swipe_start_pos.x
        dy = abs(mouse_event.pos.y - self._swipe_start_pos.y)
        if not self._swipe_active and not self._swipe_blocked:
          if dy > EDGE_SWIPE_BLOCK_VERTICAL and dy > dx:
            self._swipe_blocked = True
          elif dx > EDGE_SWIPE_ARM_DISTANCE:
            self._swipe_active = True
        if self._swipe_active:
          self._swipe_dx = max(0.0, dx)

      elif mouse_event.left_released:
        if self._swipe_active:
          complete = self._swipe_dx > self._rect.width * EDGE_SWIPE_COMPLETE_FRACTION
          self._begin_swipe_settle(complete)
        self._reset_swipe()

  def _start_transition(self, from_mode: str, to_mode: str, state: MenuTransitionState):
    self._transition = MenuTransition(
      state=state,
      t=0.0,
      duration=SETTINGS_TRANSITION_SECONDS,
      from_screen=from_mode,
      to_screen=to_mode,
    )

  def _render(self, rect: rl.Rectangle):
    if self._render_transition(rect):
      return

    if self._swipe_settling:
      if self._update_swipe_settle():
        self._render_swipe_drag(rect)
        return
      # settled this frame; fall through to render the (possibly switched) mode
    elif self._swipe_active and self._mode == "panel":
      self._render_swipe_drag(rect)
      return

    self._render_mode(self._mode, rect)

  def _begin_swipe_settle(self, complete: bool):
    # On release, glide from where the finger let go to fully-open (complete -> grid) or closed
    # (cancel -> stay on panel) instead of snapping.
    self._swipe_settle_from = self._swipe_dx
    self._swipe_settle_to = self._rect.width if complete else 0.0
    self._swipe_completing = complete
    self._swipe_settle_t = 0.0
    self._swipe_settling = True

  def _update_swipe_settle(self) -> bool:
    """Advance the release animation. Returns True while still animating."""
    self._swipe_settle_t += rl.get_frame_time()
    p = _clamp(self._swipe_settle_t / SWIPE_SETTLE_SECONDS)
    self._swipe_dx = _lerp(self._swipe_settle_from, self._swipe_settle_to, _ease_out_cubic(p))
    if p < 1.0:
      return True
    self._swipe_settling = False
    completing = self._swipe_completing
    self._swipe_completing = False
    self._swipe_dx = 0.0
    if completing:
      self._mode = "grid"
      self._transition = MenuTransition()
    return False

  def _render_swipe_drag(self, rect: rl.Rectangle):
    # Live, finger-following preview of the panel -> grid pop, mirroring _render_transition's
    # POPPING geometry but driven 1:1 by touch position instead of eased elapsed time.
    dx = min(self._swipe_dx, rect.width)
    rl.draw_rectangle_rec(rect, TRANSITION_SURFACE_BG)
    self._render_mode_surface_translated("grid", rect, dx - rect.width)
    self._render_mode_surface_translated("panel", rect, dx)

  def _layout_rects(self, rect: rl.Rectangle) -> tuple[rl.Rectangle, rl.Rectangle]:
    header_rect = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, HEADER_HEIGHT)
    content_y = header_rect.y + HEADER_HEIGHT + SPACING
    content_rect = rl.Rectangle(rect.x + MARGIN, content_y, rect.width - 2 * MARGIN,
                                rect.y + rect.height - content_y - MARGIN)
    return header_rect, content_rect

  def _render_mode(self, mode: str, rect: rl.Rectangle, interactive: bool = True):
    if mode == "panel" and self._cur_panel is not None:
      self._render_panel(rect, interactive)
    else:
      self._render_grid(rect, interactive)

  def _render_mode_surface(self, mode: str, rect: rl.Rectangle, interactive: bool = True):
    bg_rect = rl.Rectangle(
      rect.x - TRANSITION_SURFACE_OVERSCAN,
      rect.y - TRANSITION_SURFACE_OVERSCAN,
      rect.width + TRANSITION_SURFACE_OVERSCAN * 2,
      rect.height + TRANSITION_SURFACE_OVERSCAN * 2,
    )
    rl.draw_rectangle_rec(bg_rect, TRANSITION_SURFACE_BG)
    self._render_mode(mode, rect, interactive)

  def _render_mode_surface_translated(self, mode: str, rect: rl.Rectangle, x_offset: float):
    translated_rect = rl.Rectangle(round(rect.x + x_offset), rect.y, rect.width, rect.height)
    self._render_mode_surface(mode, translated_rect, interactive=False)

  def _render_transition(self, rect: rl.Rectangle) -> bool:
    if not self._transition.active:
      return False

    from_mode = self._transition.from_screen
    to_mode = self._transition.to_screen
    if from_mode is None or to_mode is None:
      self._finish_transition()
      return False
    from_mode = str(from_mode)
    to_mode = str(to_mode)

    self._transition.t += rl.get_frame_time()
    if self._transition.t >= self._transition.duration:
      self._finish_transition()
      return False

    p = _clamp(self._transition.t / self._transition.duration)
    e = _ease_emphasized(p)
    w = rect.width
    pushing = self._transition.state == MenuTransitionState.PUSHING

    # The incoming card slides its full width on top; the other page parallaxes a fraction and dims.
    if pushing:
      top_mode, back_mode = to_mode, from_mode
      top_x = _lerp(w, 0.0, e)
      back_x = _lerp(0.0, -w * TRANSITION_PARALLAX, e)
      back_dim = int(_lerp(0.0, TRANSITION_MAX_DIM, e) * 255)
    else:
      top_mode, back_mode = from_mode, to_mode
      top_x = _lerp(0.0, w, e)
      back_x = _lerp(-w * TRANSITION_PARALLAX, 0.0, e)
      back_dim = int(_lerp(TRANSITION_MAX_DIM, 0.0, e) * 255)

    back_rect = rl.Rectangle(round(rect.x + back_x), rect.y, rect.width, rect.height)

    rl.draw_rectangle_rec(rect, TRANSITION_SURFACE_BG)
    self._render_mode_surface_translated(back_mode, rect, back_x)
    if back_dim > 0:
      rl.draw_rectangle_rec(back_rect, rl.Color(0, 0, 0, back_dim))
    # soft shadow cast by the top card's leading edge onto the page behind
    edge_x = round(rect.x + top_x)
    if edge_x > rect.x:
      sh = int(min(TRANSITION_SHADOW_W, edge_x - rect.x))
      rl.draw_rectangle_gradient_h(edge_x - sh, int(rect.y), sh, int(rect.height),
                                   rl.Color(0, 0, 0, 0), rl.Color(0, 0, 0, 120))
    self._render_mode_surface_translated(top_mode, rect, top_x)
    return True

  def _finish_transition(self):
    if self._transition.to_screen is not None:
      self._mode = str(self._transition.to_screen)
    self._transition = MenuTransition()

  def _render_widget(self, widget: Widget, rect: rl.Rectangle, interactive: bool):
    if interactive:
      widget.render(rect)
      return

    enabled = widget._enabled
    widget.set_enabled(False)
    try:
      widget.render(rect)
    finally:
      widget.set_enabled(enabled)

  def _render_panel(self, rect: rl.Rectangle, interactive: bool = True):
    header_rect, content_rect = self._layout_rects(rect)

    self._header.set_title(tr(self._settings._panels[self._cur_panel].name))
    self._header.set_on_back(self._back_to_grid)
    self._header.set_title_offset(0)
    self._render_widget(self._header, header_rect, interactive)

    panel = self._settings._panels[self._settings._current_panel].instance
    enabled = panel._enabled
    if not interactive:
      panel.set_enabled(False)
    try:
      self._settings._draw_current_panel(content_rect)
    finally:
      if not interactive:
        panel.set_enabled(enabled)

  def _render_grid(self, rect: rl.Rectangle, interactive: bool = True):
    header_rect, content_rect = self._layout_rects(rect)

    # Grid landing
    title = tr("Settings")
    title_offset = 5 * BUBBLE_SIZE + 4 * 18 + 36
    self._header.set_title(title)
    self._header.set_on_back(self._on_close)
    self._header.set_title_offset(title_offset)  # make room for the bubbles
    self._render_widget(self._header, header_rect, interactive)

    # Restart / power-off / always-offroad bubbles, just right of the back button
    cy = header_rect.y + HEADER_HEIGHT / 2
    bx = header_rect.x + BACK_BTN_SIZE + 24
    self._restart_rect = rl.Rectangle(bx, cy - BUBBLE_SIZE / 2, BUBBLE_SIZE, BUBBLE_SIZE)
    self._power_rect = rl.Rectangle(bx + BUBBLE_SIZE + 18, cy - BUBBLE_SIZE / 2, BUBBLE_SIZE, BUBBLE_SIZE)
    self._offroad_rect = rl.Rectangle(bx + 2 * (BUBBLE_SIZE + 18), cy - BUBBLE_SIZE / 2, BUBBLE_SIZE, BUBBLE_SIZE)
    self._night_rect = rl.Rectangle(bx + 3 * (BUBBLE_SIZE + 18), cy - BUBBLE_SIZE / 2, BUBBLE_SIZE, BUBBLE_SIZE)
    self._quiet_rect = rl.Rectangle(bx + 4 * (BUBBLE_SIZE + 18), cy - BUBBLE_SIZE / 2, BUBBLE_SIZE, BUBBLE_SIZE)
    mouse = rl.get_mouse_position()
    for r, icon in ((self._restart_rect, self._restart_icon), (self._power_rect, self._power_icon)):
      pressed = self.is_pressed and rl.check_collision_point_rec(mouse, r)
      rl.draw_circle(int(r.x + BUBBLE_SIZE / 2), int(cy), BUBBLE_SIZE / 2, BUBBLE_RED_PRESSED if pressed else BUBBLE_RED)
      rl.draw_texture(icon, int(r.x + (BUBBLE_SIZE - icon.width) / 2), int(cy - icon.height / 2), rl.WHITE)
    # Always Offroad bubble (grey when off, teal when on)
    offroad_active = ui_state.params.get_bool("OffroadMode")
    pressed = self.is_pressed and rl.check_collision_point_rec(mouse, self._offroad_rect)
    offroad_color = (BUBBLE_TEAL_PRESSED if pressed else BUBBLE_TEAL) if offroad_active else (BUBBLE_GREY_PRESSED if pressed else BUBBLE_GREY)
    rl.draw_circle(int(self._offroad_rect.x + BUBBLE_SIZE / 2), int(cy), BUBBLE_SIZE / 2, offroad_color)
    rl.draw_texture(self._offroad_icon,
                    int(self._offroad_rect.x + (BUBBLE_SIZE - self._offroad_icon.width) / 2),
                    int(cy - self._offroad_icon.height / 2), rl.WHITE)
    # Night Mode bubble (grey when off, teal when on)
    night_active = ui_state.params.get_bool("NightMode")
    pressed = self.is_pressed and rl.check_collision_point_rec(mouse, self._night_rect)
    night_color = (BUBBLE_TEAL_PRESSED if pressed else BUBBLE_TEAL) if night_active else (BUBBLE_GREY_PRESSED if pressed else BUBBLE_GREY)
    rl.draw_circle(int(self._night_rect.x + BUBBLE_SIZE / 2), int(cy), BUBBLE_SIZE / 2, night_color)
    rl.draw_texture(self._night_icon,
                    int(self._night_rect.x + (BUBBLE_SIZE - self._night_icon.width) / 2),
                    int(cy - self._night_icon.height / 2), rl.WHITE)

    # Quiet Mode bubble (grey bell when off, red bell-with-slash when on)
    quiet_active = ui_state.params.get_bool("IQAlertSilence")
    pressed = self.is_pressed and rl.check_collision_point_rec(mouse, self._quiet_rect)
    quiet_color = (BUBBLE_RED_PRESSED if pressed else BUBBLE_RED) if quiet_active else (BUBBLE_GREY_PRESSED if pressed else BUBBLE_GREY)
    quiet_icon = self._bell_slash_icon if quiet_active else self._bell_icon
    rl.draw_circle(int(self._quiet_rect.x + BUBBLE_SIZE / 2), int(cy), BUBBLE_SIZE / 2, quiet_color)
    rl.draw_texture(quiet_icon,
                    int(self._quiet_rect.x + (BUBBLE_SIZE - quiet_icon.width) / 2),
                    int(cy - quiet_icon.height / 2), rl.WHITE)

    # Small version label, top-right of the header row. Its scroll viewport
    # starts after the title, so long branch text does not clip at the bubbles.
    font = gui_app.font(FontWeight.MEDIUM)
    title_font = gui_app.font(FontWeight.BOLD)
    ver_fs = 44
    title_size = measure_text_cached(title_font, title, 64)
    ver_size = measure_text_cached(font, self._version_text, ver_fs)
    title_x = header_rect.x + BACK_BTN_SIZE + 36 + title_offset
    version_left = title_x + title_size.x + 36
    version_right = header_rect.x + header_rect.width
    version_rect = rl.Rectangle(version_left, header_rect.y, max(0, version_right - version_left), HEADER_HEIGHT)
    if version_rect.width > 0:
      if ver_size.x <= version_rect.width:
        rl.draw_text_ex(font, self._version_text,
                        rl.Vector2(int(header_rect.x + header_rect.width - ver_size.x),
                                   int(header_rect.y + (HEADER_HEIGHT - ver_size.y) / 2)),
                        ver_fs, 0, rl.Color(185, 185, 190, 255))
      else:
        self._version_label.set_text(self._version_text)
        self._version_label.render(version_rect)

    rows = (len(self._pills) + COLUMNS - 1) // COLUMNS
    pill_w = (content_rect.width - PILL_GAP * (COLUMNS - 1)) / COLUMNS
    pill_h = max(PILL_MIN_HEIGHT, (content_rect.height - PILL_GAP * (rows - 1)) / rows)
    for i, pill in enumerate(self._pills):
      col = i % COLUMNS
      row = i // COLUMNS
      px = content_rect.x + col * (pill_w + PILL_GAP)
      py = content_rect.y + row * (pill_h + PILL_GAP)
      self._render_widget(pill, rl.Rectangle(px, py, pill_w, pill_h), interactive)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if self._mode != "grid" or self._transition.active:
      return
    if rl.check_collision_point_rec(mouse_pos, self._restart_rect):
      self._reboot_prompt()
    elif rl.check_collision_point_rec(mouse_pos, self._power_rect):
      self._power_off_prompt()
    elif rl.check_collision_point_rec(mouse_pos, self._offroad_rect):
      self._toggle_offroad_prompt()
    elif rl.check_collision_point_rec(mouse_pos, self._night_rect):
      ui_state.params.put_bool("NightMode", not ui_state.params.get_bool("NightMode"))
    elif rl.check_collision_point_rec(mouse_pos, self._quiet_rect):
      ui_state.params.put_bool("IQAlertSilence", not ui_state.params.get_bool("IQAlertSilence"))

  def _reboot_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Reboot")))
      return
    dialog = ConfirmDialog(tr("Are you sure you want to reboot?"), tr("Reboot"))
    gui_app.set_modal_overlay(dialog, callback=self._perform_reboot)

  def _perform_reboot(self, result: int):
    if not ui_state.engaged and result == DialogResult.CONFIRM:
      self._params.put_bool_nonblocking("DoReboot", True)

  def _power_off_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Power Off")))
      return
    dialog = ConfirmDialog(tr("Are you sure you want to power off?"), tr("Power Off"))
    gui_app.set_modal_overlay(dialog, callback=self._perform_power_off)

  def _perform_power_off(self, result: int):
    if not ui_state.engaged and result == DialogResult.CONFIRM:
      self._params.put_bool_nonblocking("DoShutdown", True)

  def _toggle_offroad_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Enter Always Offroad Mode")))
      return
    active = ui_state.params.get_bool("OffroadMode")
    msg = tr("Are you sure you want to exit Always Offroad mode?") if active else tr("Are you sure you want to enter Always Offroad mode?")

    def _confirm(result: int):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        ui_state.params.put_bool("OffroadMode", not active)

    gui_app.set_modal_overlay(ConfirmDialog(msg, tr("Confirm")), callback=_confirm)
