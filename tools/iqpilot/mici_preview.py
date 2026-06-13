#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  IQ.Pilot MICI UI Preview Tool                                           ║
║  ──────────────────────────────────────────────────────────────────────  ║
║  Renders any MICI layout/widget at 536×240 on your Mac desktop so you   ║
║  can visually inspect and iterate without a physical comma 4.            ║
║                                                                          ║
║  MODES                                                                   ║
║    screenshot  — render N frames, save PNG(s), open in Preview           ║
║    video       — render N seconds to MP4 via ffmpeg, open in QuickTime   ║
║    live        — interactive window, hot-reload on file-save             ║
║                                                                          ║
║  USAGE                                                                   ║
║    python tools/iqpilot/mici_preview.py [OPTIONS]                        ║
║                                                                          ║
║  OPTIONS                                                                 ║
║    --panel  PANEL    Panel to render: steering, visuals, display,        ║
║                      software, cruise, trips, osm, models, toggles,      ║
║                      device, developer, home, settings (default: steering)║
║    --mode   MODE     screenshot | video | live  (default: screenshot)    ║
║    --frames N        Frames to settle before screenshot  (default: 90)   ║
║    --shots  N        Number of screenshots to take       (default: 1)    ║
║    --duration S      Video duration in seconds           (default: 4)    ║
║    --fps    N        Render FPS                          (default: 60)   ║
║    --scale  F        Window scale multiplier (2.0 = 1072×480 window)     ║
║                      (default: 2.5)                                       ║
║    --out    PATH     Output file/dir  (default: /tmp/mici_preview/)      ║
║    --open           Open output file(s) after capture  (default: True)  ║
║    --mock           Use mock UI state (no real params needed)            ║
║                                                                          ║
║  EXAMPLES                                                                ║
║    # Screenshot the steering panel (scaled 2.5×, opens in Preview)      ║
║    python tools/iqpilot/mici_preview.py --panel steering                ║
║                                                                          ║
║    # 4-second video of the neon glow animation                          ║
║    python tools/iqpilot/mici_preview.py --panel steering --mode video   ║
║                                                                          ║
║    # Live interactive window with hot-reload                            ║
║    python tools/iqpilot/mici_preview.py --panel visuals --mode live     ║
║                                                                          ║
║    # Multiple panels in one go (screenshots)                            ║
║    python tools/iqpilot/mici_preview.py --panel all                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import importlib
import os
import subprocess
import sys
import time
import queue
import threading
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Force MICI mode (no BIG UI)
os.environ.setdefault("BIG", "0")
os.environ.setdefault("IQPILOT_UI", "1")
# Use offscreen mode for screenshot/video (no FPS cap → fast capture)
# Live mode overrides this below.

import pyray as rl  # noqa: E402 — must come after env setup

# ── MICI canvas dimensions ─────────────────────────────────────────────────
MICI_W = 536
MICI_H = 240

# ── Output directory ───────────────────────────────────────────────────────
DEFAULT_OUT = Path("/tmp/mici_preview")

# ── Color palette for the preview chrome ──────────────────────────────────
CHROME_BG = rl.Color(18, 18, 22, 255)       # dark bg behind the MICI canvas
LABEL_COLOR = rl.Color(160, 160, 160, 200)  # panel label text

# ── All available panels ───────────────────────────────────────────────────
ALL_PANELS = [
  "steering", "visuals", "display", "software", "cruise",
  "trips", "osm", "models", "toggles", "device", "developer", "home",
]


# ─────────────────────────────────────────────────────────────────────────────
# Mock UI state so we can run without a live comma process
# ─────────────────────────────────────────────────────────────────────────────

def _patch_mock_state():
  """Replace real ui_state and Params with lightweight mocks."""
  import types

  # ── Shared in-memory store ────────────────────────────────────────────────
  _store: dict = {}

  class MockParams:
    """
    Drop-in Params mock that also supports `Params | None` type expressions
    at module import time by implementing __or__ / __ror__ on the class itself.
    """
    # Allow  `Params | None`  as a runtime type-union expression
    def __class_getitem__(cls, item):
      return cls
    def __or__(cls, other):
      import types as _t
      return _t.UnionType if hasattr(_t, 'UnionType') else object
    __ror__ = __or__

    def __init__(self, _=None, **__):
      pass  # ignore any constructor args (real Params accepts path kwarg)

    def get(self, key, default=None, return_default=False):
      val = _store.get(key, default)
      # Real Params.get() returns str or None; convert bools → str
      if isinstance(val, bool):
        return str(int(val))
      return val

    def get_bool(self, key, default=False):
      val = _store.get(key, default)
      if isinstance(val, str):
        return val not in ('', '0', 'false', 'False', 'None')
      return bool(val)

    def put(self, key, val):
      _store[key] = val

    def put_bool(self, key, val):
      _store[key] = bool(val)

    def put_nonblocking(self, key, val):
      _store[key] = val

  # Seed some sensible defaults so widgets render realistically
  mp = MockParams()
  # ── Steering ────────────────────────────────────────────────────────────
  mp.put("AolEnabled",                False)
  mp.put("AolSteeringMode",           0)      # 0=remain active, 1=pause, 2=disengage
  mp.put("AolMainCruiseAllowed",      True)
  mp.put("AolUnifiedEngagementMode",  False)
  mp.put("EnforceTorqueControl",      False)
  mp.put("NeuralNetworkFeedForward",  False)
  mp.put("AutoLaneChangeTimer",       0)      # nudge
  mp.put("AutoLaneChangeBsmDelay",    False)
  mp.put("LiveTorqueParamsToggle",    False)
  mp.put("LiveTorqueParamsRelaxedToggle", False)
  mp.put("CustomTorqueParams",        False)
  mp.put("TorqueParamsOverrideEnabled", False)

  # ── Visuals (correct param keys matching visuals.py) ─────────────────────
  mp.put("BlindSpot",             True)
  mp.put("TorqueBar",             True)
  mp.put("RoadNameToggle",        True)
  mp.put("ShowTurnSignals",       True)
  mp.put("RocketFuel",            False)
  mp.put("ChevronInfo",           0)          # 0=off
  mp.put("DevUIInfo",             0)          # 0=off
  mp.put("AlphaLongitudinalEnabled", False)   # real param; gates ChevronInfo

  # ── Display ───────────────────────────────────────────────────────────────
  mp.put("OnroadScreenOffBrightness", 0)     # 0=auto
  mp.put("OnroadScreenOffTimer",      60)    # 1m
  mp.put("InteractivityTimeout",      0)     # default

  # ── Software ──────────────────────────────────────────────────────────────
  mp.put("DisableUpdates",  False)
  mp.put("GitBranch",       "master-mici")
  mp.put("Version",         "IQ.Pilot 0.9.5-mici")

  # ── Models ────────────────────────────────────────────────────────────────
  mp.put("LagdToggle",      False)
  mp.put("LaneTurnDesire",  False)
  mp.put("LaneTurnValue",   "19.0")

  # ── Cruise ────────────────────────────────────────────────────────────────
  mp.put("ExperimentalMode",      False)
  mp.put("IQDynamicMode",         False)
  mp.put("LongitudinalPersonality", 1)   # 0=aggressive,1=standard,2=relaxed,3=stock
  mp.put("SpeedLimitMode",        0)     # 0=off

  # ── Misc / system ─────────────────────────────────────────────────────────
  mp.put("IsMetric",        False)
  mp.put("UIAccentColor",   "#00FFF5")   # default neon cyan

  # Inject mock into common.params
  # IMPORTANT: inject the CLASS (not an instance) so that `Params | None`
  # type-union expressions in downstream modules work at import time.
  mock_module = types.ModuleType("openpilot.common.params")
  mock_module.Params = MockParams
  sys.modules["openpilot.common.params"] = mock_module

  # ── Mock ui_state (both the iqpilot layer and the top-level selfdrive layer) ─
  class MockCP:
    enableBsm = True
    openpilotLongitudinalControl = True
    alphaLongitudinalAvailable = False

  # Minimal mock for ui_state.sm — returns empty/default objects for any key
  class _MockBundle:
    internalName = "mock-model"
    displayName = "Mock Model"
    index = 0
    status = None   # not downloading
    models = []
    overrides = []

  class _MockModelManager:
    availableBundles = []
    activeBundle = _MockBundle()
    selectedBundle = None   # None = not downloading

  class _MockSM:
    """Minimal SubMaster-like dict that returns sensible defaults."""
    _data = {
      "iqModelManager": _MockModelManager(),
    }
    def __getitem__(self, key):
      return self._data.get(key, type("Empty", (), {"enabled": False})())
    @property
    def updated(self):
      return type("U", (), {"__getitem__": lambda s, k: False})()
    @property
    def alive(self):
      return type("A", (), {"__getitem__": lambda s, k: True})()
    @property
    def valid(self):
      return type("V", (), {"__getitem__": lambda s, k: True})()
    @property
    def frame(self): return 0
    def __contains__(self, key): return True

  class MockUIState:
    CP = MockCP()
    params = mp
    sm = _MockSM()
    started = False
    ignition = False
    is_metric = False
    has_longitudinal_control = True
    always_on_dm = False
    recording_audio = False
    personality = 1  # standard
    custom_interactive_timeout = 0
    light_sensor = -1.0
    is_release = False
    # IQ-specific extras
    aol_enabled = False
    aol_state = 0

    def is_offroad(self): return True
    def is_onroad(self): return False
    def add_offroad_transition_callback(self, cb): pass
    def add_engaged_transition_callback(self, cb): pass
    def update_params(self): pass

    @property
    def engaged(self): return False

  _mock_ui_state = MockUIState()

  # openpilot.selfdrive.ui.iqpilot.ui_state  (IQ-specific layer)
  mock_iq_ui_mod = types.ModuleType("openpilot.selfdrive.ui.iqpilot.ui_state")
  mock_iq_ui_mod.ui_state = _mock_ui_state
  sys.modules["openpilot.selfdrive.ui.iqpilot.ui_state"] = mock_iq_ui_mod

  # openpilot.selfdrive.ui.ui_state  (base openpilot layer — also imported by some widgets)
  from enum import Enum
  class _UIStatus(Enum):
    DISENGAGED = "disengaged"
    ENGAGED = "engaged"
    OVERRIDE = "override"
    LAT_ONLY = "lat_only"
    LONG_ONLY = "long_only"

  mock_base_ui_mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mock_base_ui_mod.ui_state = _mock_ui_state
  mock_base_ui_mod.UIStatus = _UIStatus
  mock_base_ui_mod.device = type("MockDevice", (), {"awake": True})()
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mock_base_ui_mod

  return mp


# ─────────────────────────────────────────────────────────────────────────────
# Panel loader
# ─────────────────────────────────────────────────────────────────────────────

def load_panel(name: str):
  """
  Instantiate a MICI panel/layout by name.
  Returns a Widget instance with set_rect() already called.
  """
  rect = rl.Rectangle(0, 0, MICI_W, MICI_H)

  layouts = {
    "steering": ("openpilot.selfdrive.ui.iqpilot.mici.layouts.steering", "SteeringLayoutMici"),
    "visuals":  ("openpilot.selfdrive.ui.iqpilot.mici.layouts.visuals",  "VisualsLayoutMici"),
    "display":  ("openpilot.selfdrive.ui.iqpilot.mici.layouts.display",  "DisplayLayoutMici"),
    "software": ("openpilot.selfdrive.ui.iqpilot.mici.layouts.software", "SoftwareLayoutMici"),
    "cruise":   ("openpilot.selfdrive.ui.iqpilot.mici.layouts.cruise",   "CruiseLayoutMici"),
    "trips":    ("openpilot.selfdrive.ui.iqpilot.mici.layouts.trips",    "TripsLayoutMici"),
    "osm":      ("openpilot.selfdrive.ui.iqpilot.mici.layouts.osm",      "OSMLayoutMici"),
    "models":   ("openpilot.selfdrive.ui.iqpilot.mici.layouts.models",   "ModelsLayoutMici"),
    "toggles":  ("openpilot.selfdrive.ui.mici.layouts.settings.toggles", "TogglesLayoutMici"),
    "device":   ("openpilot.selfdrive.ui.mici.layouts.settings.device",  "DeviceLayoutMici"),
    "developer":("openpilot.selfdrive.ui.mici.layouts.settings.developer","DeveloperLayoutMici"),
    "home":     ("openpilot.selfdrive.ui.mici.layouts.home",             "MiciHomeLayout"),
    "settings": ("openpilot.selfdrive.ui.iqpilot.mici.layouts.settings", "IQMiciSettingsLayout"),
  }

  if name not in layouts:
    raise ValueError(f"Unknown panel '{name}'. Choose from: {', '.join(layouts)}")

  # All IQ.Pilot MICI layout panels accept an optional back_callback
  NEEDS_BACK_CB = {
    "steering", "visuals", "display", "software", "cruise",
    "trips", "osm", "models", "toggles", "device", "developer",
  }

  mod_path, cls_name = layouts[name]
  mod = importlib.import_module(mod_path)
  cls = getattr(mod, cls_name)
  if name in NEEDS_BACK_CB:
    widget = cls(back_callback=lambda: None)
  else:
    widget = cls()
  widget.set_rect(rect)
  widget.show_event()
  return widget


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

def _draw_chrome(panel_name: str, scale: float, canvas_x: int, canvas_y: int):
  """Draw the preview window chrome: background, label, dimension hint."""
  # Nothing to draw outside the canvas — the window IS the canvas (+ padding)
  pass


def _render_frame(widget, render_tex: rl.RenderTexture, canvas_x: int, canvas_y: int, scale: float, panel_name: str):
  """
  Render one frame:
    1. Draw the MICI widget into render_tex (536×240 offscreen)
    2. Blit the texture into the window at the correct position + scale
    3. Draw chrome overlays (panel label, grid, etc.)
  """
  # Draw into the MICI-sized render texture
  rl.begin_texture_mode(render_tex)
  rl.clear_background(rl.Color(0, 0, 0, 255))
  widget.render(rl.Rectangle(0, 0, MICI_W, MICI_H))
  rl.end_texture_mode()

  # Blit to screen (flip Y because OpenGL textures are upside-down)
  src = rl.Rectangle(0, 0, MICI_W, -MICI_H)   # negative H = flip
  dst = rl.Rectangle(canvas_x, canvas_y, MICI_W * scale, MICI_H * scale)
  rl.draw_texture_pro(render_tex.texture, src, dst, rl.Vector2(0, 0), 0, rl.WHITE)

  # Panel name label bottom-left
  rl.draw_text(panel_name.upper(), canvas_x + 6, canvas_y + int(MICI_H * scale) + 6,
               14, rl.Color(120, 120, 120, 180))

  # Dimension hint bottom-right
  hint = f"{MICI_W}×{MICI_H}  (×{scale:.1f})"
  hint_w = rl.measure_text(hint, 12)
  win_w = rl.get_screen_width()
  rl.draw_text(hint, win_w - hint_w - 8, canvas_y + int(MICI_H * scale) + 6,
               12, rl.Color(80, 80, 80, 160))


# ─────────────────────────────────────────────────────────────────────────────
# Screenshot mode
# ─────────────────────────────────────────────────────────────────────────────

def run_screenshot(panel_name: str, args, out_dir: Path) -> list[Path]:
  """
  Render `args.frames` frames (so animations settle), then take `args.shots`
  screenshots 0.5s apart. Returns list of saved PNG paths.

  Uses gui_app.init_window() so fonts are loaded correctly, and the SCALE
  env var (set to args.scale in main()) controls window size.
  """
  from openpilot.system.ui.lib.application import gui_app

  gui_app.init_window(f"MICI Preview — {panel_name}", fps=args.fps)

  # Offscreen MICI-resolution render texture
  render_tex = rl.load_render_texture(MICI_W, MICI_H)

  # Load widget AFTER window/fonts are initialized
  widget = load_panel(panel_name)

  saved: list[Path] = []
  frame = 0
  shots_taken = 0
  next_shot_frame = args.frames  # first shot after settle

  # Display at native scaled window coords (0,0 → screen size)
  win_w = rl.get_screen_width()
  win_h = rl.get_screen_height()

  while not rl.window_should_close() and shots_taken < args.shots:
    rl.begin_drawing()
    rl.clear_background(CHROME_BG)

    # Render widget into the MICI-sized texture, then blit full-window
    rl.begin_texture_mode(render_tex)
    rl.clear_background(rl.BLACK)
    widget.render(rl.Rectangle(0, 0, MICI_W, MICI_H))
    rl.end_texture_mode()

    # Blit the render texture to fill the whole window (Y-flipped)
    src = rl.Rectangle(0, 0, MICI_W, -MICI_H)
    dst = rl.Rectangle(0, 0, win_w, win_h)
    rl.draw_texture_pro(render_tex.texture, src, dst, rl.Vector2(0, 0), 0, rl.WHITE)

    # Settle progress bar
    if frame < args.frames:
      pct = frame / args.frames
      rl.draw_rectangle(0, win_h - 3, int(win_w * pct), 3, rl.Color(0, 255, 245, 140))
      rl.draw_text(f"settling {frame}/{args.frames}", 6, 6, 11, rl.Color(100, 100, 100, 160))

    rl.end_drawing()
    frame += 1

    if frame == next_shot_frame:
      # Read from render texture (native MICI res, no padding to crop)
      img = rl.load_image_from_texture(render_tex.texture)
      rl.image_flip_vertical(img)
      # Save at 2× native for clarity on Retina displays
      rl.image_resize(img, MICI_W * 2, MICI_H * 2)
      out_dir.mkdir(parents=True, exist_ok=True)
      ts = int(time.time() * 1000)
      path = out_dir / f"mici_{panel_name}_{shots_taken + 1:02d}_{ts}.png"
      rl.export_image(img, str(path))
      rl.unload_image(img)
      saved.append(path)
      print(f"  📸  saved: {path}")
      shots_taken += 1
      next_shot_frame += int(args.fps * 0.5)  # 0.5s between shots

  rl.unload_render_texture(render_tex)
  rl.close_window()
  return saved


# ─────────────────────────────────────────────────────────────────────────────
# Video mode
# ─────────────────────────────────────────────────────────────────────────────

def run_video(panel_name: str, args, out_dir: Path) -> Path:
  """
  Render args.duration seconds at args.fps, pipe raw RGBA frames to ffmpeg → MP4.
  Returns the output MP4 path.
  """
  from openpilot.system.ui.lib.application import gui_app

  out_dir.mkdir(parents=True, exist_ok=True)
  ts = int(time.time())
  mp4_path = out_dir / f"mici_{panel_name}_{ts}.mp4"

  # Launch ffmpeg to accept raw RGBA frames at MICI native resolution
  ffmpeg = subprocess.Popen([
    "ffmpeg", "-v", "warning", "-nostats",
    "-f", "rawvideo", "-pix_fmt", "rgba",
    "-s", f"{MICI_W}x{MICI_H}",
    "-r", str(args.fps),
    "-i", "pipe:0",
    "-vf", "vflip,format=yuv420p",
    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-y", str(mp4_path),
  ], stdin=subprocess.PIPE)

  # Write-queue so rendering doesn't block on ffmpeg
  frame_queue: queue.Queue = queue.Queue(maxsize=args.fps * 2)
  stop_event = threading.Event()

  def _writer():
    while not stop_event.is_set() or not frame_queue.empty():
      try:
        data = frame_queue.get(timeout=0.1)
        ffmpeg.stdin.write(data)
      except queue.Empty:
        pass
    ffmpeg.stdin.close()

  writer_thread = threading.Thread(target=_writer, daemon=True)
  writer_thread.start()

  gui_app.init_window(f"MICI Preview (recording) — {panel_name}", fps=args.fps)
  render_tex = rl.load_render_texture(MICI_W, MICI_H)
  widget = load_panel(panel_name)

  win_w = rl.get_screen_width()
  win_h = rl.get_screen_height()
  total_frames = int(args.fps * args.duration)
  frame = 0
  settle = min(args.frames, total_frames // 4)

  print(f"  🎬  recording {args.duration}s at {args.fps}fps → {mp4_path.name}")

  while not rl.window_should_close() and frame < total_frames:
    rl.begin_drawing()
    rl.clear_background(CHROME_BG)

    rl.begin_texture_mode(render_tex)
    rl.clear_background(rl.BLACK)
    widget.render(rl.Rectangle(0, 0, MICI_W, MICI_H))
    rl.end_texture_mode()

    src = rl.Rectangle(0, 0, MICI_W, -MICI_H)
    dst = rl.Rectangle(0, 0, win_w, win_h)
    rl.draw_texture_pro(render_tex.texture, src, dst, rl.Vector2(0, 0), 0, rl.WHITE)

    # REC progress bar
    pct = frame / total_frames
    rl.draw_rectangle(0, win_h - 3, int(win_w * pct), 3, rl.Color(255, 80, 80, 180))
    rl.draw_text(f"REC  {frame}/{total_frames}", 6, 6, 11, rl.Color(255, 80, 80, 200))

    rl.end_drawing()

    # Queue raw RGBA from MICI-res texture for ffmpeg
    if frame >= settle:
      import ctypes
      img = rl.load_image_from_texture(render_tex.texture)
      colors = rl.load_image_colors(img)
      raw = bytes(ctypes.string_at(colors, MICI_W * MICI_H * 4))
      rl.unload_image_colors(colors)
      rl.unload_image(img)
      try:
        frame_queue.put(raw, timeout=1.0)
      except queue.Full:
        pass

    frame += 1

  rl.unload_render_texture(render_tex)
  rl.close_window()

  stop_event.set()
  writer_thread.join(timeout=10)
  ffmpeg.wait(timeout=15)

  print(f"  ✅  video saved: {mp4_path}")
  return mp4_path


# ─────────────────────────────────────────────────────────────────────────────
# Live / hot-reload mode
# ─────────────────────────────────────────────────────────────────────────────

def run_live(panel_name: str, args, mock_params):
  """
  Interactive window with hot-reload.
  Watches the source file of the selected panel; re-imports it on save.
  Press S to take a screenshot, R to force reload, Q/Esc to quit.
  """
  from openpilot.system.ui.lib.application import gui_app

  gui_app.init_window(f"MICI Live — {panel_name}  [S=shot  R=reload  Q=quit]", fps=args.fps)
  render_tex = rl.load_render_texture(MICI_W, MICI_H)
  win_w = rl.get_screen_width()
  win_h = rl.get_screen_height()

  widget = load_panel(panel_name)
  last_mtime: dict[str, float] = {}

  def _watch_paths() -> list[Path]:
    """Files to watch for changes (panel module + shared theme/button)."""
    mods = [
      ROOT / "selfdrive/ui/iqpilot/mici/layouts" / f"{panel_name}.py",
      ROOT / "selfdrive/ui/iqpilot/theme.py",
      ROOT / "selfdrive/ui/mici/widgets/button.py",
    ]
    return [p for p in mods if p.exists()]

  def _needs_reload() -> bool:
    for p in _watch_paths():
      mtime = p.stat().st_mtime
      if last_mtime.get(str(p), 0) != mtime:
        last_mtime[str(p)] = mtime
        return True
    return False

  def _reload():
    nonlocal widget
    print("  🔄  reloading...")
    # Invalidate cached modules so importlib picks up changes
    prefix = "openpilot.selfdrive.ui.iqpilot.mici.layouts"
    for key in list(sys.modules.keys()):
      if key.startswith(prefix) or key == "openpilot.selfdrive.ui.iqpilot.theme":
        del sys.modules[key]
    try:
      widget = load_panel(panel_name)
      print("  ✅  reloaded OK")
    except Exception as e:
      print(f"  ❌  reload error: {e}")

  # Seed mtimes
  for p in _watch_paths():
    last_mtime[str(p)] = p.stat().st_mtime

  out_dir = Path(args.out)
  shot_count = 0

  while not rl.window_should_close():
    # Check for file changes
    if _needs_reload():
      _reload()

    # Key bindings
    if rl.is_key_pressed(rl.KeyboardKey.KEY_Q) or rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
      break
    if rl.is_key_pressed(rl.KeyboardKey.KEY_R):
      _reload()
    if rl.is_key_pressed(rl.KeyboardKey.KEY_S):
      # Take screenshot from render texture (native MICI res)
      img = rl.load_image_from_texture(render_tex.texture)
      rl.image_flip_vertical(img)
      rl.image_resize(img, MICI_W * 2, MICI_H * 2)
      out_dir.mkdir(parents=True, exist_ok=True)
      ts = int(time.time() * 1000)
      path = out_dir / f"mici_{panel_name}_live_{shot_count:03d}_{ts}.png"
      rl.export_image(img, str(path))
      rl.unload_image(img)
      shot_count += 1
      print(f"  📸  screenshot saved: {path}")
      if args.open:
        subprocess.Popen(["open", str(path)])

    rl.begin_drawing()
    rl.clear_background(CHROME_BG)

    # Render widget into MICI-sized texture, blit to full window
    rl.begin_texture_mode(render_tex)
    rl.clear_background(rl.BLACK)
    widget.render(rl.Rectangle(0, 0, MICI_W, MICI_H))
    rl.end_texture_mode()

    src = rl.Rectangle(0, 0, MICI_W, -MICI_H)
    dst = rl.Rectangle(0, 0, win_w, win_h)
    rl.draw_texture_pro(render_tex.texture, src, dst, rl.Vector2(0, 0), 0, rl.WHITE)

    # Status hint overlay
    watch_files = _watch_paths()
    hint = f"watching {len(watch_files)} file(s)  |  S=shot  R=reload  Q=quit"
    rl.draw_text(hint, 6, win_h - 18, 11, rl.Color(80, 80, 80, 160))

    rl.end_drawing()

  rl.unload_render_texture(render_tex)
  rl.close_window()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
  p = argparse.ArgumentParser(
    description="IQ.Pilot MICI UI Preview Tool",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=__doc__,
  )
  p.add_argument("--panel",    default="steering",
                 help="Panel name or 'all'")
  p.add_argument("--mode",     default="screenshot",
                 choices=["screenshot", "video", "live"],
                 help="Capture mode")
  p.add_argument("--frames",   type=int, default=90,
                 help="Settle frames before screenshot")
  p.add_argument("--shots",    type=int, default=1,
                 help="Number of screenshots")
  p.add_argument("--duration", type=float, default=4.0,
                 help="Video duration in seconds")
  p.add_argument("--fps",      type=int, default=60,
                 help="Render FPS")
  p.add_argument("--scale",    type=float, default=2.5,
                 help="Window scale multiplier (1.0 = native 536×240)")
  p.add_argument("--out",      default=str(DEFAULT_OUT),
                 help="Output directory")
  p.add_argument("--open",     action="store_true", default=True,
                 help="Open output after capture (macOS)")
  p.add_argument("--no-open",  dest="open", action="store_false")
  p.add_argument("--mock",     action="store_true", default=True,
                 help="Use mock UI state (no live process needed)")
  p.add_argument("--no-mock",  dest="mock", action="store_false")
  p.add_argument("--accent",   default=None,
                 help="Override neon accent color, e.g. '#FF6B00'")
  return p.parse_args()


def main():
  args = parse_args()
  out_dir = Path(args.out)
  out_dir.mkdir(parents=True, exist_ok=True)

  # Set SCALE env var BEFORE gui_app module is imported (it reads it at import time)
  os.environ["SCALE"] = str(args.scale)

  # Apply mock state early (before any widget imports)
  mock_params = None
  if args.mock:
    print("  🎭  using mock UI state (--no-mock to use live params)")
    mock_params = _patch_mock_state()

  # Override accent color if requested
  if args.accent:
    if mock_params:
      mock_params.put("UIAccentColor", args.accent)
    print(f"  🎨  accent color: {args.accent}")

  panels = ALL_PANELS if args.panel == "all" else [args.panel]
  mode = args.mode

  if mode == "live" and len(panels) > 1:
    print("  ⚠️  live mode only supports a single panel. Using first panel.")
    panels = panels[:1]

  all_outputs: list[Path] = []

  for panel_name in panels:
    print(f"\n  ▶  {mode.upper()}  —  panel: {panel_name}")

    try:
      if mode == "live":
        run_live(panel_name, args, mock_params)
      elif mode == "screenshot":
        saved = run_screenshot(panel_name, args, out_dir)
        all_outputs.extend(saved)
      elif mode == "video":
        mp4 = run_video(panel_name, args, out_dir)
        all_outputs.append(mp4)
    except Exception as e:
      print(f"  ❌  failed for panel '{panel_name}': {e}")
      import traceback; traceback.print_exc()
      if rl.is_window_ready():
        rl.close_window()

  # Open all outputs at once
  if args.open and all_outputs:
    print(f"\n  📂  opening {len(all_outputs)} output(s)...")
    subprocess.Popen(["open"] + [str(p) for p in all_outputs])

  print("\n  ✨  done\n")


if __name__ == "__main__":
  main()
