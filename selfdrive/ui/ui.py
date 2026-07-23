#!/usr/bin/env python3
import ctypes
import os
import time
import pyray as rl

from openpilot.system.hardware import TICI
from openpilot.common.realtime import Priority, config_realtime_process, set_core_affinity
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.main import MainLayout
from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
from openpilot.selfdrive.ui.ui_state import ui_state

_FPS_OVERRIDE = os.getenv("FPS")
UI_OFFROAD_FPS = int(os.getenv("UI_OFFROAD_FPS", _FPS_OVERRIDE or "60"))
UI_ONROAD_FPS = int(os.getenv("UI_ONROAD_FPS", _FPS_OVERRIDE or "20"))


def main():
  cores = {5, }
  # Run the UI above plannerd/radard (CTRL_LOW=51), which share core 5 with us after the TICI
  # reaffine. At equal priority under SCHED_FIFO the render loop can't preempt their bursts and
  # misses the vblank deadline onroad; stock runs the UI at CTRL_HIGH for exactly this reason.
  config_realtime_process(0, Priority.CTRL_HIGH)

  gui_app.init_window("UI", fps=UI_OFFROAD_FPS, screen_recordable=True)
  big = gui_app.big_ui()
  if big:
    # BIG UI (comma 3/3x): rendered manually each frame (unchanged).
    main_layout = MainLayout()
    main_layout.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
  else:
    # mici (comma 4): drives the nav stack; MiciMainLayout pushes itself in __init__
    # and is rendered by gui_app.render() (settings push on top).
    main_layout = MiciMainLayout()

  # Tile decode/upload churn (1MB stb buffers off worker threads) grows glibc arenas
  # that are never returned to the kernel; periodic trim keeps freed pages from
  # accumulating as resident memory on long map/nav drives.
  libc_trim = None
  if TICI:
    try:
      libc_trim = ctypes.CDLL("libc.so.6").malloc_trim
    except (OSError, AttributeError):
      libc_trim = None
  last_trim = time.monotonic()

  for should_render in gui_app.render():
    ui_state.update()
    gui_app.set_target_fps(UI_ONROAD_FPS if ui_state.started else UI_OFFROAD_FPS)
    if should_render:
      if big:
        main_layout.render()

      # reaffine after power save offlines our core
      if TICI and os.sched_getaffinity(0) != cores:
        try:
          set_core_affinity(list(cores))
        except OSError:
          pass

      if libc_trim is not None and time.monotonic() - last_trim > 300.0:
        last_trim = time.monotonic()
        libc_trim(0)


if __name__ == "__main__":
  main()
