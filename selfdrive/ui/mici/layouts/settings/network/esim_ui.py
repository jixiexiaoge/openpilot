from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.system.hardware.base import Profile
from openpilot.system.hardware.tici.esim_manager import EsimManager, EsimUiState, get_esim_manager
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult, NavWidget
from openpilot.system.ui.widgets.esim_scanner import EsimQrScannerDialog
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigInputDialog, BigMultiOptionDialog, BigConfirmationDialogV2
from openpilot.system.ui.widgets.scroller import Scroller


class EsimUIMici(NavWidget):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self._manager: EsimManager = get_esim_manager()
    self._state = EsimUiState()
    self._callback_registered = False
    self._scroller = Scroller([], snap_items=False)
    self._rebuild_scroller()
    self.set_back_callback(back_callback)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    if not self._callback_registered:
      self._manager.add_callback(self._on_state_update)
      self._callback_registered = True
    self._manager.refresh_profiles()

  def hide_event(self):
    super().hide_event()
    if self._callback_registered:
      self._manager.remove_callback(self._on_state_update)
      self._callback_registered = False

  def _is_busy(self) -> bool:
    return self._state.busy

  def _status_text(self) -> str:
    if self._state.message:
      return self._state.message
    return self._state.state.value

  def _on_state_update(self, state: EsimUiState):
    self._state = state
    self._rebuild_scroller()

  def _show_choice_dialog(self, title: str, options: list[str], callback: Callable[[str], None]) -> None:
    if not options:
      return
    dlg = BigMultiOptionDialog(
      options,
      options[0],
      right_btn="check",
      right_btn_callback=lambda: callback(dlg.get_selected_option()),
    )
    gui_app.set_modal_overlay(dlg)

  def _rebuild_scroller(self):
    widgets = []

    status_btn = NeonBigButton("status", chips=[self._status_text()])
    status_btn.set_enabled(False)
    widgets.append(status_btn)

    refresh_btn = NeonBigButton("refresh profiles")
    refresh_btn.set_enabled(lambda: not self._is_busy())
    refresh_btn.set_click_callback(lambda: self._manager.refresh_profiles())
    widgets.append(refresh_btn)

    add_btn = NeonBigButton("add profile", chips=["scan qr / enter code"])
    add_btn.set_enabled(lambda: not self._is_busy())
    add_btn.set_click_callback(self._on_add_profile)
    widgets.append(add_btn)

    profiles = self._state.profiles or []
    for p in profiles:
      widgets.append(self._make_profile_button(p))

    self._scroller = Scroller(widgets, snap_items=False)

  def _make_profile_button(self, profile: Profile) -> NeonBigButton:
    title = profile.nickname if profile.nickname else profile.iccid
    value = f"{profile.provider or 'provider unknown'}{'  •  active' if profile.enabled else ''}"
    btn = NeonBigButton(title, chips=[value])
    btn.set_enabled(lambda: not self._is_busy())
    btn.set_click_callback(lambda profile=profile: self._on_profile_selected(profile))
    return btn

  def _on_add_profile(self):
    options = ["scan qr", "enter code"]

    def _selected(option: str):
      if option == "scan qr":
        self._scan_qr()
      elif option == "enter code":
        self._manual_entry()

    self._show_choice_dialog("add esim profile", options, _selected)

  def _scan_qr(self):
    scanner = EsimQrScannerDialog()
    self._manager.set_scanning_state(True)

    def _done(result: int):
      self._manager.set_scanning_state(False)
      if result != DialogResult.CONFIRM or not scanner.code:
        return
      self._prompt_nickname_and_add(scanner.code)

    gui_app.set_modal_overlay(scanner, _done)

  def _manual_entry(self):
    dlg = BigInputDialog("enter LPA activation code...", "", minimum_length=1,
                         confirm_callback=lambda code: self._prompt_nickname_and_add(code.strip()) if code.strip() else None)
    gui_app.set_modal_overlay(dlg)

  def _prompt_nickname_and_add(self, code: str):
    dlg = BigInputDialog("optional nickname...", "", minimum_length=0,
                         confirm_callback=lambda nickname: self._manager.add_profile(code, nickname.strip() or None))
    gui_app.set_modal_overlay(dlg)

  def _on_profile_selected(self, profile: Profile):
    options = []
    if not profile.enabled:
      options.append("activate")
    options.append("rename")
    if self._manager.is_comma_profile(profile.iccid):
      options.append("remove comma psim")
    elif not profile.enabled:
      options.append("delete")

    def _selected(option: str):
      if option == "activate":
        self._manager.switch_profile(profile.iccid)
      elif option == "rename":
        self._rename_profile(profile)
      elif option == "remove comma psim":
        self._remove_comma_profile()
      elif option == "delete":
        self._manager.delete_profile(profile.iccid)

    self._show_choice_dialog("profile actions", options, _selected)

  def _rename_profile(self, profile: Profile):
    dlg = BigInputDialog("rename profile...", profile.nickname or "", minimum_length=1,
                         confirm_callback=lambda nickname: self._manager.rename_profile(profile.iccid, nickname.strip()) if nickname.strip() else None)
    gui_app.set_modal_overlay(dlg)

  def _remove_comma_profile(self):
    dlg = BigDialog(
      "Warning",
      "This will permanently wipe the Comma pSIM profile from the SIM.",
      right_btn="check",
      right_btn_callback=self._remove_comma_profile_final_warning,
    )
    gui_app.set_modal_overlay(dlg)

  def _remove_comma_profile_final_warning(self):
    dlg = BigDialog(
      "Final Warning",
      "You must use your own eSIM profile after this. You cannot use Comma Prime again unless you buy a new SIM from comma.",
      right_btn="check",
      right_btn_callback=self._confirm_remove_comma_profile,
    )
    gui_app.set_modal_overlay(dlg)

  def _confirm_remove_comma_profile(self):
    dlg = BigConfirmationDialogV2(
      "slide to remove\ncomma psim",
      "icons_mici/settings/network/new/trash.png",
      red=True,
      confirm_callback=self._manager.bootstrap,
    )
    gui_app.set_modal_overlay(dlg)

  def _render(self, rect: rl.Rectangle):
    if not self._manager.is_supported():
      from openpilot.system.ui.widgets.label import gui_label
      gui_label(rect, "Insert the original comma SIM card that came with the device to use eSIM", 48, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
      return
    self._scroller.render(rect)
