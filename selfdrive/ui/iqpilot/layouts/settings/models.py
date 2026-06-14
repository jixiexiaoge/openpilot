"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os
import re
import time
import pyray as rl

from cereal import custom
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog, ConfirmDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.toggle import ON_COLOR

from openpilot.iqpilot.models.runners.constants import CUSTOM_MODEL_PATH
from openpilot.iqpilot.models.helpers import get_default_model_bundle
from openpilot.system.ui.iqpilot.lib.styles import style
from openpilot.system.ui.iqpilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem, toggle_item, option_item
from openpilot.system.ui.iqpilot.widgets.progress_bar import progress_item
from openpilot.system.ui.iqpilot.widgets.tree_dialog import TreeOptionDialog, TreeNode, TreeFolder

if gui_app.iqpilot_ui():
  from openpilot.system.ui.iqpilot.widgets.list_view import button_item as button_item


class ModelsLayout(Widget):
  def __init__(self):
    super().__init__()
    self.model_manager = None
    self.download_status = None
    self.prev_download_status = None
    self.model_dialog = None
    self.last_cache_calc_time = 0

    self._initialize_items()

    self.clear_cache_item.action_item.set_value(f"{self._calculate_cache_size():.2f} MB")
    for ctrl, key in [(self.lane_turn_value_control, "LaneTurnValue"), (self.delay_control, "LagdToggleDelay")]:
      ctrl.action_item.set_value(int(float(ui_state.params.get(key, return_default=True)) * 100))

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

    self.refresh_item = button_item(tr("Refresh Model List"), tr("REFRESH"), "",
                                    lambda: (ui_state.params.put("ModelManager_LastSyncTime", 0),
                                             gui_app.set_modal_overlay(alert_dialog(tr("Fetching Latest Models")))))

    self.clear_cache_item = IQListItem(
      title=tr("Clear Model Cache"),
      description="",
      action_item=NoElideButtonAction(tr("CLEAR")),
      callback=self._clear_cache
    )

    self.cancel_download_item = button_item(tr("Cancel Download"), tr("Cancel"), "", lambda: ui_state.params.remove("ModelManager_DownloadIndex"))

    self.lane_turn_value_control = option_item(tr("Adjust Lane Turn Desire Speed"), "LaneTurnValue", 500, 2000,
                                                  tr("Sets the speed threshold used by Lane Turn Desires. Below this value, turn desires can plan into the nearest drivable turn path. Default is 19 mph."),
                                                  int(round(100 / CV.MPH_TO_KPH)), None, True, "", style.BUTTON_ACTION_WIDTH, None, True,
                                                  lambda v: f"{int(round(v * (CV.MPH_TO_KPH if ui_state.is_metric else 1)))}" +
                                                            f" {'km/h' if ui_state.is_metric else 'mph'}")

    self.lane_turn_desire_toggle = toggle_item(tr("Use Lane Turn Desires"),
                                                  tr("If you're driving at 20 mph (32 km/h) or below and have your blinker on," +
                                                     " the car will plan a turn in that direction at the nearest drivable path. " +
                                                     "This prevents situations (like at red lights) where the car might plan the wrong turn direction."),
                                                  param="LaneTurnDesire")

    self.delay_control = option_item(tr("Adjust Software Delay"), "LagdToggleDelay", 5, 50,
                                        tr("Adjust the fixed software delay added to steer actuator delay when Live Learning Steer Delay is turned off. The default software delay value is 0.2 s."),
                                        1, None, True, "", style.BUTTON_ACTION_WIDTH, None, True, lambda v: f"{float(v):.2f}s")

    self.lagd_toggle = toggle_item(tr("Live Learning Steer Delay"), "", param="LagdToggle")

    self.items = [self.current_model_item, self.cancel_download_item, self.supercombo_label, self.vision_label,
                  self.policy_label, self.refresh_item, self.clear_cache_item, self.lane_turn_desire_toggle,
                  self.lane_turn_value_control, self.lagd_toggle, self.delay_control]

  def _update_lagd_description(self, lagd_toggle: bool):
    desc = tr("Enable this for the car to learn and adapt its steering response time. Disable to use a fixed steering response time. " +
              "Keeping this on provides the stock openpilot experience.")
    if lagd_toggle:
      desc += f"<br>{tr('Live Steer Delay:')} {ui_state.sm['liveDelay'].lateralDelay:.3f} s"
    elif ui_state.CP:
      sw = float(ui_state.params.get("LagdToggleDelay", "0.2"))
      cp = ui_state.CP.steerActuatorDelay
      desc += f"<br>{tr('Actuator Delay:')} {cp:.2f} s + {tr('Software Delay:')} {sw:.2f} s = {tr('Total Delay:')} {cp + sw:.2f} s"
    self.lagd_toggle.set_description(desc)

  def _is_downloading(self):
    return (self.model_manager and self.model_manager.selectedBundle and
            self.model_manager.selectedBundle.status == custom.IQModelManager.DownloadStatus.downloading)

  @staticmethod
  def _has_download_request() -> bool:
    try:
      return int(ui_state.params.get("ModelManager_DownloadIndex")) >= 0
    except (TypeError, ValueError):
      return False

  @staticmethod
  def _calculate_cache_size():
    cache_size = 0.0
    if os.path.exists(CUSTOM_MODEL_PATH):
      cache_size = sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, file)) for file in os.listdir(CUSTOM_MODEL_PATH)) / (1024**2)
    return cache_size

  def _clear_cache(self):
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.put_bool("ModelManager_ClearCache", True)
        self.clear_cache_item.action_item.set_value(f"{self._calculate_cache_size():.2f} MB")

    gui_app.set_modal_overlay(ConfirmDialog(tr("This will delete ALL downloaded models from the cache except the currently active model. Are you sure?"),
                                            tr("Clear Cache")), callback=_callback)

  def _handle_bundle_download_progress(self):
    labels = {custom.IQModelManager.Model.Type.supercombo: self.supercombo_label,
              custom.IQModelManager.Model.Type.vision: self.vision_label,
              custom.IQModelManager.Model.Type.policy: self.policy_label}
    for label in labels.values():
      label.set_visible(False)
    self.cancel_download_item.set_visible(False)

    if not self.model_manager or (not self.model_manager.selectedBundle and not self.model_manager.activeBundle):
      return

    bundle = self.model_manager.selectedBundle if self._is_downloading() or (
      self.model_manager.selectedBundle and self.model_manager.selectedBundle.status == custom.IQModelManager.DownloadStatus.failed
    ) else self.model_manager.activeBundle
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

    for model in bundle.models:
      if label := labels.get(getattr(model.type, 'raw', model.type)):
        label.set_visible(True)
        p = model.artifact.downloadProgress
        text, show, color = f"pending - {bundle.displayName}", False, rl.GRAY
        if p.status == custom.IQModelManager.DownloadStatus.downloading:
          text, show = f"{int(p.progress)}% - {bundle.displayName}", True
        elif p.status in (custom.IQModelManager.DownloadStatus.downloaded, custom.IQModelManager.DownloadStatus.cached):
          status_text = tr("from cache" if p.status == custom.IQModelManager.DownloadStatus.cached else "downloaded")
          text, color = f"{bundle.displayName} - {status_text if status_changed else tr('ready')}", ON_COLOR
        elif p.status == custom.IQModelManager.DownloadStatus.failed:
          text, color = f"download failed - {bundle.displayName}", rl.RED
        label.action_item.update(p.progress, text, show, color)

  @staticmethod
  def _show_reset_params_dialog():
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.remove("CalibrationParams")
        ui_state.params.remove("LiveTorqueParameters")
    msg = tr("Model download has started in the background. We suggest resetting calibration. Would you like to do that now?")
    gui_app.set_modal_overlay(ConfirmDialog(msg, tr("Reset Calibration")), callback=_callback)

  def _on_model_selected(self, result):
    if result != DialogResult.CONFIRM:
      return
    selected_ref = self.model_dialog.selection_ref
    if selected_ref == "Default":
      default_bundle = get_default_model_bundle(self.model_manager.availableBundles)
      if default_bundle:
        ui_state.params.put("ModelManager_DownloadIndex", default_bundle.index)
      self._show_reset_params_dialog()
    elif selected_bundle := next((bundle for bundle in self.model_manager.availableBundles if bundle.ref == selected_ref), None):
      ui_state.params.put("ModelManager_DownloadIndex", selected_bundle.index)
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

    folders_list = [TreeFolder("", [TreeNode("Default", {'display_name': tr("Default Model"), 'short_name': "Default"})])]
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

    active_ref = self.model_manager.activeBundle.ref if self.model_manager.activeBundle else "Default"
    self.model_dialog = TreeOptionDialog(tr("Select a Model"), folders_list, active_ref, "ModelManager_Favs",
                                         get_folders_fn=self._get_folders, on_exit=self._on_model_selected)
    gui_app.set_modal_overlay(self.model_dialog, callback=self._on_model_selected)

  def _update_state(self):
    turn_desire: bool = ui_state.params.get_bool("LaneTurnDesire")
    live_delay: bool = ui_state.params.get_bool("LagdToggle")

    self.lane_turn_desire_toggle.action_item.set_state(turn_desire)
    self.lane_turn_value_control.set_visible(turn_desire)
    self.lagd_toggle.action_item.set_state(live_delay)
    self.delay_control.set_visible(not live_delay)
    new_step = int(round(100 / CV.MPH_TO_KPH)) if ui_state.is_metric else 100
    if self.lane_turn_value_control.action_item.value_change_step != new_step:
      self.lane_turn_value_control.action_item.value_change_step = new_step

    self._update_lagd_description(live_delay)
    self.model_manager = ui_state.sm["iqModelManager"]
    self._handle_bundle_download_progress()
    active_name = self.model_manager.activeBundle.internalName if self.model_manager and self.model_manager.activeBundle.ref else tr("Default Model")
    self.current_model_item.action_item.set_value(active_name)

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
