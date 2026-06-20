"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Software / update settings for MICI (comma 4).
"""
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton, NeonBigParamToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialogV2, BigMultiOptionDialog
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import Scroller

RELEASE_BRANCHES = ["release3-staging", "release3", "nightly", "nightly-dev"]
MICI_BRANCHES    = ["master-mici", "master-mici-staging"]


class SoftwareLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()

    # Info labels (read-only display at the top)
    self._branch_label = UnifiedLabel(
      self._get_branch_text(), 30, FontWeight.ROMAN,
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
    )
    self._version_label = UnifiedLabel(
      self._get_version_text(), 26, FontWeight.ROMAN,
      rl.Color(180, 180, 180, 200),
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
    )

    # Disable Updates — destructive action so uses NeonBigParamToggle
    self._disable_updates = NeonBigParamToggle(
      "Disable Updates", "DisableUpdates",
      toggle_callback=self._on_disable_updates_toggled,
    )

    # Change Branch — navigation action uses NeonBigButton
    self._change_branch_btn = NeonBigButton("change branch →")
    self._change_branch_btn.set_click_callback(self._open_branch_dialog)

    self._scroller = Scroller(
      [self._disable_updates, self._change_branch_btn],
      snap_items=False,
    )

    if back_callback:
      self.set_back_callback(back_callback)

  # ── Helpers ────────────────────────────────────────────────────────────────

  def _get_branch_text(self) -> str:
    return f"branch: {self._params.get('GitBranch') or 'unknown'}"

  def _get_version_text(self) -> str:
    v = self._params.get("UpdaterCurrentDescription") or self._params.get("Version") or "unknown"
    return v[:40]

  def _get_branches(self) -> list[str]:
    device = HARDWARE.get_device_type()
    branches = list(RELEASE_BRANCHES)
    if device == "mici":
      branches = MICI_BRANCHES + branches
    return branches

  # ── Callbacks ──────────────────────────────────────────────────────────────

  def _on_disable_updates_toggled(self, checked: bool):
    if checked:
      dlg = BigConfirmationDialogV2(
        "Disable updates?",
        "icons_mici/settings/device/update.png",
        red=True,
        confirm_callback=lambda: None,
      )
      gui_app.set_modal_overlay(dlg)

  def _open_branch_dialog(self):
    branches = self._get_branches()
    current_branch = self._params.get("GitBranch") or ""

    def on_confirm():
      selected = dlg.get_selected_option()
      if selected and selected != current_branch:
        self._params.put_nonblocking("SwitchToBranch", selected)
        self._branch_label.set_text(f"branch: {selected} (pending reboot)")

    dlg = BigMultiOptionDialog(
      options=branches,
      default=current_branch if current_branch in branches else None,
      right_btn="check",
      right_btn_callback=on_confirm,
    )
    gui_app.set_modal_overlay(dlg)

  # ── Lifecycle ──────────────────────────────────────────────────────────────

  def show_event(self):
    super().show_event()
    self._disable_updates.refresh()
    self._branch_label.set_text(self._get_branch_text())
    self._version_label.set_text(self._get_version_text())
    self._scroller.show_event()

  def _render(self, rect: rl.Rectangle):
    info_h = 70
    self._branch_label.render(rl.Rectangle(rect.x + 16, rect.y + 8, rect.width - 32, 32))
    self._version_label.render(rl.Rectangle(rect.x + 16, rect.y + 40, rect.width - 32, 28))
    self._scroller.render(rl.Rectangle(rect.x, rect.y + info_h, rect.width, rect.height - info_h))
