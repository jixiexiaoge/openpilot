#!/usr/bin/env python3
from abc import abstractmethod
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
from collections.abc import Callable

import pyray as rl

from openpilot.common.utils import run_cmd
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.lib.scroll_panel2 import GuiScrollPanel2
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import (IconButton, SmallButton, WideRoundedButton, SmallerRoundedButton,
                                                SmallCircleIconButton, WidishRoundedButton, SmallRedPillButton,
                                                FullRoundedButton)
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.slider import LargerSlider, SmallSlider
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog

try:
  from cereal import log
  NetworkType = log.DeviceState.NetworkType
except ImportError:
  NetworkType = None

NETWORK_CHECK_URL = "https://openpilot.comma.ai"
IQPILOT_INSTALLER_URL = "IQLvbs/release"
USER_AGENT = f"AGNOSSetup-{HARDWARE.get_os_version()}"

CONTINUE_PATH = "/data/continue.sh"
TMP_CONTINUE_PATH = "/data/continue.sh.new"
INSTALL_PATH = "/data/openpilot"
TMP_INSTALL_PATH = "/data/tmppilot"
VALID_CACHE_PATH = "/data/.openpilot_cache"
INSTALLER_SOURCE_PATH = "/usr/comma/installer"
INSTALLER_DESTINATION_PATH = "/tmp/installer"
INSTALLER_URL_PATH = "/tmp/installer_url"

# "<user>/<branch>" maps to a GitHub fork. IQ.OS uses the DRM "magic" compositor, not Wayland,
# so comma's downloaded installers (installer.comma.ai) crash on launch; clone the fork directly.
GITHUB_FORK_URL = "https://github.com/{user}/openpilot.git"
# IQ.Pilot lives on the IQ Lvbs git server; github.com/IQLvbs is DMCA'd and dead.
GIT_URL_OVERRIDES = {"IQLvbs": "https://git.konn3kt.com/IQ.Lvbs/IQ.Pilot.git"}

CONTINUE = """#!/usr/bin/env bash

cd /data/openpilot
exec ./launch_openpilot.sh
"""


class NetworkConnectivityMonitor:
  def __init__(self, should_check: Callable[[], bool] | None = None, check_interval: float = 1.0):
    self.network_connected = threading.Event()
    self.wifi_connected = threading.Event()
    self._should_check = should_check or (lambda: True)
    self._check_interval = check_interval
    self._stop_event = threading.Event()
    self._thread: threading.Thread | None = None

  def start(self):
    self._stop_event.clear()
    if self._thread is None or not self._thread.is_alive():
      self._thread = threading.Thread(target=self._run, daemon=True)
      self._thread.start()

  def stop(self):
    if self._thread is not None:
      self._stop_event.set()
      self._thread.join()
      self._thread = None

  def reset(self):
    self.network_connected.clear()
    self.wifi_connected.clear()

  def _run(self):
    while not self._stop_event.is_set():
      if self._should_check():
        try:
          request = urllib.request.Request(NETWORK_CHECK_URL, method="HEAD")
          urllib.request.urlopen(request, timeout=1.0)
          self.network_connected.set()
          if NetworkType is not None and HARDWARE.get_network_type() == NetworkType.wifi:
            self.wifi_connected.set()
        except Exception:
          self.reset()
      else:
        self.reset()

      if self._stop_event.wait(timeout=self._check_interval):
        break


class SetupState(IntEnum):
  GETTING_STARTED = 0
  NETWORK_SETUP = 1
  NETWORK_SETUP_CUSTOM_SOFTWARE = 8
  SOFTWARE_SELECTION = 2
  DOWNLOADING = 4
  DOWNLOAD_FAILED = 5
  CUSTOM_SOFTWARE_WARNING = 6


IQ_GREEN = rl.Color(16, 185, 129, 255)  # konn3kt/IQ accent


class SetupBleCodePage(Widget):
  """The 6-digit pairing code the konn3kt app asks for when setting up this
  device over Bluetooth. Shown on-screen (Chromecast-style) while a phone drives
  setup — the code is the setup authorization."""
  def __init__(self, code_getter: Callable[[], str]):
    super().__init__()
    self._code_getter = code_getter

    self._eyebrow = UnifiedLabel("SET UP FROM YOUR PHONE", 26,
                                 text_color=rl.Color(255, 255, 255, int(255 * 0.55)),
                                 font_weight=FontWeight.BOLD, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                                 alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE, letter_spacing=0.14)
    self._code = UnifiedLabel(lambda: self._spaced_code(), 76,
                              text_color=rl.Color(255, 255, 255, int(255 * 0.95)),
                              font_weight=FontWeight.DISPLAY, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                              alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE,
                              letter_spacing=0.08, elide=False, wrap_text=False)
    self._hint = UnifiedLabel("Enter this code in the konn3kt app", 27,
                              text_color=IQ_GREEN, font_weight=FontWeight.MEDIUM,
                              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                              alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)

  def _spaced_code(self) -> str:
    c = (self._code_getter() or "").strip()
    return " ".join(c) if c else "······"

  def _render(self, rect: rl.Rectangle):
    self._eyebrow.render(rl.Rectangle(rect.x, rect.y + 30, rect.width, 34))
    self._code.render(rl.Rectangle(rect.x, rect.y + 84, rect.width, 90))
    self._hint.render(rl.Rectangle(rect.x, rect.y + rect.height - 48, rect.width, 34))


class StartPage(Widget):
  def __init__(self):
    super().__init__()

    self._title = UnifiedLabel("start", 64, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                               font_weight=FontWeight.DISPLAY, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
                               alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE)

    self._start_bg_txt = gui_app.texture("icons_mici/setup/green_button.png", 520, 224)
    self._start_bg_pressed_txt = gui_app.texture("icons_mici/setup/green_button_pressed.png", 520, 224)

  def _render(self, rect: rl.Rectangle):
    draw_x = rect.x + (rect.width - self._start_bg_txt.width) / 2
    draw_y = rect.y + (rect.height - self._start_bg_txt.height) / 2
    texture = self._start_bg_pressed_txt if self.is_pressed else self._start_bg_txt
    rl.draw_texture(texture, int(draw_x), int(draw_y), rl.WHITE)

    self._title.render(rect)


class SoftwareSelectionPage(Widget):
  def __init__(self, use_openpilot_callback: Callable,
               use_custom_software_callback: Callable):
    super().__init__()

    self._openpilot_slider = LargerSlider("slide to install\nIQ.Pilot", use_openpilot_callback)
    self._openpilot_slider.set_enabled(lambda: self.enabled)  # for nav stack
    self._custom_software_slider = LargerSlider("slide to use\ncustom software", use_custom_software_callback, green=False)
    self._custom_software_slider.set_enabled(lambda: self.enabled)  # for nav stack

  def reset(self):
    self._openpilot_slider.reset()
    self._custom_software_slider.reset()

  def _render(self, rect: rl.Rectangle):
    self._openpilot_slider.set_opacity(1.0 - self._custom_software_slider.slider_percentage)
    self._custom_software_slider.set_opacity(1.0 - self._openpilot_slider.slider_percentage)

    openpilot_rect = rl.Rectangle(
      rect.x + (rect.width - self._openpilot_slider.rect.width) / 2,
      rect.y,
      self._openpilot_slider.rect.width,
      rect.height / 2,
    )
    self._openpilot_slider.render(openpilot_rect)

    custom_software_rect = rl.Rectangle(
      rect.x + (rect.width - self._custom_software_slider.rect.width) / 2,
      rect.y + rect.height / 2,
      self._custom_software_slider.rect.width,
      rect.height / 2,
    )
    self._custom_software_slider.render(custom_software_rect)


class TermsHeader(Widget):
  def __init__(self, text: str, icon_texture: rl.Texture):
    super().__init__()

    self._title = UnifiedLabel(text, 36, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                               font_weight=FontWeight.BOLD, alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE,
                               line_height=0.8)
    self._icon_texture = icon_texture

    self.set_rect(rl.Rectangle(0, 0, gui_app.width - 16 * 2, self._icon_texture.height))

  def set_title(self, text: str):
    self._title.set_text(text)

  def set_icon(self, icon_texture: rl.Texture):
    self._icon_texture = icon_texture

  def _render(self, _):
    rl.draw_texture_ex(self._icon_texture, rl.Vector2(self._rect.x, self._rect.y),
                       0.0, 1.0, rl.WHITE)

    # May expand outside parent rect
    title_content_height = self._title.get_content_height(int(self._rect.width - self._icon_texture.width - 16))
    title_rect = rl.Rectangle(
      self._rect.x + self._icon_texture.width + 16,
      self._rect.y + (self._rect.height - title_content_height) / 2,
      self._rect.width - self._icon_texture.width - 16,
      title_content_height,
    )
    self._title.render(title_rect)


class TermsPage(Widget):
  ITEM_SPACING = 20

  def __init__(self, continue_callback: Callable, back_callback: Callable | None = None,
               back_text: str = "back", continue_text: str = "accept"):
    super().__init__()

    # TODO: use Scroller
    self._scroll_panel = GuiScrollPanel2(horizontal=False)

    self._continue_text = continue_text
    self._continue_slider: bool = continue_text in ("reboot", "power off")
    self._continue_button: WideRoundedButton | FullRoundedButton | SmallSlider
    if self._continue_slider:
      self._continue_button = SmallSlider(continue_text, confirm_callback=continue_callback)
      self._scroll_panel.set_enabled(lambda: not self._continue_button.is_pressed)
    elif back_callback is not None:
      self._continue_button = WideRoundedButton(continue_text)
    else:
      self._continue_button = FullRoundedButton(continue_text)
    self._continue_button.set_enabled(False)
    self._continue_button.set_opacity(0.0)
    self._continue_button.set_touch_valid_callback(self._scroll_panel.is_touch_valid)
    if not self._continue_slider:
      self._continue_button.set_click_callback(continue_callback)

    self._enable_back = back_callback is not None
    self._back_button = SmallButton(back_text)
    self._back_button.set_opacity(0.0)
    self._back_button.set_touch_valid_callback(self._scroll_panel.is_touch_valid)
    self._back_button.set_click_callback(back_callback)

    self._scroll_down_indicator = IconButton(gui_app.texture("icons_mici/setup/scroll_down_indicator.png", 64, 78))
    self._scroll_down_indicator.set_enabled(False)

  def reset(self):
    self._scroll_panel.set_offset(0)
    self._continue_button.set_enabled(False)
    self._continue_button.set_opacity(0.0)
    self._back_button.set_enabled(False)
    self._back_button.set_opacity(0.0)
    self._scroll_down_indicator.set_opacity(1.0)

  def show_event(self):
    super().show_event()
    self.reset()

  @property
  @abstractmethod
  def _content_height(self):
    pass

  @property
  def _scrolled_down_offset(self):
    return -self._content_height + (self._continue_button.rect.height + 16 + 30)

  @abstractmethod
  def _render_content(self, scroll_offset):
    pass

  def _render(self, _):
    scroll_offset = round(self._scroll_panel.update(self._rect, self._content_height + self._continue_button.rect.height + 16))

    if scroll_offset <= self._scrolled_down_offset:
      # don't show back if not enabled
      if self._enable_back:
        self._back_button.set_enabled(True)
        self._back_button.set_opacity(1.0, smooth=True)
      self._continue_button.set_enabled(True)
      self._continue_button.set_opacity(1.0, smooth=True)
      self._scroll_down_indicator.set_opacity(0.0, smooth=True)
    else:
      self._back_button.set_enabled(False)
      self._back_button.set_opacity(0.0, smooth=True)
      self._continue_button.set_enabled(False)
      self._continue_button.set_opacity(0.0, smooth=True)
      self._scroll_down_indicator.set_opacity(1.0, smooth=True)

    # Render content
    self._render_content(scroll_offset)

    # black gradient at top and bottom for scrolling content
    rl.draw_rectangle_gradient_v(int(self._rect.x), int(self._rect.y),
                                 int(self._rect.width), 20, rl.BLACK, rl.BLANK)
    rl.draw_rectangle_gradient_v(int(self._rect.x), int(self._rect.y + self._rect.height - 20),
                                 int(self._rect.width), 20, rl.BLANK, rl.BLACK)

    # fade out back button as slider is moved
    if self._continue_slider and scroll_offset <= self._scrolled_down_offset:
      self._back_button.set_opacity(1.0 - self._continue_button.slider_percentage)
      self._back_button.set_visible(self._continue_button.slider_percentage < 0.99)

    self._back_button.render(rl.Rectangle(
      self._rect.x + 8,
      self._rect.y + self._rect.height - self._back_button.rect.height,
      self._back_button.rect.width,
      self._back_button.rect.height,
    ))

    continue_x = self._rect.x + 8
    if self._enable_back:
      continue_x = self._rect.x + self._rect.width - self._continue_button.rect.width - 8
    if self._continue_slider:
      continue_x += 8
    self._continue_button.render(rl.Rectangle(
      continue_x,
      self._rect.y + self._rect.height - self._continue_button.rect.height,
      self._continue_button.rect.width,
      self._continue_button.rect.height,
    ))

    self._scroll_down_indicator.render(rl.Rectangle(
      self._rect.x + self._rect.width - self._scroll_down_indicator.rect.width - 8,
      self._rect.y + self._rect.height - self._scroll_down_indicator.rect.height - 8,
      self._scroll_down_indicator.rect.width,
      self._scroll_down_indicator.rect.height,
    ))


class CustomSoftwareWarningPage(TermsPage):
  def __init__(self, continue_callback: Callable, back_callback: Callable):
    super().__init__(continue_callback, back_callback)

    self._title_header = TermsHeader("use caution installing\n3rd party software",
                                     gui_app.texture("icons_mici/setup/warning.png", 66, 60))
    self._body = UnifiedLabel("• It has not been tested by comma.\n" +
                              "• It may not comply with relevant safety standards.\n" +
                              "• It may cause damage to your device and/or vehicle.\n", 36, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                              font_weight=FontWeight.ROMAN)

    self._restore_header = TermsHeader("how to backup &\nrestore", gui_app.texture("icons_mici/setup/restore.png", 60, 60))
    self._restore_body = UnifiedLabel("To restore your device to a factory state later, use https://flash.comma.ai",
                                      36, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                                      font_weight=FontWeight.ROMAN)

  @property
  def _content_height(self):
    return self._restore_body.rect.y + self._restore_body.rect.height - self._scroll_panel.get_offset()

  def _render_content(self, scroll_offset):
    self._title_header.set_position(self._rect.x + 16, self._rect.y + 8 + scroll_offset)
    self._title_header.render()

    body_rect = rl.Rectangle(
      self._rect.x + 8,
      self._title_header.rect.y + self._title_header.rect.height + self.ITEM_SPACING,
      self._rect.width - 50,
      self._body.get_content_height(int(self._rect.width - 50)),
    )
    self._body.render(body_rect)

    self._restore_header.set_position(self._rect.x + 16, self._body.rect.y + self._body.rect.height + self.ITEM_SPACING)
    self._restore_header.render()

    self._restore_body.render(rl.Rectangle(
      self._rect.x + 8,
      self._restore_header.rect.y + self._restore_header.rect.height + self.ITEM_SPACING,
      self._rect.width - 50,
      self._restore_body.get_content_height(int(self._rect.width - 50)),
    ))


class DownloadingPage(Widget):
  def __init__(self):
    super().__init__()

    self._title_label = UnifiedLabel("downloading", 64, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                                     font_weight=FontWeight.DISPLAY)
    self._progress_label = UnifiedLabel("", 128, text_color=rl.Color(255, 255, 255, int(255 * 0.9 * 0.35)),
                                        font_weight=FontWeight.ROMAN, alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_BOTTOM)
    self._progress = 0

  def set_progress(self, progress: int):
    self._progress = progress
    self._progress_label.set_text(f"{progress}%")

  def _render(self, rect: rl.Rectangle):
    self._title_label.render(rl.Rectangle(
      rect.x + 20,
      rect.y + 10,
      rect.width,
      64,
    ))

    self._progress_label.render(rl.Rectangle(
      rect.x + 20,
      rect.y + 20,
      rect.width,
      rect.height,
    ))


class FailedPage(Widget):
  def __init__(self, reboot_callback: Callable, retry_callback: Callable, title: str = "download failed"):
    super().__init__()

    self._title_label = UnifiedLabel(title, 64, text_color=rl.Color(255, 255, 255, int(255 * 0.9)),
                                     font_weight=FontWeight.DISPLAY)
    self._reason_label = UnifiedLabel("", 36, text_color=rl.Color(255, 255, 255, int(255 * 0.9 * 0.65)),
                                      font_weight=FontWeight.ROMAN)

    self._reboot_button = SmallRedPillButton("reboot")
    self._reboot_button.set_click_callback(reboot_callback)
    self._reboot_button.set_enabled(lambda: self.enabled)  # for nav stack

    self._retry_button = WideRoundedButton("retry")
    self._retry_button.set_click_callback(retry_callback)
    self._retry_button.set_enabled(lambda: self.enabled)  # for nav stack

  def set_reason(self, reason: str):
    self._reason_label.set_text(reason)

  def _render(self, rect: rl.Rectangle):
    self._title_label.render(rl.Rectangle(
      rect.x + 8,
      rect.y + 10,
      rect.width,
      64,
    ))

    self._reason_label.render(rl.Rectangle(
      rect.x + 8,
      rect.y + 10 + 64,
      rect.width,
      36,
    ))

    self._reboot_button.render(rl.Rectangle(
      rect.x + 8,
      rect.y + rect.height - self._reboot_button.rect.height,
      self._reboot_button.rect.width,
      self._reboot_button.rect.height,
    ))

    self._retry_button.render(rl.Rectangle(
      rect.x + 8 + self._reboot_button.rect.width + 8,
      rect.y + rect.height - self._retry_button.rect.height,
      self._retry_button.rect.width,
      self._retry_button.rect.height,
    ))


class NetworkSetupPage(Widget):
  def __init__(self, wifi_manager, continue_callback: Callable, back_callback: Callable):
    super().__init__()
    self._wifi_ui = WifiUIMici(wifi_manager)

    self._no_wifi_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_slash.png", 58, 50)
    self._wifi_full_txt = gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 58, 50)
    self._waiting_text = "waiting for internet..."
    self._network_header = TermsHeader(self._waiting_text, self._no_wifi_txt)

    back_txt = gui_app.texture("icons_mici/setup/back_new.png", 37, 32)
    self._back_button = SmallCircleIconButton(back_txt)
    self._back_button.set_click_callback(back_callback)
    self._back_button.set_enabled(lambda: self.enabled)  # for nav stack

    self._wifi_button = SmallerRoundedButton("wifi")
    self._wifi_button.set_click_callback(lambda: gui_app.push_widget(self._wifi_ui))
    self._wifi_button.set_enabled(lambda: self.enabled)  # for nav stack

    self._continue_button = WidishRoundedButton("continue")
    self._continue_button.set_enabled(False)
    self._continue_button.set_click_callback(continue_callback)

  def set_has_internet(self, has_internet: bool):
    if has_internet:
      self._network_header.set_title("connected to internet")
      self._network_header.set_icon(self._wifi_full_txt)
      self._continue_button.set_enabled(self.enabled)
    else:
      self._network_header.set_title(self._waiting_text)
      self._network_header.set_icon(self._no_wifi_txt)
      self._continue_button.set_enabled(False)

  def _render(self, _):
    self._network_header.render(rl.Rectangle(
      self._rect.x + 16,
      self._rect.y + 16,
      self._rect.width - 32,
      self._network_header.rect.height,
    ))

    self._back_button.render(rl.Rectangle(
      self._rect.x + 8,
      self._rect.y + self._rect.height - self._back_button.rect.height,
      self._back_button.rect.width,
      self._back_button.rect.height,
    ))

    self._wifi_button.render(rl.Rectangle(
      self._rect.x + 8 + self._back_button.rect.width + 10,
      self._rect.y + self._rect.height - self._wifi_button.rect.height,
      self._wifi_button.rect.width,
      self._wifi_button.rect.height,
    ))

    self._continue_button.render(rl.Rectangle(
      self._rect.x + self._rect.width - self._continue_button.rect.width - 8,
      self._rect.y + self._rect.height - self._continue_button.rect.height,
      self._continue_button.rect.width,
      self._continue_button.rect.height,
    ))


class Setup(Widget):
  def __init__(self):
    super().__init__()
    self.state = SetupState.GETTING_STARTED
    self.failed_url = ""
    self.failed_reason = ""
    self.download_url = ""
    self.download_progress = 0
    self.download_thread = None
    self._wifi_manager = WifiManager()
    self._wifi_manager.set_active(True)
    # BLE zero-touch setup (Phase A) — shares this WifiManager. Best-effort.
    self.ble_setup = None
    self._ble_pending_install_url = None
    self._init_ble_setup()
    self._network_monitor = NetworkConnectivityMonitor()
    self._network_monitor.start()
    self._prev_has_internet = False
    gui_app.add_nav_stack_tick(self._nav_stack_tick)

    self._start_page = StartPage()
    self._start_page.set_click_callback(self._getting_started_button_callback)

    self._network_setup_page = NetworkSetupPage(self._wifi_manager, self._network_setup_continue_button_callback,
                                                self._network_setup_back_button_callback)
    self._network_setup_page.set_enabled(lambda: self.enabled)  # for nav stack

    self._software_selection_page = SoftwareSelectionPage(self._software_selection_continue_button_callback,
                                                          self._software_selection_custom_software_button_callback)
    self._software_selection_page.set_enabled(lambda: self.enabled)  # for nav stack

    self._download_failed_page = FailedPage(HARDWARE.reboot, self._download_failed_startover_button_callback)
    self._download_failed_page.set_enabled(lambda: self.enabled)  # for nav stack

    self._custom_software_warning_page = CustomSoftwareWarningPage(self._software_selection_custom_software_continue,
                                                                   self._custom_software_warning_back_button_callback)
    self._custom_software_warning_page.set_enabled(lambda: self.enabled)  # for nav stack

    self._downloading_page = DownloadingPage()

  def _nav_stack_tick(self):
    has_internet = self._network_monitor.network_connected.is_set()
    if has_internet and not self._prev_has_internet:
      gui_app.pop_widgets_to(self)
    self._prev_has_internet = has_internet

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
        wifi_manager=self._wifi_manager,
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
    self._ble_pending_install_url = url

  def _ble_sync(self):
    if self.ble_setup is None:
      return
    if self._ble_pending_install_url is not None:
      url = self._ble_pending_install_url
      self._ble_pending_install_url = None
      if self.state not in (SetupState.DOWNLOADING, SetupState.DOWNLOAD_FAILED):
        self.download(url)
    # Install progress is reported by the install thread (_ble_progress /
    # _maybe_update_os) as the single source of truth. Do NOT push per-frame here:
    # a ~60fps "downloading" push floods over the thread's os_update_required /
    # installing / rebooting states so the phone never sees them (the OS-update
    # confirm prompt would never appear). Only relay the terminal failure reason.
    if self.state == SetupState.DOWNLOAD_FAILED:
      self.ble_setup.set_install_progress("failed", 0, self.failed_reason)

  def _update_state(self):
    self._ble_sync()
    self._wifi_manager.process_callbacks()

  def _set_state(self, state: SetupState):
    self.state = state
    if self.state == SetupState.SOFTWARE_SELECTION:
      self._software_selection_page.reset()
    elif self.state == SetupState.CUSTOM_SOFTWARE_WARNING:
      self._custom_software_warning_page.reset()

    if self.state in (SetupState.NETWORK_SETUP, SetupState.NETWORK_SETUP_CUSTOM_SOFTWARE):
      self._network_setup_page.show_event()
      self._network_monitor.reset()
    else:
      self._network_setup_page.hide_event()

  def _render(self, rect: rl.Rectangle):
    if self.state == SetupState.GETTING_STARTED:
      self._start_page.render(rect)
    elif self.state in (SetupState.NETWORK_SETUP, SetupState.NETWORK_SETUP_CUSTOM_SOFTWARE):
      self.render_network_setup(rect)
    elif self.state == SetupState.SOFTWARE_SELECTION:
      self._software_selection_page.render(rect)
    elif self.state == SetupState.CUSTOM_SOFTWARE_WARNING:
      self._custom_software_warning_page.render(rect)
    elif self.state == SetupState.DOWNLOADING:
      self.render_downloading(rect)
    elif self.state == SetupState.DOWNLOAD_FAILED:
      self._download_failed_page.render(rect)

  def _custom_software_warning_back_button_callback(self):
    self._set_state(SetupState.SOFTWARE_SELECTION)

  def _getting_started_button_callback(self):
    self._set_state(SetupState.SOFTWARE_SELECTION)

  def _software_selection_back_button_callback(self):
    self._set_state(SetupState.GETTING_STARTED)

  def _software_selection_continue_button_callback(self):
    self.use_iqpilot()

  def _software_selection_custom_software_button_callback(self):
    self._set_state(SetupState.CUSTOM_SOFTWARE_WARNING)

  def _software_selection_custom_software_continue(self):
    self._set_state(SetupState.NETWORK_SETUP_CUSTOM_SOFTWARE)

  def _download_failed_startover_button_callback(self):
    self._set_state(SetupState.GETTING_STARTED)

  def _network_setup_back_button_callback(self):
    self._set_state(SetupState.SOFTWARE_SELECTION)

  def _network_setup_continue_button_callback(self):
    if self.state == SetupState.NETWORK_SETUP:
      self.download(IQPILOT_INSTALLER_URL)
    elif self.state == SetupState.NETWORK_SETUP_CUSTOM_SOFTWARE:
      def handle_keyboard_result(text):
        url = text.strip()
        if url:
          self.download(url)

      keyboard = BigInputDialog("custom software URL", confirm_callback=handle_keyboard_result)
      gui_app.push_widget(keyboard)

  def close(self):
    self._network_monitor.stop()

  def render_network_setup(self, rect: rl.Rectangle):
    has_internet = self._network_monitor.network_connected.is_set()
    self._network_setup_page.set_has_internet(has_internet)
    self._network_setup_page.render(rect)

  def render_downloading(self, rect: rl.Rectangle):
    self._downloading_page.set_progress(self.download_progress)
    self._downloading_page.render(rect)

  def use_iqpilot(self):
    self._set_state(SetupState.NETWORK_SETUP)

  def download(self, url: str):
    self._set_state(SetupState.DOWNLOADING)

    # "<user>/<branch>" maps to a GitHub fork (e.g. IQLvbs/release). Clone it directly here rather
    # than fetching comma's Wayland installer, which can't run on IQ.OS's DRM compositor.
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
    try:
      subprocess.run(["rm", "-rf", TMP_INSTALL_PATH], check=False)

      self._ble_progress("downloading", 10)
      clone = subprocess.run(["git", "clone", "--depth=1", "--recurse-submodules",
                              "-b", branch, git_url, TMP_INSTALL_PATH])
      if clone.returncode != 0:
        self._ble_progress("failed")
        self.download_failed(label, "No custom software found at this URL.")
        return

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

      # comma.sh blocks waiting for /tmp/installer before checking for continue.sh; the real
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
      self.download_failed(label, "Invalid URL")

  def _maybe_update_os(self, label: str) -> bool:
    # The freshly-installed fork pins the IQ.OS it needs in launch_env.sh. If it
    # differs from what we're running, flash it now (via comma's agnos.py) so the
    # upcoming single reboot lands on a compatible OS instead of dead-ending on
    # "update required". Returns False (and shows the failed page) on abort.
    from openpilot.system.ui.lib.os_update import os_update_needed, run_agnos_update
    try:
      needed, current, required = os_update_needed(INSTALL_PATH)
    except Exception:
      return True  # never block an install on a version-check failure
    if not needed:
      return True

    ble = self.ble_setup
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
            self._downloading_page.set_progress(self.download_progress)

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
        error_msg = "Incompatible IQ.Pilot version"
        self.download_failed(self.download_url, error_msg)
    except Exception:
      error_msg = "Invalid URL"
      self.download_failed(self.download_url, error_msg)

  def download_failed(self, url: str, reason: str):
    self.failed_url = url
    self.failed_reason = reason
    self._download_failed_page.set_reason(reason)
    self._set_state(SetupState.DOWNLOAD_FAILED)


def main():
  try:
    gui_app.init_window("Setup")
    setup = Setup()
    gui_app.push_widget(setup)
    for _ in gui_app.render():
      pass
    setup.close()
  except Exception as e:
    print(f"Setup error: {e}")
  finally:
    gui_app.close()


if __name__ == "__main__":
  main()
