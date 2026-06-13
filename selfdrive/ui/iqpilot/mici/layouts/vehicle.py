"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Vehicle settings for MICI (comma 4).
Allows force-fingerprinting a vehicle and shows brand-specific toggles.
"""
import json
import os
import unicodedata
from collections.abc import Callable

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton, NeonBigParamToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigMultiOptionDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import NavWidget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import Scroller

CAR_LIST_JSON = os.path.join(BASEDIR, "opendbc", "iqpilot", "car", "car_list.json")


def _ascii_safe(text: str) -> str:
  return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")

_COLOR_GREEN  = rl.Color(0,   195, 111, 255)   # auto-fingerprinted
_COLOR_BLUE   = rl.Color(49,  152, 255, 255)   # manually selected
_COLOR_YELLOW = rl.Color(255, 200,  50, 255)   # unrecognized


def _load_platforms() -> dict:
  try:
    with open(CAR_LIST_JSON) as f:
      return json.load(f)
  except Exception:
    return {}


class VehicleLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable | None = None):
    super().__init__()
    self._params = Params()
    self._platforms = _load_platforms()
    self._current_brand = None
    self._vehicle_btn = NeonBigButton("select vehicle")
    self._vehicle_btn.set_click_callback(self._on_vehicle_btn_clicked)
    self._status_label = UnifiedLabel(
      "", 26, FontWeight.ROMAN,
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
    )
    self._toyota_stock_long = NeonBigParamToggle(
      "Enforce Factory Long.", "ToyotaEnforceStockLongitudinal",
      toggle_callback=self._on_toyota_stock_long_toggled,
    )
    self._hyundai_tuning = NeonBigButton("hyundai long. tuning")
    self._hyundai_tuning.set_click_callback(self._open_hyundai_tuning)
    self._subaru_snag   = NeonBigParamToggle("Stop and Go (Beta)",              "SubaruStopAndGo")
    self._subaru_manual = NeonBigParamToggle("Stop and Go Manual Parking Brake", "SubaruStopAndGoManualParkingBrake")
    self._vw_pq_hca  = NeonBigParamToggle("PQ HCA Status 7 Mode",              "pqhca5or7Toggle")
    self._vw_lateral = NeonBigParamToggle("Lateral When Cruise Faulted",       "AllowLateralWhenLongUnavailable")
    self._tesla_vtb  = NeonBigParamToggle("VTB (Virtual Torque Blending)",     "TeslaCoopSteering")
    self._brand_items: dict[str, list] = {
      "toyota":     [self._toyota_stock_long],
      "hyundai":    [self._hyundai_tuning],
      "subaru":     [self._subaru_snag, self._subaru_manual],
      "volkswagen": [self._vw_pq_hca, self._vw_lateral],
      "tesla":      [self._tesla_vtb],
    }

    self._scroller = Scroller([self._vehicle_btn], snap_items=False)

    if back_callback:
      self.set_back_callback(back_callback)
  def _get_fingerprint_info(self) -> tuple[str, rl.Color]:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      return bundle.get("name", "?"), _COLOR_BLUE
    if ui_state.CP and ui_state.CP.carFingerprint not in ("", "MOCK"):
      return ui_state.CP.carFingerprint, _COLOR_GREEN
    return tr("No vehicle selected"), _COLOR_YELLOW
  def _get_current_brand(self) -> str:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      return bundle.get("brand", "")
    if ui_state.CP:
      return getattr(ui_state.CP, "brand", "")
    return ""

  def _on_vehicle_btn_clicked(self):
    if ui_state.params.get("CarPlatformBundle"):
      ui_state.params.remove("CarPlatformBundle")
      self._rebuild_scroller()
    else:
      self._show_make_picker()

  def _show_make_picker(self):
    raw_makes = sorted({v.get("make", "") for v in self._platforms.values() if v.get("make")})
    label_to_make = {_ascii_safe(m): m for m in raw_makes}
    labels = list(label_to_make.keys())

    dlg_ref: list = []

    def _on_confirmed():
      label = dlg_ref[0].get_selected_option()
      self._show_model_picker(label_to_make.get(label, label))

    dlg = BigMultiOptionDialog(labels, default=None, right_btn="check",
                               right_btn_callback=_on_confirmed)
    dlg_ref.append(dlg)
    gui_app.set_modal_overlay(dlg)

  def _show_model_picker(self, make: str):
    full_keys = sorted(
      p for p, v in self._platforms.items()
      if v.get("make") == make
    )
    if not full_keys:
      return
    make_prefix = make + " "
    def _strip_make(key: str) -> str:
      stripped = key[len(make_prefix):] if key.lower().startswith(make_prefix.lower()) else key
      return _ascii_safe(stripped)
    label_to_key = {_strip_make(k): k for k in full_keys}
    labels = list(label_to_key.keys())

    dlg_ref: list = []

    def _on_confirmed():
      label = dlg_ref[0].get_selected_option()
      platform_name = label_to_key.get(label, label)
      if data := self._platforms.get(platform_name):
        ui_state.params.put("CarPlatformBundle", {**data, "name": platform_name})
        self._rebuild_scroller()

    dlg = BigMultiOptionDialog(labels, default=None, right_btn="check",
                               right_btn_callback=_on_confirmed)
    dlg_ref.append(dlg)
    gui_app.set_modal_overlay(dlg)


  def _on_toyota_stock_long_toggled(self, checked: bool):
    if checked:
      if ui_state.params.get_bool("AlphaLongitudinalEnabled"):
        ui_state.params.put_bool("AlphaLongitudinalEnabled", False)
      ui_state.params.put_bool("OnroadCycleRequested", True)
    else:
      ui_state.params.put_bool("OnroadCycleRequested", True)

  def _open_hyundai_tuning(self):
    options = ["off", "dynamic", "predictive"]
    try:
      cur_idx = int(self._params.get("HyundaiLongitudinalTuning") or "0")
      cur = options[min(cur_idx, len(options) - 1)]
    except (TypeError, ValueError):
      cur = options[0]

    dlg_ref: list = []

    def _on_confirmed():
      sel = dlg_ref[0].get_selected_option()
      if sel in options:
        self._params.put_nonblocking("HyundaiLongitudinalTuning", options.index(sel))

    dlg = BigMultiOptionDialog(options, default=cur, right_btn="check",
                               right_btn_callback=_on_confirmed)
    dlg_ref.append(dlg)
    gui_app.set_modal_overlay(dlg)

  def _rebuild_scroller(self):
    brand = self._get_current_brand()
    fp_name, fp_color = self._get_fingerprint_info()

    safe_name = _ascii_safe(fp_name)
    chip_name = safe_name
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      make = bundle.get("make", "")
      if make:
        safe_make = _ascii_safe(make)
        if chip_name.lower().startswith(safe_make.lower() + " "):
          chip_name = chip_name[len(safe_make) + 1:]
    if bundle:
      self._vehicle_btn.set_chips([chip_name, "tap to clear"])
    else:
      self._vehicle_btn.set_chips([chip_name])

    self._status_label.set_text(f"fingerprint: {safe_name}")

    brand_widgets = self._brand_items.get(brand, [])

    for w in brand_widgets:
      if hasattr(w, "refresh"):
        w.refresh()
    offroad = ui_state.is_offroad()
    self._toyota_stock_long.set_enabled(offroad)
    self._subaru_snag.set_enabled(offroad)
    self._subaru_manual.set_enabled(offroad)
    is_pq = self._is_vw_pq()
    self._vw_pq_hca.set_visible(is_pq)
    self._vw_lateral.set_visible(is_pq)
    self._tesla_vtb.set_enabled(offroad)
    long_enabled = ui_state.has_longitudinal_control if hasattr(ui_state, "has_longitudinal_control") else False
    self._hyundai_tuning.set_enabled(offroad and long_enabled)
    new_items = [self._vehicle_btn] + brand_widgets
    self._scroller._items = new_items
    self._current_brand = brand

  def _is_vw_pq(self) -> bool:
    try:
      from opendbc.car.volkswagen.values import CAR, VolkswagenFlags
      bundle = ui_state.params.get("CarPlatformBundle")
      if bundle:
        platform = bundle.get("platform")
        if platform:
          return bool(CAR[platform].config.flags & VolkswagenFlags.PQ)
      if ui_state.CP:
        return bool(ui_state.CP.flags & VolkswagenFlags.PQ)
    except Exception:
      pass
    return False
  def show_event(self):
    super().show_event()
    self._rebuild_scroller()
    self._scroller.show_event()

  def _update_state(self):
    super()._update_state()
    brand = self._get_current_brand()
    if brand != self._current_brand:
      self._rebuild_scroller()

  def _render(self, rect: rl.Rectangle):
    # Draw status label at top (small, 24px tall)
    label_h = 28
    label_rect = rl.Rectangle(rect.x + 12, rect.y + 4, rect.width - 24, label_h)
    self._status_label.render(label_rect)

    # Scroller below
    scroll_rect = rl.Rectangle(rect.x, rect.y + label_h + 6, rect.width, rect.height - label_h - 6)
    self._scroller.render(scroll_rect)
