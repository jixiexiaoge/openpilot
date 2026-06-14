"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os
import re
from collections.abc import Callable

from cereal import custom
from openpilot.selfdrive.ui.mici.widgets.button import (
  DrumFloatMappedParamButton, NeonBigButton, NeonBigParamToggle,
)
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialogV2
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import NavWidget, Widget, DialogResult
from openpilot.system.ui.widgets.scroller import Scroller

from openpilot.iqpilot.models.runners.constants import CUSTOM_MODEL_PATH
from openpilot.iqpilot.models.helpers import get_default_model_bundle


class ModelsLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)
    self.original_back_callback = back_callback
    self.focused_widget = None

    # ── Current model / download ──────────────────────────────────────────────
    self.current_model_btn = NeonBigButton(tr("current model"))
    self.current_model_btn.set_click_callback(self._show_folders)

    self.cancel_download_btn = NeonBigButton(tr("cancel download"))
    self.cancel_download_btn.set_click_callback(lambda: ui_state.params.remove("ModelManager_DownloadIndex"))

    # ── Refresh / clear cache ─────────────────────────────────────────────────
    self.refresh_btn = NeonBigButton(tr("refresh model list"))
    self.refresh_btn.set_click_callback(self._refresh_model_list)

    self.clear_cache_btn = NeonBigButton(tr("clear model cache"))
    self.clear_cache_btn.set_click_callback(self._confirm_clear_cache)
    self.clear_cache_btn.set_enabled(lambda: ui_state.is_offroad())

    # ── Tuning toggles ────────────────────────────────────────────────────────
    self.lagd_toggle = NeonBigParamToggle("live learning steer delay", "LagdToggle")
    self.delay_control = DrumFloatMappedParamButton(
      "software delay",
      "LagdToggleDelay",
      ["0.05s", "0.10s", "0.15s", "0.20s", "0.25s", "0.30s", "0.35s", "0.40s", "0.45s", "0.50s"],
      [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
    )
    self.delay_control.set_visible(lambda: not self.lagd_toggle._checked)

    self.lane_turn_toggle = NeonBigParamToggle("use lane turn desires", "LaneTurnDesire")
    self.lane_turn_value = DrumFloatMappedParamButton(
      "lane turn speed",
      "LaneTurnValue",
      ["slow", "normal", "fast"],
      [15.0, 19.0, 20.0],
    )
    self.lane_turn_value.set_visible(lambda: self.lane_turn_toggle._checked)

    # ── Main scroller items ───────────────────────────────────────────────────
    self.main_items: list[Widget] = [
      self.current_model_btn,
      self.cancel_download_btn,
      self.refresh_btn,
      self.clear_cache_btn,
      self.lagd_toggle,
      self.delay_control,
      self.lane_turn_toggle,
      self.lane_turn_value,
    ]
    self._scroller = Scroller(self.main_items, snap_items=False)

  # ── Helpers ────────────────────────────────────────────────────────────────

  @property
  def model_manager(self):
    return ui_state.sm["iqModelManager"]

  def _get_grouped_bundles(self):
    bundles = self.model_manager.availableBundles
    folders = {}
    for bundle in bundles:
      folder = next((override.value for override in bundle.overrides if override.key == "folder"), "")
      folders.setdefault(folder, []).append(bundle)
    return folders

  @staticmethod
  def _calculate_cache_size():
    cache_size = 0.0
    if os.path.exists(CUSTOM_MODEL_PATH):
      cache_size = sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, f)) for f in os.listdir(CUSTOM_MODEL_PATH)) / (1024**2)
    return cache_size

  def _refresh_model_list(self):
    ui_state.params.put("ModelManager_LastSyncTime", 0)

  # ── Cache clear confirmation ───────────────────────────────────────────────

  def _confirm_clear_cache(self):
    def _on_confirm():
      ui_state.params.put_bool("ModelManager_ClearCache", True)

    dlg = BigConfirmationDialogV2(
      title="clear cache?",
      icon="icons_mici/settings/developer_icon.png",
      red=True,
      exit_on_confirm=True,
      confirm_callback=_on_confirm,
    )

    def _cb(result):
      pass  # dialog handles everything via confirm_callback + exit_on_confirm

    gui_app.set_modal_overlay(dlg, callback=_cb)

  # ── Folder / model selection navigation ───────────────────────────────────

  def _show_selection_view(self, items: list[Widget], back_callback: Callable):
    self._scroller._items = items
    for item in items:
      item.set_touch_valid_callback(lambda: self._scroller.scroll_panel.is_touch_valid() and self._scroller.enabled)
    self._scroller.scroll_panel.set_offset(0)
    self.set_back_callback(back_callback)

  def _show_folders(self):
    self.focused_widget = self.current_model_btn
    folders = self._get_grouped_bundles()
    folder_buttons = []

    default_btn = NeonBigButton(tr("default model"))
    default_btn.set_click_callback(self._select_default)
    folder_buttons.append(default_btn)

    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()
    if favorites:
      fav_bundles = [b for b in self.model_manager.availableBundles if b.ref in favorites]
      if fav_bundles:
        fav_btn = NeonBigButton("favorites")
        fav_btn.set_chips([str(len(fav_bundles))])
        fav_btn.set_click_callback(lambda: self._select_folder_bundles("favorites", fav_bundles))
        folder_buttons.append(fav_btn)

    for folder in sorted(folders.keys(), key=lambda f: max((bundle.index for bundle in folders[f]), default=-1), reverse=True):
      display_name = folder.lower() if folder else "other"
      folder_bundles = folders[folder]
      folder_bundles_sorted = sorted(folder_bundles, key=lambda b: b.index, reverse=True)
      if folder_bundles_sorted:
        m = re.search(r'\(([^)]*)\)[^(]*$', folder_bundles_sorted[0].displayName)
        if m:
          display_name += f" ({m.group(1)})"
      btn = NeonBigButton(display_name)
      btn.set_click_callback(lambda f=folder: self._select_folder(f))
      folder_buttons.append(btn)

    self._show_selection_view(folder_buttons, self._reset_main_view)

  def _select_model(self, bundle):
    ui_state.params.put("ModelManager_DownloadIndex", bundle.index)
    self._reset_main_view()

  def _select_default(self):
    default_bundle = get_default_model_bundle(self.model_manager.availableBundles)
    if default_bundle:
      ui_state.params.put("ModelManager_DownloadIndex", default_bundle.index)
    self._reset_main_view()

  def _select_folder(self, folder_name):
    folders = self._get_grouped_bundles()
    bundles = sorted(folders.get(folder_name, []), key=lambda b: b.index, reverse=True)
    self._select_folder_bundles(folder_name, bundles)

  def _select_folder_bundles(self, folder_name, bundles):
    btns = []
    for bundle in bundles:
      txt = bundle.displayName.lower()
      btn = NeonBigButton(txt)
      btn.set_click_callback(lambda b=bundle: self._select_model(b))
      btns.append(btn)
    self._show_selection_view(btns, self._show_folders)

  def _reset_main_view(self):
    self._scroller._items = self.main_items
    self.set_back_callback(self.original_back_callback)
    if self.focused_widget and self.focused_widget in self.main_items:
      x = self._scroller._pad_start
      for item in self.main_items:
        if not item.is_visible:
          continue
        if item == self.focused_widget:
          break
        x += item.rect.width + self._scroller._spacing
      self._scroller.scroll_panel.set_offset(0)
      self._scroller.scroll_to(x)
      self.focused_widget = None
    else:
      self._scroller.scroll_panel.set_offset(0)

  # ── State update ──────────────────────────────────────────────────────────

  def _update_state(self):
    super()._update_state()

    manager = self.model_manager
    downloading = (manager.selectedBundle and
                   manager.selectedBundle.status == custom.IQModelManager.DownloadStatus.downloading)

    if downloading:
      chips = []
      try:
        bundle = manager.selectedBundle
        for model in bundle.models:
          p = model.artifact.downloadProgress
          if p.status == custom.IQModelManager.DownloadStatus.downloading:
            chips.append(f"{int(p.progress)}%")
          elif p.status in (custom.IQModelManager.DownloadStatus.downloaded, custom.IQModelManager.DownloadStatus.cached):
            chips.append("ready")
          elif p.status == custom.IQModelManager.DownloadStatus.failed:
            chips.append("failed")
      except Exception:
        pass
      self.current_model_btn.set_chips(chips or ["downloading..."])
      self.cancel_download_btn.set_visible(True)
    else:
      active_name = manager.activeBundle.internalName.lower() if manager.activeBundle else tr("default model")
      self.current_model_btn.set_chips([active_name])
      self.cancel_download_btn.set_visible(False)

    self.current_model_btn.set_enabled(ui_state.is_offroad())

    self.clear_cache_btn.set_chips([f"{self._calculate_cache_size():.1f} MB"])

    # Refresh toggles from params
    self.lagd_toggle.refresh()
    self.delay_control.refresh()
    self.lane_turn_toggle.refresh()
    self.lane_turn_value.refresh()

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
