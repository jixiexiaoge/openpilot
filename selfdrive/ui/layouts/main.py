import pyray as rl
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
import cereal.messaging as messaging
from openpilot.system.ui.lib.application import gui_app, MouseEvent
from openpilot.selfdrive.ui.layouts.sidebar import Sidebar, SIDEBAR_WIDTH
from openpilot.selfdrive.ui.layouts.home import HomeLayout
from openpilot.selfdrive.ui.layouts.stats import StatsLayout
from openpilot.selfdrive.ui.layouts.nav import NavLayout
from openpilot.selfdrive.ui.layouts.routes import RoutesLayout
from openpilot.selfdrive.ui.layouts.video_player import VideoPlayerLayout
from openpilot.selfdrive.ui.layouts.settings_hub import SettingsHubLayout
from openpilot.selfdrive.ui.layouts.settings.settings import PanelType
from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.layouts.onboarding import OnboardingWindow
from openpilot.system.version import training_version


class MainState(IntEnum):
  HOME = 0
  SETTINGS = 1
  ONROAD = 2
  STATS = 3
  NAV = 4
  ROUTES = 5
  VIDEO = 6


OFFROAD_TRANSITION_SECONDS = 0.30
TRANSITION_SURFACE_OVERSCAN = 4
TRANSITION_SURFACE_BG = rl.Color(10, 10, 10, 255)

# iOS-style swipe-from-the-left-edge-to-go-back, generalized across the whole offroad UI (settings
# hub still owns its own panel->grid swipe; this covers the top-level pages).
EDGE_SWIPE_ZONE = 80                 # px from the left edge a swipe-back must start within
EDGE_SWIPE_ARM_DISTANCE = 8          # px of rightward movement before we commit to a swipe
EDGE_SWIPE_BLOCK_VERTICAL = 60       # px of vertical movement (under arm distance) that cancels it
EDGE_SWIPE_COMPLETE_FRACTION = 0.3   # fraction of width dragged to complete the pop on release
SWIPE_SETTLE_SECONDS = 0.16          # animate from the release point to done/cancelled (no snap)


class MenuTransitionState(Enum):
  IDLE = auto()
  PUSHING = auto()
  POPPING = auto()


@dataclass
class MenuTransition:
  state: MenuTransitionState = MenuTransitionState.IDLE
  t: float = 0.0
  duration: float = OFFROAD_TRANSITION_SECONDS
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


# Depth cues for the page push/pop (iOS-style): the underneath page parallaxes a fraction of the
# way, dims into the background, and the top card casts a soft shadow off its leading edge.
TRANSITION_PARALLAX = 0.28
TRANSITION_MAX_DIM = 0.5
TRANSITION_SHADOW_W = 32


class MainLayout(Widget):
  def __init__(self):
    super().__init__()

    self._pm = messaging.PubMaster(['bookmarkButton'])

    self._sidebar = Sidebar()
    # The offroad launcher owns the full screen; the sidebar is reserved for onroad.
    self._sidebar.set_visible(False)
    self._current_mode = MainState.HOME
    self._prev_onroad = False

    # Initialize layouts
    self._layouts = {
      MainState.HOME: HomeLayout(),
      MainState.SETTINGS: SettingsHubLayout(),
      MainState.ONROAD: AugmentedRoadView(),
      MainState.STATS: StatsLayout(),
      MainState.NAV: NavLayout(),
      MainState.ROUTES: RoutesLayout(),
      MainState.VIDEO: VideoPlayerLayout(),
    }

    self._sidebar_rect = rl.Rectangle(0, 0, 0, 0)
    self._content_rect = rl.Rectangle(0, 0, 0, 0)
    self._transition = MenuTransition()

    # Edge-swipe-back drag state
    self._swipe_start_pos = None
    self._swipe_active = False
    self._swipe_blocked = False
    self._swipe_dx = 0.0
    # Release-settle animation (glide to done/cancelled instead of snapping)
    self._swipe_settling = False
    self._swipe_settle_from = 0.0
    self._swipe_settle_to = 0.0
    self._swipe_settle_t = 0.0
    self._swipe_render_target: MainState | None = None
    self._swipe_completing = False
    # Set callbacks
    self._setup_callbacks()

    if ui_state.params.get("CompletedTrainingVersion") != training_version:
      ui_state.params.put("CompletedTrainingVersion", training_version)

    self._onboarding_window = OnboardingWindow()
    if not self._onboarding_window.completed:
      gui_app.set_modal_overlay(self._onboarding_window)

  def _render(self, _):
    self._handle_onroad_transition()
    self._render_main_content()

  def _setup_callbacks(self):
    self._sidebar.set_callbacks(on_settings=self._on_settings_clicked,
                                on_flag=self._on_bookmark_clicked,
                                open_settings=lambda: self.open_settings(PanelType.TOGGLES))
    self._layouts[MainState.HOME].set_settings_callback(self.open_settings)
    self._layouts[MainState.HOME].set_stats_callback(self.open_stats)
    self._layouts[MainState.HOME].set_nav_callback(self.open_nav)
    self._layouts[MainState.HOME].set_routes_callback(self.open_routes)
    self._layouts[MainState.SETTINGS].set_callbacks(on_close=self._set_mode_for_state)
    self._layouts[MainState.STATS].set_on_back(self._set_mode_for_state)
    self._layouts[MainState.NAV].set_on_back(self._set_mode_for_state)
    self._layouts[MainState.ROUTES].set_on_back(self._set_mode_for_state)
    self._layouts[MainState.ROUTES].set_on_play(self.open_video)
    self._layouts[MainState.VIDEO].set_on_back(self.open_routes)
    self._layouts[MainState.ONROAD].set_click_callback(self._on_onroad_clicked)
    device.add_interactive_timeout_callback(self._set_mode_for_state)

  def _update_layout_rects(self):
    self._sidebar_rect = rl.Rectangle(self._rect.x, self._rect.y, SIDEBAR_WIDTH, self._rect.height)

    x_offset = SIDEBAR_WIDTH if self._sidebar.is_visible else 0
    self._content_rect = rl.Rectangle(self._rect.x + x_offset, self._rect.y, self._rect.width - x_offset, self._rect.height)

  def _handle_onroad_transition(self):
    if ui_state.started != self._prev_onroad:
      self._prev_onroad = ui_state.started

      self._set_mode_for_state()

  def _set_mode_for_state(self):
    if ui_state.started:
      # Don't hide sidebar from interactive timeout
      if self._current_mode != MainState.ONROAD:
        self._set_sidebar_visible(False)
      self._set_current_layout(MainState.ONROAD)
    else:
      # Offroad launcher owns the full screen; the sidebar is reserved for onroad.
      self._set_current_layout(MainState.HOME)
      self._set_sidebar_visible(False)

  def _set_current_layout(self, layout: MainState):
    if self._transition.active:
      if layout == MainState.ONROAD or ui_state.started:
        self._cancel_transition()
      elif layout == self._current_mode:
        self._cancel_transition()
        return
      else:
        return

    if layout == self._current_mode:
      return

    old_mode = self._current_mode
    if self._should_animate_transition(old_mode, layout):
      self._start_transition(old_mode, layout)
      return

    self._layouts[old_mode].hide_event()
    self._current_mode = layout
    self._layouts[self._current_mode].show_event()

  def _should_animate_transition(self, old_mode: MainState, new_mode: MainState) -> bool:
    return (
      not ui_state.started
      and old_mode != MainState.ONROAD
      and new_mode != MainState.ONROAD
      and (old_mode == MainState.HOME or new_mode == MainState.HOME)
    )

  def _start_transition(self, old_mode: MainState, new_mode: MainState):
    state = MenuTransitionState.PUSHING if old_mode == MainState.HOME else MenuTransitionState.POPPING
    self._transition = MenuTransition(
      state=state,
      t=0.0,
      duration=OFFROAD_TRANSITION_SECONDS,
      from_screen=old_mode,
      to_screen=new_mode,
    )
    self._layouts[new_mode].show_event()

  def _cancel_transition(self):
    pending_mode = self._transition.to_screen
    if pending_mode is not None and pending_mode != self._current_mode:
      self._layouts[pending_mode].hide_event()
    self._transition = MenuTransition()

  def _finish_transition(self):
    old_mode = self._transition.from_screen
    new_mode = self._transition.to_screen
    if old_mode is not None:
      self._layouts[old_mode].hide_event()
    if new_mode is not None:
      self._current_mode = new_mode
    self._transition = MenuTransition()

  def _render_layout(self, layout: Widget, rect: rl.Rectangle, interactive: bool = True):
    if interactive:
      layout.render(rect)
      return

    enabled = layout._enabled
    layout.set_enabled(False)
    try:
      layout.render(rect)
    finally:
      layout.set_enabled(enabled)

  def _render_layout_surface(self, layout: Widget, rect: rl.Rectangle, interactive: bool = True):
    bg_rect = rl.Rectangle(
      rect.x - TRANSITION_SURFACE_OVERSCAN,
      rect.y - TRANSITION_SURFACE_OVERSCAN,
      rect.width + TRANSITION_SURFACE_OVERSCAN * 2,
      rect.height + TRANSITION_SURFACE_OVERSCAN * 2,
    )
    rl.draw_rectangle_rec(bg_rect, TRANSITION_SURFACE_BG)
    self._render_layout(layout, rect, interactive)

  def _render_layout_surface_translated(self, layout: Widget, rect: rl.Rectangle, x_offset: float):
    translated_rect = rl.Rectangle(round(rect.x + x_offset), rect.y, rect.width, rect.height)
    self._render_layout_surface(layout, translated_rect, interactive=False)

  def _render_transition(self, content_rect: rl.Rectangle) -> bool:
    if not self._transition.active:
      return False

    from_mode = self._transition.from_screen
    to_mode = self._transition.to_screen
    if from_mode is None or to_mode is None:
      self._finish_transition()
      return False

    self._transition.t += rl.get_frame_time()
    if self._transition.t >= self._transition.duration:
      self._finish_transition()
      return False

    p = _clamp(self._transition.t / self._transition.duration)
    e = _ease_emphasized(p)
    w = content_rect.width
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

    back_rect = rl.Rectangle(round(content_rect.x + back_x), content_rect.y, content_rect.width, content_rect.height)

    rl.draw_rectangle_rec(content_rect, TRANSITION_SURFACE_BG)
    self._render_layout_surface_translated(self._layouts[back_mode], content_rect, back_x)
    if back_dim > 0:
      rl.draw_rectangle_rec(back_rect, rl.Color(0, 0, 0, back_dim))
    # soft shadow cast by the top card's leading edge onto the page behind
    edge_x = round(content_rect.x + top_x)
    if edge_x > content_rect.x:
      sh = int(min(TRANSITION_SHADOW_W, edge_x - content_rect.x))
      rl.draw_rectangle_gradient_h(edge_x - sh, int(content_rect.y), sh, int(content_rect.height),
                                   rl.Color(0, 0, 0, 0), rl.Color(0, 0, 0, 120))
    self._render_layout_surface_translated(self._layouts[top_mode], content_rect, top_x)
    return True

  def open_settings(self, panel_type: PanelType | None = None):
    self._set_current_layout(MainState.SETTINGS)
    if panel_type is None:
      self._layouts[MainState.SETTINGS].show_grid()
    else:
      self._layouts[MainState.SETTINGS].set_current_panel(panel_type)
    self._set_sidebar_visible(False)

  def open_stats(self):
    self._set_current_layout(MainState.STATS)
    self._set_sidebar_visible(False)

  def open_nav(self):
    self._set_current_layout(MainState.NAV)
    self._set_sidebar_visible(False)

  def open_routes(self):
    self._set_current_layout(MainState.ROUTES)
    self._set_sidebar_visible(False)

  def open_video(self, route: str):
    self._layouts[MainState.VIDEO].set_route(route)
    self._set_current_layout(MainState.VIDEO)
    self._set_sidebar_visible(False)

  def _on_settings_clicked(self):
    self.open_settings()

  def _on_bookmark_clicked(self):
    user_bookmark = messaging.new_message('bookmarkButton')
    user_bookmark.valid = True
    self._pm.send('bookmarkButton', user_bookmark)

  def _set_sidebar_visible(self, visible: bool):
    self._sidebar.set_visible(visible)
    self._update_layout_rects()

  def _on_onroad_clicked(self):
    self._set_sidebar_visible(not self._sidebar.is_visible)

  def _back_target(self) -> MainState | None:
    """The page an edge-swipe-back should return to, or None if there's nowhere to go back."""
    if ui_state.started:
      return None
    mode = self._current_mode
    if mode == MainState.VIDEO:
      return MainState.ROUTES
    if mode in (MainState.SETTINGS, MainState.STATS, MainState.NAV, MainState.ROUTES):
      # The settings hub owns its own panel->grid swipe; only take over once it's back at the grid.
      if mode == MainState.SETTINGS and getattr(self._layouts[MainState.SETTINGS], "_mode", "grid") == "panel":
        return None
      return MainState.HOME
    return None

  def _reset_swipe(self):
    self._swipe_start_pos = None
    self._swipe_active = False
    self._swipe_blocked = False
    self._swipe_dx = 0.0

  def _handle_mouse_event(self, mouse_event: MouseEvent) -> None:
    super()._handle_mouse_event(mouse_event)

    if self._swipe_settling:
      return  # let the release animation finish before accepting a new gesture

    if mouse_event.slot != 0 or self._transition.active or self._back_target() is None:
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
            self._swipe_blocked = True  # user is scrolling, not swiping back
          elif dx > EDGE_SWIPE_ARM_DISTANCE:
            self._swipe_active = True
        if self._swipe_active:
          self._swipe_dx = max(0.0, dx)

      elif mouse_event.left_released:
        if self._swipe_active:
          target = self._back_target()
          complete = target is not None and self._swipe_dx > self._rect.width * EDGE_SWIPE_COMPLETE_FRACTION
          self._begin_swipe_settle(target, complete)
        self._reset_swipe()

  def _complete_back(self, target: MainState):
    # The finger already dragged the page most of the way across, so switch instantly (matching the
    # settings hub's swipe) rather than replaying the eased transition.
    old_mode = self._current_mode
    if old_mode == target:
      return
    self._layouts[old_mode].hide_event()
    self._current_mode = target
    self._layouts[target].show_event()

  def _begin_swipe_settle(self, target: MainState | None, complete: bool):
    # On release, glide from where the finger let go to fully-open (complete) or closed (cancel)
    # instead of snapping. Needs a back page to slide behind; if there's none, just drop the drag.
    if target is None:
      return
    self._swipe_settle_from = self._swipe_dx
    self._swipe_settle_to = self._rect.width if complete else 0.0
    self._swipe_render_target = target
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
    target, completing = self._swipe_render_target, self._swipe_completing
    self._swipe_render_target = None
    self._swipe_completing = False
    self._swipe_dx = 0.0
    if completing and target is not None:
      self._complete_back(target)
    return False

  def _render_swipe_drag(self, rect: rl.Rectangle, target: MainState):
    # Live finger-following pop: the destination sits behind, the current page slides out right.
    dx = min(self._swipe_dx, rect.width)
    rl.draw_rectangle_rec(rect, TRANSITION_SURFACE_BG)
    self._render_layout_surface_translated(self._layouts[target], rect, dx - rect.width)
    self._render_layout_surface_translated(self._layouts[self._current_mode], rect, dx)

  def _render_main_content(self):
    # Render sidebar (onroad only)
    if self._sidebar.is_visible:
      self._sidebar.render(self._sidebar_rect)

    content_rect = self._content_rect if self._sidebar.is_visible else self._rect
    if self._render_transition(content_rect):
      return
    if self._swipe_settling:
      if self._update_swipe_settle():
        self._render_swipe_drag(content_rect, self._swipe_render_target)
        return
      # settled this frame; fall through to render the (possibly switched) current page
    elif self._swipe_active:
      target = self._back_target()
      if target is not None:
        self._render_swipe_drag(content_rect, target)
        return
    self._layouts[self._current_mode].render(content_rect)
