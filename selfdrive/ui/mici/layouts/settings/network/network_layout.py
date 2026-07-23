"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import pyray as rl
from enum import IntEnum
from collections.abc import Callable

from openpilot.system.ui.widgets.scroller import Scroller, draw_scroller_edge_fades, draw_scroller_page_slider
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
from openpilot.selfdrive.ui.mici.layouts.settings.network.esim_ui import EsimUIMici
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigParamControl, BigMultiToggle
from openpilot.selfdrive.ui.mici.widgets.stock_dialog import BigInputDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.system.ui.lib.wifi_manager import WifiManager, Network, MeteredType
from openpilot.system.hardware.tici.esim_manager import get_esim_manager


class NetworkPanelType(IntEnum):
  NONE = 0
  WIFI = 1
  ESIM = 2


class NetworkLayoutMici(NavWidget):
  CALLBACK_INTERVAL_FRAMES = 3

  def __init__(self, back_callback: Callable):
    super().__init__()

    self._current_panel = NetworkPanelType.WIFI
    self._callback_frame = 0
    self._esim_profile_count: str | None = None
    self._esim_profile_frame = 0

    self._wifi_manager = WifiManager()
    self._wifi_manager.set_active(False)
    self._wifi_ui = WifiUIMici(self._wifi_manager)
    self._esim_ui = EsimUIMici(back_callback=lambda: self._switch_to_panel(NetworkPanelType.NONE))
    self._esim_manager = get_esim_manager()

    self._wifi_manager.add_callbacks(
      networks_updated=self._on_network_updated,
    )

    # ******** Tethering ********
    def tethering_toggle_callback(checked: bool):
      self._tethering_toggle_btn.set_enabled(False)
      self._network_metered_btn.set_enabled(False)
      self._wifi_manager.set_tethering_active(checked)

    self._tethering_checked = False
    self._tethering_toggle_btn = BigButton("tethering", "disabled")
    self._tethering_toggle_btn.set_click_callback(lambda: self._on_tethering_clicked(tethering_toggle_callback))

    def tethering_password_callback(password: str):
      if password:
        self._wifi_manager.set_tethering_password(password)

    def tethering_password_clicked():
      tethering_password = self._wifi_manager.tethering_password
      dlg = BigInputDialog("enter password...", tethering_password, minimum_length=8,
                           confirm_callback=tethering_password_callback)
      gui_app.push_widget(dlg)

    self._tethering_password_btn = BigButton("tethering password")
    self._tethering_password_btn.set_click_callback(tethering_password_clicked)

    # ******** IP Address ********
    self._ip_address_btn = BigButton("IP Address", "Not connected")

    # ******** Network Metered ********
    def network_metered_callback(value: str):
      self._network_metered_btn.set_enabled(False)
      metered = {
        'default': MeteredType.UNKNOWN,
        'metered': MeteredType.YES,
        'unmetered': MeteredType.NO
      }.get(value, MeteredType.UNKNOWN)
      self._wifi_manager.set_current_network_metered(metered)

    # TODO: signal for current network metered type when changing networks, this is wrong until you press it once
    # TODO: disable when not connected
    self._network_metered_btn = BigMultiToggle("network usage", ["default", "metered", "unmetered"], select_callback=network_metered_callback)
    self._network_metered_btn.set_enabled(False)

    wifi_button = BigButton("wi-fi")
    wifi_button.set_click_callback(lambda: gui_app.push_widget(self._wifi_ui))
    self._esim_button = BigButton("eSIM", "manage profiles")
    self._esim_button.set_click_callback(lambda: self._switch_to_panel(NetworkPanelType.ESIM))
    self._esim_button.set_visible(lambda: self._esim_manager.is_supported())

    # ******** Advanced settings ********
    # ******** Roaming toggle ********
    self._roaming_btn = BigParamControl("enable roaming", "GsmRoaming", toggle_callback=self._toggle_roaming)

    # ******** APN settings ********
    self._apn_btn = BigButton("apn settings")
    self._apn_btn.set_click_callback(self._edit_apn)

    # ******** Cellular metered toggle ********
    self._cellular_metered_btn = BigParamControl("cellular metered", "GsmMetered", toggle_callback=self._toggle_cellular_metered)

    # Main scroller ----------------------------------
    self._scroller = Scroller([
      wifi_button,
      self._esim_button,
      self._network_metered_btn,
      self._tethering_toggle_btn,
      self._tethering_password_btn,
      # /* Advanced settings
      self._roaming_btn,
      self._apn_btn,
      self._cellular_metered_btn,
      # */
      self._ip_address_btn,
    ], snap_items=False)

    # Set initial config
    roaming_enabled = ui_state.params.get_bool("GsmRoaming")
    metered = ui_state.params.get_bool("GsmMetered")
    self._wifi_manager.update_gsm_settings(roaming_enabled, ui_state.params.get("GsmApn") or "", metered)

    # Set up back navigation
    self.set_back_callback(back_callback)

  def _back_enabled(self) -> bool:
    # Only allow swipe-to-dismiss back to settings when no sub-panel (eSIM) is open.
    return self._current_panel == NetworkPanelType.NONE

  def _update_state(self):
    super()._update_state()

    # konn3kt has no managed cellular SIM, so always expose the GSM/APN settings.
    show_cell_settings = True
    self._wifi_manager.set_ipv4_forward(show_cell_settings)
    self._roaming_btn.set_visible(show_cell_settings)
    self._apn_btn.set_visible(show_cell_settings)
    self._cellular_metered_btn.set_visible(show_cell_settings)

    self._esim_profile_frame += 1
    if self._esim_profile_frame % 30 == 0:
      esim_profiles = (self._esim_manager.get_state().profiles or []) if self._esim_manager.is_supported() else []
      count = f"{len(esim_profiles)} profiles"
      if count != self._esim_profile_count:
        self._esim_profile_count = count
        self._esim_button.set_value(count)

  def show_event(self):
    super().show_event()
    self._current_panel = NetworkPanelType.NONE
    self._esim_profile_frame = 0
    self._esim_profile_count = None
    self._roaming_btn.refresh()
    self._cellular_metered_btn.refresh()
    self._scroller.show_event()

  def hide_event(self):
    super().hide_event()
    if self._current_panel == NetworkPanelType.ESIM:
      self._esim_ui.hide_event()

  def _toggle_roaming(self, checked: bool):
    self._wifi_manager.update_gsm_settings(checked, ui_state.params.get("GsmApn") or "", ui_state.params.get_bool("GsmMetered"))

  def _edit_apn(self):
    def update_apn(apn: str):
      apn = apn.strip()
      if apn == "":
        ui_state.params.remove("GsmApn")
      else:
        ui_state.params.put("GsmApn", apn)

      self._wifi_manager.update_gsm_settings(ui_state.params.get_bool("GsmRoaming"), apn, ui_state.params.get_bool("GsmMetered"))

    current_apn = ui_state.params.get("GsmApn") or ""
    dlg = BigInputDialog("enter APN", current_apn, minimum_length=0, confirm_callback=update_apn)
    gui_app.push_widget(dlg)

  def _toggle_cellular_metered(self, checked: bool):
    self._wifi_manager.update_gsm_settings(ui_state.params.get_bool("GsmRoaming"), ui_state.params.get("GsmApn") or "", checked)

  def _on_tethering_clicked(self, toggle_callback):
    self._tethering_checked = not self._tethering_checked
    self._tethering_toggle_btn.set_value("enabled" if self._tethering_checked else "disabled")
    toggle_callback(self._tethering_checked)

  def _on_network_updated(self, networks: list[Network]):
    # Update tethering state
    tethering_active = self._wifi_manager.is_tethering_active()
    self._tethering_toggle_btn.set_enabled(True)
    self._network_metered_btn.set_enabled(lambda: not tethering_active and bool(self._wifi_manager.ipv4_address))
    self._tethering_checked = tethering_active
    self._tethering_toggle_btn.set_value("enabled" if tethering_active else "disabled")

    # Update IP address
    self._ip_address_btn.set_value(self._wifi_manager.ipv4_address or "Not connected")

    # Update network metered
    self._network_metered_btn.set_value(
      {
        MeteredType.UNKNOWN: 'default',
        MeteredType.YES: 'metered',
        MeteredType.NO: 'unmetered'
      }.get(self._wifi_manager.current_network_metered, 'default'))

  def _switch_to_panel(self, panel_type: NetworkPanelType):
    if panel_type == NetworkPanelType.ESIM:
      if not self._esim_manager.is_supported():
        return
      self._esim_ui.show_event()
    elif self._current_panel == NetworkPanelType.ESIM:
      self._esim_ui.hide_event()

    self._current_panel = panel_type

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    if self._callback_frame % self.CALLBACK_INTERVAL_FRAMES == 0:
      self._wifi_manager.process_callbacks()
    self._callback_frame += 1

    if self._current_panel == NetworkPanelType.ESIM:
      self._esim_ui.render(rect)
    else:
      self._scroller.render(rect)
      draw_scroller_edge_fades(rect)
      draw_scroller_page_slider(self._scroller, rect)
