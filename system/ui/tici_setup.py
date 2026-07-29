#!/usr/bin/env python3
import os
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from enum import IntEnum
import shutil

import pyray as rl

from openpilot.common.utils import run_cmd
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle, ButtonRadio
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.label import Label
from openpilot.system.ui.widgets.network import WifiManagerUI, WifiManager

try:
  from cereal import log
  NetworkType = log.DeviceState.NetworkType
except ImportError:
  NetworkType = None

MARGIN = 50
TITLE_FONT_SIZE = 90
TITLE_FONT_WEIGHT = FontWeight.MEDIUM
NEXT_BUTTON_WIDTH = 310
BODY_FONT_SIZE = 80
BUTTON_HEIGHT = 160
BUTTON_SPACING = 50

NETWORK_CHECK_URL = "https://openpilot.comma.ai"
IQPILOT_BETA_URL = "IQLvbs/beta"
IQPILOT_RELEASE_URL = "IQLvbs/release"
USER_AGENT = f"AGNOSSetup-{HARDWARE.get_os_version()}"

CONTINUE_PATH = "/data/continue.sh"
TMP_CONTINUE_PATH = "/data/continue.sh.new"
INSTALL_PATH = "/data/openpilot"
TMP_INSTALL_PATH = "/data/tmppilot"
VALID_CACHE_PATH = "/data/.openpilot_cache"
INSTALLER_SOURCE_PATH = "/usr/comma/installer"
INSTALLER_DESTINATION_PATH = "/tmp/installer"
INSTALLER_URL_PATH = "/tmp/installer_url"

GITHUB_FORK_URL = "https://github.com/{user}/openpilot.git"
# IQ.Pilot lives on the IQ Lvbs git server; github.com/IQLvbs is DMCA'd and dead.
GIT_URL_OVERRIDES = {"IQLvbs": "https://git.konn3kt.com/IQ.Lvbs/IQ.Pilot.git"}

CONTINUE = """#!/usr/bin/env bash

cd /data/openpilot
exec ./launch_openpilot.sh
"""


class SetupState(IntEnum):
  LOW_VOLTAGE = 0
  GETTING_STARTED = 1
  NETWORK_SETUP = 2
  SOFTWARE_SELECTION = 3
  CUSTOM_SOFTWARE = 4
  DOWNLOADING = 5
  DOWNLOAD_FAILED = 6
  CUSTOM_SOFTWARE_WARNING = 7
  IQPILOT_BRANCH_SELECTION = 8


class Setup(Widget):
  def __init__(self):
    super().__init__()
    self.state = SetupState.GETTING_STARTED
    self.network_check_thread = None
    self.network_connected = threading.Event()
    self.wifi_connected = threading.Event()
    self.stop_network_check_thread = threading.Event()
    self.failed_url = ""
    self.failed_reason = ""
    self.download_url = ""
    self.download_progress = 0
    self.download_thread = None
    # Single WifiManager shared with the BLE setup transport so a phone can scan
    # and connect Wi-Fi over Bluetooth using the same NM state the on-screen UI shows.
    self.wifi_manager = WifiManager()
    self.wifi_ui = WifiManagerUI(self.wifi_manager)
    self.keyboard = Keyboard()

    # BLE zero-touch setup (Phase A): advertise so the konn3kt app can drive
    # Wi-Fi + install over Bluetooth. Best-effort — on-screen setup is unaffected
    # if BlueZ is unavailable.
    self.ble_setup = None
    self._ble_pending_install_url = None
    self._init_ble_setup()
    self.selected_radio = None
    self.warning = gui_app.texture("icons/warning.png", 150, 150)
    self.checkmark = gui_app.texture("icons/circled_check.png", 100, 100)

    self._low_voltage_title_label = Label("WARNING: Low Voltage", TITLE_FONT_SIZE, FontWeight.MEDIUM, rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                                          text_color=rl.Color(255, 89, 79, 255), text_padding=20)
    self._low_voltage_body_label = Label("Power your device in a car with a harness or proceed at your own risk.", BODY_FONT_SIZE,
                                         text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)
    self._low_voltage_continue_button = Button("Continue", self._low_voltage_continue_button_callback)
    self._low_voltage_poweroff_button = Button("Power Off", HARDWARE.shutdown)

    self._getting_started_button = Button("", self._getting_started_button_callback, button_style=ButtonStyle.PRIMARY, border_radius=0)
    self._getting_started_title_label = Label("Getting Started", TITLE_FONT_SIZE, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)
    self._getting_started_body_label = Label("Before we get on the road, let's finish installation and cover some details.",
                                             BODY_FONT_SIZE, text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)

    self.iqpilot_url = IQPILOT_RELEASE_URL

    self._software_selection_iqpilot_button = ButtonRadio("IQ.Pilot", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._software_selection_openpilot_button = ButtonRadio("openpilot", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._software_selection_custom_software_button = ButtonRadio("Custom Software", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._software_selection_continue_button = Button("Continue", self._software_selection_continue_button_callback,
                                                      button_style=ButtonStyle.PRIMARY)
    self._software_selection_continue_button.set_enabled(False)
    self._software_selection_back_button = Button("Back", self._software_selection_back_button_callback)
    self._software_selection_title_label = Label("Choose Software to Use", TITLE_FONT_SIZE, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                                                 text_padding=20)

    self._iqpilot_branch_beta_button = ButtonRadio("Beta", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._iqpilot_branch_release_button = ButtonRadio("Release", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._iqpilot_branch_continue_button = Button("Continue", self._iqpilot_branch_continue_button_callback,
                                                  button_style=ButtonStyle.PRIMARY)
    self._iqpilot_branch_continue_button.set_enabled(False)
    self._iqpilot_branch_back_button = Button("Back", self._iqpilot_branch_back_button_callback)
    self._iqpilot_branch_title_label = Label("Branch:", TITLE_FONT_SIZE, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                                             text_padding=20)

    self._download_failed_reboot_button = Button("Reboot device", HARDWARE.reboot)
    self._download_failed_startover_button = Button("Start over", self._download_failed_startover_button_callback, button_style=ButtonStyle.PRIMARY)
    self._download_failed_title_label = Label("Download Failed", TITLE_FONT_SIZE, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)
    self._download_failed_url_label = Label("", 52, FontWeight.NORMAL, rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)
    self._download_failed_body_label = Label("", BODY_FONT_SIZE, text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)

    self._network_setup_back_button = Button("Back", self._network_setup_back_button_callback)
    self._network_setup_continue_button = Button("Waiting for internet", self._network_setup_continue_button_callback,
                                                 button_style=ButtonStyle.PRIMARY)
    self._network_setup_continue_button.set_enabled(False)
    self._network_setup_title_label = Label("Connect to Wi-Fi", TITLE_FONT_SIZE, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=20)

    self._custom_software_warning_continue_button = Button("Scroll to continue", self._custom_software_warning_continue_button_callback,
                                                           button_style=ButtonStyle.PRIMARY)
    self._custom_software_warning_continue_button.set_enabled(False)
    self._custom_software_warning_back_button = Button("Back", self._custom_software_warning_back_button_callback)
    self._custom_software_warning_title_label = Label("WARNING: Custom Software", 81, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
                                                      text_color=rl.Color(255, 89, 79, 255),
                                                      text_padding=60)
    self._custom_software_warning_body_label = Label("Use caution when installing third-party software.\n\n"
                                                     + "⚠️ It has not been tested by comma.\n\n"
                                                     + "⚠️ It may not comply with relevant safety standards.\n\n"
                                                     + "⚠️ It may cause damage to your device and/or vehicle.\n\n"
                                                     + "If you'd like to proceed, use https://flash.comma.ai "
                                                     + "to restore your device to a factory state later.",
                                                     68, text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, text_padding=60)
    self._custom_software_warning_body_scroll_panel = GuiScrollPanel()

    self._downloading_body_label = Label("Downloading...", TITLE_FONT_SIZE, FontWeight.MEDIUM, text_padding=20)
    # Persistent "set up from your phone" banner: an eyebrow + the big pairing
    # code, shown on every setup page so the konn3kt app can drive setup at any point.
    self._ble_eyebrow_label = Label("KONN3KT SETUP CODE", 26, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                                    text_color=rl.Color(255, 255, 255, 150))
    self._ble_code_label = Label("", 56, FontWeight.BOLD, rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                                 text_color=rl.Color(255, 255, 255, 240))
    self._ble_connected_label = Label("Phone connected - continue in app", 28, FontWeight.MEDIUM,
                                      rl.GuiTextAlignment.TEXT_ALIGN_CENTER, text_color=rl.Color(16, 185, 129, 255))

    try:
      with open("/sys/class/hwmon/hwmon1/in1_input") as f:
        voltage = float(f.read().strip()) / 1000.0
        if voltage < 7:
          self.state = SetupState.LOW_VOLTAGE
    except (FileNotFoundError, ValueError):
      self.state = SetupState.LOW_VOLTAGE

  def _init_ble_setup(self):
    try:
      from openpilot.system.ui.lib.setup_controller import SetupController
      version = ""
      try:
        with open("/VERSION") as f:
          version = f.read().strip()
      except Exception:
        pass
      controller = SetupController(
        serial=HARDWARE.get_serial(),
        hardware=HARDWARE,
        wifi_manager=self.wifi_manager,
        on_start_install=self._ble_request_install,
        version=version,
      )
      self.ble_setup = controller
      # controller.start() can block on BlueZ D-Bus registration (up to ~30s if
      # BlueZ is unhealthy) — run it off the UI thread so the setup screen never
      # stalls. The UI already guards ble_setup being None / not-yet-advertising.
      def _start_ble():
        try:
          if not controller.start():
            self.ble_setup = None
        except Exception:
          self.ble_setup = None
      threading.Thread(target=_start_ble, name="ble_setup_start", daemon=True).start()
    except Exception:
      self.ble_setup = None

  def _ble_request_install(self, url: str):
    # Called from the BLE thread — defer to the UI thread (raylib is not
    # thread-safe). The render loop consumes this and starts the real install.
    self._ble_pending_install_url = url

  def _ble_sync(self):
    if self.ble_setup is None:
      return
    # start a phone-requested install on the UI thread
    if self._ble_pending_install_url is not None:
      url = self._ble_pending_install_url
      self._ble_pending_install_url = None
      self.iqpilot_url = url
      if self.state not in (SetupState.DOWNLOADING, SetupState.DOWNLOAD_FAILED):
        self.download(url)
    # Install progress is reported by the install thread (_ble_progress /
    # _maybe_update_os) as the single source of truth. Do NOT push per-frame from
    # here: a ~60fps "downloading" push floods over the install thread's
    # os_update_required / installing / rebooting states and the phone never sees
    # them (the OS-update confirm prompt would never appear). Only relay the
    # terminal failure reason, which the thread doesn't spell out over BLE.
    if self.state == SetupState.DOWNLOAD_FAILED:
      self.ble_setup.set_install_progress("failed", 0, self.failed_reason)

  def _render_ble_overlay(self, rect: rl.Rectangle):
    # Compact top-right chip on every setup page (except while installing): the
    # 6-digit pairing code so the konn3kt app can drive setup over Bluetooth, or
    # the connected state once a phone has joined. Corner placement keeps it off
    # the page titles (top-left) and the continue/back buttons (bottom).
    if self.ble_setup is None or self.state in (SetupState.DOWNLOADING, SetupState.LOW_VOLTAGE):
      return
    snap = self.ble_setup.snapshot()

    margin = 24
    if snap.get("phone_active"):
      chip_w, chip_h = 700, 64
      chip_x = int(rect.x + rect.width - chip_w - margin)
      chip_y = int(rect.y + margin)
      chip = rl.Rectangle(chip_x, chip_y, chip_w, chip_h)
      rl.draw_rectangle_rounded(chip, 0.5, 12, rl.Color(12, 12, 14, 225))
      rl.draw_circle(chip_x + 42, chip_y + chip_h // 2, 8, rl.Color(16, 185, 129, 255))
      self._ble_connected_label.render(rl.Rectangle(chip_x + 60, chip_y + (chip_h - 32) / 2, chip_w - 90, 36))
    else:
      chip_w, chip_h = 430, 132
      chip_x = int(rect.x + rect.width - chip_w - margin)
      chip_y = int(rect.y + margin)
      chip = rl.Rectangle(chip_x, chip_y, chip_w, chip_h)
      rl.draw_rectangle_rounded(chip, 0.3, 12, rl.Color(12, 12, 14, 225))
      rl.draw_rectangle(chip_x, chip_y + chip_h - 3, chip_w, 3, rl.Color(16, 185, 129, 255))
      code = self.ble_setup.code
      spaced = "  ".join(code) if code else "- - -"
      self._ble_code_label.set_text(spaced)
      self._ble_eyebrow_label.render(rl.Rectangle(chip_x, chip_y + 18, chip_w, 30))
      self._ble_code_label.render(rl.Rectangle(chip_x, chip_y + 54, chip_w, 62))

  def _render(self, rect: rl.Rectangle):
    self._ble_sync()
    if self.state == SetupState.LOW_VOLTAGE:
      self.render_low_voltage(rect)
    elif self.state == SetupState.GETTING_STARTED:
      self.render_getting_started(rect)
    elif self.state == SetupState.NETWORK_SETUP:
      self.render_network_setup(rect)
    elif self.state == SetupState.SOFTWARE_SELECTION:
      self.render_software_selection(rect)
    elif self.state == SetupState.CUSTOM_SOFTWARE_WARNING:
      self.render_custom_software_warning(rect)
    elif self.state == SetupState.IQPILOT_BRANCH_SELECTION:
      self.render_iqpilot_branch_selection(rect)
    elif self.state == SetupState.CUSTOM_SOFTWARE:
      self.render_custom_software()
    elif self.state == SetupState.DOWNLOADING:
      self.render_downloading(rect)
    elif self.state == SetupState.DOWNLOAD_FAILED:
      self.render_download_failed(rect)
    self._render_ble_overlay(rect)

  def _low_voltage_continue_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _custom_software_warning_back_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _custom_software_warning_continue_button_callback(self):
    self.state = SetupState.NETWORK_SETUP
    self.stop_network_check_thread.clear()
    self.start_network_check()

  def _getting_started_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _software_selection_back_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _software_selection_continue_button_callback(self):
    if self._software_selection_iqpilot_button.selected:
      self.state = SetupState.IQPILOT_BRANCH_SELECTION
    elif self._software_selection_openpilot_button.selected:
      self.use_openpilot()
    else:
      self.state = SetupState.CUSTOM_SOFTWARE_WARNING

  def _iqpilot_branch_back_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _iqpilot_branch_continue_button_callback(self):
    self.iqpilot_url = IQPILOT_BETA_URL if self._iqpilot_branch_beta_button.selected else IQPILOT_RELEASE_URL
    self.state = SetupState.NETWORK_SETUP
    self.stop_network_check_thread.clear()
    self.start_network_check()

  def _download_failed_startover_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _network_setup_back_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _network_setup_continue_button_callback(self):
    self.stop_network_check_thread.set()
    if self._software_selection_iqpilot_button.selected:
      self.download(self.iqpilot_url)
    elif self._software_selection_openpilot_button.selected:
      self.use_baked_installer()
    else:
      self.state = SetupState.CUSTOM_SOFTWARE

  def render_low_voltage(self, rect: rl.Rectangle):
    rl.draw_texture(self.warning, int(rect.x + 150), int(rect.y + 110), rl.WHITE)

    self._low_voltage_title_label.render(rl.Rectangle(rect.x + 150, rect.y + 110 + 150 + 100, rect.width - 500 - 150, TITLE_FONT_SIZE * FONT_SCALE))
    self._low_voltage_body_label.render(rl.Rectangle(rect.x + 150, rect.y + 110 + 150 + 150, rect.width - 500, BODY_FONT_SIZE * FONT_SCALE * 3))

    button_width = (rect.width - MARGIN * 3) / 2
    button_y = rect.height - MARGIN - BUTTON_HEIGHT
    self._low_voltage_poweroff_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._low_voltage_continue_button.render(rl.Rectangle(rect.x + MARGIN * 2 + button_width, button_y, button_width, BUTTON_HEIGHT))

  def render_getting_started(self, rect: rl.Rectangle):
    self._getting_started_title_label.render(rl.Rectangle(rect.x + 165, rect.y + 280, rect.width - 265, TITLE_FONT_SIZE * FONT_SCALE))
    self._getting_started_body_label.render(rl.Rectangle(rect.x + 165, rect.y + 280 + TITLE_FONT_SIZE * FONT_SCALE, rect.width - 500,
                                                         BODY_FONT_SIZE * FONT_SCALE * 3))

    btn_rect = rl.Rectangle(rect.width - NEXT_BUTTON_WIDTH, 0, NEXT_BUTTON_WIDTH, rect.height)
    self._getting_started_button.render(btn_rect)
    triangle = gui_app.texture("images/button_continue_triangle.png", 54, int(btn_rect.height))
    rl.draw_texture_v(triangle, rl.Vector2(btn_rect.x + btn_rect.width / 2 - triangle.width / 2, btn_rect.height / 2 - triangle.height / 2), rl.WHITE)

  def check_network_connectivity(self):
    while not self.stop_network_check_thread.is_set():
      if self.state == SetupState.NETWORK_SETUP:
        try:
          urllib.request.urlopen(NETWORK_CHECK_URL, timeout=2)
          self.network_connected.set()
          if NetworkType is not None and HARDWARE.get_network_type() == NetworkType.wifi:
            self.wifi_connected.set()
          else:
            self.wifi_connected.clear()
        except Exception:
          self.network_connected.clear()
      time.sleep(1)

  def start_network_check(self):
    if self.network_check_thread is None or not self.network_check_thread.is_alive():
      self.network_check_thread = threading.Thread(target=self.check_network_connectivity, daemon=True)
      self.network_check_thread.start()

  def close(self):
    if self.network_check_thread is not None:
      self.stop_network_check_thread.set()
      self.network_check_thread.join()

  def render_network_setup(self, rect: rl.Rectangle):
    self._network_setup_title_label.render(rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - MARGIN * 2, TITLE_FONT_SIZE * FONT_SCALE))

    wifi_rect = rl.Rectangle(rect.x + MARGIN, rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN + 25, rect.width - MARGIN * 2,
                             rect.height - TITLE_FONT_SIZE * FONT_SCALE - 25 - BUTTON_HEIGHT - MARGIN * 3)
    rl.draw_rectangle_rounded(wifi_rect, 0.05, 10, rl.Color(51, 51, 51, 255))
    wifi_content_rect = rl.Rectangle(wifi_rect.x + MARGIN, wifi_rect.y, wifi_rect.width - MARGIN * 2, wifi_rect.height)
    self.wifi_ui.render(wifi_content_rect)

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN

    self._network_setup_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))

    # Check network connectivity status
    continue_enabled = self.network_connected.is_set()
    self._network_setup_continue_button.set_enabled(continue_enabled)
    continue_text = ("Continue" if self.wifi_connected.is_set() else "Continue without Wi-Fi") if continue_enabled else "Waiting for internet"
    self._network_setup_continue_button.set_text(continue_text)
    self._network_setup_continue_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_software_selection(self, rect: rl.Rectangle):
    self._software_selection_title_label.render(rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - MARGIN * 2, TITLE_FONT_SIZE * FONT_SCALE))

    # three options need to fit above the bottom buttons, so they're shorter than the stock two-option layout
    radio_height = 185
    radio_spacing = 25

    self._software_selection_continue_button.set_enabled(False)

    base_y = rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN * 2

    # each radio is rendered, then immediately enforces single-selection by clearing the others;
    # because each button processes its own tap during render(), the just-tapped radio always wins
    iqpilot_rect = rl.Rectangle(rect.x + MARGIN, base_y, rect.width - MARGIN * 2, radio_height)
    self._software_selection_iqpilot_button.render(iqpilot_rect)
    if self._software_selection_iqpilot_button.selected:
      self._software_selection_continue_button.set_enabled(True)
      self._software_selection_openpilot_button.selected = False
      self._software_selection_custom_software_button.selected = False

    openpilot_rect = rl.Rectangle(rect.x + MARGIN, base_y + (radio_height + radio_spacing), rect.width - MARGIN * 2, radio_height)
    self._software_selection_openpilot_button.render(openpilot_rect)
    if self._software_selection_openpilot_button.selected:
      self._software_selection_continue_button.set_enabled(True)
      self._software_selection_iqpilot_button.selected = False
      self._software_selection_custom_software_button.selected = False

    custom_rect = rl.Rectangle(rect.x + MARGIN, base_y + 2 * (radio_height + radio_spacing), rect.width - MARGIN * 2, radio_height)
    self._software_selection_custom_software_button.render(custom_rect)
    if self._software_selection_custom_software_button.selected:
      self._software_selection_continue_button.set_enabled(True)
      self._software_selection_iqpilot_button.selected = False
      self._software_selection_openpilot_button.selected = False

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN

    self._software_selection_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._software_selection_continue_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_iqpilot_branch_selection(self, rect: rl.Rectangle):
    self._iqpilot_branch_title_label.render(rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - MARGIN * 2, TITLE_FONT_SIZE * FONT_SCALE))

    radio_height = 230
    radio_spacing = 30

    self._iqpilot_branch_continue_button.set_enabled(False)

    base_y = rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN * 2

    beta_rect = rl.Rectangle(rect.x + MARGIN, base_y, rect.width - MARGIN * 2, radio_height)
    self._iqpilot_branch_beta_button.render(beta_rect)
    if self._iqpilot_branch_beta_button.selected:
      self._iqpilot_branch_continue_button.set_enabled(True)
      self._iqpilot_branch_release_button.selected = False

    release_rect = rl.Rectangle(rect.x + MARGIN, base_y + (radio_height + radio_spacing), rect.width - MARGIN * 2, radio_height)
    self._iqpilot_branch_release_button.render(release_rect)
    if self._iqpilot_branch_release_button.selected:
      self._iqpilot_branch_continue_button.set_enabled(True)
      self._iqpilot_branch_beta_button.selected = False

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN

    self._iqpilot_branch_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._iqpilot_branch_continue_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_downloading(self, rect: rl.Rectangle):
    self._downloading_body_label.render(rl.Rectangle(rect.x, rect.y + rect.height / 2 - TITLE_FONT_SIZE * FONT_SCALE / 2, rect.width,
                                                     TITLE_FONT_SIZE * FONT_SCALE))

  def render_download_failed(self, rect: rl.Rectangle):
    self._download_failed_title_label.render(rl.Rectangle(rect.x + 117, rect.y + 185, rect.width - 117, TITLE_FONT_SIZE * FONT_SCALE))
    self._download_failed_url_label.set_text(self.failed_url)
    self._download_failed_url_label.render(rl.Rectangle(rect.x + 117, rect.y + 185 + TITLE_FONT_SIZE * FONT_SCALE + 67, rect.width - 117 - 100, 64))

    self._download_failed_body_label.set_text(self.failed_reason)
    self._download_failed_body_label.render(rl.Rectangle(rect.x + 117, rect.y, rect.width - 117 - 100, rect.height))

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN
    self._download_failed_reboot_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._download_failed_startover_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_custom_software_warning(self, rect: rl.Rectangle):
    warn_rect = rl.Rectangle(rect.x, rect.y, rect.width, 1500)
    offset = self._custom_software_warning_body_scroll_panel.update(rect, warn_rect)

    button_width = (rect.width - MARGIN * 3) / 2
    button_y = rect.height - MARGIN - BUTTON_HEIGHT

    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(button_y - BODY_FONT_SIZE * FONT_SCALE))
    y_offset = rect.y + offset
    self._custom_software_warning_title_label.render(rl.Rectangle(rect.x + 50, y_offset + 150, rect.width - 265, TITLE_FONT_SIZE * FONT_SCALE))
    self._custom_software_warning_body_label.render(rl.Rectangle(rect.x + 50, y_offset + 400, rect.width - 50, BODY_FONT_SIZE * FONT_SCALE * 3))
    rl.end_scissor_mode()

    self._custom_software_warning_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._custom_software_warning_continue_button.render(rl.Rectangle(rect.x + MARGIN * 2 + button_width, button_y, button_width, BUTTON_HEIGHT))
    if offset < (rect.height - warn_rect.height):
      self._custom_software_warning_continue_button.set_enabled(True)
      self._custom_software_warning_continue_button.set_text("Continue")

  def render_custom_software(self):
    def handle_keyboard_result(result):
      # Enter pressed
      if result == 1:
        url = self.keyboard.text
        self.keyboard.clear()
        if url:
          self.download(url)

      # Cancel pressed
      elif result == 0:
        self.state = SetupState.SOFTWARE_SELECTION

    self.keyboard.reset(min_text_size=1)
    self.keyboard.set_title("Enter URL", "for Custom Software")
    gui_app.set_modal_overlay(self.keyboard, callback=handle_keyboard_result)

  def use_openpilot(self):
    if os.path.isdir(INSTALL_PATH) and os.path.isfile(VALID_CACHE_PATH):
      os.remove(VALID_CACHE_PATH)
      with open(TMP_CONTINUE_PATH, "w") as f:
        f.write(CONTINUE)
      run_cmd(["chmod", "+x", TMP_CONTINUE_PATH])
      shutil.move(TMP_CONTINUE_PATH, CONTINUE_PATH)
      shutil.copyfile(INSTALLER_SOURCE_PATH, INSTALLER_DESTINATION_PATH)

      # give time for installer UI to take over
      time.sleep(0.1)
      gui_app.request_close()
    else:
      self.state = SetupState.NETWORK_SETUP
      self.stop_network_check_thread.clear()
      self.start_network_check()

  def use_baked_installer(self):
    # /usr/comma/installer is the local DRM "magic" installer (clones commaai/openpilot); comma's
    # downloaded Wayland installer can't initialize a display on IQ.OS, so always use the baked one.
    shutil.copyfile(INSTALLER_SOURCE_PATH, INSTALLER_DESTINATION_PATH)

    # give time for installer UI to take over
    time.sleep(0.1)
    gui_app.request_close()

  def download(self, url: str):
    self.state = SetupState.DOWNLOADING

    # "<user>/<branch>" maps to a GitHub fork (e.g. IQLvbs/release-new). Clone it directly here
    # rather than fetching comma's Wayland installer, which can't run on IQ.OS's DRM compositor.
    match = re.match(r"^([^/.]+)/([^/]+)$", url)
    if match:
      user, branch = match.group(1), match.group(2)
      self.download_url = f"{user}/{branch}"
      self.download_thread = threading.Thread(target=self._fork_install_thread, args=(user, branch), daemon=True)
      self.download_thread.start()
      return

    parsed = urlparse(url, scheme='https')
    self.download_url = (urlparse(f"https://{url}") if not parsed.netloc else parsed).geturl()

    self.download_thread = threading.Thread(target=self._download_thread, daemon=True)
    self.download_thread.start()

  def _ble_progress(self, state: str, percent: int = 0):
    # Mirror install milestones to a phone driving setup over BLE so it can track
    # the flow and hand off to Phase B. Best-effort — no-op without a BLE session.
    if self.ble_setup is not None:
      try:
        self.ble_setup.set_install_progress(state, percent)
      except Exception:
        pass

  def _write_setup_claim(self):
    ble = self.ble_setup
    if ble is None or not getattr(ble, "phone_active", False):
      return
    try:
      import hashlib
      claim_id = hashlib.sha256(f"k3setup-claim:v1:{ble.code}:{ble.serial}".encode()).hexdigest()
      with open("/data/setup_claim_id", "w") as f:
        f.write(claim_id)
    except Exception:
      pass

  def _fork_install_thread(self, user: str, branch: str):
    git_url = GIT_URL_OVERRIDES.get(user) or GITHUB_FORK_URL.format(user=user)
    label = f"{user}/{branch}"
    fail_msg = "Ensure the entered URL is valid, and the device's internet connection is good."
    try:
      subprocess.run(["rm", "-rf", TMP_INSTALL_PATH], check=False)

      self._ble_progress("downloading", 10)
      clone = subprocess.run(["git", "clone", "--depth=1", "--recurse-submodules",
                              "-b", branch, git_url, TMP_INSTALL_PATH])
      if clone.returncode != 0:
        self._ble_progress("failed")
        self.download_failed(label, "No custom software found at this URL.")
        return

      # match the installer: pin to the remote branch and pull submodules, then move into place
      self._ble_progress("downloading", 70)
      subprocess.run(["git", "-C", TMP_INSTALL_PATH, "reset", "--hard", f"origin/{branch}"], check=True)
      subprocess.run(["git", "-C", TMP_INSTALL_PATH, "submodule", "update", "--init"], check=False)

      run_cmd(["rm", "-f", VALID_CACHE_PATH])
      # sudo: a prior *run* install can leave root-owned .pyc here that a comma-user rm can't delete.
      run_cmd(["sudo", "rm", "-rf", INSTALL_PATH])
      run_cmd(["mv", TMP_INSTALL_PATH, INSTALL_PATH])

      self._ble_progress("installing", 90)

      # If the chosen channel targets a newer IQ.OS than we're running, flash it
      # BEFORE writing continue.sh so the single reboot lands on a compatible OS.
      if not self._maybe_update_os(label):
        return

      self._write_setup_claim()

      with open(TMP_CONTINUE_PATH, "w") as f:
        f.write(CONTINUE)
      run_cmd(["chmod", "+x", TMP_CONTINUE_PATH])
      shutil.move(TMP_CONTINUE_PATH, CONTINUE_PATH)

      with open(INSTALLER_URL_PATH, "w") as f:
        f.write(label)

      # comma.sh blocks waiting for /tmp/installer before it checks for continue.sh; the real
      # install is already done above, so drop a no-op installer to let it proceed and launch.
      with open(INSTALLER_DESTINATION_PATH, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
      run_cmd(["chmod", "+x", INSTALLER_DESTINATION_PATH])

      # Tell the phone we're about to reboot into the installed fork so it can
      # switch to Phase B; give the event a moment to flush before the link drops.
      self._ble_progress("rebooting", 100)
      time.sleep(0.4)
      gui_app.request_close()
    except Exception:
      self._ble_progress("failed")
      self.download_failed(label, fail_msg)

  def _maybe_update_os(self, label: str) -> bool:
    # The freshly-installed fork pins the IQ.OS it needs in launch_env.sh. If it
    # differs from what we're running, flash it now (via comma's agnos.py) so the
    # upcoming single reboot lands on a compatible OS instead of dead-ending on
    # "update required". Returns False (and shows Download Failed) on abort.
    from openpilot.system.ui.lib.os_update import os_update_needed, run_agnos_update
    try:
      needed, current, required = os_update_needed(INSTALL_PATH)
    except Exception:
      return True  # never block an install on a version-check failure
    if not needed:
      return True

    ble = self.ble_setup
    # When a phone is driving setup, require it to confirm the OS update. With no
    # phone (on-screen-only install) proceed automatically — the fork requires it.
    if ble is not None and getattr(ble, "phone_active", False):
      ble.os_update.request(current, required)
      ble.set_install_progress("os_update_required", 0, os_from=current, os_to=required)
      if not ble.os_update.wait_for_confirm(timeout=300):
        ble.set_install_progress("failed", error="os_update_not_confirmed")
        self.download_failed(label, f"IQ.OS update to {required} was not confirmed.")
        return False

    def _cb(pct: int, note: str):
      if ble is not None:
        ble.set_install_progress("os_updating", pct, error=note, os_from=current, os_to=required)

    if not run_agnos_update(INSTALL_PATH, HARDWARE.get_device_type(), _cb):
      if ble is not None:
        ble.set_install_progress("failed", error="os_update_failed")
      self.download_failed(label, f"IQ.OS update to {required} failed. Please try again.")
      return False
    return True

  def _download_thread(self):
    try:
      import tempfile

      fd, tmpfile = tempfile.mkstemp(prefix="installer_")

      headers = {"User-Agent": USER_AGENT,
                 "X-openpilot-serial": HARDWARE.get_serial(),
                 "X-openpilot-device-type": HARDWARE.get_device_type()}
      req = urllib.request.Request(self.download_url, headers=headers)

      with open(tmpfile, 'wb') as f, urllib.request.urlopen(req, timeout=30) as response:
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        block_size = 8192

        while True:
          buffer = response.read(block_size)
          if not buffer:
            break

          downloaded += len(buffer)
          f.write(buffer)

          if total_size:
            self.download_progress = int(downloaded * 100 / total_size)

      is_elf = False
      with open(tmpfile, 'rb') as f:
        header = f.read(4)
        is_elf = header == b'\x7fELF'

      if not is_elf:
        self.download_failed(self.download_url, "No custom software found at this URL.")
        return

      # AGNOS might try to execute the installer before this process exits.
      # Therefore, important to close the fd before renaming the installer.
      os.close(fd)
      # comma's ELF installer does `rm -rf /data/openpilot` as the comma user and asserts it
      # succeeds; a prior *run* install leaves root-owned __pycache__ .pyc it can't delete, so it
      # aborts before continue.sh and bounces back to setup. Clear the old tree first (sudo) so the
      # installer's rm succeeds.
      subprocess.run(["sudo", "rm", "-rf", INSTALL_PATH], check=False)
      os.rename(tmpfile, INSTALLER_DESTINATION_PATH)

      with open(INSTALLER_URL_PATH, "w") as f:
        f.write(self.download_url)

      # give time for installer UI to take over
      time.sleep(0.1)
      gui_app.request_close()

    except urllib.error.HTTPError as e:
      if e.code == 409:
        error_msg = e.read().decode("utf-8")
        self.download_failed(self.download_url, error_msg)
    except Exception:
      error_msg = "Ensure the entered URL is valid, and the device's internet connection is good."
      self.download_failed(self.download_url, error_msg)

  def download_failed(self, url: str, reason: str):
    self.failed_url = url
    self.failed_reason = reason
    self.state = SetupState.DOWNLOAD_FAILED


def main():
  try:
    gui_app.init_window("Setup", 20)
    setup = Setup()
    for should_render in gui_app.render():
      if should_render:
        setup.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
    setup.close()
  except Exception as e:
    print(f"Setup error: {e}")
  finally:
    gui_app.close()


if __name__ == "__main__":
  main()
