"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import threading
import time
import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.network import NetworkUI, PanelType
from openpilot.common.swaglog import cloudlog


class IQNetworkUI(NetworkUI):
  def __init__(self, wifi_manager):
    super().__init__(wifi_manager)

    self.scan_button = Button(tr("Scan"), self._scan_clicked, button_style=ButtonStyle.NORMAL, font_size=60, border_radius=30)
    self.scan_button.set_rect(rl.Rectangle(0, 0, 400, 100))

    self._scanning = False
    self._scan_failed = False
    self._wifi_manager.add_callbacks(networks_updated=self._on_networks_updated)

  def _scan_clicked(self):
    self._scanning = True
    self.scan_button.set_text(tr("Scanning..."))
    self.scan_button.set_enabled(False)
    threading.Thread(target=self._run_scan, daemon=True).start()

  def _run_scan(self):
    try:
      self._wifi_manager._update_networks()
      self._wifi_manager._request_scan()
      self._wifi_manager._last_network_update = time.monotonic()
    except Exception:
      cloudlog.exception("IQNetworkUI scan failed")
      self._scan_failed = True

  def _on_networks_updated(self, networks):
    if self._scanning:
      self._scanning = False
      self._scan_failed = False
      self.scan_button.set_text(tr("Scan"))
      self.scan_button.set_enabled(True)

  def _render(self, rect: rl.Rectangle):
    super()._render(rect)

    if self._scan_failed:
      self._scan_failed = False
      self._scanning = False
      self.scan_button.set_text(tr("Scan"))
      self.scan_button.set_enabled(True)

    if self._current_panel == PanelType.WIFI:
      self.scan_button.set_position(self._rect.x, self._rect.y + 20)
      self.scan_button.render()
