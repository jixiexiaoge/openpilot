"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import os
import re
import time

import pyray as rl

from cereal import custom

from openpilot.system.ui.iqpilot.widgets.helpers.glyphs import draw_star

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigParamControl, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.stock_dialog import BigConfirmationDialog
from openpilot.selfdrive.ui.mici.layouts.settings.iq_widgets import MappedParamToggle

from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import select_default_model, is_default_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import CUSTOM_MODEL_PATH

_DELAY_OPTIONS = ["0.05s", "0.10s", "0.15s", "0.20s", "0.25s", "0.30s", "0.35s", "0.40s", "0.45s", "0.50s"]
_DELAY_VALUES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]

_LANE_TURN_OPTIONS = ["slow", "normal", "fast"]
_LANE_TURN_VALUES = [15.0, 19.0, 20.0]

_DL = custom.IQModelManager.DownloadStatus
_ACTIVE_BUNDLE_KEY = "ModelManager_ActiveBundle"
_DOWNLOAD_INDEX_KEY = "ModelManager_DownloadIndex"
_RUNNER_CACHE_KEY = "ModelRunnerTypeCache"


def _display_model_name(bundle) -> str:
  return bundle.internalName if getattr(bundle, "internalName", "") else bundle.displayName


class _ModelSelectPanel(NavScroller):
  """A throwaway scroller panel (folder list or bundle list) pushed onto the nav stack."""
  def __init__(self, items):
    super().__init__()
    self._scroller.add_widgets(items)


class _ModelButton(BigButton):
  """A bundle in the model list: single tap selects (download), double tap toggles favorite.

  A golden star is drawn in the corner when the model is favorited.
  """
  THRESHOLD = 0.4
  _STAR_GOLD = rl.Color(0xFF, 0xC1, 0x07, 255)

  def __init__(self, bundle, on_select, on_favorite, is_favorite):
    super().__init__(bundle.displayName)
    self._bundle = bundle
    self._on_select = on_select
    self._on_favorite = on_favorite
    self._is_favorite = is_favorite
    self._pending_t = 0.0
    self._pending_pos = None

  def _handle_mouse_release(self, mouse_pos):
    now = time.monotonic()
    if self._pending_pos is not None and now - self._pending_t < self.THRESHOLD:
      self._pending_pos = None
      self._pending_t = 0.0
      self._is_favorite = self._on_favorite(self._bundle)
      return
    self._pending_t = now
    self._pending_pos = mouse_pos

  def _update_state(self):
    super()._update_state()
    if self._pending_pos is not None and time.monotonic() - self._pending_t >= self.THRESHOLD:
      self._pending_pos = None
      self._on_select(self._bundle)

  def _render(self, _):
    super()._render(_)
    if self._is_favorite:
      cx = self._rect.x + self._rect.width - 46
      cy = self._rect.y + 46
      draw_star(cx, cy, 24, True, self._STAR_GOLD)


class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._last_cache_t = 0.0
    self._download_status = None
    self._prev_download_status = None
    self._clear_icon = gui_app.texture("icons_mici/settings/developer_icon.png", 56, 56)
    self._redownload_icon = gui_app.texture("icons_mici/settings/device/update.png", 56, 56, keep_aspect_ratio=True)
    self._reset_icon = gui_app.texture("icons_mici/wheel.png", 56, 56)

    self._current = BigButton("current model")
    self._current.set_click_callback(self._show_folders)

    self._cancel = BigButton("cancel download")
    self._cancel.set_click_callback(self._cancel_model_request)
    self._cancel.set_visible(self._is_downloading)

    self._redownload = BigButton("redownload model")
    self._redownload.set_click_callback(self._confirm_redownload_model)
    self._redownload.set_enabled(self._can_redownload)

    self._refresh = BigButton("refresh model list")
    self._refresh.set_click_callback(lambda: ui_state.params.put("ModelManager_LastSyncTime", 0))

    self._supercombo = GreyBigButton("driving model")
    self._supercombo.set_visible(False)
    self._vision = GreyBigButton("vision model")
    self._vision.set_visible(False)
    self._policy = GreyBigButton("policy model")
    self._policy.set_visible(False)

    self._clear = BigButton("clear model cache")
    self._clear.set_click_callback(self._confirm_clear_cache)
    self._clear.set_enabled(lambda: ui_state.is_offroad())

    self._lagd = BigParamControl("live learning steer delay", "LagdToggle")
    self._sw_delay = MappedParamToggle("software delay", "LagdToggleDelay", _DELAY_OPTIONS, _DELAY_VALUES)
    self._sw_delay.set_visible(lambda: not self._lagd._checked)

    self._lane_turn = BigParamControl("use lane turn desires", "IQLaneTurnDesire")
    self._lane_speed = MappedParamToggle("lane turn speed", "IQLaneTurnValue", _LANE_TURN_OPTIONS, _LANE_TURN_VALUES)
    self._lane_speed.set_visible(lambda: self._lane_turn._checked)

    self._main_items = [self._current, self._cancel, self._supercombo, self._vision, self._policy, self._redownload, self._refresh, self._clear,
                        self._lagd, self._sw_delay, self._lane_turn, self._lane_speed]
    self._scroller.add_widgets(self._main_items)

  @property
  def model_manager(self):
    return ui_state.sm["iqModelManager"]

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

  def _is_downloading(self) -> bool:
    try:
      return bool(self.model_manager.selectedBundle and self.model_manager.selectedBundle.status == _DL.downloading)
    except Exception:
      return False

  @staticmethod
  def _calculate_cache_size() -> float:
    if os.path.exists(CUSTOM_MODEL_PATH):
      return sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, f)) for f in os.listdir(CUSTOM_MODEL_PATH)) / (1024 ** 2)
    return 0.0

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

  def _group_folders(self, bundles):
    folders: dict = {}
    for bundle in bundles:
      folder = next((ov.value for ov in bundle.overrides if ov.key == "folder"), "")
      folders.setdefault(folder, []).append(bundle)
    return folders

  @staticmethod
  def _read_favorites() -> set:
    favs = ui_state.params.get("ModelManager_Favs")
    return set(favs.split(';')) if favs else set()

  def _toggle_favorite(self, bundle) -> bool:
    favs = self._read_favorites()
    if bundle.ref in favs:
      favs.discard(bundle.ref)
    else:
      favs.add(bundle.ref)
    ui_state.params.put("ModelManager_Favs", ';'.join(sorted(favs)))
    return bundle.ref in favs

  def _confirm_clear_cache(self):
    gui_app.push_widget(BigConfirmationDialog("slide to\nclear cache", self._clear_icon,
                                              lambda: ui_state.params.put_bool("ModelManager_ClearCache", True),
                                              red=True))

  def _redownload_target_bundle(self):
    try:
      selected = self.model_manager.selectedBundle
      if selected and selected.status == _DL.failed:
        return selected
      active = self.model_manager.activeBundle
      if self._has_active_bundle_param() and active and active.ref:
        return active
    except Exception:
      pass
    return None

  def _redownload_target_index(self) -> int | None:
    target = self._redownload_target_bundle()
    if not target:
      return None

    try:
      return int(target.index)
    except (TypeError, ValueError):
      pass

    try:
      for bundle in self.model_manager.availableBundles:
        if bundle.ref and bundle.ref == target.ref:
          return int(bundle.index)
        if bundle.internalName and bundle.internalName == target.internalName:
          return int(bundle.index)
    except Exception:
      pass
    return None

  def _can_redownload(self) -> bool:
    return bool(ui_state.is_offroad() and not self._is_downloading() and not self._has_model_request() and self._redownload_target_index() is not None)

  def _cancel_model_request(self):
    ui_state.params.remove(_DOWNLOAD_INDEX_KEY)

  def _confirm_redownload_model(self):
    index = self._redownload_target_index()
    if index is None:
      return

    def _redownload():
      target = self._redownload_target_bundle()
      if target is not None:
        self._remove_bundle_files(target)
        if self._bundle_matches(getattr(self.model_manager, "activeBundle", None), target):
          ui_state.params.remove(_ACTIVE_BUNDLE_KEY)
          ui_state.params.remove(_RUNNER_CACHE_KEY)
      ui_state.params.put(_DOWNLOAD_INDEX_KEY, index)
      self._redownload.set_value("queued")

    gui_app.push_widget(BigConfirmationDialog("slide to\nredownload", self._redownload_icon, _redownload, red=True))

  def _show_folders(self):
    bundles = list(self.model_manager.availableBundles)
    favorites = self._read_favorites()
    btns = []

    default_btn = BigButton("Default (CD210)")
    default_btn.set_click_callback(self._select_default)
    btns.append(default_btn)

    if favorites and (fav_bundles := [b for b in bundles if b.ref in favorites]):
      fav_btn = BigButton("Favorites", str(len(fav_bundles)))
      fav_btn.set_click_callback(lambda fb=fav_bundles: self._show_bundles(fb))
      btns.append(fav_btn)

    folders = self._group_folders(bundles)
    for folder in sorted(folders, key=lambda f: max((b.index for b in folders[f]), default=-1), reverse=True):
      name = folder if folder else "Other"
      folder_bundles = sorted(folders[folder], key=lambda b: b.index, reverse=True)
      if folder_bundles and (m := re.search(r'\(([^)]*)\)[^(]*$', folder_bundles[0].displayName)):
        name += f" ({m.group(1)})"
      btn = BigButton(name)
      btn.set_click_callback(lambda fb=folder_bundles: self._show_bundles(fb))
      btns.append(btn)

    gui_app.push_widget(_ModelSelectPanel(btns))

  def _show_bundles(self, bundles):
    favorites = self._read_favorites()
    btns = [_ModelButton(b, self._select_model, self._toggle_favorite, b.ref in favorites) for b in bundles]
    gui_app.push_widget(_ModelSelectPanel(btns))

  def _generation_changed(self, bundle) -> bool:
    try:
      active = self.model_manager.activeBundle
      return bool(active and active.ref and bundle.generation != active.generation)
    except Exception:
      return False

  def _select_model(self, bundle):
    ui_state.params.put(_DOWNLOAD_INDEX_KEY, bundle.index)
    cb = self._show_reset_calibration_prompt if self._generation_changed(bundle) else lambda: None
    gui_app.pop_widgets_to(self, callback=cb)

  def _select_default(self):
    try:
      active = self.model_manager.activeBundle
      had_custom_model = bool(active and active.ref and not is_default_bundle(active))
    except Exception:
      had_custom_model = False

    select_default_model(ui_state.params)
    gui_app.pop_widgets_to(self, callback=self._show_reset_calibration_prompt if had_custom_model else (lambda: None))

  def _show_reset_calibration_prompt(self):
    def _reset():
      ui_state.params.remove("CalibrationParams")
      ui_state.params.remove("LiveTorqueParameters")
    gui_app.push_widget(BigConfirmationDialog("slide to\nreset calibration", self._reset_icon, _reset))

  def _update_state(self):
    super()._update_state()

    self._handle_bundle_download_progress()
    self._current.set_value(self._current_model_value())
    self._current.set_enabled(ui_state.is_offroad())
    target = self._redownload_target_bundle()
    self._redownload.set_value(_display_model_name(target) if target else "")

    now = time.monotonic()
    if now - self._last_cache_t > 1.0:
      self._last_cache_t = now
      self._clear.set_value(f"{self._calculate_cache_size():.1f} MB")

    self._update_lagd_subtext()

  def _progress_target_bundle(self):
    try:
      selected = self.model_manager.selectedBundle
      active = self.model_manager.activeBundle
    except Exception:
      return None

    if selected and (selected.status == _DL.downloading or selected.status == _DL.failed):
      return selected
    return active if self._has_active_bundle_param() else None

  def _handle_bundle_download_progress(self):
    labels = {
      custom.IQModelManager.Model.Type.supercombo: self._supercombo,
      custom.IQModelManager.Model.Type.vision: self._vision,
      custom.IQModelManager.Model.Type.policy: self._policy,
    }
    for label in labels.values():
      label.set_visible(False)
      label.set_value("")

    self._cancel.set_visible(False)

    bundle = self._progress_target_bundle()
    if not bundle:
      self._download_status = None
      self._prev_download_status = None
      return

    self._download_status = bundle.status
    status_changed = self._download_status != self._prev_download_status
    self._prev_download_status = self._download_status

    self._cancel.set_visible(bool(getattr(self.model_manager, "selectedBundle", None)) and self._has_download_request())

    if self._download_status not in (_DL.downloading, _DL.failed):
      return

    if self._download_status == _DL.downloading:
      try:
        from openpilot.selfdrive.ui.ui_state import device
        device._reset_interactive_timeout()
      except Exception:
        pass

    for model in bundle.models:
      label = labels.get(getattr(model.type, "raw", model.type))
      if label is None:
        continue
      label.set_visible(True)
      label.set_value(self._download_label_text(bundle, model, status_changed))

  def _download_label_text(self, bundle, model, status_changed: bool) -> str:
    p = model.artifact.downloadProgress
    if p.status == _DL.downloading:
      return f"{int(p.progress)}% downloading {_display_model_name(bundle)}"
    if p.status in (_DL.downloaded, _DL.cached):
      if self._download_status == _DL.downloading:
        return f"{_display_model_name(bundle)} ready"
      return f"{_display_model_name(bundle)} {'downloaded' if status_changed else 'ready'}"
    if p.status == _DL.failed:
      return f"download failed {_display_model_name(bundle)}"
    return f"pending {_display_model_name(bundle)}"

  def _current_model_value(self) -> str:
    bundle = self._progress_target_bundle()
    if not bundle:
      return self._active_model_name()

    if self._download_status == _DL.downloading:
      return self._download_progress_text(bundle)
    if self._download_status == _DL.failed:
      return f"failed: {_display_model_name(bundle)}"
    return self._active_model_name()

  def _update_lagd_subtext(self):
    if self._lagd._checked:
      try:
        self._lagd.set_value(f"live {ui_state.sm['liveDelay'].lateralDelay:.3f} s")
      except Exception:
        self._lagd.set_value("")
      return
    try:
      sw = float(ui_state.params.get("LagdToggleDelay", return_default=True))
    except (TypeError, ValueError):
      sw = 0.2
    if ui_state.CP is not None:
      self._lagd.set_value(f"total {ui_state.CP.steerActuatorDelay + sw:.2f} s")
    else:
      self._lagd.set_value(f"+{sw:.2f} s software")

  def _active_model_name(self) -> str:
    if not self._has_active_bundle_param():
      return "Default (CD210)"

    try:
      active = self.model_manager.activeBundle
      if is_default_bundle(active):
        return active.displayName or "Default (CD210)"
      if active and active.ref:
        return _display_model_name(active)
    except Exception:
      pass
    return "Default (CD210)"

  def _download_progress_text(self, bundle=None) -> str:
    bundle = bundle or getattr(self.model_manager, "selectedBundle", None)
    if not bundle:
      return "downloading..."
    try:
      parts = []
      for model in bundle.models:
        p = model.artifact.downloadProgress
        if p.status == _DL.downloading:
          parts.append(f"{int(p.progress)}%")
        elif p.status in (_DL.downloaded, _DL.cached):
          parts.append("ready")
        elif p.status == _DL.failed:
          parts.append("failed")
      return f"{_display_model_name(bundle)} {' '.join(parts)}".strip() or "downloading..."
    except Exception:
      return "downloading..."

  def show_event(self):
    super().show_event()
    for w in (self._lagd, self._sw_delay, self._lane_turn, self._lane_speed):
      w.refresh()
