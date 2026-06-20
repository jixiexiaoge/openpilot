"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Offline maps (OSM) settings for MICI (comma 4).
"""
import threading
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialogV2, BigMultiOptionDialog
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.label import UnifiedLabel

try:
  from openpilot.selfdrive.ui.iqpilot.layouts.settings.osm import (
    delete_maps,
    fetch_available_regions,
    get_download_progress,
    get_downloaded_maps,
    get_mapd_version,
    start_map_download,
  )
  _OSM_AVAILABLE = True
except ImportError:
  _OSM_AVAILABLE = False
  def fetch_available_regions(): return {}
  def get_downloaded_maps(): return []
  def delete_maps(): pass
  def start_map_download(r): pass
  def get_download_progress(): return -1.0
  def get_mapd_version(): return "unknown"


class OSMLayoutMici(NavWidget):
  PAD        = 16
  INFO_H     = 64
  PROGRESS_H = 16

  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()
    self._regions: dict          = {}
    self._selected_region: str   = ""
    self._downloading: bool      = False

    self._mapd_version_label = UnifiedLabel(
      f"mapd: {get_mapd_version()}", 26, FontWeight.ROMAN,
      rl.Color(180, 180, 180, 200),
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
    )
    self._region_label = UnifiedLabel(
      "no region selected", 28, FontWeight.ROMAN,
      rl.Color(255, 255, 255, int(255 * 0.75)),
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
    )

    # All action buttons use NeonBigButton for consistent neon style
    self._select_region_btn = NeonBigButton("select region →")
    self._select_region_btn.set_click_callback(self._open_region_dialog)

    self._download_btn = NeonBigButton("download maps")
    self._download_btn.set_click_callback(self._start_download)

    self._delete_btn = NeonBigButton("delete maps")
    self._delete_btn.set_click_callback(self._confirm_delete)

    if back_callback:
      self.set_back_callback(back_callback)

    self._fetch_regions_bg()

  # ── Background region fetch ────────────────────────────────────────────────

  def _fetch_regions_bg(self):
    def _fetch():
      try:
        self._regions = fetch_available_regions()
      except Exception:
        self._regions = {}
    threading.Thread(target=_fetch, daemon=True).start()

  # ── Dialogs ────────────────────────────────────────────────────────────────

  def _open_region_dialog(self):
    if not self._regions:
      return
    options = sorted(self._regions.keys())
    current = self._selected_region if self._selected_region in options else None

    def on_confirm():
      self._selected_region = country_dlg.get_selected_option()
      self._region_label.set_text(self._selected_region)
      states = self._regions.get(self._selected_region, [])
      if states:
        self._open_state_dialog(states)

    country_dlg = BigMultiOptionDialog(
      options=options, default=current,
      right_btn="check", right_btn_callback=on_confirm,
    )
    gui_app.set_modal_overlay(country_dlg)

  def _open_state_dialog(self, states: list[str]):
    def on_confirm():
      state = state_dlg.get_selected_option()
      self._selected_region = f"{self._selected_region}/{state}"
      self._region_label.set_text(self._selected_region)

    state_dlg = BigMultiOptionDialog(
      options=sorted(states), default=None,
      right_btn="check", right_btn_callback=on_confirm,
    )
    gui_app.set_modal_overlay(state_dlg)

  # ── Actions ────────────────────────────────────────────────────────────────

  def _start_download(self):
    if not self._selected_region or self._downloading:
      return
    self._downloading = True
    self._download_btn.set_enabled(False)
    threading.Thread(
      target=lambda: start_map_download(self._selected_region), daemon=True,
    ).start()

  def _confirm_delete(self):
    def do_delete():
      threading.Thread(target=delete_maps, daemon=True).start()
      self._region_label.set_text("maps deleted")

    dlg = BigConfirmationDialogV2(
      "Delete all maps?",
      "icons_mici/settings/device/uninstall.png",
      red=True, confirm_callback=do_delete,
    )
    gui_app.set_modal_overlay(dlg)

  # ── Lifecycle ──────────────────────────────────────────────────────────────

  def show_event(self):
    super().show_event()
    self._mapd_version_label.set_text(f"mapd: {get_mapd_version()}")
    progress = get_download_progress()
    self._downloading = 0.0 <= progress < 1.0
    self._download_btn.set_enabled(not self._downloading and bool(self._selected_region))
    self._delete_btn.set_enabled(bool(get_downloaded_maps()))

  def _render(self, rect: rl.Rectangle):
    px = rect.x + self.PAD
    w  = rect.width - self.PAD * 2

    self._mapd_version_label.render(rl.Rectangle(px, rect.y + 4,  w, 28))
    self._region_label.render(      rl.Rectangle(px, rect.y + 34, w, 30))

    progress = get_download_progress()
    prog_y   = rect.y + self.INFO_H

    if 0.0 <= progress < 1.0:
      self._downloading = True
      track_rect = rl.Rectangle(px, prog_y, w, self.PROGRESS_H)
      rl.draw_rectangle_rounded(track_rect, 0.5, 6, rl.Color(50, 50, 50, 200))
      fill_w = int(w * progress)
      if fill_w > 0:
        rl.draw_rectangle_rounded(
          rl.Rectangle(px, prog_y, fill_w, self.PROGRESS_H),
          0.5, 6, rl.Color(0x00, 0xC0, 0xB0, 220),
        )
      prog_h = self.PROGRESS_H + 8
    else:
      self._downloading = False
      self._download_btn.set_enabled(bool(self._selected_region))
      prog_h = 0

    btn_y = prog_y + prog_h + 8
    btn_h = self._select_region_btn._rect.height
    btn_w = self._select_region_btn._rect.width

    self._select_region_btn.render(rl.Rectangle(px, btn_y, btn_w, btn_h))
    btn_y += btn_h + 8
    self._download_btn.render(rl.Rectangle(px, btn_y, btn_w, btn_h))
    btn_y += btn_h + 8
    self._delete_btn.render(rl.Rectangle(px, btn_y, btn_w, btn_h))
