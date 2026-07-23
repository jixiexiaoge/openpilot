"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import atexit
import cffi
import os
import queue
import time
import signal
import sys
import pyray as rl
import threading
import platform
import subprocess
from contextlib import contextmanager
from collections.abc import Callable
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple
from importlib.resources import as_file, files
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.ui.lib.multilang import multilang
from openpilot.common.realtime import Ratekeeper

from openpilot.system.ui.iqpilot.lib.application import IQAppHooks
from openpilot.system.ui.lib.screen_recorder import ScreenRecorder

_DEFAULT_FPS = int(os.getenv("FPS", {'tizi': 20, 'tici': 20}.get(HARDWARE.get_device_type(), 60)))
# Benign raylib warnings emitted on the headless DRM/EGL target (no window manager / monitor).
# These repeat on every UI init and carry no signal; the trace-log callback drops them.
_RAYLIB_BENIGN_WARNINGS = (
  "SetWindowState() not available on target platform",
  "GetCurrentMonitor() not implemented on target platform",
  "GetMonitorRefreshRate() not implemented on target platform",
)
FPS_LOG_INTERVAL = 5  # Seconds between logging FPS drops
FPS_DROP_THRESHOLD = 0.9  # FPS drop threshold for triggering a warning
FPS_CRITICAL_THRESHOLD = 0.5  # Critical threshold for triggering strict actions
MOUSE_THREAD_RATE = 140  # touch controller runs at 140Hz
MAX_TOUCH_SLOTS = 2
TOUCH_HISTORY_TIMEOUT = 3.0  # Seconds before touch points fade out

BIG_UI = os.getenv("BIG", "0") == "1"
SMALL_UI = os.getenv("SMALL", "0") == "1"
ENABLE_VSYNC = os.getenv("ENABLE_VSYNC", "1") != "0"
VSYNC_REAPPLY_INTERVAL = float(os.getenv("VSYNC_REAPPLY_INTERVAL", "1.0"))
DISPLAY_SYNC_BEFORE_SWAP = os.getenv("UI_DISPLAY_SYNC_BEFORE_SWAP", "1" if not PC else "0") != "0"
SHOW_FPS = os.getenv("SHOW_FPS") == "1"
SHOW_TEMP_FPS = os.getenv("SHOW_TEMP_FPS") == "1"
SHOW_TOUCHES = os.getenv("SHOW_TOUCHES") == "1"
STRICT_MODE = os.getenv("STRICT_MODE") == "1"
SCALE = float(os.getenv("SCALE", "1.0"))
GRID_SIZE = int(os.getenv("GRID", "0"))
PROFILE_RENDER = int(os.getenv("PROFILE_RENDER", "0"))
PROFILE_STATS = int(os.getenv("PROFILE_STATS", "100"))  # Number of functions to show in profile output
RECORD = os.getenv("RECORD") == "1"
RECORD_OUTPUT = str(Path(os.getenv("RECORD_OUTPUT", "output")).with_suffix(".mp4"))
RECORD_BITRATE = os.getenv("RECORD_BITRATE", "")  # Target bitrate e.g. "2000k"
RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier
OFFSCREEN = os.getenv("OFFSCREEN") == "1"  # Disable FPS limiting for fast offline rendering

GL_VERSION = """
#version 300 es
precision highp float;
"""
if platform.system() == "Darwin":
  GL_VERSION = """
    #version 330 core
  """

BURN_IN_MODE = "BURN_IN" in os.environ
BURN_IN_VERTEX_SHADER = GL_VERSION + """
in vec3 vertexPosition;
in vec2 vertexTexCoord;
uniform mat4 mvp;
out vec2 fragTexCoord;
void main() {
  fragTexCoord = vertexTexCoord;
  gl_Position = mvp * vec4(vertexPosition, 1.0);
}
"""
BURN_IN_FRAGMENT_SHADER = GL_VERSION + """
in vec2 fragTexCoord;
uniform sampler2D texture0;
out vec4 fragColor;
void main() {
  vec4 sampled = texture(texture0, fragTexCoord);
  float intensity = sampled.b;
  // Map blue intensity to green -> yellow -> red to highlight burn-in risk.
  vec3 start = vec3(0.0, 1.0, 0.0);
  vec3 middle = vec3(1.0, 1.0, 0.0);
  vec3 end = vec3(1.0, 0.0, 0.0);
  vec3 gradient = mix(start, middle, clamp(intensity * 2.0, 0.0, 1.0));
  gradient = mix(gradient, end, clamp((intensity - 0.5) * 2.0, 0.0, 1.0));
  fragColor = vec4(gradient, sampled.a);
}
"""

DEFAULT_TEXT_SIZE = 60
DEFAULT_TEXT_COLOR = rl.Color(255, 255, 255, int(255 * 0.9))

# Qt draws fonts accounting for ascent/descent differently, so compensate to match old styles
# The real scales for the fonts below range from 1.212 to 1.266
FONT_SCALE = 1.242 if BIG_UI else 1.16

ASSETS_DIR = files("openpilot.selfdrive").joinpath("assets")
FONT_DIR = ASSETS_DIR.joinpath("fonts")


class FontWeight(StrEnum):
  LIGHT = "Inter-Light.fnt"
  NORMAL = "Inter-Regular.fnt" if BIG_UI else "Inter-Medium.fnt"
  MEDIUM = "Inter-Medium.fnt"
  BOLD = "Inter-Bold.fnt"
  SEMI_BOLD = "Inter-SemiBold.fnt"
  UNIFONT = "unifont.fnt"
  AUDIOWIDE = "Audiowide-Regular.fnt"
  SYNCOPATE = "Syncopate-Regular.fnt"

  # Small UI fonts
  DISPLAY_REGULAR = "Inter-Regular.fnt"
  ROMAN = "Inter-Regular.fnt"
  DISPLAY = "Inter-Bold.fnt"


FONT_SOURCE_FILES = {
  FontWeight.LIGHT: "Inter-Light.ttf",
  FontWeight.NORMAL: "Inter-Regular.ttf" if BIG_UI else "Inter-Medium.ttf",
  FontWeight.MEDIUM: "Inter-Medium.ttf",
  FontWeight.BOLD: "Inter-Bold.ttf",
  FontWeight.SEMI_BOLD: "Inter-SemiBold.ttf",
  FontWeight.UNIFONT: "unifont.otf",
  FontWeight.AUDIOWIDE: "Audiowide-Regular.ttf",
  FontWeight.SYNCOPATE: "Syncopate-Regular.ttf",
  FontWeight.DISPLAY_REGULAR: "Inter-Regular.ttf",
  FontWeight.ROMAN: "Inter-Regular.ttf",
  FontWeight.DISPLAY: "Inter-Bold.ttf",
}


def font_fallback(font: rl.Font) -> rl.Font:
  """Fall back to unifont for languages that require it."""
  if multilang.requires_unifont():
    return gui_app.font(FontWeight.UNIFONT)
  return font


@dataclass
class ModalOverlay:
  overlay: object = None
  callback: Callable | None = None


class MousePos(NamedTuple):
  x: float
  y: float


class MousePosWithTime(NamedTuple):
  x: float
  y: float
  t: float


class MouseEvent(NamedTuple):
  pos: MousePos
  slot: int
  left_pressed: bool
  left_released: bool
  left_down: bool
  t: float


class MouseState:
  def __init__(self, scale: float = 1.0):
    self._scale = scale
    self._events: deque[MouseEvent] = deque(maxlen=MOUSE_THREAD_RATE)  # bound event list
    self._prev_mouse_event: list[MouseEvent | None] = [None] * MAX_TOUCH_SLOTS

    self._rk = Ratekeeper(MOUSE_THREAD_RATE, print_delay_threshold=None)
    self._lock = threading.Lock()
    self._exit_event = threading.Event()
    self._thread = None

  def get_events(self) -> list[MouseEvent]:
    with self._lock:
      events = list(self._events)
      self._events.clear()
    return events

  def start(self):
    self._exit_event.clear()
    if self._thread is None or not self._thread.is_alive():
      self._thread = threading.Thread(target=self._run_thread, daemon=True)
      self._thread.start()

  def stop(self):
    self._exit_event.set()
    if self._thread is not None and self._thread.is_alive():
      self._thread.join()

  def _run_thread(self):
    while not self._exit_event.is_set():
      rl.poll_input_events()
      self._handle_mouse_event()
      self._rk.keep_time()

  def _handle_mouse_event(self):
    for slot in range(MAX_TOUCH_SLOTS):
      mouse_pos = rl.get_touch_position(slot)
      x = mouse_pos.x / self._scale if self._scale != 1.0 else mouse_pos.x
      y = mouse_pos.y / self._scale if self._scale != 1.0 else mouse_pos.y
      ev = MouseEvent(
        MousePos(x, y),
        slot,
        rl.is_mouse_button_pressed(slot),  # noqa: TID251
        rl.is_mouse_button_released(slot),  # noqa: TID251
        rl.is_mouse_button_down(slot),
        time.monotonic(),
      )
      # Only add changes
      prev = self._prev_mouse_event[slot]
      if prev is None or ev[:-1] != prev[:-1]:
        with self._lock:
          self._events.append(ev)
        self._prev_mouse_event[slot] = ev


class GuiApplication(IQAppHooks):
  def __init__(self, width: int | None = None, height: int | None = None):
    self._set_log_callback()

    self._fonts: dict[FontWeight, rl.Font] = {}
    self._width = width if width is not None else GuiApplication._default_width()
    self._height = height if height is not None else GuiApplication._default_height()

    if PC and os.getenv("SCALE") is None:
      self._scale = self._calculate_auto_scale()
    else:
      self._scale = SCALE

    # Scale, then ensure dimensions are even
    self._scaled_width = int(self._width * self._scale)
    self._scaled_height = int(self._height * self._scale)
    self._scaled_width += self._scaled_width % 2
    self._scaled_height += self._scaled_height % 2

    self._render_texture: rl.RenderTexture | None = None
    self._screen_recorder: ScreenRecorder | None = None
    self._burn_in_shader: rl.Shader | None = None
    self._ffmpeg_proc: subprocess.Popen | None = None
    self._ffmpeg_queue: queue.Queue | None = None
    self._ffmpeg_thread: threading.Thread | None = None
    self._ffmpeg_stop_event: threading.Event | None = None
    self._textures: dict[str, rl.Texture] = {}
    self._target_fps: int = _DEFAULT_FPS
    self._last_frame_pacing_refresh_time: float = 0.0
    # Last swap interval we told EGL to use, and whether vsync is the active pacer. The Adreno/GBM
    # EGL silently drops the swap interval back to 0 (intermittent screen tearing on scroll), so we
    # re-assert it cheaply every frame — see _refresh_frame_pacing_if_needed.
    self._vsync_interval: int = 0
    self._paced_by_vsync: bool = False
    self._last_fps_log_time: float = time.monotonic()
    self._frame = 0
    self._window_close_requested = False
    self._modal_overlay = ModalOverlay()
    self._modal_overlay_shown = False
    self._modal_overlay_tick: Callable[[], None] | None = None

    self._nav_stack: list[object] = []
    self._nav_stack_ticks: list[Callable[[], None]] = []
    self._nav_stack_widgets_to_render = 1 if self.big_ui() else 2

    self._mouse = MouseState(self._scale)
    self._mouse_events: list[MouseEvent] = []
    self._last_mouse_event: MouseEvent = MouseEvent(MousePos(0, 0), 0, False, False, False, 0.0)

    self._should_render = True
    self._display_sync_available: bool | None = None

    # Debug variables
    self._mouse_history: deque[MousePosWithTime] = deque(maxlen=MOUSE_THREAD_RATE)
    self._show_touches = SHOW_TOUCHES
    self._show_fps = SHOW_FPS
    self._grid_size = GRID_SIZE
    self._profile_render_frames = PROFILE_RENDER
    self._render_profiler = None
    self._render_profile_start_time = None

    IQAppHooks.__init__(self)

  @property
  def frame(self):
    return self._frame

  def set_show_touches(self, show: bool):
    self._show_touches = show

  def set_show_fps(self, show: bool):
    self._show_fps = show

  @property
  def target_fps(self):
    return self._target_fps

  def _monitor_refresh_rate(self) -> int:
    if not rl.is_window_ready():
      return 60
    try:
      monitor = rl.get_current_monitor()
      if monitor < 0:  # PC: GLFW can fail to resolve a monitor; the C call segfaults on -1
        return 60
      refresh = int(rl.get_monitor_refresh_rate(monitor))
    except Exception:
      refresh = 60
    return max(1, refresh or 60)

  def _apply_vsync_interval(self, fps: int) -> bool:
    if OFFSCREEN or not rl.is_window_ready() or not ENABLE_VSYNC:
      if hasattr(rl, "glfw_swap_interval") and rl.is_window_ready() and not OFFSCREEN:
        try:
          rl.glfw_swap_interval(0)
        except Exception:
          pass
      if not PC and rl.is_window_ready() and not OFFSCREEN:
        try:
          from openpilot.system.ui.lib.egl import set_swap_interval
          set_swap_interval(0)
        except Exception:
          pass
      return False

    if hasattr(rl, "set_window_state"):
      rl.set_window_state(rl.ConfigFlags.FLAG_VSYNC_HINT)

    refresh = self._monitor_refresh_rate()
    interval = 1 if fps >= refresh else max(1, round(refresh / fps))

    glfw_vsync = False
    if hasattr(rl, "glfw_swap_interval"):
      try:
        rl.glfw_swap_interval(interval)
        glfw_vsync = True
      except Exception:
        glfw_vsync = False

    egl_vsync = False
    if not PC:
      try:
        from openpilot.system.ui.lib.egl import set_swap_interval
        egl_vsync = set_swap_interval(interval)
      except Exception:
        egl_vsync = False

    paced = glfw_vsync or egl_vsync
    self._paced_by_vsync = paced
    self._vsync_interval = interval if paced else 0
    return paced

  @staticmethod
  def _flush_raylib_batch() -> None:
    if hasattr(rl, "rl_draw_render_batch_active"):
      rl.rl_draw_render_batch_active()

  def _apply_display_sync_before_swap(self) -> None:
    if PC or OFFSCREEN or not DISPLAY_SYNC_BEFORE_SWAP or self._display_sync_available is False:
      return
    try:
      self._flush_raylib_batch()
      from openpilot.system.ui.lib.egl import finish_gl
      self._display_sync_available = finish_gl()
    except Exception:
      self._display_sync_available = False

  def _apply_target_fps(self, fps: int):
    fps = max(1, int(fps))
    paced_by_vsync = self._apply_vsync_interval(fps)
    rl.set_target_fps(0 if OFFSCREEN or paced_by_vsync else fps)
    self._target_fps = fps
    self._last_frame_pacing_refresh_time = time.monotonic()

  def set_target_fps(self, fps: int):
    fps = max(1, int(fps))
    if fps != self._target_fps:
      self._apply_target_fps(fps)

  def _refresh_frame_pacing_if_needed(self):
    if not ENABLE_VSYNC or OFFSCREEN:
      return
    # The Adreno/GBM EGL silently resets the swap interval back to 0, which shows up as
    # intermittent screen tearing when scrolling (the content moves, so a mid-scanout swap is
    # visible). eglSwapInterval is a trivial call, so re-assert it every frame to keep FIFO vsync
    # pinned instead of relying on the slow (VSYNC_REAPPLY_INTERVAL) full re-apply below.
    if self._paced_by_vsync and self._vsync_interval > 0 and not PC and rl.is_window_ready():
      try:
        from openpilot.system.ui.lib.egl import set_swap_interval
        set_swap_interval(self._vsync_interval)
      except Exception:
        pass
    if VSYNC_REAPPLY_INTERVAL > 0 and time.monotonic() - self._last_frame_pacing_refresh_time >= VSYNC_REAPPLY_INTERVAL:
      self._apply_target_fps(self._target_fps)

  def request_close(self):
    self._window_close_requested = True

  def init_window(self, title: str, fps: int = _DEFAULT_FPS, screen_recordable: bool = False):
    with self._startup_profile_context():
      def _close(sig, frame):
        self.close()
        sys.exit(0)
      signal.signal(signal.SIGINT, _close)
      atexit.register(self.close)

      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT
      if ENABLE_VSYNC and not OFFSCREEN:
        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT
      rl.set_config_flags(flags)

      rl.init_window(self._scaled_width, self._scaled_height, title)

      needs_render_texture = self._scale != 1.0 or BURN_IN_MODE or RECORD
      if self._scale != 1.0:
        rl.set_mouse_scale(1 / self._scale, 1 / self._scale)
      if needs_render_texture:
        self._render_texture = rl.load_render_texture(self._width, self._height)
        rl.set_texture_filter(self._render_texture.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

      if RECORD:
        output_fps = fps * RECORD_SPEED
        ffmpeg_args = [
          'ffmpeg',
          '-v', 'warning',          # Reduce ffmpeg log spam
          '-nostats',               # Suppress encoding progress
          '-f', 'rawvideo',         # Input format
          '-pix_fmt', 'rgba',       # Input pixel format
          '-s', f'{self._width}x{self._height}',  # Input resolution
          '-r', str(fps),           # Input frame rate
          '-i', 'pipe:0',           # Input from stdin
          '-vf', 'vflip,format=yuv420p',  # Flip vertically and convert to yuv420p
          '-r', str(output_fps),    # Output frame rate (for speed multiplier)
          '-c:v', 'libx264',
          '-preset', 'ultrafast',
        ]
        if RECORD_BITRATE:
          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]
        ffmpeg_args += [
          '-y',                     # Overwrite existing file
          '-f', 'mp4',              # Output format
          RECORD_OUTPUT,            # Output file path
        ]
        self._ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE)
        self._ffmpeg_queue = queue.Queue(maxsize=60)  # Buffer up to 60 frames
        self._ffmpeg_stop_event = threading.Event()
        self._ffmpeg_thread = threading.Thread(target=self._ffmpeg_writer_thread, daemon=True)
        self._ffmpeg_thread.start()

      self._apply_target_fps(fps)
      if screen_recordable and not OFFSCREEN and not RECORD:
        self._screen_recorder = ScreenRecorder(self._width, self._height, fps)
      self._set_styles()
      self._load_fonts()
      self._patch_text_functions()
      if BURN_IN_MODE and self._burn_in_shader is None:
        self._burn_in_shader = rl.load_shader_from_memory(BURN_IN_VERTEX_SHADER, BURN_IN_FRAGMENT_SHADER)

      if not PC:
        self._mouse.start()

  @contextmanager
  def _startup_profile_context(self):
    if "PROFILE_STARTUP" not in os.environ:
      yield
      return

    import cProfile
    import io
    import pstats

    profiler = cProfile.Profile()
    start_time = time.monotonic()
    profiler.enable()

    # do the init
    yield

    profiler.disable()
    elapsed_ms = (time.monotonic() - start_time) * 1e3

    stats_stream = io.StringIO()
    pstats.Stats(profiler, stream=stats_stream).sort_stats("cumtime").print_stats(25)
    print("\n=== Startup profile ===")
    print(stats_stream.getvalue().rstrip())

    green = "\033[92m"
    reset = "\033[0m"
    print(f"{green}UI window ready in {elapsed_ms:.1f} ms{reset}")
    sys.exit(0)

  def _ffmpeg_writer_thread(self):
    """Background thread that writes frames to ffmpeg."""
    while True:
      try:
        data = self._ffmpeg_queue.get(timeout=1.0)
        if data is None:  # Sentinel to stop
          break
        self._ffmpeg_proc.stdin.write(data)
      except queue.Empty:
        if self._ffmpeg_stop_event.is_set():
          break
        continue
      except Exception:
        break

  def set_modal_overlay(self, overlay, callback: Callable | None = None):
    if self._modal_overlay.overlay is not None:
      if hasattr(self._modal_overlay.overlay, 'hide_event'):
        self._modal_overlay.overlay.hide_event()

      if self._modal_overlay.callback is not None:
        self._modal_overlay.callback(-1)

    self._modal_overlay = ModalOverlay(overlay=overlay, callback=callback)

    # NavWidget dialogs (keyboard, confirm, etc.) return None from render() and self-close via an
    # exit callback rather than a render result. Bridge them onto the legacy modal API so callers
    # that still use set_modal_overlay (e.g. the setup's wifi password keyboard) keep working:
    # clear the overlay and fire the modal callback when the NavWidget finishes.
    if overlay is not None and hasattr(overlay, 'set_exit_callback'):
      def _nav_exit(result, _ov=overlay, _cb=callback):
        if self._modal_overlay.overlay is _ov:
          self._modal_overlay = ModalOverlay()
        if _cb is not None:
          _cb(result)
      overlay.set_exit_callback(_nav_exit)

  def set_modal_overlay_tick(self, tick_function: Callable | None):
    self._modal_overlay_tick = tick_function


  def push_widget(self, widget: object):
    if widget in self._nav_stack:
      cloudlog.warning("Widget already in stack, cannot push again!")
      return

    if len(self._nav_stack) > 0:
      prev_widget = self._nav_stack[-1]
      prev_widget.set_enabled(False)
      # The press that opened this new page may have armed a swipe/drag on the page now being
      # covered. It won't be rendered while covered, so its own cleanup can't run; clear that
      # stale state now so it doesn't track the finger the instant it's revealed again.
      settle = getattr(prev_widget, "settle_to_top", None)
      if settle is not None:
        settle()

    self._nav_stack.append(widget)
    widget.show_event()
    widget.set_enabled(True)

  def pop_widget(self, idx: int | None = None):
    if len(self._nav_stack) < 2:
      cloudlog.warning("At least one widget should remain on the stack, ignoring pop!")
      return

    idx_to_pop = len(self._nav_stack) - 1 if idx is None else idx
    if idx_to_pop <= 0 or idx_to_pop >= len(self._nav_stack):
      cloudlog.warning(f"Invalid index {idx_to_pop} to pop, ignoring!")
      return

    if idx_to_pop == len(self._nav_stack) - 1:
      prev_widget = self._nav_stack[idx_to_pop - 1]
      prev_widget.set_enabled(True)
      # The revealed page was hidden (not rendered) while covered, so an in-flight slide-in
      # animation is frozen mid-way. Settle it to rest so it appears in place instead of
      # bouncing/sliding in when it becomes visible again.
      settle = getattr(prev_widget, "settle_to_top", None)
      if settle is not None:
        settle()

    widget = self._nav_stack.pop(idx_to_pop)
    widget.hide_event()

  def pop_widgets_to(self, widget: object, callback: Callable[[], None] | None = None, instant: bool = False):
    if widget not in self._nav_stack:
      cloudlog.warning("Widget not in stack, cannot pop to it!")
      return

    top_widget = self._nav_stack[-1]
    if top_widget == widget:
      if callback:
        callback()
      return

    while len(self._nav_stack) > 1 and self._nav_stack[-2] != widget:
      self.pop_widget(len(self._nav_stack) - 2)

    if not instant:
      top_widget.dismiss(callback)
    else:
      self.pop_widget()

  def get_active_widget(self):
    if len(self._nav_stack) > 0:
      return self._nav_stack[-1]
    return None

  def widget_in_stack(self, widget: object) -> bool:
    return widget in self._nav_stack

  def add_nav_stack_tick(self, tick_function: Callable[[], None]):
    if tick_function not in self._nav_stack_ticks:
      self._nav_stack_ticks.append(tick_function)

  def remove_nav_stack_tick(self, tick_function: Callable[[], None]):
    if tick_function in self._nav_stack_ticks:
      self._nav_stack_ticks.remove(tick_function)

  @property
  def screen_recorder_active(self) -> bool:
    return self._screen_recorder is not None and self._screen_recorder.active

  def set_should_render(self, should_render: bool):
    if should_render and not self._should_render:
      self._apply_target_fps(self._target_fps)
    self._should_render = should_render

  def texture(self, asset_path: str, width: int | None = None, height: int | None = None,
              alpha_premultiply=False, keep_aspect_ratio=True):
    cache_key = f"{asset_path}_{width}_{height}_{alpha_premultiply}{keep_aspect_ratio}"
    if cache_key in self._textures:
      return self._textures[cache_key]

    with as_file(ASSETS_DIR.joinpath(asset_path)) as fspath:
      image_obj = self._load_image_from_path(fspath.as_posix(), width, height, alpha_premultiply, keep_aspect_ratio)
      texture_obj = self._load_texture_from_image(image_obj)
    self._textures[cache_key] = texture_obj
    return texture_obj

  def _load_image_from_path(self, image_path: str, width: int | None = None, height: int | None = None,
                            alpha_premultiply: bool = False, keep_aspect_ratio: bool = True) -> rl.Image:
    """Load and resize an image, storing it for later automatic unloading."""
    image = rl.load_image(image_path)

    if alpha_premultiply:
      rl.image_alpha_premultiply(image)

    if width is not None and height is not None:
      same_dimensions = image.width == width and image.height == height

      # Resize with aspect ratio preservation if requested
      if not same_dimensions:
        if keep_aspect_ratio:
          orig_width = image.width
          orig_height = image.height

          if orig_width == 0 or orig_height == 0:
            # Image failed to load (e.g. missing file); skip resize
            return image

          scale_width = width / orig_width
          scale_height = height / orig_height

          # Calculate new dimensions
          scale = min(scale_width, scale_height)
          new_width = int(orig_width * scale)
          new_height = int(orig_height * scale)

          rl.image_resize(image, new_width, new_height)
        else:
          rl.image_resize(image, width, height)
    else:
      assert keep_aspect_ratio, "Cannot resize without specifying width and height"
    return image

  def _load_texture_from_image(self, image: rl.Image) -> rl.Texture:
    """Send image to GPU and unload original image."""
    texture = rl.load_texture_from_image(image)
    # Set texture filtering to smooth the result
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    # prevent artifacts from wrapping coordinates
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)

    rl.unload_image(image)
    return texture

  def close_ffmpeg(self):
    if self._ffmpeg_thread is not None:
      # Signal thread to stop, send sentinel, then wait for it to drain
      self._ffmpeg_stop_event.set()
      self._ffmpeg_queue.put(None)
      self._ffmpeg_thread.join(timeout=30)

    if self._ffmpeg_proc is not None:
      self._ffmpeg_proc.stdin.flush()
      self._ffmpeg_proc.stdin.close()
      try:
        self._ffmpeg_proc.wait(timeout=30)
      except subprocess.TimeoutExpired:
        self._ffmpeg_proc.terminate()
        self._ffmpeg_proc.wait()

  def close(self):
    if not rl.is_window_ready():
      return

    if self._screen_recorder is not None:
      self._screen_recorder.close()
      self._screen_recorder = None

    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures = {}

    for font in self._fonts.values():
      rl.unload_font(font)
    self._fonts = {}

    if self._render_texture is not None:
      rl.unload_render_texture(self._render_texture)
      self._render_texture = None

    if self._burn_in_shader:
      rl.unload_shader(self._burn_in_shader)
      self._burn_in_shader = None

    if not PC:
      self._mouse.stop()

    self.close_ffmpeg()

    rl.close_window()

  @property
  def mouse_events(self) -> list[MouseEvent]:
    return self._mouse_events

  @property
  def last_mouse_event(self) -> MouseEvent:
    return self._last_mouse_event

  def render(self):
    try:
      if self._profile_render_frames > 0:
        import cProfile
        self._render_profiler = cProfile.Profile()
        self._render_profile_start_time = time.monotonic()
        self._render_profiler.enable()

      while not (self._window_close_requested or rl.window_should_close()):
        if PC:
          # Thread is not used on PC, need to manually add mouse events
          self._mouse._handle_mouse_event()

        # Store all mouse events for the current frame
        self._mouse_events = self._mouse.get_events()
        if len(self._mouse_events) > 0:
          self._last_mouse_event = self._mouse_events[-1]

        # Skip rendering when screen is off
        if not self._should_render:
          if self._screen_recorder is not None:
            self._screen_recorder.update(self._render_texture)
          if PC:
            rl.poll_input_events()
          time.sleep(1 / self._target_fps)
          yield False
          continue

        self._refresh_frame_pacing_if_needed()

        capture_now = False
        if self._screen_recorder is not None:
          self._screen_recorder.update(self._render_texture)
          capture_now = self._screen_recorder.begin_frame()
        frame_rt = self._render_texture
        # Only reroute through the recorder's RenderTexture (and pay the extra present-blit)
        # on frames we will actually capture.
        if frame_rt is None and capture_now:
          frame_rt = self._screen_recorder.render_texture

        if frame_rt:
          rl.begin_texture_mode(frame_rt)
          rl.clear_background(rl.BLACK)
        else:
          rl.begin_drawing()
          rl.clear_background(rl.BLACK)

        for tick in self._nav_stack_ticks:
          tick()
        to_render = self._nav_stack[-self._nav_stack_widgets_to_render:]
        # Skip widgets fully hidden behind an opaque, settled top widget (e.g. the onroad
        # camera view underneath the settings) — avoids redrawing them every frame.
        if len(to_render) > 1:
          covers = getattr(to_render[-1], 'covers_below', None)
          if covers is not None and covers():
            to_render = to_render[-1:]
        for widget in to_render:
          widget.render(rl.Rectangle(0, 0, self.width, self.height))

        # Handle modal overlay rendering and input processing
        if self._handle_modal_overlay():
          # Allow a Widget to still run a function while overlay is shown
          if self._modal_overlay_tick is not None:
            self._modal_overlay_tick()
          yield False
        else:
          yield True

        if frame_rt:
          rl.end_texture_mode()
          rl.begin_drawing()
          rl.clear_background(rl.BLACK)
          src_rect = rl.Rectangle(0, 0, float(self._width), -float(self._height))
          dst_rect = rl.Rectangle(0, 0, float(self._scaled_width), float(self._scaled_height))
          texture = frame_rt.texture
          if texture:
            if BURN_IN_MODE and self._burn_in_shader:
              rl.begin_shader_mode(self._burn_in_shader)
              rl.draw_texture_pro(texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
              rl.end_shader_mode()
            else:
              rl.draw_texture_pro(texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)

        # REC dot drawn to the screen every active frame (not into the recorder RT, so it
        # neither flickers on non-capture frames nor bloats the video)
        if self._screen_recorder is not None and self._screen_recorder.active:
          self._screen_recorder.draw_indicator(self._scaled_width)

        if self._show_fps:
          rl.draw_fps(10, 10)

        if SHOW_TEMP_FPS:
          self._draw_tiny_fps()

        if self._show_touches:
          self._draw_touch_points()

        if self.pointer_probe_enabled:
          self.draw_pointer_probe(gui_app.font(FontWeight.SEMI_BOLD))

        if self._grid_size > 0:
          self._draw_grid()

        self._apply_display_sync_before_swap()
        # Re-assert vsync FIFO one more time immediately before the swap. The pre-frame re-assert
        # (_refresh_frame_pacing_if_needed) isn't enough during video playback: uploading/drawing a
        # full-res frame texture can make the Adreno/GBM driver silently reset the swap interval to 0
        # *after* that call but before this swap, which reintroduced tearing. This is the swap that
        # actually matters, so pin the interval here too.
        if (ENABLE_VSYNC and not OFFSCREEN and not PC and self._paced_by_vsync
            and self._vsync_interval > 0 and rl.is_window_ready()):
          try:
            from openpilot.system.ui.lib.egl import set_swap_interval
            set_swap_interval(self._vsync_interval)
          except Exception:
            pass
        rl.end_drawing()

        if RECORD:
          image = rl.load_image_from_texture(self._render_texture.texture)
          data_size = image.width * image.height * 4
          data = bytes(rl.ffi.buffer(image.data, data_size))
          self._ffmpeg_queue.put(data)  # Async write via background thread
          rl.unload_image(image)

        if self._screen_recorder is not None and self._screen_recorder.active and frame_rt:
          self._screen_recorder.capture(frame_rt)

        self._monitor_fps()
        self._frame += 1

        if self._profile_render_frames > 0 and self._frame >= self._profile_render_frames:
          self._output_render_profile()
    except KeyboardInterrupt:
      pass

  def font(self, font_weight: FontWeight = FontWeight.NORMAL) -> rl.Font:
    return self._fonts[font_weight]

  @property
  def width(self):
    return self._width

  @property
  def height(self):
    return self._height

  def _handle_modal_overlay(self) -> bool:
    if self._modal_overlay.overlay:
      if hasattr(self._modal_overlay.overlay, 'render'):
        result = self._modal_overlay.overlay.render(rl.Rectangle(0, 0, self.width, self.height))
      elif callable(self._modal_overlay.overlay):
        result = self._modal_overlay.overlay()
      else:
        raise Exception

      # Send show event to Widget
      if not self._modal_overlay_shown and hasattr(self._modal_overlay.overlay, 'show_event'):
        self._modal_overlay.overlay.show_event()
        self._modal_overlay_shown = True

      # NavWidget overlays return None (they self-close via their exit callback, wired up in
      # set_modal_overlay); only legacy overlays return an int result to act on here.
      if result is not None and result >= 0:
        # Clear the overlay and execute the callback
        original_modal = self._modal_overlay
        self._modal_overlay = ModalOverlay()
        if hasattr(original_modal.overlay, 'hide_event'):
          original_modal.overlay.hide_event()
        if original_modal.callback is not None:
          original_modal.callback(result)
      return True
    else:
      self._modal_overlay_shown = False
      return False

  def _load_fonts(self):
    with as_file(FONT_DIR) as fspath:
      for font_weight_file in FontWeight:
        fnt_path = fspath / font_weight_file
        if fnt_path.is_file():
          font = rl.load_font(fnt_path.as_posix())
        else:
          source_name = FONT_SOURCE_FILES[font_weight_file]
          source_path = fspath / source_name
          cloudlog.warning(f"font atlas missing for {font_weight_file}, loading source font {source_name}")
          font = rl.load_font_ex(source_path.as_posix(), 120, None, 0)
        if font_weight_file != FontWeight.UNIFONT:
          rl.gen_texture_mipmaps(font.texture)
          rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
        self._fonts[font_weight_file] = font
    rl.gui_set_font(self._fonts[FontWeight.NORMAL])

  def _set_styles(self):
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.BORDER_WIDTH, 0)
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiDefaultProperty.TEXT_SIZE, DEFAULT_TEXT_SIZE)
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiDefaultProperty.BACKGROUND_COLOR, rl.color_to_int(rl.BLACK))
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.TEXT_COLOR_NORMAL, rl.color_to_int(DEFAULT_TEXT_COLOR))
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.BASE_COLOR_NORMAL, rl.color_to_int(rl.Color(50, 50, 50, 255)))

  def _patch_text_functions(self):
    # Wrap pyray text APIs to apply a global text size scale so our px sizes match Qt
    if not hasattr(rl, "_orig_draw_text_ex"):
      rl._orig_draw_text_ex = rl.draw_text_ex

    def _draw_text_ex_scaled(font, text, position, font_size, spacing, tint):
      font = font_fallback(font)
      return rl._orig_draw_text_ex(font, text, position, font_size * FONT_SCALE, spacing, tint)

    rl.draw_text_ex = _draw_text_ex_scaled

  def _set_log_callback(self):
    ffi_libc = cffi.FFI()
    ffi_libc.cdef("""
      int vasprintf(char **strp, const char *fmt, void *ap);
      void free(void *ptr);
    """)
    libc = ffi_libc.dlopen(None)

    @rl.ffi.callback("void(int, char *, void *)")
    def trace_log_callback(log_level, text, args):
      try:
        text_addr = int(rl.ffi.cast("uintptr_t", text))
        args_addr = int(rl.ffi.cast("uintptr_t", args))
        text_libc = ffi_libc.cast("char *", text_addr)
        args_libc = ffi_libc.cast("void *", args_addr)

        out = ffi_libc.new("char **")
        if libc.vasprintf(out, text_libc, args_libc) >= 0 and out[0] != ffi_libc.NULL:
          text_str = ffi_libc.string(out[0]).decode("utf-8", "replace")
          libc.free(out[0])
        else:
          text_str = rl.ffi.string(text).decode("utf-8", "replace")
      except Exception as e:
        text_str = f"[Log decode error: {e}]"

      # raylib emits a fixed set of benign "not implemented on target platform" warnings on the
      # comma's headless DRM/EGL backend (no window manager or monitor object). They carry no
      # signal, repeat on every UI (re)init, and drown the log/tmux. Drop them entirely.
      if any(s in text_str for s in _RAYLIB_BENIGN_WARNINGS):
        return

      if log_level == rl.TraceLogLevel.LOG_ERROR:
        cloudlog.error(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_WARNING:
        cloudlog.warning(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_INFO:
        cloudlog.info(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_DEBUG:
        cloudlog.debug(f"raylib: {text_str}")
      else:
        cloudlog.error(f"raylib: Unknown level {log_level}: {text_str}")

    # ensure we get all the logs forwarded to us
    rl.set_trace_log_level(rl.TraceLogLevel.LOG_DEBUG)

    # Store callback reference
    self._trace_log_callback = trace_log_callback
    rl.set_trace_log_callback(self._trace_log_callback)

  def _monitor_fps(self):
    fps = rl.get_fps()

    # Log FPS drop below threshold at regular intervals
    if fps < self._target_fps * FPS_DROP_THRESHOLD:
      current_time = time.monotonic()
      if current_time - self._last_fps_log_time >= FPS_LOG_INTERVAL:
        # debug not warning: transient drops shouldn't spam the shared console
        cloudlog.debug(f"FPS dropped below {self._target_fps}: {fps}")
        self._last_fps_log_time = current_time

    # Strict mode: terminate UI if FPS drops too much
    if STRICT_MODE and fps < self._target_fps * FPS_CRITICAL_THRESHOLD:
      cloudlog.error(f"FPS dropped critically below {fps}. Shutting down UI.")
      self.close_ffmpeg()
      os._exit(1)

  def _draw_touch_points(self):
    current_time = time.monotonic()

    for mouse_event in self._mouse_events:
      if mouse_event.left_pressed:
        self._mouse_history.clear()
      self._mouse_history.append(MousePosWithTime(mouse_event.pos.x * self._scale, mouse_event.pos.y * self._scale, current_time))

    # Remove old touch points that exceed the timeout
    while self._mouse_history and (current_time - self._mouse_history[0].t) > TOUCH_HISTORY_TIMEOUT:
      self._mouse_history.popleft()

    if self._mouse_history:
      mouse_pos = self._mouse_history[-1]
      rl.draw_circle(int(mouse_pos.x), int(mouse_pos.y), 15, rl.RED)
      for idx, mouse_pos in enumerate(self._mouse_history):
        perc = idx / len(self._mouse_history)
        color = rl.Color(min(int(255 * (1.5 - perc)), 255), int(min(255 * (perc + 0.5), 255)), 50, 255)
        rl.draw_circle(int(mouse_pos.x), int(mouse_pos.y), 5, color)

  def _draw_grid(self):
    grid_color = rl.Color(60, 60, 60, 255)
    # Draw vertical lines
    x = 0
    while x <= self._scaled_width:
      rl.draw_line(x, 0, x, self._scaled_height, grid_color)
      x += self._grid_size
    # Draw horizontal lines
    y = 0
    while y <= self._scaled_height:
      rl.draw_line(0, y, self._scaled_width, y, grid_color)
      y += self._grid_size

  def _draw_tiny_fps(self):
    text = f"{rl.get_fps()} FPS"
    font_size = 22
    font = self.font(FontWeight.MEDIUM)
    rl.draw_text_ex(font, text, rl.Vector2(12, self._scaled_height - 34), font_size, 0, rl.Color(210, 210, 210, 170))

  def _output_render_profile(self):
    import io
    import pstats

    self._render_profiler.disable()
    elapsed_ms = (time.monotonic() - self._render_profile_start_time) * 1e3
    avg_frame_time = elapsed_ms / self._frame if self._frame > 0 else 0

    stats_stream = io.StringIO()
    pstats.Stats(self._render_profiler, stream=stats_stream).sort_stats("cumtime").print_stats(PROFILE_STATS)
    print("\n=== Render loop profile ===")
    print(stats_stream.getvalue().rstrip())

    green = "\033[92m"
    reset = "\033[0m"
    print(f"\n{green}Rendered {self._frame} frames in {elapsed_ms:.1f} ms{reset}")
    print(f"{green}Average frame time: {avg_frame_time:.2f} ms ({1000/avg_frame_time:.1f} FPS){reset}")
    sys.exit(0)

  def _calculate_auto_scale(self) -> float:
     # Create temporary window to query monitor info
    rl.init_window(1, 1, "")
    w, h = rl.get_monitor_width(0), rl.get_monitor_height(0)
    rl.close_window()

    if w == 0 or h == 0 or (w >= self._width and h >= self._height):
      return 1.0

    # Apply 0.95 factor for window decorations/taskbar margin
    return max(0.3, min(w / self._width, h / self._height) * 0.95)

  @staticmethod
  def _default_width() -> int:
    return 2160 if GuiApplication.big_ui() else 536

  @staticmethod
  def _default_height() -> int:
    return 1080 if GuiApplication.big_ui() else 240

  @staticmethod
  def big_ui() -> bool:
    if SMALL_UI:
      return False
    try:
      from openpilot.common.params import Params
      if Params().get_bool("ForceSmallUI"):
        return False
    except ImportError:
      # The compiled params_pyx isn't built yet during a first-install compile, when the
      # loading spinner imports this before scons finishes. Without this guard the spinner
      # crashes on import and the screen sits on the boot logo with no progress bar. The
      # ForceSmallUI override doesn't matter for the build spinner — fall back to device type.
      pass
    return HARDWARE.get_device_type() in ('tici', 'tizi') or BIG_UI


gui_app = GuiApplication()
