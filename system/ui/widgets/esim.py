from __future__ import annotations

import pyray as rl

from openpilot.system.hardware.base import Profile
from openpilot.system.hardware.tici.esim_manager import EsimManager, EsimOperationState, EsimUiState, get_esim_manager
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import ListItem, button_item, text_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.esim_scanner import EsimQrScannerDialog


class EsimPanel(Widget):
  def __init__(self):
    super().__init__()
    self._manager: EsimManager = get_esim_manager()
    self._state = EsimUiState()
    self._keyboard = Keyboard(max_text_size=256, min_text_size=0)
    self._callback_registered = False
    self._scroller = Scroller([])
    self._rebuild_scroller()

  def show_event(self):
    if not self._callback_registered:
      self._manager.add_callback(self._on_state_update)
      self._callback_registered = True
    self._manager.refresh_profiles()

  def hide_event(self):
    if self._callback_registered:
      self._manager.remove_callback(self._on_state_update)
      self._callback_registered = False

  def _is_busy(self) -> bool:
    return self._state.busy

  def is_supported(self) -> bool:
    return self._manager.is_supported()

  def _on_state_update(self, state: EsimUiState):
    self._state = state
    self._rebuild_scroller()

  def _state_text(self) -> str:
    if self._state.message:
      return self._state.message
    return self._state.state.value

  def _rebuild_scroller(self):
    items: list[Widget] = [
      text_item(lambda: tr("Status"), lambda: self._state_text()),
      button_item(
        lambda: tr("Refresh Profiles"),
        lambda: tr("REFRESH"),
        callback=self._on_refresh,
        enabled=lambda: not self._is_busy(),
      ),
      button_item(
        lambda: tr("Add Profile"),
        lambda: tr("ADD"),
        description=lambda: tr("Scan QR or enter activation code"),
        callback=self._on_add_profile,
        enabled=lambda: not self._is_busy(),
      ),
    ]

    profiles = self._state.profiles or []
    for profile in profiles:
      items.append(self._make_profile_item(profile))

    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _make_profile_item(self, profile: Profile) -> ListItem:
    label = profile.nickname if profile.nickname else profile.iccid
    provider = profile.provider if profile.provider else tr("Unknown provider")
    description = f"{provider}\n{profile.iccid}"
    action = tr("ACTIVE") if profile.enabled else tr("USE")
    return button_item(
      lambda label=label: label,
      lambda action=action: action,
      description=lambda description=description: description,
      callback=lambda profile=profile: self._on_profile_selected(profile),
      enabled=lambda: not self._is_busy(),
    )

  def _on_refresh(self):
    self._manager.refresh_profiles()

  def _on_add_profile(self):
    options = [tr("Scan QR"), tr("Enter Code")]
    dialog = MultiOptionDialog(tr("Add eSIM Profile"), options, current="")
    dialog.selection = options[0]

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      if dialog.selection == options[0]:
        self._scan_qr()
      else:
        self._manual_code_entry()

    gui_app.set_modal_overlay(dialog, _done)

  def _scan_qr(self):
    scanner = EsimQrScannerDialog()
    self._manager.set_scanning_state(True)

    def _done(result: int):
      self._manager.set_scanning_state(False)
      if result != DialogResult.CONFIRM or not scanner.code:
        return
      self._confirm_add_code(scanner.code)

    gui_app.set_modal_overlay(scanner, _done)

  def _manual_code_entry(self):
    self._keyboard.reset(min_text_size=1)
    self._keyboard.set_title(tr("Enter Activation Code"), tr("format: LPA:1$...$..."))
    self._keyboard.clear()

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      code = self._keyboard.text.strip()
      if code:
        self._confirm_add_code(code)

    gui_app.set_modal_overlay(self._keyboard, _done)

  def _confirm_add_code(self, code: str):
    confirm = ConfirmDialog("", tr("Continue"), tr("Cancel"))
    code_preview = code if len(code) < 64 else (code[:61] + "...")
    confirm.set_text(tr("Use activation code:\n{}").format(code_preview))
    confirm.reset()

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      self._prompt_nickname_and_add(code)

    gui_app.set_modal_overlay(confirm, _done)

  def _prompt_nickname_and_add(self, code: str):
    self._keyboard.reset(min_text_size=0)
    self._keyboard.set_title(tr("Optional Nickname"), tr("leave blank to skip"))
    self._keyboard.clear()

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      nickname = self._keyboard.text.strip()
      self._manager.add_profile(code, nickname if nickname else None)

    gui_app.set_modal_overlay(self._keyboard, _done)

  def _on_profile_selected(self, profile: Profile):
    options = []
    if not profile.enabled:
      options.append(tr("Activate"))
    options.append(tr("Rename"))
    if self._manager.is_comma_profile(profile.iccid):
      options.append(tr("Remove Comma pSIM"))
    elif not profile.enabled:
      options.append(tr("Delete"))

    if len(options) == 0:
      return

    dialog = MultiOptionDialog(tr("Profile Actions"), options, current="")
    dialog.selection = options[0]

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      if dialog.selection == tr("Activate"):
        self._manager.switch_profile(profile.iccid)
      elif dialog.selection == tr("Rename"):
        self._rename_profile(profile)
      elif dialog.selection == tr("Remove Comma pSIM"):
        self._remove_comma_profile()
      elif dialog.selection == tr("Delete"):
        self._delete_profile(profile)

    gui_app.set_modal_overlay(dialog, _done)

  def _rename_profile(self, profile: Profile):
    self._keyboard.reset(min_text_size=1)
    self._keyboard.set_title(tr("Rename Profile"), "")
    self._keyboard.set_text(profile.nickname or "")

    def _done(result: int):
      if result != DialogResult.CONFIRM:
        return
      name = self._keyboard.text.strip()
      if name:
        self._manager.rename_profile(profile.iccid, name)

    gui_app.set_modal_overlay(self._keyboard, _done)

  def _delete_profile(self, profile: Profile):
    confirm = ConfirmDialog("", tr("Delete"), tr("Cancel"))
    confirm.set_text(tr("Delete disabled profile \"{}\"?").format(profile.nickname or profile.iccid))
    confirm.reset()

    def _done(result: int):
      if result == DialogResult.CONFIRM:
        self._manager.delete_profile(profile.iccid)

    gui_app.set_modal_overlay(confirm, _done)

  def _remove_comma_profile(self):
    confirm = ConfirmDialog("", tr("Continue"), tr("Cancel"))
    confirm.set_text(
      tr("This will permanently wipe the Comma pSIM profile from the SIM.")
    )
    confirm.reset()

    def _done(result: int):
      if result == DialogResult.CONFIRM:
        self._remove_comma_profile_final_warning()

    gui_app.set_modal_overlay(confirm, _done)

  def _remove_comma_profile_final_warning(self):
    confirm = ConfirmDialog("", tr("Remove"), tr("Cancel"))
    confirm.set_text(
      tr("After this, you must use your own eSIM profile.\n\nYou cannot use Comma Prime again unless you buy a new SIM from comma.")
    )
    confirm.reset()

    def _done(result: int):
      if result == DialogResult.CONFIRM:
        self._manager.bootstrap()

    gui_app.set_modal_overlay(confirm, _done)

  def _render(self, _):
    if not self.is_supported():
      from openpilot.system.ui.widgets.label import gui_label
      gui_label(self._rect, tr("Insert the original comma SIM card that came with the device to use eSIM"), 64, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
      return
    self._scroller.render(self._rect)
