"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Consolidated IQ.Pilot settings panels (display, visuals, network, maps, steering
and its lane-change / steering-assist sub-panels) in one module.
"""
from cereal import car
from collections.abc import Callable
from enum import Enum
from enum import IntEnum
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import OnroadBrightness
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.selfdrive.controls.lib.helpers.lane_change import AutoLaneChangeMode
from openpilot.iqpilot.ui.onroad.offline_tiles import offline_map_root
from openpilot.selfdrive.ui.layouts.settings.software import time_ago
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.iqpilot.lib.styles import style
from openpilot.system.ui.iqpilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem, toggle_item
from openpilot.system.ui.iqpilot.widgets.list_view import OptionControl
from openpilot.system.ui.iqpilot.widgets.list_view import multiple_button_item, toggle_item
from openpilot.system.ui.iqpilot.widgets.list_view import option_item, toggle_item, ToggleAction
from openpilot.system.ui.iqpilot.widgets.list_view import progress_item
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item, multiple_button_item, IQListItem, IQLineSeparator
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item, option_item, IQLineSeparator
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item, simple_button_item, option_item, IQLineSeparator
from openpilot.system.ui.iqpilot.widgets.list_view import TreeFolder, TreeNode, TreeOptionDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.network import NetworkUI, PanelType as NetworkPanelType, TEAL
from openpilot.system.ui.widgets.scroller_tici import Scroller
from pathlib import Path
from time import monotonic
import datetime
import os
import platform
import pyray as rl
import requests
import shutil
import threading
import time


from cereal import custom
from dataclasses import dataclass
from openpilot.iqpilot.selfdrive.car.vehicle_catalog import load_catalog
from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import select_default_model, is_default_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import CUSTOM_MODEL_PATH
from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.iqpilot.lib.styles import metrics
from openpilot.system.ui.iqpilot.widgets.list_view import (
  option_item as option_item,
  multiple_button_item as multiple_button_item,
  button_item as button_item,
  dual_button_item as dual_button_item,
  NavSectionButton,
  Spacer,
)
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem, IQMultipleButtonAction, IQToggleAction, IQLineSeparator
from openpilot.system.ui.iqpilot.widgets.list_view import button_item, toggle_item
from openpilot.system.ui.iqpilot.widgets.list_view import NoticeModal
from openpilot.system.ui.iqpilot.widgets.list_view import TreeOptionDialog, TreeNode, TreeFolder
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog, ConfirmDialog
from openpilot.system.ui.widgets.list_view import button_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import LineSeparator
from openpilot.system.ui.widgets.toggle import ON_COLOR
import re

from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.selfdrive.ui.layouts.settings.device import DeviceLayout
from openpilot.selfdrive.ui.layouts.settings.software import SoftwareLayout, time_ago

from functools import partial
from iqdbc.car.hyundai.values import CAR, CANFD_UNSUPPORTED_LONGITUDINAL_CAR, UNSUPPORTED_LONGITUDINAL_CAR
from iqdbc.car.subaru.values import CAR, SubaruFlags
from iqdbc.car.volkswagen.values import CAR, VolkswagenFlags
from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.iqpilot.lib.styles import ink
from openpilot.system.ui.iqpilot.widgets.list_view import multiple_button_item
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets.list_view import ButtonAction
import json

# ===== display =====

ONROAD_BRIGHTNESS_TIMER_VALUES = {0: 15, 1: 30, **{i: (i - 1) * 60 for i in range(2, 12)}}




def _fmt_seconds(value) -> str:
  return f"{value} s" if value < 60 else f"{int(value / 60)} m"


def onroad_brightness_label(val) -> str:
  if val == OnroadBrightness.AUTO:
    return tr("Auto (Default)")
  if val == OnroadBrightness.AUTO_DARK:
    return tr("Auto (Dark)")
  return f"{(val - 1) * 5} %"


class DisplayLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._scroller = Scroller(self._build_rows(), line_separator=True, spacing=0)

  def _build_rows(self):
    self._force_mici_ui = toggle_item(
      title=lambda: tr("Force Mici UI"),
      description=lambda: tr("Run the compact comma 4 (mici) interface on this device") if self._params.get_bool("ForceSmallUI") else "",
      param="ForceSmallUI",
    )
    self._brightness_row = option_item(
      param="Brightness", title=lambda: tr("Display Brightness"), description="",
      min_value=0, max_value=100, value_change_step=5,
      label_callback=lambda v: tr("Default") if v == 0 else f"{v} %", inline=True,
    )
    self._onroad_brightness_row = option_item(
      param="OnroadScreenOffBrightness", title=lambda: tr("Onroad Brightness"), description="",
      min_value=0, max_value=21, value_change_step=1,
      label_callback=onroad_brightness_label, inline=True,
    )
    self._dim_delay_row = option_item(
      param="OnroadScreenOffTimer", title=lambda: tr("Onroad Brightness Delay"), description="",
      min_value=0, max_value=11, value_change_step=1,
      value_map=ONROAD_BRIGHTNESS_TIMER_VALUES, label_callback=_fmt_seconds, inline=True,
    )
    self._idle_close_row = option_item(
      param="InteractivityTimeout", title=lambda: tr("Interactivity Timeout"),
      description=lambda: tr("How long the settings screen may sit untouched before it closes itself."),
      min_value=0, max_value=120, value_change_step=10,
      label_callback=lambda v: tr("Default") if not v else _fmt_seconds(v), inline=True,
    )
    return [
      self._force_mici_ui,
      self._brightness_row,
      self._onroad_brightness_row,
      self._dim_delay_row,
      self._idle_close_row,
    ]

  # kept name: visuals.py and ui_state historically called through this
  update_onroad_brightness = staticmethod(onroad_brightness_label)

  def _update_state(self):
    super()._update_state()
    for row in self._scroller._items:
      action = row.action_item
      if isinstance(action, ToggleAction) and action.toggle.param_key is not None:
        action.set_state(self._params.get_bool(action.toggle.param_key))
      elif isinstance(action, OptionControl) and action.param_key is not None:
        action.set_value(self._params.get(action.param_key, return_default=True))

    mode = self._params.get("OnroadScreenOffBrightness", return_default=True)
    self._dim_delay_row.action_item.set_enabled(mode not in (OnroadBrightness.AUTO, OnroadBrightness.AUTO_DARK))

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()

# ===== visuals =====

CHEVRON_INFO_DESCRIPTION = {
  "enabled": tr_noop("Pins live readouts (gap, speed, time-to-lead) to the chevron marking the car ahead. "
                     "Needs IQ.Pilot to be the one controlling gas and brake."),
  "disabled": tr_noop("Unavailable — IQ.Pilot longitudinal control is not active on this car."),
}

# param key -> (title fn, description fn)
_HUD_TOGGLES = {
  "BlindSpot": (
    lambda: tr("Show Blind Spot Warnings"),
    lambda: tr("Flashes a side warning whenever the car reports something sitting in your blind spot (BSM-equipped cars only)."),
  ),
  "IQExpandedStatus": (
    lambda: tr("Expanded Status Bar"),
    lambda: tr("Bring back the classic UI's wide offroad status strip: temperature, vehicle, and Konn3kt state at a glance."),
  ),
  "TorqueBar": (
    lambda: tr("Steering Arc"),
    lambda: tr("Trace an arc over the road view showing how much steering IQ.Pilot is applying while lateral control runs."),
  ),
  "RoadNameToggle": (
    lambda: tr("Display Road Name"),
    lambda: tr("Show the current road's name over the driving view."
               "<br>Requires offline map data for your region to be installed."),
  ),
  "ShowTurnSignals": (
    lambda: tr("Display Turn Signals"),
    lambda: tr("Mirror the car's blinkers as arrows on the driving screen."),
  ),
  "RocketFuel": (
    lambda: tr("Real-time Acceleration Bar"),
    lambda: tr("Draw a bar along the left edge tracking measured acceleration and braking — what the car is actually "
               "doing right now, not the planner's request."),
  ),
}

_SECTION_TITLE_COLOR = rl.Color(16, 185, 169, 255)


class VisualsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._display_layout = DisplayLayout()
    self._scroller = Scroller(self._build_rows(), line_separator=True, spacing=0)

  def _build_rows(self):
    self._toggles = {
      key: toggle_item(title=title, description=desc, param=key,
                       initial_state=ui_state.params.get_bool(key))
      for key, (title, desc) in _HUD_TOGGLES.items()
    }

    self._chevron_info = multiple_button_item(
      title=lambda: tr("Display Metrics Below Chevron"),
      description="",
      buttons=[lambda: tr("Off"), lambda: tr("Distance"), lambda: tr("Speed"), lambda: tr("Time"), lambda: tr("All")],
      param="ChevronInfo",
      inline=False,
    )
    self._dev_ui_info = toggle_item(
      title=lambda: tr("Onroad Developer UI"),
      description=lambda: tr("Overlay a bar of live control metrics (steering, lateral accel, lead data) while driving."),
      initial_state=bool(int(ui_state.params.get("IQDevUIInfo", return_default=True))),
      callback=lambda on: ui_state.params.put("IQDevUIInfo", 3 if on else 0),
    )

    # Display rows are shared with DisplayLayout (its row 0, Force Mici UI, stays there)
    display_rows = self._display_layout._scroller._items[1:]

    return [
      IQListItem(title=lambda: tr("Display"), description="", action_item=None, inline=True,
                 title_color=_SECTION_TITLE_COLOR),
      IQLineSeparator(20),
      *display_rows,
      IQLineSeparator(60),
      *self._toggles.values(),
      self._chevron_info,
      self._dev_ui_info,
    ]

  def _sync_chevron_row(self):
    if ui_state.has_longitudinal_control:
      self._chevron_info.set_description(tr(CHEVRON_INFO_DESCRIPTION["enabled"]))
      self._chevron_info.action_item.set_selected_button(ui_state.params.get("ChevronInfo", return_default=True))
      self._chevron_info.action_item.set_enabled(True)
    else:
      self._chevron_info.set_description(tr(CHEVRON_INFO_DESCRIPTION["disabled"]))
      self._chevron_info.action_item.set_enabled(False)
      ui_state.params.put("ChevronInfo", 0)

  def _update_state(self):
    super()._update_state()
    for key, row in self._toggles.items():
      row.action_item.set_state(self._params.get_bool(key))
    self._dev_ui_info.action_item.set_state(bool(int(ui_state.params.get("IQDevUIInfo", return_default=True))))
    self._sync_chevron_row()

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._display_layout.show_event()
    self._scroller.show_event()
    if not ui_state.has_longitudinal_control:
      self._chevron_info.set_description(tr(CHEVRON_INFO_DESCRIPTION["disabled"]))
      self._chevron_info.show_description(True)

# ===== network =====

_IDLE_BG = rl.Color(52, 55, 62, 255)


class ScanPhase(Enum):
  IDLE = 0
  RUNNING = 1
  FAILED = 2


class IQNetworkUI(NetworkUI):
  """Stock network panel plus a manual wifi rescan button."""

  def __init__(self, wifi_manager):
    super().__init__(wifi_manager)
    self._phase = ScanPhase.IDLE
    self.scan_button = Button(tr("Scan"), self._start_scan, button_style=ButtonStyle.TRANSPARENT_WHITE_TEXT,
                              font_size=60, border_radius=30)
    self.scan_button.set_rect(rl.Rectangle(0, 0, 400, 100))
    self._wifi_manager.add_callbacks(networks_updated=self._on_networks_updated)

  def _set_phase(self, phase: ScanPhase):
    self._phase = phase
    running = phase == ScanPhase.RUNNING
    self.scan_button.set_text(tr("Scanning...") if running else tr("Scan"))
    self.scan_button.set_enabled(not running)
    # keep the manager's spinner in step with the button, not just the quick scan call
    self._wifi_manager._scanning = running

  def _start_scan(self):
    self._set_phase(ScanPhase.RUNNING)
    threading.Thread(target=self._scan_worker, daemon=True).start()

  def _scan_worker(self):
    try:
      self._wifi_manager._update_networks()
      self._wifi_manager._request_scan()
      self._wifi_manager._last_network_update = time.monotonic()
    except Exception:
      cloudlog.exception("IQNetworkUI scan failed")
      self._phase = ScanPhase.FAILED

  def _on_networks_updated(self, networks):
    if self._phase == ScanPhase.RUNNING:
      self._set_phase(ScanPhase.IDLE)

  def _render(self, rect: rl.Rectangle):
    super()._render(rect)

    if self._phase == ScanPhase.FAILED:
      self._set_phase(ScanPhase.IDLE)

    if self._current_panel == NetworkPanelType.WIFI:
      self.scan_button.set_position(self._rect.x, self._rect.y + 20)
      r = self.scan_button.rect
      bg = TEAL if self.scan_button.enabled else _IDLE_BG
      rl.draw_rectangle_rounded(r, 30 / (min(r.width, r.height) / 2), 10, bg)
      self.scan_button.render()

# ===== iq_maps =====

MAP_PATH = Path(Paths.mapd_root()) / "offline"
OFFLINE_TILES_PATH = offline_map_root() / "regions"

_BOUNDS_BASE_URL = "https://raw.githubusercontent.com/pfeiferj/openpilot-mapd/main/"
_REGION_PARAMS = ("OsmDownloadedDate", "OsmLocal", "OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle")


def _fmt_bytes(n: int) -> str:
  return f"{n / 1024 ** 2:.2f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.2f} GB"


def _tree_size(*roots: Path) -> int:
  total = 0
  pending = [p for p in roots if p.exists()]
  while pending:
    try:
      for entry in os.scandir(pending.pop()):
        if entry.is_file():
          total += entry.stat().st_size
        elif entry.is_dir():
          pending.append(entry.path)
    except OSError:
      pass
  return total


class IQMapsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._current_percent = 0
    self._last_sync = 0
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params
    self._build_rows()
    self._refresh_disk_usage()
    self._progress.set_visible(False)
    self._tile_progress.set_visible(False)
    self._state_btn.set_visible(False)
    self._mapd_version.action_item.set_text(ui_state.params.get("MapdVersion") or "Loading...")
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _build_rows(self):
    self._mapd_version = text_item(tr("Mapd Version"), lambda: ui_state.params.get("MapdVersion") or "Loading...")
    self._online_maps_toggle = toggle_item(
      tr("Online On-Screen Maps"),
      tr("Pull live Mapbox tiles for the on-screen map whenever the device has internet."),
      param="OnlineOSMaps",
    )
    self._offline_maps_toggle = toggle_item(
      tr("Offline On-Screen Maps"),
      tr("Draw the on-screen map from tiles stored on the device. Combined with Online, stored tiles "
         "take over the moment connectivity drops. Tiles come down with your selected region."),
      param="OfflineOSMaps",
    )
    self._delete_maps_btn = IQListItem(tr("Downloaded Maps"), action_item=NoElideButtonAction(tr("DELETE"), enabled=True),
                                       callback=self._confirm_wipe)
    self._progress = progress_item(tr("Downloading Map"))
    self._tile_progress = progress_item(tr("Downloading Map Tiles"))
    self._update_btn = IQListItem(tr("Database Update"), action_item=NoElideButtonAction(tr("CHECK"), enabled=True),
                                  callback=self._confirm_db_refresh)
    self._country_btn = IQListItem(tr("Country"), action_item=NoElideButtonAction(tr("SELECT"), enabled=True),
                                   callback=lambda: self._open_region_picker("Country"))
    self._state_btn = IQListItem(tr("State"), action_item=NoElideButtonAction(tr("SELECT"), enabled=True),
                                 callback=lambda: self._open_region_picker("State"))

    self.items = [self._mapd_version, self._online_maps_toggle, self._offline_maps_toggle, self._delete_maps_btn,
                  self._progress, self._tile_progress, self._update_btn, self._country_btn, self._state_btn]

  # -- disk usage ---------------------------------------------------------------
  def _refresh_disk_usage(self):
    def worker():
      self._delete_maps_btn.action_item.set_value(_fmt_bytes(_tree_size(MAP_PATH, OFFLINE_TILES_PATH)))
    threading.Thread(target=worker, daemon=True).start()

  # -- wipe ---------------------------------------------------------------------
  def _confirm_wipe(self):
    self._ask(tr("This will delete ALL downloaded maps\n\nAre you sure you want to delete all maps?"),
              tr("Yes, delete all maps"), self._start_wipe)

  def _start_wipe(self):
    self._delete_maps_btn.action_item.set_enabled(False)
    self._delete_maps_btn.action_item.set_text(tr("DELETING..."))
    threading.Thread(target=self._wipe_worker, daemon=True).start()

  def _wipe_worker(self):
    for root in (MAP_PATH, OFFLINE_TILES_PATH):
      if root.exists():
        shutil.rmtree(root)
    for param in _REGION_PARAMS:
      ui_state.params.remove(param)
    self._delete_maps_btn.action_item.set_enabled(True)
    self._delete_maps_btn.action_item.set_text(tr("DELETE"))
    self._refresh_disk_usage()

  # -- database download ----------------------------------------------------------
  @staticmethod
  def _ask(msg, confirm_text, then):
    gui_app.set_modal_overlay(ConfirmDialog(msg, confirm_text),
                              lambda res: then() if res == DialogResult.CONFIRM else None)

  def _confirm_db_refresh(self):
    self._ask(tr("This will start the download process and it might take a while to complete."),
              tr("Start Download"), self._request_db_download)

  def _request_db_download(self):
    ui_state.params.put_bool("OsmDbUpdatesCheck", True)
    nations = [c] if (c := ui_state.params.get("OsmLocationName") or "") else []
    states = [s] if (s := ui_state.params.get("OsmStateName") or "") else []
    if "US" in nations and states:
      # a state list replaces the whole-US download; "All" is just the marker for every state
      if any(x.lower() == "all" for x in states):
        states = [x for x in states if x.lower() != "all"]
      else:
        nations.remove("US")
    self._mem_params.put("OSMDownloadLocations", {"nations": nations, "states": states})

  # -- region picker ---------------------------------------------------------------
  def _open_region_picker(self, region_type):
    btn = self._country_btn if region_type == "Country" else self._state_btn
    btn.action_item.set_enabled(False)
    btn.action_item.set_text(tr("FETCHING..."))
    threading.Thread(target=self._region_picker_worker, args=(region_type, btn), daemon=True).start()

  @staticmethod
  def _fetch_regions(region_type):
    url = _BOUNDS_BASE_URL + ("nation_bounding_boxes.json" if region_type == "Country" else "us_states_bounding_boxes.json")
    try:
      data = requests.get(url, timeout=10).json()
      return sorted((TreeNode(ref=k, data={'display_name': v['full_name']}) for k, v in data.items()),
                    key=lambda n: n.data['display_name'])
    except Exception:
      return []

  def _region_picker_worker(self, region_type, btn):
    locations = self._fetch_regions(region_type)
    if region_type == "State":
      locations.insert(0, TreeNode(ref="All", data={'display_name': tr("All states (~6.0 GB)")}))

    btn.action_item.set_enabled(True)
    btn.action_item.set_text(tr("SELECT"))

    key = "OsmLocation" if region_type == "Country" else "OsmState"
    current = ui_state.params.get(f"{key}Name") or ""
    dialog = TreeOptionDialog(tr(f"Select {region_type}"), [TreeFolder(folder="", nodes=locations)],
                              current_ref=current, search_prompt=tr("Perform a search"))
    done = lambda res: self._on_region_picked(region_type, locations, key, res, dialog.selection_ref)  # noqa: E731
    dialog.on_exit = done
    gui_app.set_modal_overlay(dialog, callback=done)

  def _on_region_picked(self, region_type, locations, key, res, ref):
    if res != DialogResult.CONFIRM or not ref:
      # cancelling the state picker right after choosing US leaves a half-configured selection — undo it
      if region_type == "State" and res == DialogResult.CANCEL:
        if ui_state.params.get("OsmLocationName") == "US" and not ui_state.params.get("OsmStateName"):
          for param in ("OsmLocationName", "OsmLocationTitle", "OsmLocal"):
            ui_state.params.remove(param)
          self._sync_rows()
      return

    if region_type == "Country":
      ui_state.params.put_bool("OsmLocal", True)
      ui_state.params.remove("OsmStateName")
      ui_state.params.remove("OsmStateTitle")

    ui_state.params.put(f"{key}Name", ref)
    title = next((n.data['display_name'] for n in locations if n.ref == ref), ref)
    ui_state.params.put(f"{key}Title", title)

    if ref == "US" and region_type == "Country":
      self._open_region_picker("State")
    else:
      self._confirm_db_refresh()

  # -- progress sync -----------------------------------------------------------------
  def _sync_tile_progress(self):
    if not self._mem_params.get("OfflineTilesDownloadRequest"):
      self._tile_progress.set_visible(False)
      return
    device._reset_interactive_timeout()
    self._refresh_disk_usage()
    self._tile_progress.set_visible(True)
    progress = self._mem_params.get("OfflineTilesDownloadProgress") or {}
    total = progress.get("total_bytes", 0)
    done = progress.get("downloaded_bytes", 0)
    if total > 0:
      pct = max(0.0, min(100.0, done / total * 100.0))
      self._tile_progress.action_item.update(pct, f"{int(pct)}% - Downloading Map Tiles", show_progress=True)
    else:
      self._tile_progress.action_item.update(0.0, tr("Preparing Map Tiles..."), show_progress=False)

  def _sync_db_progress(self, downloading: bool):
    self._progress.set_visible(True)
    progress = ui_state.params.get("OSMDownloadProgress") or {}
    total = progress.get('total_files', 0)
    done = progress.get('downloaded_files', 0)
    failed = total > 0 and not downloading and done < total

    if failed:
      self._current_percent = 0.0
      bar_text, btn_text = "0% - Downloading Maps", tr("Error: Invalid download. Retry.")
    elif total > 0 and downloading:
      self._current_percent = max(0.0, min(100.0, done / total * 100.0))
      pct = int(self._current_percent)
      bar_text, btn_text = f"{pct}% - Downloading Maps", f"{done}/{total} ({pct}%)"
    else:
      self._current_percent = 0.0
      bar_text, btn_text = "0% - Downloading Maps", tr("Downloading Maps...")

    self._progress.action_item.update(self._current_percent, bar_text,
                                      show_progress=total > 0 and downloading and not failed)
    self._update_btn.action_item.set_value(btn_text)

  def _set_rows_busy(self, busy: bool):
    for row in (self._update_btn, self._country_btn, self._state_btn, self._delete_maps_btn):
      row.action_item.set_enabled(not busy)

  def _sync_rows(self):
    downloading = bool(self._mem_params.get("OSMDownloadLocations"))
    self._sync_tile_progress()
    self._country_btn.set_enabled(not downloading)
    self._state_btn.set_enabled(not downloading)
    self._state_btn.set_visible(ui_state.params.get("OsmLocationName") == "US")
    self._update_btn.set_visible(bool(ui_state.params.get("OsmLocationName")))
    self._country_btn.action_item.set_value(ui_state.params.get("OsmLocationTitle") or "")
    self._state_btn.action_item.set_value(ui_state.params.get("OsmStateTitle") or "")

    if downloading or ui_state.params.get_bool("OsmDbUpdatesCheck"):
      if downloading:
        device._reset_interactive_timeout()
        self._refresh_disk_usage()
      self._sync_db_progress(downloading)
      self._set_rows_busy(downloading)  # TODO-IQ: introduce CANCEL database download with mapd
      return

    self._progress.set_visible(False)
    self._set_rows_busy(False)

    dt = None
    if ts := ui_state.params.get("OsmDownloadedDate"):
      try:
        if float(ts) > 0:
          dt = datetime.datetime.fromtimestamp(float(ts), tz=datetime.UTC)
      except (ValueError, TypeError):
        dt = None
    self._update_btn.action_item.set_value(tr("Last checked {}").format(time_ago(dt)))

  def _update_state(self):
    now = monotonic()
    if now - self._last_sync >= 1.0:
      self._last_sync = now
      self._sync_rows()

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()

# ===== lane_change_settings =====

_TIMER_LABELS = {
  -1: lambda: tr("Off"),
  0: lambda: tr("Nudge"),
  1: lambda: tr("Nudgeless"),
  2: lambda: f"0.5 {tr('s')}",
  3: lambda: f"1 {tr('s')}",
  4: lambda: f"2 {tr('s')}",
  5: lambda: f"3 {tr('s')}",
}


class LaneChangeSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    self._scroller = Scroller(self._build_rows(), line_separator=False, spacing=0)

  def _build_rows(self):
    self._lane_change_timer = option_item(
      title=lambda: tr("Auto Lane Change by Blinker"),
      param="AutoLaneChangeTimer",
      description=lambda: tr("Delay before a blinker-triggered lane change starts on its own — no wheel nudge "
                             "needed once a delay is set (default is Nudge).<br>Use the blinker for this only "
                             "when traffic and the road actually allow the maneuver."),
      min_value=-1, max_value=5, value_change_step=1,
      label_callback=lambda x: _TIMER_LABELS[int(x)](),
    )
    self._bsm_delay = toggle_item(
      param="AutoLaneChangeBsmDelay",
      title=lambda: tr("Auto Lane Change: Delay with Blind Spot"),
      description=lambda: tr("Hold the automatic lane change while blind spot monitoring reports a car in the "
                             "target lane, releasing it once the lane is clear."),
    )
    self._continuous = toggle_item(
      param="LaneChangeContinuous",
      title=lambda: tr("Auto Lane Change: Continuous Changes"),
      description=lambda: tr("Normally one maneuver ends the lane change even with the blinker held. Turn this on "
                             "to chain further changes while the blinker stays on — each follow-up still wants a "
                             "wheel nudge."),
    )
    return [
      self._lane_change_timer,
      IQLineSeparator(40),
      self._bsm_delay,
      IQLineSeparator(40),
      self._continuous,
    ]

  def _update_state(self):
    super()._update_state()
    has_bsm = bool(ui_state.CP and ui_state.CP.enableBsm)
    if not has_bsm and ui_state.params.get_bool("AutoLaneChangeBsmDelay"):
      ui_state.params.remove("AutoLaneChangeBsmDelay")
    timer_armed = ui_state.params.get("AutoLaneChangeTimer", return_default=True) > AutoLaneChangeMode.NUDGE
    self._bsm_delay.action_item.set_enabled(has_bsm and timer_armed)

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    below_button = self._back_button.rect.height + 40
    self._scroller.render(rl.Rectangle(rect.x, rect.y + below_button, rect.width, rect.height - below_button))

  def show_event(self):
    self._scroller.show_event()

# ===== sab_settings =====

# (segment label, explanation) — order matches the AolSteeringMode param values
SAB_BRAKE_RESPONSE_OPTIONS = [
  (tr("Remain Active"), tr_noop("Remain Active: braking never interrupts steering assistance.")),
  (tr("Standby"), tr_noop("Standby: braking parks steering assistance; it rejoins once you're off the pedal.")),
  (tr("Disengage"), tr_noop("Disengage: braking shuts steering assistance off entirely.")),
]

_MODE_DISENGAGE = 2
_MODE_STANDBY = 1

SAB_AVAILABILITY_DESC = tr("Note: on cars lacking an LFA/LKAS button, turning this off keeps steering assistance "
                           "from arming as cruise availability flips.")
SAB_DRIVER_INTERVENTION_DESC = tr("Pick what a brake-pedal press does to steering assistance.")
DEFAULT_TO_OFF = tr("Locked OFF on this platform; the vehicle can't support other choices.")
STATUS_DISENGAGE_ONLY = tr("This platform is limited to Disengage mode.")


class SabSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    self._scroller = Scroller(self._build_rows(), line_separator=True, spacing=0)

  def _build_rows(self):
    self._main_cruise_toggle = toggle_item(
      title=lambda: tr("Availability While Cruise Changes"),
      description=SAB_AVAILABILITY_DESC,
      param="AolMainCruiseAllowed",
    )
    self._disengage_on_brake_toggle = toggle_item(
      title=lambda: tr("Driver Intervention Handling"),
      description=SAB_DRIVER_INTERVENTION_DESC,
      initial_state=False,
      callback=self._on_brake_shortcut_toggled,
    )
    self._steering_mode = multiple_button_item(
      param="AolSteeringMode",
      title=lambda: tr("Brake Response Mode"),
      description="",
      buttons=[label for label, _ in SAB_BRAKE_RESPONSE_OPTIONS],
      inline=False,
      button_width=350,
      callback=self._refresh_mode_description,
    )
    return [self._main_cruise_toggle, self._disengage_on_brake_toggle, self._steering_mode]

  # -- platform capability ----------------------------------------------------
  @staticmethod
  def _has_limited_sab_options() -> bool:
    brand = ""
    if ui_state.is_offroad():
      if bundle := ui_state.params.get("CarPlatformBundle"):
        brand = bundle.get("brand", "")
    if not brand and ui_state.CP:
      brand = ui_state.CP.brand
    return brand == "rivian"

  # -- interactions -------------------------------------------------------------
  def _on_brake_shortcut_toggled(self, enabled: bool):
    """The 'Driver Intervention' toggle is a shortcut between Disengage and Standby."""
    current = int(ui_state.params.get("AolSteeringMode", return_default=True))
    if enabled:
      target = _MODE_DISENGAGE
    elif current == _MODE_DISENGAGE:
      target = _MODE_STANDBY
    else:
      return
    ui_state.params.put("AolSteeringMode", target)
    self._steering_mode.action_item.set_selected_button(target)

  def _refresh_mode_description(self, selected: int):
    lines = [tr("Pick how steering assistance reacts once the driver brakes in IQ.Pilot."), ""]
    for i, (_, blurb) in enumerate(SAB_BRAKE_RESPONSE_OPTIONS):
      text = tr(blurb)
      lines.append(f"<b>{text}</b>" if i == selected else text)
    self._steering_mode.set_description("<br>".join(lines))
    self._steering_mode.show_description(True)

  # -- state sync ---------------------------------------------------------------
  def _apply_limited_platform(self):
    ui_state.params.remove("AolMainCruiseAllowed")
    ui_state.params.put_bool("AolUnifiedEngagementMode", True)
    ui_state.params.put("AolSteeringMode", _MODE_DISENGAGE)

    self._main_cruise_toggle.action_item.set_enabled(False)
    self._main_cruise_toggle.action_item.set_state(False)
    self._main_cruise_toggle.set_description(f"<b>{DEFAULT_TO_OFF}</b><br>{SAB_AVAILABILITY_DESC}")

    self._disengage_on_brake_toggle.action_item.set_enabled(False)
    self._disengage_on_brake_toggle.action_item.set_state(True)
    self._disengage_on_brake_toggle.set_description(STATUS_DISENGAGE_ONLY)

    self._steering_mode.action_item.set_enabled(False)
    self._steering_mode.set_description(STATUS_DISENGAGE_ONLY)
    self._steering_mode.action_item.set_selected_button(_MODE_DISENGAGE)

  def _apply_full_platform(self):
    self._main_cruise_toggle.action_item.set_enabled(True)
    self._main_cruise_toggle.set_description(SAB_AVAILABILITY_DESC)
    self._disengage_on_brake_toggle.action_item.set_enabled(True)
    self._disengage_on_brake_toggle.set_description(SAB_DRIVER_INTERVENTION_DESC)
    self._steering_mode.action_item.set_enabled(True)

  def _update_state(self):
    super()._update_state()
    if ui_state.params.get_bool("AolEnabled"):
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)

    current = int(ui_state.params.get("AolSteeringMode", return_default=True))
    self._disengage_on_brake_toggle.action_item.set_state(current == _MODE_DISENGAGE)
    self._refresh_mode_description(self._steering_mode.action_item.get_selected_button())

    if self._has_limited_sab_options():
      self._apply_limited_platform()
    else:
      self._apply_full_platform()

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    below_button = self._back_button.rect.height + 40
    self._scroller.render(rl.Rectangle(rect.x, rect.y + below_button, rect.width, rect.height - below_button))

  def show_event(self):
    self._scroller.show_event()

# ===== steering =====

class PanelType(IntEnum):
  STEERING = 0
  SAB = 1
  LANE_CHANGE = 2


class SteeringLayout(Widget):
  def __init__(self):
    super().__init__()

    self._current_panel = PanelType.STEERING
    self._lane_change_settings_layout = LaneChangeSettingsLayout(lambda: self._set_current_panel(PanelType.STEERING))
    self._sab_settings_layout = SabSettingsLayout(lambda: self._set_current_panel(PanelType.STEERING))

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

    for ctrl, key in [(self._lane_turn_value_control, "IQLaneTurnValue"), (self._delay_control, "LagdToggleDelay")]:
      ctrl.action_item.set_value(int(float(ui_state.params.get(key, return_default=True)) * 100))

  def _initialize_items(self):
    self._aol_base_desc = tr("Enable Always on Lateral (AOL). Disable this toggle to return to stock IQ.Pilot steering engagement behavior.")
    self._sab_limited_desc = tr("This platform supports a limited set of steering assistance behavior options.")
    self._sab_full_desc = tr("This platform supports the full steering assistance behavior configuration.")
    self._sab_check_compat_desc = tr("Start the vehicle to check steering assistance behavior compatibility.")

    self._aol_toggle = toggle_item(
      param="AolEnabled",
      title=lambda: tr("Always on Lateral (AOL)"),
      description=self._aol_base_desc,
    )
    self._aol_settings_button = simple_button_item(
      button_text=lambda: tr("Steering Assistance Behavior"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.SAB)
    )
    self._lane_change_settings_button = simple_button_item(
      button_text=lambda: tr("Customize Lane Change"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.LANE_CHANGE)
    )
    self._nnff_toggle = toggle_item(
      param="NeuralNetworkFeedForward",
      title=lambda: tr("Neural Network Feed Forward (NNFF)"),
      description=""
    )
    self._lane_turn_desire_toggle = toggle_item(
      tr("Use Lane Turn Desires"),
      tr("If you're driving at 20 mph (32 km/h) or below and have your blinker on,"
         " the car will plan a turn in that direction at the nearest drivable path."
         " This prevents situations (like at red lights) where the car might plan the wrong turn direction."),
      param="IQLaneTurnDesire"
    )
    self._lane_turn_value_control = option_item(
      tr("Adjust Lane Turn Desire Speed"), "IQLaneTurnValue", 500, 2000,
      tr("Sets the speed threshold used by Lane Turn Desires. Below this value, turn desires can plan into the nearest drivable turn path. Default is 19 mph."),
      int(round(100 / CV.MPH_TO_KPH)), None, True, "", style.BUTTON_ACTION_WIDTH, None, True,
      lambda v: f"{int(round(v * (CV.MPH_TO_KPH if ui_state.is_metric else 1)))}"
                f" {'km/h' if ui_state.is_metric else 'mph'}"
    )
    self._lagd_toggle = toggle_item(tr("Live Learning Steer Delay"), "", param="LagdToggle")
    self._delay_control = option_item(
      tr("Adjust Software Delay"), "LagdToggleDelay", 5, 50,
      tr("Adjust the fixed software delay added to steer actuator delay when Live Learning Steer Delay is turned off. The default software delay value is 0.2 s."),
      1, None, True, "", style.BUTTON_ACTION_WIDTH, None, True, lambda v: f"{float(v):.2f}s"
    )

    items = [
      self._aol_toggle,
      self._nnff_toggle,
      IQLineSeparator(40),
      self._aol_settings_button,
      IQLineSeparator(40),
      self._lane_change_settings_button,
      IQLineSeparator(40),
      self._lane_turn_desire_toggle,
      self._lane_turn_value_control,
      IQLineSeparator(40),
      self._lagd_toggle,
      self._delay_control,
    ]
    return items

  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel

  def _update_state(self):
    super()._update_state()

    steering_supported = True
    if ui_state.CP is not None:
      sab_desc = self._sab_limited_desc if self._sab_settings_layout._has_limited_sab_options() else self._sab_full_desc
      self._aol_toggle.set_description(f"<b>{sab_desc}</b><br><br>{self._aol_base_desc}")

      if ui_state.CP.steerControlType == car.CarParams.SteerControlType.angle:
        ui_state.params.remove("NeuralNetworkFeedForward")
        steering_supported = False
    else:
      self._aol_toggle.set_description(f"<b>{self._sab_check_compat_desc}</b><br><br>{self._aol_base_desc}")
      ui_state.params.remove("NeuralNetworkFeedForward")
      steering_supported = False

    self._aol_toggle.action_item.set_enabled(ui_state.is_offroad())
    self._aol_settings_button.action_item.set_enabled(ui_state.is_offroad() and self._aol_toggle.action_item.get_state())
    self._nnff_toggle.action_item.set_enabled(ui_state.is_offroad() and steering_supported)

    turn_desire = ui_state.params.get_bool("IQLaneTurnDesire")
    live_delay = ui_state.params.get_bool("LagdToggle")
    self._lane_turn_desire_toggle.action_item.set_state(turn_desire)
    self._lane_turn_value_control.set_visible(turn_desire)
    self._lagd_toggle.action_item.set_state(live_delay)
    self._delay_control.set_visible(not live_delay)
    new_step = int(round(100 / CV.MPH_TO_KPH)) if ui_state.is_metric else 100
    if self._lane_turn_value_control.action_item.value_change_step != new_step:
      self._lane_turn_value_control.action_item.value_change_step = new_step
    lagd_desc = tr("Enable this for the car to learn and adapt its steering response time. Disable to use a fixed steering response time.")
    if live_delay:
      lagd_desc += f"<br>{tr('Live Steer Delay:')} {ui_state.sm['liveDelay'].lateralDelay:.3f} s"
    elif ui_state.CP:
      sw = float(ui_state.params.get("LagdToggleDelay", "0.2"))
      cp = ui_state.CP.steerActuatorDelay
      lagd_desc += f"<br>{tr('Actuator Delay:')} {cp:.2f} s + {tr('Software Delay:')} {sw:.2f} s = {tr('Total Delay:')} {cp + sw:.2f} s"
    self._lagd_toggle.set_description(lagd_desc)

  def _render(self, rect):
    if self._current_panel == PanelType.LANE_CHANGE:
      self._lane_change_settings_layout.render(rect)
    elif self._current_panel == PanelType.SAB:
      self._sab_settings_layout.render(rect)
    else:
      self._scroller.render(rect)

  def show_event(self):
    self._set_current_panel(PanelType.STEERING)
    self._scroller.show_event()


# ===== cruise =====

class CruiseLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._scroller = Scroller(self._initialize_items(), line_separator=True, spacing=0)

  @staticmethod
  def _toggle_item(title: str, description: str, param: str):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=IQToggleAction(initial_state=Params().get_bool(param), callback=lambda state: Params().put_bool(param, state), param=param),
    )

  @staticmethod
  def _mode_item(title: str, description: str, param: str, labels: list[str], width: int, inline: bool = False):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=IQMultipleButtonAction(buttons=[lambda s=s: tr(s) for s in labels], button_width=width, param=param),
      inline=inline,
    )

  @staticmethod
  def _option_item(title: str, description: str, param: str, minimum: int, maximum: int, step: int = 1,
                   label_callback=None, use_float_scaling: bool = False):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=OptionControl(
        param=param,
        min_value=minimum,
        max_value=maximum,
        value_change_step=step,
        use_float_scaling=use_float_scaling,
        label_callback=label_callback,
      ),
    )

  def _initialize_items(self):
    ms_to_mph = 2.23694

    def speed_label(value: float | int) -> str:
      return f"{int(round(value * ms_to_mph))} mph"

    def seconds_label(value: float | int) -> str:
      return f"{float(value):.1f}s"

    def distance_label(value: float | int) -> str:
      value = int(value)
      return "Stock" if value == 0 else f"{value:+d} m"

    items = [
      IQListItem(title=lambda: tr("Speed Limit Control"), description="", action_item=None, inline=True,
                 title_color=rl.Color(16, 185, 169, 255)),
      IQLineSeparator(20),
      self._mode_item(
        "IQ Speed Limit Mode",
        "Choose how IQ.Pilot handles speed limit data. Control adjusts cruise speed. Warning only highlights overspeed.",
        "IQSpeedAssistMode",
        ["Off", "Info", "Warn", "Control"],
        180,
      ),
      self._mode_item(
        "IQ SLC Policy",
        "Select how IQ.Pilot resolves conflicting speed limit sources.",
        "SLCPolicy",
        ["Map", "Priority", "Combined"],
        180,
      ),
      self._toggle_item(
        "IQ SLC Confirm Higher",
        "Require confirmation before IQ.Pilot accepts a higher detected speed limit.",
        "SpeedLimitConfirmationHigher",
      ),
      self._toggle_item(
        "IQ SLC Confirm Lower",
        "Require confirmation before IQ.Pilot accepts a lower detected speed limit.",
        "SpeedLimitConfirmationLower",
      ),
      self._toggle_item(
        "IQ SLC Auto Confirm",
        "Automatically accept speed limit changes after a 5-second timeout without requiring a cruise button press.",
        "SLCAutoConfirm",
      ),
      self._toggle_item(
        "IQ SLC Fallback Set Speed",
        "If no speed limit is available, use the current set speed as the controller target.",
        "SLCFallbackSetSpeed",
      ),
      self._toggle_item(
        "IQ SLC Fallback Previous",
        "If a new limit is denied, reuse the previous accepted speed limit when possible.",
        "SLCFallbackPreviousSpeedLimit",
      ),
      self._toggle_item(
        "IQ SLC Fallback Experimental",
        "When no speed limit is available, let IQ.Dynamic request experimental longitudinal behavior.",
        "SLCFallbackExperimentalMode",
      ),
      self._toggle_item(
        "IQ SLC Online Filler",
        "Use online sources (TomTom + Mapbox) to fill in missing speed limits when local map data is unavailable.",
        "SLCOnlineFiller",
      ),
      self._option_item(
        "IQ Map Lookahead Higher",
        "How far ahead IQ.Pilot should apply an upcoming higher map speed limit before the limit changes.",
        "MapSpeedLookaheadHigher",
        100,
        1000,
        step=50,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      self._option_item(
        "IQ Map Lookahead Lower",
        "How far ahead IQ.Pilot should apply an upcoming lower map speed limit before the limit changes.",
        "MapSpeedLookaheadLower",
        100,
        1000,
        step=50,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      IQLineSeparator(60),
      IQListItem(title=lambda: tr("IQ.Dynamic"), description="", action_item=None, inline=True,
                 title_color=rl.Color(16, 185, 169, 255)),
      IQLineSeparator(20),
      self._toggle_item(
        "IQ.Dynamic Curves",
        "Allow IQ.Dynamic to enter blended control for curves and strong vision slowdown cues.",
        "IQDynamicConditionalCurves",
      ),
      self._toggle_item(
        "IQ.Dynamic Slower Lead",
        "Allow IQ.Dynamic to switch toward blended control when a slower lead vehicle is detected.",
        "IQDynamicConditionalSlowerLead",
      ),
      self._toggle_item(
        "IQ.Dynamic Stopped Lead",
        "Allow IQ.Dynamic to react more aggressively when a lead vehicle is nearly stopped.",
        "IQDynamicConditionalStoppedLead",
      ),
      self._toggle_item(
        "IQ.Dynamic Model Stops",
        "Allow IQ.Dynamic to switch toward blended control for stop-sign and stop-light style vision stops.",
        "IQDynamicConditionalModelStops",
      ),
      self._toggle_item(
        "IQ.Dynamic SLC Fallback",
        "Allow IQ.Dynamic to request blended control when Speed Limit Controller has no usable target.",
        "IQDynamicConditionalSLCFallback",
      ),
      self._option_item(
        "IQ.Dynamic Low Speed",
        "Below this speed, IQ.Dynamic prefers blended control when no lead is present.",
        "IQDynamicConditionalSpeed",
        500,
        3500,
        step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      self._option_item(
        "IQ.Dynamic Lead Speed",
        "Below this speed, IQ.Dynamic prefers blended control even with a tracked lead.",
        "IQDynamicConditionalLeadSpeed",
        500,
        4000,
        step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      self._option_item(
        "IQ.Dynamic Model Stop Time",
        "Sets the vision stop prediction time horizon used by IQ.Dynamic and IQ Force Stops. Shorter values react later. Longer values react earlier.",
        "IQDynamicModelStopTime",
        100,
        600,
        step=25,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      self._toggle_item(
        "IQ Force Stops",
        "Bring the car to a complete stop for stop signs and stop lights, and feather the brake in the final meters of "
        "every stop so it settles gently instead of rocking on its suspension. Yields full braking authority when a lead "
        "is close. Override with the accelerator.",
        "IQForceStops",
      ),
      self._option_item(
        "IQ Custom Stop Distance",
        "Nudge how far back IQ.Pilot stops behind a stopped lead vehicle or a model-held stop (red light). Positive "
        "stops further back, negative settles in closer. Works whether IQ Force Stops is on or off.",
        "IQCustomStopDistance",
        -2,
        2,
        step=1,
        label_callback=distance_label,
      ),
    ]
    return items

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()


# ===== developer =====

class IQDeveloperLayout(DeveloperLayout):
  def __init__(self):
    super().__init__()
    self.error_log_path = os.path.join(Paths.crash_log_root(), "error.log")
    self._is_release_branch: bool = self._is_release or ui_state.params.get_bool("IsReleaseIqBranch")
    self._is_development_branch: bool = ui_state.params.get_bool("IsTestedBranch") or ui_state.params.get_bool("IsDevelopmentBranch")
    self._initialize_items()

    for item in self.items:
      self._scroller.add_widget(item)

  def _initialize_items(self):
    self.error_log_btn = button_item(tr("Error Log"), tr("VIEW"), tr("View the error log for IQ.Pilot crashes."), callback=self._on_error_log_clicked)

    self.items: list = [self.error_log_btn]

  def _on_delete_confirm(self, result):
    if result == DialogResult.CONFIRM:
      if os.path.exists(self.error_log_path):
        os.remove(self.error_log_path)

  def _on_error_log_closed(self, result, log_exists):
    if result == DialogResult.CONFIRM and log_exists:
      dialog2 = ConfirmDialog(tr("Would you like to delete this log?"), tr("Yes"), tr("No"), rich=False)
      gui_app.set_modal_overlay(dialog2, callback=self._on_delete_confirm)

  def _on_error_log_clicked(self):
    text = ""
    if os.path.exists(self.error_log_path):
      text = f"<b>{datetime.datetime.fromtimestamp(os.path.getmtime(self.error_log_path)).strftime('%d-%b-%Y %H:%M:%S').upper()}</b><br><br>"
      try:
        with open(self.error_log_path) as file:
          text += file.read()
      except Exception:
        pass
    dialog = NoticeModal(text=text, callback=lambda result: self._on_error_log_closed(result, os.path.exists(self.error_log_path)))
    gui_app.set_modal_overlay(dialog)

  def _update_state(self):
    self.error_log_btn.set_visible(not self._is_release_branch)


# ===== software =====

UPDATES_DESCRIPTIONS = {
  'disable_updates_offroad': tr_noop(
    "When enabled, automatic software updates will be off.<br><b>This requires a reboot to take effect.</b>"
  ),
  'disable_updates_onroad': tr_noop(
    "Please enable \"Always Offroad\" mode or turn off the vehicle to adjust these toggles."
  ),
  'install_mode_offroad': tr_noop(
    "Choose whether updates only download and wait for confirmation, or download and install automatically after they are ready."
  ),
  'install_mode_onroad': tr_noop(
    "Please enable \"Always Offroad\" mode or turn off the vehicle to adjust update install behavior."
  )
}

INSTALL_MODE_DOWNLOAD_ONLY = "download_only"
INSTALL_MODE_DOWNLOAD_AND_INSTALL = "download_and_install"
INSTALL_MODE_OPTIONS = [
  INSTALL_MODE_DOWNLOAD_ONLY,
  INSTALL_MODE_DOWNLOAD_AND_INSTALL,
]
INSTALL_MODE_LABELS = {
  INSTALL_MODE_DOWNLOAD_ONLY: tr_noop("Predownload Only"),
  INSTALL_MODE_DOWNLOAD_AND_INSTALL: tr_noop("Predownload + Preinstall"),
}


class IQSoftwareLayout(SoftwareLayout):
  def __init__(self):
    super().__init__()
    self.disable_updates_toggle = toggle_item(
      lambda: tr("Disable Updates"),
      description="",
      initial_state=ui_state.params.get_bool("DisableUpdates"),
      callback=self._on_disable_updates_toggled,
    )
    install_mode = ui_state.params.get("UpdaterInstallMode") or INSTALL_MODE_DOWNLOAD_AND_INSTALL
    if install_mode not in INSTALL_MODE_OPTIONS:
      install_mode = INSTALL_MODE_DOWNLOAD_AND_INSTALL
    self._install_mode_dialog = None
    self.install_mode_btn = button_item(
      lambda: tr("Update Install Mode"),
      lambda: tr("CHANGE"),
      description="",
      callback=self._on_change_install_mode,
    )
    self.install_mode_btn.action_item.set_value(tr(INSTALL_MODE_LABELS[install_mode]))
    try:
      os_version = HARDWARE.get_os_version() or "unknown"
    except Exception:
      os_version = "unknown"
    self.iqos_version_item = text_item(lambda: tr("IQ.OS Version"), os_version)
    self._scroller.add_widget(self.iqos_version_item)
    self._scroller.add_widget(self.disable_updates_toggle)
    self._scroller.add_widget(self.install_mode_btn)

  def _handle_reboot(self, result):
    if result == DialogResult.CONFIRM:
      ui_state.params.put_bool("DisableUpdates", self.disable_updates_toggle.action_item.get_state())
      ui_state.params.put_bool("DoReboot", True)
    else:
      self.disable_updates_toggle.action_item.set_state(ui_state.params.get_bool("DisableUpdates"))

  def _on_disable_updates_toggled(self, enabled):
    dialog = ConfirmDialog(tr("System reboot required for changes to take effect. Reboot now?"), tr("Reboot"))
    gui_app.set_modal_overlay(dialog, callback=self._handle_reboot)

  def _on_change_install_mode(self):
    current_mode = ui_state.params.get("UpdaterInstallMode") or INSTALL_MODE_DOWNLOAD_AND_INSTALL
    if current_mode not in INSTALL_MODE_OPTIONS:
      current_mode = INSTALL_MODE_DOWNLOAD_AND_INSTALL

    labels = [tr(INSTALL_MODE_LABELS[mode]) for mode in INSTALL_MODE_OPTIONS]
    current_label = tr(INSTALL_MODE_LABELS[current_mode])
    self._install_mode_dialog = MultiOptionDialog(tr("Update Install Mode"), labels, current_label)

    def handle_selection(result):
      if result == DialogResult.CONFIRM and self._install_mode_dialog is not None and self._install_mode_dialog.selection:
        selected_label = self._install_mode_dialog.selection
        for mode in INSTALL_MODE_OPTIONS:
          if selected_label == tr(INSTALL_MODE_LABELS[mode]):
            ui_state.params.put("UpdaterInstallMode", mode)
            self.install_mode_btn.action_item.set_value(selected_label)
            break
      self._install_mode_dialog = None

    gui_app.set_modal_overlay(self._install_mode_dialog, callback=handle_selection)

  def _on_uninstall(self):
    def handle_uninstall_confirmation(result):
      if result == DialogResult.CONFIRM:
        ui_state.params.put_bool("DoUninstall", True)
        gui_app.request_close()

    dialog = ConfirmDialog(tr("Are you sure you want to uninstall?"), tr("Uninstall"))
    gui_app.set_modal_overlay(dialog, callback=handle_uninstall_confirmation)

  def _on_select_branch(self):
    current_git_branch = ui_state.params.get("GitBranch") or ""
    branches_str = ui_state.params.get("UpdaterAvailableBranches") or ""
    branches = [b for b in branches_str.split(",") if b]
    current_target = ui_state.params.get("UpdaterTargetBranch") or ""
    top_level_branches = [current_git_branch, "release-mici", "release-tizi", "staging", "dev", "master"]

    if HARDWARE.get_device_type() == "tici":
      top_level_branches = ["release-new", "release-tici", "staging-tici"]
      branches = [b for b in branches if b in ("release-new", "beta") or b.endswith("-tici")]

    # single flat list: pinned branches first, then the rest alphabetically.
    # prebuilt ("-prebuilt") branches are internal build outputs, not user-selectable.
    pinned_nodes = [TreeNode(b, {'display_name': b}) for b in top_level_branches if b in branches]
    other_nodes = [TreeNode(b, {'display_name': b}) for b in sorted(branches)
                   if b not in top_level_branches and not b.endswith("-prebuilt")]

    folders = [TreeFolder("", pinned_nodes + other_nodes)]

    def _on_branch_selected(result):
      if result == DialogResult.CONFIRM and self._branch_dialog is not None:
        selection = self._branch_dialog.selection_ref
        if selection:
          ui_state.params.put("UpdaterTargetBranch", selection)
          self._branch_btn.action_item.set_value(selection)
          os.system("pkill -SIGUSR1 -f system.updated.updated")
      self._branch_dialog = None

    self._branch_dialog = TreeOptionDialog(tr("Select a branch"), folders, current_target, "",
                                           on_exit=_on_branch_selected)

    gui_app.set_modal_overlay(self._branch_dialog, callback=_on_branch_selected)

  def _update_state(self):
    super()._update_state()
    self.disable_updates_toggle.action_item.set_enabled(ui_state.is_offroad())
    self.disable_updates_toggle.set_visible(True)
    self.install_mode_btn.action_item.set_enabled(ui_state.is_offroad())
    self.install_mode_btn.set_visible(True)

    disable_updates_desc = tr(UPDATES_DESCRIPTIONS["disable_updates_offroad"] if ui_state.is_offroad() else UPDATES_DESCRIPTIONS["disable_updates_onroad"])
    self.disable_updates_toggle.set_description(disable_updates_desc)
    install_mode_desc = tr(UPDATES_DESCRIPTIONS["install_mode_offroad"] if ui_state.is_offroad() else UPDATES_DESCRIPTIONS["install_mode_onroad"])
    self.install_mode_btn.set_description(install_mode_desc)

    install_mode = ui_state.params.get("UpdaterInstallMode") or INSTALL_MODE_DOWNLOAD_AND_INSTALL
    if install_mode not in INSTALL_MODE_OPTIONS:
      install_mode = INSTALL_MODE_DOWNLOAD_AND_INSTALL
    self.install_mode_btn.action_item.set_value(tr(INSTALL_MODE_LABELS[install_mode]))

    # While we've asked the updater to check but it hasn't responded yet, show an inline spinner
    # instead of a stale value with a dead greyed-out button.
    waiting = getattr(self, "_waiting_for_updater", False)
    self._download_btn.action_item.set_loading(waiting)
    if waiting:
      self._download_btn.action_item.set_enabled(False)


# ===== device =====

# minutes the device may sit offroad before auto-shutdown, indexed by slider step
_OFFROAD_SHUTDOWN_MINUTES = (0, 5, 10, 15, 30, 60, 120, 180, 300, 600, 1440, 1800)
offroad_time_options = dict(enumerate(_OFFROAD_SHUTDOWN_MINUTES))

FORCE_ONROAD_DURATION_SEC = 10 * 60
FORCE_ONROAD_PARAM = "ForceOnroadUntil"


class IQDeviceLayout(DeviceLayout):
  MENU_ROOT = 0
  MENU_SYSTEM = 1
  MENU_MAINTENANCE = 2

  def __init__(self):
    DeviceLayout.__init__(self)
    self._scroller._line_separator = None
    self._submenu = self.MENU_ROOT

  def _initialize_items(self):
    DeviceLayout._initialize_items(self)

    # Using dual button with no right button for better alignment
    self._always_offroad_btn = self._left_button(lambda: tr("Enable Always Offroad"), self._handle_always_offroad)
    self._force_onroad_btn = self._left_button(lambda: tr("Force On-Road (10 min)"), self._handle_force_onroad)

    self._max_time_offroad = option_item(
      title=lambda: tr("Max Time Offroad"),
      description=lambda: tr("Device will automatically shutdown after set time once the engine is turned off.\n(30h is the default)"),
      param="MaxTimeOffroad",
      min_value=0,
      max_value=11,
      value_change_step=1,
      on_value_changed=None,
      enabled=True,
      icon="",
      value_map=offroad_time_options,
      label_width=360,
      use_float_scaling=False,
      inline=True,
      label_callback=self._update_max_time_offroad_label
    )

    self._device_wake_mode = multiple_button_item(
      title=lambda: tr("Wake Up Behavior"),
      description=self.wake_mode_description,
      param="DeviceBootMode",
      buttons=[lambda: tr("Default"), lambda: tr("Offroad")],
      button_width=364,
      callback=None,
      inline=True,
    )
    self._change_language_btn = button_item(lambda: tr("Change Language"), lambda: tr("CHANGE"), callback=self._show_language_dialog)

    # Quiet Mode moved to the settings-hub top bar (bell bubble); this is just the dcam preview now.
    self._driver_camera_btn = button_item(lambda: tr("Driver Camera Preview"), lambda: tr("PREVIEW"),
                                          callback=self._show_driver_camera)

    self._reg_and_training = dual_button_item(
      left_text=lambda: tr("Regulatory"),
      left_callback=self._on_regulatory,
      right_text=lambda: tr("Training Guide"),
      right_callback=self._on_review_training_guide
    )
    self._reg_and_training.action_item.right_button.set_button_style(ButtonStyle.NORMAL)

    self._onroad_uploads_and_reset_settings = dual_button_item(
      left_text=lambda: tr("Onroad Uploads"),
      left_callback=lambda: ui_state.params.put_bool("OnroadUploads", not ui_state.params.get_bool("OnroadUploads")),
      right_text=lambda: tr("Reset Settings"),
      right_callback=self._reset_settings
    )

    self._power_buttons = dual_button_item(
      left_text=lambda: tr("Reboot"),
      right_text=lambda: tr("Power Off"),
      left_callback=self._reboot_prompt,
      right_callback=self._power_off_prompt
    )

    self._submenu_system_btn = self._section_button(lambda: tr("System"), "icons/iq/sec_system.png", self.MENU_SYSTEM)
    self._submenu_maintenance_btn = self._section_button(lambda: tr("Maintenance"), "icons/iq/sec_maintenance.png", self.MENU_MAINTENANCE)
    self._submenu_back_btn = self._left_button(lambda: tr("Back"), self._go_back)

    self._submenu_top_separator = LineSeparator(height=10)
    self._submenu_gap = Spacer(10)
    self._submenu_bottom_separator = LineSeparator(height=10)
    self._system_sep_a = LineSeparator()
    self._system_sep_b = LineSeparator()
    self._system_sep_c = LineSeparator()
    self._system_sep_d = LineSeparator()

    items = [
      text_item(lambda: tr("Dongle ID"), self._params.get("DongleId") or (lambda: tr("N/A"))),
      LineSeparator(),
      text_item(lambda: tr("Serial"), self._params.get("HardwareSerial") or (lambda: tr("N/A"))),
      self._system_sep_a,
      self._reset_calib_btn,
      self._system_sep_b,
      self._change_language_btn,
      self._system_sep_c,
      self._device_wake_mode,
      self._system_sep_d,
      self._max_time_offroad,
      self._submenu_top_separator,
      self._submenu_system_btn,
      self._submenu_maintenance_btn,
      self._submenu_back_btn,
      self._driver_camera_btn,
      self._reg_and_training,
      self._onroad_uploads_and_reset_settings,
      self._submenu_gap,
      self._submenu_bottom_separator,
      self._power_buttons,
    ]

    return items

  def _left_button(self, text, callback):
    item = dual_button_item(left_text=text, left_callback=callback, right_text="", right_callback=None)
    item.action_item.right_button.set_visible(False)
    return item

  def _section_button(self, text, icon, submenu):
    item = self._left_button(text, lambda: self._set_submenu(submenu))
    item.action_item.left_button = NavSectionButton(text, icon, lambda: self._set_submenu(submenu))
    return item

  def _set_submenu(self, submenu: int):
    self._submenu = submenu
    # Reset scroll so switching menus doesn't keep a now-invalid offset (which jumps the view).
    self._scroller.scroll_panel.set_offset(0)

  def _go_back(self):
    self._set_submenu(self.MENU_ROOT)

  def _offroad_transition(self):
    self._power_buttons.action_item.right_button.set_visible(ui_state.is_offroad())

  @staticmethod
  def wake_mode_description() -> str:
    def_str = tr("Default: Device will boot/wake-up normally & will be ready to engage.")
    offrd_str = tr("Offroad: Device will be in Always Offroad mode after boot/wake-up.")
    header = tr("Controls state of the device after boot/sleep.")

    return f"{header}\n\n{def_str}\n{offrd_str}"

  @staticmethod
  def _reset_settings():
    def _do_reset(result: int):
      if result == DialogResult.CONFIRM:
        for _key in ui_state.params.all_keys():
          ui_state.params.remove(_key)
        HARDWARE.reboot()

    def _second_confirm(result: int):
      if result == DialogResult.CONFIRM:
        gui_app.set_modal_overlay(ConfirmDialog(
          text=tr("The reset cannot be undone. You have been warned."),
          confirm_text=tr("Confirm")
        ), callback=_do_reset)

    gui_app.set_modal_overlay(ConfirmDialog(
      text=tr("Are you sure you want to reset all IQ.Pilot settings to default? Once the settings are reset, there is no going back."),
      confirm_text=tr("Reset")
    ), callback=_second_confirm)

  @staticmethod
  def _handle_always_offroad():
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Enter Always Offroad Mode")))
      return

    _offroad_mode_state = ui_state.params.get_bool("OffroadMode")
    _offroad_mode_str = tr("Are you sure you want to exit Always Offroad mode?") if _offroad_mode_state else \
                        tr("Are you sure you want to enter Always Offroad mode?")

    def _set_always_offroad(result: int):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        if _offroad_mode_state:
          ui_state.params.put(FORCE_ONROAD_PARAM, 0)
        ui_state.params.put_bool("OffroadMode", not _offroad_mode_state)

    gui_app.set_modal_overlay(ConfirmDialog(_offroad_mode_str, tr("Confirm")), callback=lambda result: _set_always_offroad(result))

  @staticmethod
  def _handle_force_onroad():
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage before forcing on-road")))
      return

    if not ui_state.is_offroad():
      gui_app.set_modal_overlay(alert_dialog(tr("Force On-Road can only be started while offroad")))
      return

    now = int(time.time())
    force_onroad_until = ui_state.params.get(FORCE_ONROAD_PARAM, return_default=True)
    is_active = force_onroad_until > now
    if is_active:
      prompt = tr("Force On-Road is already active. Reset the timer to 10 minutes?")
    else:
      prompt = tr("Force IQ.Pilot on-road for 10 minutes? Always Offroad will be enabled automatically and it will return to offroad after the timer.")

    def _set_force_onroad(result: int):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        # Force On-Road relies on Always Offroad being active so expiry returns to offroad.
        ui_state.params.put_bool("OffroadMode", True)
        ui_state.params.put(FORCE_ONROAD_PARAM, int(time.time()) + FORCE_ONROAD_DURATION_SEC)

    gui_app.set_modal_overlay(ConfirmDialog(prompt, tr("Confirm")), callback=_set_force_onroad)

  @staticmethod
  def _update_max_time_offroad_label(value: int) -> str:
    label = tr("Always On") if value == 0 else f"{value}" + tr("m") if value < 60 else f"{value // 60}" + tr("h")
    label += tr(" (Default)") if value == 1800 else ""
    return label

  def _update_state(self):
    super()._update_state()

    # Handle Always Offroad button
    always_offroad = ui_state.params.get_bool("OffroadMode")
    now = int(time.time())
    force_onroad_until = ui_state.params.get(FORCE_ONROAD_PARAM, return_default=True)
    force_onroad_active = force_onroad_until > now

    # Text & Color
    offroad_mode_btn_text = tr("Exit Always Offroad") if always_offroad else tr("Enable Always Offroad")
    offroad_mode_btn_style = ButtonStyle.PRIMARY if always_offroad else ButtonStyle.DANGER
    self._always_offroad_btn.action_item.left_button.set_text(offroad_mode_btn_text)
    self._always_offroad_btn.action_item.left_button.set_button_style(offroad_mode_btn_style)

    # Position
    if self._scroller._items.__contains__(self._always_offroad_btn):
      self._scroller._items.remove(self._always_offroad_btn)
    if ui_state.is_offroad() and not always_offroad:
      self._scroller._items.insert(len(self._scroller._items) - 1, self._always_offroad_btn)
    else:
      self._scroller._items.insert(0, self._always_offroad_btn)

    # Force On-Road button is always shown directly under Always Offroad in System menu.
    if self._scroller._items.__contains__(self._force_onroad_btn):
      self._scroller._items.remove(self._force_onroad_btn)
    self._scroller._items.insert(self._scroller._items.index(self._always_offroad_btn) + 1, self._force_onroad_btn)

    if force_onroad_active:
      remaining = force_onroad_until - now
      minutes = remaining // 60
      seconds = remaining % 60
      force_onroad_text = f"{tr('Forced On-Road Active')} ({minutes}:{seconds:02d})"
      force_onroad_style = ButtonStyle.PRIMARY
    else:
      force_onroad_text = tr("Force On-Road (10 min)")
      force_onroad_style = ButtonStyle.NORMAL
    self._force_onroad_btn.action_item.left_button.set_text(force_onroad_text)
    self._force_onroad_btn.action_item.left_button.set_button_style(force_onroad_style)
    self._force_onroad_btn.action_item.left_button.set_enabled(ui_state.is_offroad())

    # Onroad Uploads
    self._onroad_uploads_and_reset_settings.action_item.left_button.set_button_style(
      ButtonStyle.PRIMARY if ui_state.params.get_bool("OnroadUploads") else ButtonStyle.NORMAL
    )

    # Offroad only buttons
    self._driver_camera_btn.set_enabled(ui_state.is_offroad())
    self._reg_and_training.action_item.left_button.set_enabled(ui_state.is_offroad())
    self._reg_and_training.action_item.right_button.set_enabled(ui_state.is_offroad())
    self._onroad_uploads_and_reset_settings.action_item.right_button.set_enabled(ui_state.is_offroad())

    # Group advanced actions under submenu buttons.
    root_menu = self._submenu == self.MENU_ROOT
    system_menu = self._submenu == self.MENU_SYSTEM
    maintenance_menu = self._submenu == self.MENU_MAINTENANCE

    self._submenu_system_btn.set_visible(root_menu)
    self._submenu_maintenance_btn.set_visible(root_menu)
    self._submenu_back_btn.set_visible(not root_menu)

    self._always_offroad_btn.set_visible(system_menu)
    self._force_onroad_btn.set_visible(system_menu)
    self._reset_calib_btn.set_visible(system_menu)
    self._change_language_btn.set_visible(system_menu)
    self._system_sep_a.set_visible(system_menu)
    self._system_sep_b.set_visible(system_menu)
    self._system_sep_c.set_visible(system_menu)
    self._system_sep_d.set_visible(system_menu)
    self._device_wake_mode.set_visible(system_menu)
    self._max_time_offroad.set_visible(system_menu)
    self._driver_camera_btn.set_visible(system_menu)
    self._reg_and_training.set_visible(system_menu)

    self._onroad_uploads_and_reset_settings.set_visible(maintenance_menu)
    self._submenu_gap.set_visible(maintenance_menu)
    self._submenu_bottom_separator.set_visible(maintenance_menu)
    self._power_buttons.set_visible(maintenance_menu)

    self._submenu_top_separator.set_visible(root_menu or system_menu or maintenance_menu)


# ===== models =====

if gui_app.iqpilot_ui():
  from openpilot.system.ui.iqpilot.widgets.list_view import button_item as button_item

_ACTIVE_BUNDLE_KEY = "ModelManager_ActiveBundle"
_DOWNLOAD_INDEX_KEY = "ModelManager_DownloadIndex"
_RUNNER_CACHE_KEY = "ModelRunnerTypeCache"


class ModelsLayout(Widget):
  def __init__(self):
    super().__init__()
    self.model_manager = None
    self._refreshing = False
    self._refresh_start = 0.0
    self.download_status = None
    self.prev_download_status = None
    self.model_dialog = None
    self.last_cache_calc_time = 0

    self._initialize_items()

    self.clear_cache_item.action_item.set_value(f"{self._calculate_cache_size():.2f} MB")
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self.current_model_item = IQListItem(
      title=tr("Current Model"),
      description="",
      action_item=NoElideButtonAction(tr("SELECT")),
      callback=self._handle_current_model_clicked
    )

    self.supercombo_label = progress_item(tr("Driving Model"))
    self.vision_label = progress_item(tr("Vision Model"))
    self.policy_label = progress_item(tr("Policy Model"))

    self.refresh_item = button_item(tr("Refresh Model List"), tr("REFRESH"), "", self._on_refresh_models)

    self.clear_cache_item = IQListItem(
      title=tr("Clear Model Cache"),
      description="",
      action_item=NoElideButtonAction(tr("CLEAR")),
      callback=self._clear_cache
    )

    self.redownload_item = button_item(tr("Redownload Current Model"), tr("REDOWNLOAD"), "", self._redownload_model)
    self.cancel_download_item = button_item(tr("Cancel Download"), tr("Cancel"), "", self._cancel_model_request)

    self.items = [self.current_model_item, self.cancel_download_item, self.supercombo_label, self.vision_label,
                  self.policy_label, self.redownload_item, self.refresh_item, self.clear_cache_item]

  def _is_downloading(self):
    return (self.model_manager and self.model_manager.selectedBundle and
            self.model_manager.selectedBundle.status == custom.IQModelManager.DownloadStatus.downloading)

  @staticmethod
  def _has_download_request() -> bool:
    try:
      return int(ui_state.params.get(_DOWNLOAD_INDEX_KEY)) >= 0
    except (TypeError, ValueError):
      return False

  @staticmethod
  def _has_active_bundle_param() -> bool:
    return bool(ui_state.params.get(_ACTIVE_BUNDLE_KEY))

  def _has_model_request(self) -> bool:
    return self._has_download_request()

  @staticmethod
  def _calculate_cache_size():
    cache_size = 0.0
    if os.path.exists(CUSTOM_MODEL_PATH):
      cache_size = sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, file)) for file in os.listdir(CUSTOM_MODEL_PATH)) / (1024**2)
    return cache_size

  @staticmethod
  def _bundle_index(bundle) -> int | None:
    try:
      return int(getattr(bundle, "index", -1))
    except (TypeError, ValueError):
      return None

  @classmethod
  def _bundle_matches(cls, left, right) -> bool:
    if left is None or right is None:
      return False

    left_index = cls._bundle_index(left)
    right_index = cls._bundle_index(right)
    if left_index is not None and right_index is not None and left_index == right_index:
      return True

    for attr in ("ref", "internalName", "displayName"):
      left_value = getattr(left, attr, None)
      if left_value and left_value == getattr(right, attr, None):
        return True
    return False

  @staticmethod
  def _safe_model_path(filename: str) -> str | None:
    if not filename or os.path.basename(filename) != filename:
      return None

    root = os.path.realpath(CUSTOM_MODEL_PATH)
    path = os.path.realpath(os.path.join(root, filename))
    try:
      if os.path.commonpath([root, path]) != root:
        return None
    except ValueError:
      return None
    return path

  def _remove_bundle_files(self, bundle) -> None:
    for model in getattr(bundle, "models", []) or []:
      for artifact in (getattr(model, "metadata", None), getattr(model, "artifact", None)):
        filename = getattr(artifact, "fileName", "") if artifact is not None else ""
        path = self._safe_model_path(filename)
        if path is None:
          continue
        for candidate in (path, f"{path}.download"):
          try:
            if os.path.isfile(candidate):
              os.remove(candidate)
          except OSError:
            pass

  def _clear_cache(self):
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.put_bool("ModelManager_ClearCache", True)
        self.clear_cache_item.action_item.set_value(f"{self._calculate_cache_size():.2f} MB")

    gui_app.set_modal_overlay(ConfirmDialog(tr("This will delete ALL downloaded models from the cache except the currently active model. Are you sure?"),
                                            tr("Clear Cache")), callback=_callback)

  def _redownload_target_bundle(self):
    if not self.model_manager:
      return None
    selected = self.model_manager.selectedBundle
    if selected and selected.status == custom.IQModelManager.DownloadStatus.failed:
      return selected
    active = self.model_manager.activeBundle
    if self._has_active_bundle_param() and active and active.ref:
      return active
    return None

  def _redownload_target_index(self) -> int | None:
    target = self._redownload_target_bundle()
    if not target:
      return None
    try:
      return int(target.index)
    except (TypeError, ValueError):
      pass

    for bundle in self.model_manager.availableBundles:
      if bundle.ref and bundle.ref == target.ref:
        return int(bundle.index)
      if bundle.internalName and bundle.internalName == target.internalName:
        return int(bundle.index)
    return None

  def _can_redownload(self) -> bool:
    return bool(ui_state.is_offroad() and not self._is_downloading() and not self._has_model_request() and self._redownload_target_index() is not None)

  def _cancel_model_request(self):
    ui_state.params.remove(_DOWNLOAD_INDEX_KEY)

  def _redownload_model(self):
    index = self._redownload_target_index()
    if index is None:
      return

    def _callback(response):
      if response == DialogResult.CONFIRM:
        target = self._redownload_target_bundle()
        if target is not None:
          self._remove_bundle_files(target)
          if self._bundle_matches(getattr(self.model_manager, "activeBundle", None), target):
            ui_state.params.remove(_ACTIVE_BUNDLE_KEY)
            ui_state.params.remove(_RUNNER_CACHE_KEY)
        ui_state.params.put(_DOWNLOAD_INDEX_KEY, index)

    gui_app.set_modal_overlay(ConfirmDialog(tr("Clear the selected model cache and download it again?"),
                                            tr("Redownload")), callback=_callback)

  def _handle_bundle_download_progress(self):
    labels = {custom.IQModelManager.Model.Type.supercombo: self.supercombo_label,
              custom.IQModelManager.Model.Type.vision: self.vision_label,
              custom.IQModelManager.Model.Type.policy: self.policy_label}
    for label in labels.values():
      label.set_visible(False)
    self.cancel_download_item.set_visible(False)

    if not self.model_manager or (not self.model_manager.selectedBundle and (not self._has_active_bundle_param() or not self.model_manager.activeBundle)):
      return

    bundle = self.model_manager.selectedBundle if self._is_downloading() or (
      self.model_manager.selectedBundle and self.model_manager.selectedBundle.status == custom.IQModelManager.DownloadStatus.failed
    ) else (self.model_manager.activeBundle if self._has_active_bundle_param() else None)
    if not bundle:
      return

    self.download_status = bundle.status
    status_changed = self.prev_download_status != self.download_status
    self.prev_download_status = self.download_status

    self.cancel_download_item.set_visible(bool(self.model_manager.selectedBundle) and self._has_download_request())

    if (current_time := time.monotonic()) - self.last_cache_calc_time > 0.5:
      self.last_cache_calc_time = current_time
      self.clear_cache_item.action_item.set_value(f"{self._calculate_cache_size():.2f} MB")

    if self.download_status == custom.IQModelManager.DownloadStatus.downloading:
      device._reset_interactive_timeout()

    DS = custom.IQModelManager.DownloadStatus
    bundle_downloading = bundle.status == DS.downloading
    for model in bundle.models:
      label = labels.get(getattr(model.type, 'raw', model.type))
      if label is None:
        continue
      label.set_visible(True)
      p = model.artifact.downloadProgress
      text, show, color, indeterminate = self._model_label_state(p, bundle, bundle_downloading, status_changed)
      label.action_item.update(p.progress, text, show, color, indeterminate=indeterminate)

  def _model_label_state(self, p, bundle, bundle_downloading, status_changed):
    # RL/supercombo weights are served without a content-length, so their per-artifact
    # progress never updates; show a live bar whenever the bundle itself is downloading.
    DS = custom.IQModelManager.DownloadStatus
    name = bundle.displayName
    live = p.status == DS.downloading or (bundle_downloading and p.status not in (DS.downloaded, DS.cached, DS.failed))
    if live:
      if p.progress > 0:
        return f"{int(p.progress)}% - {name}", True, rl.GRAY, False
      return f"{tr('downloading')} - {name}", True, rl.GRAY, True
    if p.status in (DS.downloaded, DS.cached):
      status_text = tr("from cache" if p.status == DS.cached else "downloaded")
      return f"{name} - {status_text if status_changed else tr('ready')}", False, ON_COLOR, False
    if p.status == DS.failed:
      return f"download failed - {name}", False, rl.RED, False
    return f"pending - {name}", False, rl.GRAY, False

  @staticmethod
  def _show_reset_params_dialog():
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.remove("CalibrationParams")
        ui_state.params.remove("LiveTorqueParameters")
    msg = tr("The selected model changed. We suggest resetting calibration. Would you like to do that now?")
    gui_app.set_modal_overlay(ConfirmDialog(msg, tr("Reset Calibration")), callback=_callback)

  def _on_model_selected(self, result):
    if result != DialogResult.CONFIRM:
      return
    selected_ref = self.model_dialog.selection_ref
    if selected_ref == "Default":
      active = self.model_manager.activeBundle if self.model_manager else None
      had_custom_model = bool(active and active.ref and not is_default_bundle(active))
      select_default_model(ui_state.params)
      if had_custom_model:
        self._show_reset_params_dialog()
    elif selected_bundle := next((bundle for bundle in self.model_manager.availableBundles if bundle.ref == selected_ref), None):
      ui_state.params.put(_DOWNLOAD_INDEX_KEY, selected_bundle.index)
      if self.model_manager.activeBundle and selected_bundle.generation != self.model_manager.activeBundle.generation:
        self._show_reset_params_dialog()
    self.model_dialog = None

  @staticmethod
  def _bundle_to_node(bundle):
    return TreeNode(bundle.ref, {'display_name': bundle.displayName, 'short_name': bundle.internalName})

  def _get_folders(self, favorites):
    bundles = self.model_manager.availableBundles
    folders = {}
    for bundle in bundles:
      folders.setdefault(next((ov_ride.value for ov_ride in bundle.overrides if ov_ride.key == "folder"), ""), []).append(bundle)

    folders_list = [TreeFolder("", [TreeNode("Default", {'display_name': tr("Default (CD210)"), 'short_name': "Default"})])]
    for folder, folder_bundles in sorted(folders.items(), key=lambda x: max((bundle.index for bundle in x[1]), default=-1), reverse=True):
      folder_bundles.sort(key=lambda bundle: bundle.index, reverse=True)
      name = folder + (f" - (Updated: {m.group(1)})" if folder_bundles and (m := re.search(r'\(([^)]*)\)[^(]*$', folder_bundles[0].displayName)) else "")
      folders_list.append(TreeFolder(name, [self._bundle_to_node(bundle) for bundle in folder_bundles]))

    if favorites and (fav_bundles := [bundle for bundle in bundles if bundle.ref in favorites]):
      folders_list.insert(1, TreeFolder("Favorites", [self._bundle_to_node(bundle) for bundle in fav_bundles]))
    return folders_list

  def _handle_current_model_clicked(self):
    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()
    folders_list = self._get_folders(favorites)

    active_ref = self.model_manager.activeBundle.ref if self._has_active_bundle_param() and self.model_manager.activeBundle else "Default"
    self.model_dialog = TreeOptionDialog(tr("Select a Model"), folders_list, active_ref, "ModelManager_Favs",
                                         get_folders_fn=self._get_folders, on_exit=self._on_model_selected)
    gui_app.set_modal_overlay(self.model_dialog, callback=self._on_model_selected)

  def _on_refresh_models(self):
    # Trigger a re-sync and show inline loading instead of a blocking dialog
    ui_state.params.put("ModelManager_LastSyncTime", 0)
    self._refreshing = True
    self._refresh_start = time.monotonic()
    self.refresh_item.action_item.set_enabled(False)

  def _update_refresh_state(self):
    if not self._refreshing:
      return
    try:
      last_sync = int(ui_state.params.get("ModelManager_LastSyncTime", return_default=True) or 0)
    except (TypeError, ValueError):
      last_sync = 0
    elapsed = time.monotonic() - self._refresh_start
    if (last_sync > 0 and elapsed > 1.0) or elapsed > 20.0:
      self._refreshing = False
      self.refresh_item.action_item.set_loading(False)
      self.refresh_item.action_item.set_enabled(True)
    else:
      self.refresh_item.action_item.set_loading(True)
      self.refresh_item.action_item.set_enabled(False)

  def _update_state(self):
    self._update_refresh_state()
    self.model_manager = ui_state.sm["iqModelManager"]
    self._handle_bundle_download_progress()
    active = self.model_manager.activeBundle if self.model_manager else None
    if is_default_bundle(active):
      active_name = active.displayName or tr("Default (CD210)")
    elif self._has_active_bundle_param() and active and active.ref:
      active_name = active.internalName
    else:
      active_name = tr("Default (CD210)")
    self.current_model_item.action_item.set_value(active_name)
    self.redownload_item.action_item.set_enabled(self._can_redownload())
    target = self._redownload_target_bundle()
    self.redownload_item.action_item.set_value(target.internalName if target else "")

    if not ui_state.is_offroad():
      self.current_model_item.action_item.set_enabled(False)
      self.current_model_item.set_description(tr("Only available when vehicle is off, or always offroad mode is on"))
    else:
      self.current_model_item.action_item.set_enabled(True)
      self.current_model_item.set_description("")

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()


# ===== settings =====

OP.PANEL_COLOR = rl.Color(10, 10, 10, 255)
ICON_SIZE = 70

OP.PanelType = IntEnum(
  "PanelType",
  [es.name for es in OP.PanelType] + [
    "MODELS",
    "CRUISE",
    "STEERING",
    "VISUALS",
    "NAVIGATION",
    "VEHICLE",
  ],
  start=0,
)


@dataclass
class PanelInfo(OP.PanelInfo):
  icon: str = ""


class SidebarEntry(Widget):
  """One sidebar row: optional icon + label, with a rounded pill behind the active panel."""

  def __init__(self, hub, panel_type, panel_info):
    super().__init__()
    self._hub = hub
    self.panel_type = panel_type
    self.panel_info = panel_info

  @staticmethod
  def _draw_active_pill(rect: rl.Rectangle, left_x: float):
    pill = rl.Rectangle(left_x - 50, rect.y, OP.SIDEBAR_WIDTH - 50, OP.NAV_BTN_HEIGHT)
    rl.draw_rectangle_rounded(pill, 0.2, 5, OP.CLOSE_BTN_COLOR)

  def _render(self, rect):
    active = self.panel_type == self._hub._current_panel
    x = rect.x + 90
    if active:
      self._draw_active_pill(rect, x)

    if self.panel_info.icon:
      icon = gui_app.texture(self.panel_info.icon, ICON_SIZE, ICON_SIZE, keep_aspect_ratio=True)
      rl.draw_texture(icon, int(x), int(rect.y + (OP.NAV_BTN_HEIGHT - icon.height) / 2), rl.WHITE)
      x += ICON_SIZE + 20

    label_h = measure_text_cached(self._hub._font_medium, self.panel_info.name, 65).y
    rl.draw_text_ex(self._hub._font_medium, self.panel_info.name,
                    rl.Vector2(x, rect.y + (OP.NAV_BTN_HEIGHT - label_h) / 2), 55, 0,
                    OP.TEXT_SELECTED if active else OP.TEXT_NORMAL)

    # remembered for the hub's release-hit-testing
    self.panel_info.button_rect = rect


class IQSettingsLayout(OP.SettingsLayout):
  def __init__(self):
    OP.SettingsLayout.__init__(self)
    self._nav_items: list[Widget] = []
    self._sidebar_scroller = Scroller([], spacing=0, line_separator=False, pad_end=False)

    wifi_manager = WifiManager()
    wifi_manager.set_active(False)

    iq_asset = "../../iqpilot/selfdrive/assets/offroad"
    self._panels = {
      OP.PanelType.DEVICE: PanelInfo(tr_noop("Device"), IQDeviceLayout(), icon=f"{iq_asset}/icon_home.png"),
      OP.PanelType.NETWORK: PanelInfo(tr_noop("Network"), IQNetworkUI(wifi_manager), icon="icons/network.png"),
      OP.PanelType.TOGGLES: PanelInfo(tr_noop("Toggles"), TogglesLayout(), icon=f"{iq_asset}/icon_toggle.png"),
      OP.PanelType.SOFTWARE: PanelInfo(tr_noop("Software"), IQSoftwareLayout(), icon=f"{iq_asset}/icon_software.png"),
      OP.PanelType.MODELS: PanelInfo(tr_noop("Models"), ModelsLayout(), icon=f"{iq_asset}/icon_models.png"),
      OP.PanelType.CRUISE: PanelInfo(tr_noop("Cruise"), CruiseLayout(), icon=f"{iq_asset}/icon_longitudinal.png"),
      OP.PanelType.STEERING: PanelInfo(tr_noop("Steering"), SteeringLayout(), icon="icons_mici/wheel.png"),
      OP.PanelType.VISUALS: PanelInfo(tr_noop("Visuals"), VisualsLayout(), icon=f"{iq_asset}/icon_visuals.png"),
      OP.PanelType.VEHICLE: PanelInfo(tr_noop("Vehicle"), VehicleLayout(), icon=f"{iq_asset}/icon_vehicle.png"),
      OP.PanelType.DEVELOPER: PanelInfo(tr_noop("Developer"), IQDeveloperLayout(), icon="icons/shell.png"),
    }

    # Cruise is reachable only via double-click on IQ.Dynamic in Toggles
    self._hidden_from_sidebar = {OP.PanelType.CRUISE}
    self._panels[OP.PanelType.TOGGLES].instance.set_cruise_panel_callback(
      lambda: self.set_current_panel(OP.PanelType.CRUISE)
    )

  def _sidebar_entries(self):
    for panel_type, panel_info in self._panels.items():
      if panel_type not in self._hidden_from_sidebar:
        yield panel_type, panel_info

  def _populate_sidebar(self, rect: rl.Rectangle):
    for panel_type, panel_info in self._sidebar_entries():
      entry = SidebarEntry(self, panel_type, panel_info)
      entry.rect.width = rect.width - 100
      entry.rect.height = OP.NAV_BTN_HEIGHT
      self._nav_items.append(entry)
      self._sidebar_scroller.add_widget(entry)

  def _draw_close_button(self, rect: rl.Rectangle) -> rl.Rectangle:
    btn = rl.Rectangle(rect.x + metrics.GUTTER * 3, rect.y + metrics.GUTTER * 2,
                       metrics.CLOSE_BTN, metrics.CLOSE_BTN)
    pressed = (rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and
               rl.check_collision_point_rec(rl.get_mouse_position(), btn))
    rl.draw_rectangle_rounded(btn, 1.0, 20, OP.CLOSE_BTN_PRESSED if pressed else OP.CLOSE_BTN_COLOR)

    icon = self._close_icon
    dest = rl.Rectangle(btn.x + (btn.width - icon.width) / 2, btn.y + (btn.height - icon.height) / 2,
                        icon.width, icon.height)
    tint = rl.Color(220, 220, 220, 255) if pressed else rl.WHITE
    rl.draw_texture_pro(icon, rl.Rectangle(0, 0, icon.width, icon.height), dest, rl.Vector2(0, 0), 0, tint)
    return btn

  def _draw_sidebar(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, OP.SIDEBAR_COLOR)
    self._close_btn_rect = self._draw_close_button(rect)

    if not self._nav_items:
      self._populate_sidebar(rect)

    nav_rect = rl.Rectangle(rect.x, self._close_btn_rect.height + metrics.GUTTER * 4,
                            rect.width, rect.height - 300)
    self._sidebar_scroller.render(nav_rect)

  def _handle_mouse_release(self, mouse_pos: MousePos) -> bool:
    if rl.check_collision_point_rec(mouse_pos, self._close_btn_rect):
      if self._close_callback:
        self._close_callback()
      return True

    if self._sidebar_scroller.scroll_panel.is_touch_valid():
      for panel_type, panel_info in self._sidebar_entries():
        if rl.check_collision_point_rec(mouse_pos, panel_info.button_rect):
          self.set_current_panel(panel_type)
          return True
    return False

  def show_event(self):
    super().show_event()
    self._panels[self._current_panel].instance.show_event()
    self._sidebar_scroller.show_event()


# ===== vehicle_brands_base =====

class BrandSettings:
  """Per-brand extra settings rows; brands without any simply don't register."""

  def __init__(self):
    self.items: list = []

  def update_settings(self) -> None:
    pass


# ===== vehicle_brands_hyundai =====

_TUNING_BLURBS = (
  lambda: tr("Factory-default longitudinal tuning."),
  lambda: tr("Dynamic tuning: livelier gas/brake response."),
  lambda: tr("Predictive tuning: anticipates and smooths accel changes."),
)


class HyundaiSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.alpha_long_available = False
    self.longitudinal_tuning_item = multiple_button_item(
      tr("Custom Longitudinal Tuning"), "",
      [tr("Off"), tr("Dynamic"), tr("Predictive")],
      button_width=300, param="HyundaiLongitudinalTuning", inline=False,
      callback=lambda index: ui_state.params.put("HyundaiLongitudinalTuning", index))
    self.items = [self.longitudinal_tuning_item]

  def _alpha_long_supported(self) -> bool:
    if bundle := ui_state.params.get("CarPlatformBundle"):
      return CAR[bundle.get("platform")] not in (UNSUPPORTED_LONGITUDINAL_CAR | CANFD_UNSUPPORTED_LONGITUDINAL_CAR)
    if ui_state.CP:
      return ui_state.CP.alphaLongitudinalAvailable
    return False

  def update_settings(self):
    self.alpha_long_available = self._alpha_long_supported()
    selected = int(ui_state.params.get("HyundaiLongitudinalTuning") or "0")

    if not ui_state.is_offroad():
      desc, usable = tr("Unavailable while the car is onroad."), False
    elif not ui_state.has_longitudinal_control:
      desc, usable = tr("Requires IQ.Pilot Longitudinal Control (Alpha) to be enabled."), False
    else:
      blurb = _TUNING_BLURBS[selected] if selected < len(_TUNING_BLURBS) else _TUNING_BLURBS[0]
      desc, usable = blurb(), True

    row = self.longitudinal_tuning_item
    row.action_item.set_enabled(usable)
    row.set_description(desc)
    row.show_description(True)
    row.action_item.set_selected_button(selected)
    row.set_visible(self.alpha_long_available)


# ===== vehicle_brands_subaru =====

_UNSUPPORTED_FLAGS = SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID


class SubaruSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self._supported = False
    self.stop_and_go_toggle = toggle_item(tr("Stop and Go (Beta)"), "", param="SubaruStopAndGo",
                                          callback=lambda _: self.update_settings())
    self.stop_and_go_manual_parking_brake_toggle = toggle_item(
      tr("Stop and Go for Manual Parking Brake (Beta)"), "",
      param="SubaruStopAndGoManualParkingBrake", callback=lambda _: self.update_settings())
    self.items = [self.stop_and_go_toggle, self.stop_and_go_manual_parking_brake_toggle]

  def _platform_flags(self) -> int:
    if bundle := ui_state.params.get("CarPlatformBundle"):
      return CAR[bundle.get("platform")].config.flags
    if ui_state.CP:
      return ui_state.CP.flags
    return 0

  def _blocker_text(self) -> str:
    if not self._supported:
      return tr("Not available on this Subaru platform.")
    if not ui_state.is_offroad():
      return tr("Enable \"Always Offroad\" in Device panel, or turn vehicle off to toggle.")
    return ""

  def update_settings(self):
    self._supported = not (self._platform_flags() & _UNSUPPORTED_FLAGS)
    blocker = self._blocker_text()
    usable = self._supported and ui_state.is_offroad()

    rows = (
      (self.stop_and_go_toggle,
       tr("Automatically resume from a stop while following traffic, on Subaru platforms where "
          "the beta implementation applies.")),
      (self.stop_and_go_manual_parking_brake_toggle,
       tr("Stop-and-go variant for Subaru Global cars with a manual handbrake. Leave this off on "
          "cars with an electric parking brake. Thanks to martinl for this implementation!")),
    )
    for row, body in rows:
      row.action_item.set_enabled(usable)
      row.set_description(f"<b>{blocker}</b><br><br>{body}" if blocker else body)


# ===== vehicle_brands_tesla =====

COOP_STEERING_MIN_KMH = 23
OEM_STEERING_MIN_KMH = 48
KM_TO_MILE = 0.621371


def _speed_text(kmh: int) -> str:
  if ui_state.is_metric:
    return f"{kmh} km/h"
  return f"{round(kmh * KM_TO_MILE)} mph"


class TeslaSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.coop_steering_toggle = toggle_item(tr("VTB (Virtual Torque Blending)"), "", param="TeslaCoopSteering")
    self.items = [self.coop_steering_toggle]

  def update_settings(self):
    caution = tr("Warning: steering may oscillate in turns below {}; turn this off if you feel it.").format(
      _speed_text(OEM_STEERING_MIN_KMH))
    body = (f"<b>{caution}</b><br><br>"
            f"{tr('Lets you nudge the wheel while engaged without fully disengaging steering.')}<br>"
            f"{tr('Active above {} only.').format(_speed_text(COOP_STEERING_MIN_KMH))}")

    if not ui_state.is_offroad():
      blocker = tr("Enable \"Always Offroad\" in Device panel, or turn vehicle off to toggle.")
      body = f"<b>{blocker}</b><br><br>{body}"

    self.coop_steering_toggle.set_description(body)
    self.coop_steering_toggle.action_item.set_enabled(ui_state.is_offroad())


# ===== vehicle_brands_toyota =====

class ToyotaSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.enforce_stock_longitudinal = toggle_item(
      lambda: tr("Enforce Factory Longitudinal Control"),
      description=lambda: tr("Keeps gas and brakes with the factory Toyota system; IQ.Pilot steers only."),
      initial_state=ui_state.params.get_bool("ToyotaEnforceStockLongitudinal"),
      callback=self._on_toggled,
      enabled=lambda: not ui_state.engaged,
    )
    self.items = [self.enforce_stock_longitudinal]

  @staticmethod
  def _apply(enabled: bool):
    ui_state.params.put_bool("ToyotaEnforceStockLongitudinal", enabled)
    if enabled and ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      ui_state.params.put_bool("AlphaLongitudinalEnabled", False)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_toggled(self, state: bool):
    if not state:
      self._apply(False)
      return

    def after_confirm(result: int):
      if result == DialogResult.CONFIRM:
        self._apply(True)
      else:
        self.enforce_stock_longitudinal.action_item.set_state(False)

    row = self.enforce_stock_longitudinal
    prompt = f"<h1>{row.title}</h1><br><p>{row.description}</p>"
    gui_app.set_modal_overlay(ConfirmDialog(prompt, tr("Enable"), rich=True), callback=after_confirm)


# ===== vehicle_brands_volkswagen =====

DESCRIPTIONS = {
  'pqhca5or7Toggle': tr_noop(
    'Use HCA Status 7 instead of Status 5 for steering control on PQ platform vehicles. '
    'This may help with compatibility on some older Volkswagen models.'
  ),
  'AllowLateralWhenLongUnavailable': tr_noop(
    'Allow lateral control (steering) to remain active even when longitudinal control (gas/brake) '
    'is temporarily unavailable due to a cruise control fault.'
  ),
  'iqMqbAccResume': tr_noop(
    'Allow IQ.Pilot to use MQB ACC resume behavior on supported FtS with Extended Hold without Auto Resume Volkswagen MQB vehicles.'
  ),
  'iqMqbSteeringLockout': tr_noop(
    'Enable MQB steering lockout handling on Volkswagen MQB vehicles with low speed LKAS faults.'
  ),
}


class VolkswagenSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.pq_hca_toggle = toggle_item(
      lambda: tr("PQ HCA Status 7 Mode"),
      description=lambda: tr(DESCRIPTIONS["pqhca5or7Toggle"]),
      initial_state=ui_state.params.get_bool("pqhca5or7Toggle"),
      callback=self._on_pq_hca_toggle,
      enabled=lambda: not ui_state.engaged,
    )

    self.lateral_when_long_unavailable = toggle_item(
      lambda: tr("Lateral Control When Cruise Faulted"),
      description=lambda: tr(DESCRIPTIONS["AllowLateralWhenLongUnavailable"]),
      initial_state=ui_state.params.get_bool("AllowLateralWhenLongUnavailable"),
      callback=self._on_lateral_when_long_unavailable,
      enabled=lambda: not ui_state.engaged,
    )

    self.mqb_acc_resume = toggle_item(
      lambda: tr("MQB ACC Resume"),
      description=lambda: tr(DESCRIPTIONS["iqMqbAccResume"]),
      initial_state=ui_state.params.get_bool("iqMqbAccResume"),
      callback=self._on_mqb_acc_resume,
      enabled=lambda: not ui_state.engaged,
    )

    self.mqb_steering_lockout = toggle_item(
      lambda: tr("MQB Steering Lockout"),
      description=lambda: tr(DESCRIPTIONS["iqMqbSteeringLockout"]),
      initial_state=ui_state.params.get_bool("iqMqbSteeringLockout"),
      callback=self._on_mqb_steering_lockout,
      enabled=lambda: not ui_state.engaged,
    )

    self.items = [self.pq_hca_toggle, self.lateral_when_long_unavailable, self.mqb_acc_resume, self.mqb_steering_lockout]

  def _flags(self) -> VolkswagenFlags:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      platform = bundle.get("platform")
      if platform:
        try:
          return CAR[platform].config.flags
        except (KeyError, AttributeError):
          return VolkswagenFlags(0)
    elif ui_state.CP:
      return ui_state.CP.flags
    return VolkswagenFlags(0)

  def _is_pq(self) -> bool:
    return bool(self._flags() & VolkswagenFlags.PQ)

  def _is_mqb(self) -> bool:
    flags = self._flags()
    return not bool(flags & (VolkswagenFlags.PQ | VolkswagenFlags.MLB | VolkswagenFlags.MEB | VolkswagenFlags.MEB_GEN2 | VolkswagenFlags.MQB_EVO))

  def _supports_lateral_when_faulted(self) -> bool:
    return not bool(self._flags() & VolkswagenFlags.MLB)

  def _on_pq_hca_toggle(self, state: bool):
    ui_state.params.put_bool("pqhca5or7Toggle", state)

  def _on_lateral_when_long_unavailable(self, state: bool):
    ui_state.params.put_bool("AllowLateralWhenLongUnavailable", state)

  def _on_mqb_acc_resume(self, state: bool):
    ui_state.params.put_bool("iqMqbAccResume", state)

  def _on_mqb_steering_lockout(self, state: bool):
    ui_state.params.put_bool("iqMqbSteeringLockout", state)

  def update_settings(self):
    self.pq_hca_toggle.set_visible(self._is_pq())
    self.lateral_when_long_unavailable.set_visible(self._supports_lateral_when_faulted())
    is_mqb = self._is_mqb()
    self.mqb_acc_resume.set_visible(is_mqb)
    self.mqb_steering_lockout.set_visible(is_mqb)


# ===== vehicle_brands_factory =====

# Only brands that actually ship extra rows appear here; every other brand gets None.
_REGISTRY: dict[str, type[BrandSettings]] = {
  "hyundai": HyundaiSettings,
  "subaru": SubaruSettings,
  "tesla": TeslaSettings,
  "toyota": ToyotaSettings,
  "volkswagen": VolkswagenSettings,
}


def brand_settings_for(brand: str) -> BrandSettings | None:
  cls = _REGISTRY.get(brand)
  return cls() if cls else None


class BrandSettingsFactory:
  """Legacy shim for callers using the old factory name."""

  create_brand_settings = staticmethod(brand_settings_for)


# ===== vehicle_platform_selector =====


class FingerprintStatus(IntEnum):
  NONE = 0      # nothing identified, nothing forced
  AUTO = 1      # car identified itself over CAN
  FORCED = 2    # user pinned a platform manually


STATUS_COLORS = {
  FingerprintStatus.NONE: ink.STATUS_WARN,
  FingerprintStatus.AUTO: ink.STATUS_GOOD,
  FingerprintStatus.FORCED: ink.STATUS_INFO,
}


class VehicleSelection:
  """Owns the car list and the CarPlatformBundle param; widgets render from this."""

  def __init__(self):
    self.platforms: dict = load_catalog()

  @staticmethod
  def forced_bundle():
    return ui_state.params.get("CarPlatformBundle")

  def status(self) -> FingerprintStatus:
    if self.forced_bundle():
      return FingerprintStatus.FORCED
    if ui_state.CP and ui_state.CP.carFingerprint != "MOCK":
      return FingerprintStatus.AUTO
    return FingerprintStatus.NONE

  def display_name(self) -> str:
    if bundle := self.forced_bundle():
      return bundle.get("name", "")
    if ui_state.CP and ui_state.CP.carFingerprint != "MOCK":
      return ui_state.CP.carFingerprint
    return tr("No vehicle selected")

  def force(self, platform_name: str) -> bool:
    data = self.platforms.get(platform_name)
    if not data:
      return False
    ui_state.params.put("CarPlatformBundle", {**data, "name": platform_name})
    return True

  @staticmethod
  def clear():
    ui_state.params.remove("CarPlatformBundle")

  def picker_folders(self) -> list[TreeFolder]:
    def node_for(name: str) -> TreeNode:
      info = self.platforms[name]
      years = ' '.join(map(str, info.get('year', [])))
      return TreeNode(name, {
        'display_name': name,
        'search_tags': f"{name} {info.get('make')} {years} {info.get('model', name)}",
      })

    names = sorted(self.platforms)
    makes = sorted({self.platforms[n].get('make') for n in names})
    return [TreeFolder(make, [node_for(n) for n in names if self.platforms[n].get('make') == make])
            for make in makes]


class PlatformSelector(Button):
  """Row button that either clears a forced platform or opens the vehicle picker."""

  def __init__(self, on_platform_change: Callable[[], None] | None = None):
    super().__init__(tr("Vehicle"), self._on_clicked, button_style=ButtonStyle.NORMAL)
    self.set_rect(rl.Rectangle(0, 0, 0, 120))
    self.selection = VehicleSelection()
    self._on_platform_change = on_platform_change
    self.refresh()

  @property
  def text(self):
    return self._label._text

  @property
  def status(self) -> FingerprintStatus:
    return self.selection.status()

  @property
  def color(self) -> rl.Color:
    return STATUS_COLORS[self.status]

  def set_parent_rect(self, parent_rect):
    super().set_parent_rect(parent_rect)
    self._rect.width = parent_rect.width

  def refresh(self):
    self.set_text(self.selection.display_name())
    self.set_enabled(True)

  def _notify(self):
    self.refresh()
    if self._on_platform_change:
      self._on_platform_change()

  def _on_clicked(self):
    if self.selection.forced_bundle():
      self.selection.clear()
      self._notify()
    else:
      self._open_picker()

  def _open_picker(self):
    dialog = TreeOptionDialog(
      tr("Select a vehicle"),
      self.selection.picker_folders(),
      search_prompt=tr("Search make or model"),
      search_title=tr("Search your vehicle"),
      search_subtitle=tr("Enter model year (e.g., 2021) and model (Toyota Corolla):"),
      search_funcs=[lambda node: node.data.get('display_name', ''), lambda node: node.data.get('search_tags', '')],
    )
    done = partial(self._on_picked, dialog)
    dialog.on_exit = done
    gui_app.set_modal_overlay(dialog, callback=done)

  def _on_picked(self, dialog, res):
    if res != DialogResult.CONFIRM or not dialog.selection_ref:
      return
    when = tr("This setting will take effect immediately.") if ui_state.is_offroad else \
           tr("This setting will take effect once the device enters offroad state.")

    def confirm(result):
      if result == DialogResult.CONFIRM and self.selection.force(dialog.selection_ref):
        self._notify()

    gui_app.set_modal_overlay(ConfirmDialog(when, tr("Confirm")), callback=confirm)


_LEGEND = (
  (FingerprintStatus.AUTO, lambda: tr("Fingerprinted automatically")),
  (FingerprintStatus.FORCED, lambda: tr("Manually selected fingerprint")),
  (FingerprintStatus.NONE, lambda: tr("Not fingerprinted or manually selected")),
)


class LegendWidget(Widget):
  """Explains the fingerprint status colours; the active row is highlighted."""

  def __init__(self, platform_selector: PlatformSelector):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 0, 350))
    self._selector = platform_selector
    self._font = gui_app.font(FontWeight.NORMAL)
    self._bold_font = gui_app.font(FontWeight.BOLD)

  def _render(self, rect):
    x = rect.x + 20
    y = rect.y + 20
    rl.draw_text_ex(self._font, tr("Select vehicle to force fingerprint manually."), rl.Vector2(x, y), 40, 0, ink.CAPTION)
    y += 80
    rl.draw_text_ex(self._font, tr("Colors represent vehicle fingerprint status:"), rl.Vector2(x, y), 40, 0, ink.CAPTION)
    y += 80

    active = self._selector.status
    for status, label in _LEGEND:
      font = self._bold_font if status == active else self._font
      text_color = rl.WHITE if status == active else ink.CAPTION
      text = f"- {label()}"
      ts = measure_text_cached(font, text, 40)
      chip_cy = (y - 7) + ts.y / 2
      rl.draw_rectangle_rounded(rl.Rectangle(x, chip_cy - 18, 36, 36), 0.45, 10, STATUS_COLORS[status])
      rl.draw_text_ex(font, text, rl.Vector2(x + 56, y - 7), 40, 0, text_color)
      y += 50


# ===== vehicle___init__ =====

_STATUS_BADGES = {
  FingerprintStatus.AUTO: lambda: tr("AUTO"),
  FingerprintStatus.FORCED: lambda: tr("MANUAL"),
  FingerprintStatus.NONE: lambda: tr("NONE"),
}


class VehicleLayout(Widget):
  def __init__(self):
    super().__init__()
    self._brand_settings = None
    self._current_brand = None
    self._platform_selector = PlatformSelector(self._on_vehicle_changed)
    self._vehicle_item = IQListItem(title=self._platform_selector.text, action_item=ButtonAction(text=tr("SELECT")),
                                    callback=self._platform_selector._on_clicked)
    self._legend_widget = LegendWidget(self._platform_selector)
    self._refresh_vehicle_row()

    self.items = [self._vehicle_item, self._legend_widget]
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  @staticmethod
  def get_brand():
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      return bundle.get("brand", "")
    fingerprinted = ui_state.CP and ui_state.CP.carFingerprint != "MOCK"
    return ui_state.CP.brand if fingerprinted else ""

  def _refresh_vehicle_row(self):
    # White name for legibility; the fingerprint status lives in a coloured chip beside it.
    status = self._platform_selector.status
    self._vehicle_item._title = self._platform_selector.text
    self._vehicle_item.title_color = rl.WHITE
    self._vehicle_item.title_badge = (_STATUS_BADGES[status](), STATUS_COLORS[status])
    forced = ui_state.params.get("CarPlatformBundle") is not None
    self._vehicle_item.action_item.set_text(tr("REMOVE") if forced else tr("SELECT"))

  def _sync_brand_panel(self):
    brand = self.get_brand()
    if brand == self._current_brand:
      return
    self._current_brand = brand
    self._brand_settings = brand_settings_for(brand)
    brand_rows = self._brand_settings.items if self._brand_settings else []
    self.items = [self._vehicle_item, self._legend_widget, *brand_rows]
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _on_vehicle_changed(self):
    self._refresh_vehicle_row()
    self._sync_brand_panel()

  def _update_state(self):
    self._on_vehicle_changed()
    if self._brand_settings:
      self._brand_settings.update_settings()
    self._platform_selector.refresh()

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
