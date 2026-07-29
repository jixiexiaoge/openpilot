#!/usr/bin/env python3
import os
import sys
import threading
import time
from enum import IntEnum

import pyray as rl

from openpilot.system.hardware import PC
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import gui_label, gui_text_box

USERDATA = "/dev/disk/by-partlabel/userdata"
NVME = "/dev/nvme0n1"
TIMEOUT = 3*60

# Guard the confirm against the same tap-burst that triggers tap-to-reset on boot.
# The confirm button stays disabled until the screen has been quiet (no touches)
# for CONFIRM_GUARD_QUIET seconds, so the triggering taps can't carry through and
# silently confirm the wipe. The user must stop, see the screen, then tap confirm.
CONFIRM_GUARD_MIN = 1.0    # minimum seconds the screen must be shown
CONFIRM_GUARD_QUIET = 1.0  # seconds of no touch input before arming confirm


class ResetMode(IntEnum):
  USER_RESET = 0  # user initiated a factory reset from openpilot
  RECOVER = 1     # userdata is corrupt for some reason, give a chance to recover
  FORMAT = 2      # finish up a factory reset from a tool that doesn't flash an empty partition to userdata


class ResetState(IntEnum):
  NONE = 0
  CONFIRM = 1
  RESETTING = 2
  FAILED = 3


class Reset(Widget):
  def __init__(self, mode):
    super().__init__()
    self._mode = mode
    self._previous_reset_state = None
    self._reset_state = ResetState.NONE
    self._cancel_button = Button("Cancel", self._cancel_callback)
    self._confirm_button = Button("Confirm", self._confirm, button_style=ButtonStyle.PRIMARY)
    self._reboot_button = Button("Reboot", lambda: os.system("sudo reboot"))
    self._render_status = True

    # tap-burst guard (see CONFIRM_GUARD_* above)
    self._start_mono = time.monotonic()
    self._last_touch_mono = self._start_mono
    self._confirm_armed = False
    self._confirm_button.set_enabled(lambda: self._confirm_armed)

  def _cancel_callback(self):
    self._render_status = False

  def _do_erase(self):
    if PC:
      return

    # Removing data and formatting
    rm = os.system("sudo rm -rf /data/*")
    os.system(f"sudo umount {NVME}")
    os.system(f"yes | sudo mkfs.ext4 {NVME}")
    os.system(f"sudo umount {USERDATA}")
    fmt = os.system(f"yes | sudo mkfs.ext4 {USERDATA}")

    if rm == 0 or fmt == 0:
      os.system("sudo reboot")
    else:
      self._reset_state = ResetState.FAILED

  def start_reset(self):
    self._reset_state = ResetState.RESETTING
    threading.Timer(0.1, self._do_erase).start()

  def _update_state(self):
    # arm the confirm button only after the screen has been touch-quiet for a beat,
    # so the taps that triggered the reset don't carry through and confirm it
    now = time.monotonic()
    if rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT):
      self._last_touch_mono = now
    if not self._confirm_armed and (now - self._start_mono) > CONFIRM_GUARD_MIN \
        and (now - self._last_touch_mono) > CONFIRM_GUARD_QUIET:
      self._confirm_armed = True

    if self._reset_state != self._previous_reset_state:
      self._previous_reset_state = self._reset_state
      self._timeout_st = time.monotonic()
    elif self._reset_state != ResetState.RESETTING and (time.monotonic() - self._timeout_st) > TIMEOUT:
      exit(0)

  def _render(self, rect: rl.Rectangle):
    label_rect = rl.Rectangle(rect.x + 140, rect.y, rect.width - 280, 100 * FONT_SCALE)
    gui_label(label_rect, "System Reset", 100, font_weight=FontWeight.BOLD)

    text_rect = rl.Rectangle(rect.x + 140, rect.y + 140, rect.width - 280, rect.height - 90 - 100 * FONT_SCALE)
    gui_text_box(text_rect, self._get_body_text(), 90)

    button_height = 160
    button_spacing = 50
    button_top = rect.y + rect.height - button_height
    button_width = (rect.width - button_spacing) / 2.0

    if self._reset_state != ResetState.RESETTING:
      if self._mode == ResetMode.RECOVER:
        self._reboot_button.render(rl.Rectangle(rect.x, button_top, button_width, button_height))
      elif self._mode == ResetMode.USER_RESET:
        self._cancel_button.render(rl.Rectangle(rect.x, button_top, button_width, button_height))

      if self._reset_state != ResetState.FAILED:
        self._confirm_button.render(rl.Rectangle(rect.x + button_width + 50, button_top, button_width, button_height))
      else:
        self._reboot_button.render(rl.Rectangle(rect.x, button_top, rect.width, button_height))

    return self._render_status

  def _confirm(self):
    if self._reset_state == ResetState.CONFIRM:
      self.start_reset()
    else:
      self._reset_state = ResetState.CONFIRM

  def _get_body_text(self):
    if self._reset_state == ResetState.CONFIRM:
      return "Are you sure you want to reset your device?"
    if self._reset_state == ResetState.RESETTING:
      return "Resetting device...\nThis may take up to a minute."
    if self._reset_state == ResetState.FAILED:
      return "Reset failed. Reboot to try again."
    if self._mode == ResetMode.RECOVER:
      return "Unable to mount data partition. Partition may be corrupted. Press confirm to erase and reset your device."
    if not self._confirm_armed and self._reset_state == ResetState.NONE:
      return "System reset triggered. Stop touching the screen, then press confirm to erase all content and settings. Press cancel to resume boot."
    return "System reset triggered. Press confirm to erase all content and settings. Press cancel to resume boot."


def main():
  mode = ResetMode.USER_RESET
  if len(sys.argv) > 1:
    if sys.argv[1] == '--recover':
      mode = ResetMode.RECOVER
    elif sys.argv[1] == "--format":
      mode = ResetMode.FORMAT

  gui_app.init_window("System Reset", 20)
  reset = Reset(mode)

  if mode == ResetMode.FORMAT:
    reset.start_reset()

  for should_render in gui_app.render():
    if should_render:
      if not reset.render(rl.Rectangle(45, 200, gui_app.width - 90, gui_app.height - 245)):
        break


if __name__ == "__main__":
  main()
