"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import unicodedata

import pyray as rl

from openpilot.iqpilot.selfdrive.car.vehicle_catalog import load_catalog
from openpilot.selfdrive.ui.mici.widgets.stock_button import BigButton, BigParamControl
from openpilot.selfdrive.ui.mici.layouts.settings.iq_widgets import MappedParamToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller import NavScroller


def _ascii_safe(text: str) -> str:
  return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")


def _load_platforms() -> dict:
  try:
    return load_catalog()
  except Exception:
    return {}


class _PickerRow(Widget):
  HEIGHT = 92

  def __init__(self, label: str, on_tap):
    super().__init__()
    self._label = label
    self._on_tap = on_tap
    self.set_rect(rl.Rectangle(0, 0, gui_app.width, self.HEIGHT))
    self._font = gui_app.font(FontWeight.MEDIUM)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self._on_tap(self._label)

  def _render(self, _):
    color = rl.Color(255, 255, 255, 255) if self.is_pressed else rl.Color(255, 255, 255, 200)
    ts = measure_text_cached(self._font, self._label, 46)
    rl.draw_text_ex(self._font, self._label, rl.Vector2(self._rect.x + 44, self._rect.y + (self.HEIGHT - ts.y) / 2), 46, 0, color)


class _VerticalPicker(NavScroller):
  def __init__(self, options: list[str], on_pick):
    super().__init__(horizontal=False, snap_items=False, pad_start=20, pad_end=20)
    self._on_pick = on_pick
    rows = [_PickerRow(o, self._pick) for o in options]
    for row in rows:
      row.set_touch_valid_callback(lambda: self._scroller.scroll_panel.is_touch_valid())
    self._scroller.add_widgets(rows)

  def _pick(self, option: str):
    gui_app.pop_widget()
    self._on_pick(option)


class VehicleLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._platforms = _load_platforms()

    self._vehicle_btn = BigButton("vehicle")
    self._vehicle_btn.set_click_callback(self._on_vehicle_clicked)

    self._toyota_long = BigParamControl("enforce factory long.", "ToyotaEnforceStockLongitudinal",
                                        toggle_callback=self._on_toyota_long)
    self._hyundai_tuning = MappedParamToggle("hyundai long. tuning", "HyundaiLongitudinalTuning",
                                             ["off", "dynamic", "predictive"], [0, 1, 2])
    self._subaru_snag = BigParamControl("stop and go (beta)", "SubaruStopAndGo")
    self._subaru_manual = BigParamControl("stop and go manual brake", "SubaruStopAndGoManualParkingBrake")
    self._vw_pq_hca = BigParamControl("PQ HCA status 7 mode", "pqhca5or7Toggle")
    self._vw_lateral = BigParamControl("lateral when cruise faulted", "AllowLateralWhenLongUnavailable")
    self._vw_mqb_acc_resume = BigParamControl("MQB ACC resume", "iqMqbAccResume")
    self._vw_mqb_steering_lockout = BigParamControl("MQB steering lockout", "iqMqbSteeringLockout")
    self._tesla_vtb = BigParamControl("virtual torque blending", "TeslaCoopSteering")

    self._brand_widgets = {
      "toyota": [self._toyota_long],
      "hyundai": [self._hyundai_tuning],
      "subaru": [self._subaru_snag, self._subaru_manual],
      "volkswagen": [self._vw_pq_hca, self._vw_lateral, self._vw_mqb_acc_resume, self._vw_mqb_steering_lockout],
      "tesla": [self._tesla_vtb],
    }
    self._all_brand_widgets = [w for ws in self._brand_widgets.values() for w in ws]

    self._scroller.add_widgets([self._vehicle_btn] + self._all_brand_widgets)

  def _get_current_brand(self) -> str:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      return bundle.get("brand", "")
    if ui_state.CP:
      return getattr(ui_state.CP, "brand", "")
    return ""

  def _vw_flags(self):
    try:
      from iqdbc.car.volkswagen.values import CAR
      bundle = ui_state.params.get("CarPlatformBundle")
      if bundle and (platform := bundle.get("platform")):
        return CAR[platform].config.flags
      if ui_state.CP:
        return ui_state.CP.flags
    except Exception:
      pass
    return 0

  def _is_vw_pq(self) -> bool:
    from iqdbc.car.volkswagen.values import VolkswagenFlags
    return bool(self._vw_flags() & VolkswagenFlags.PQ)

  def _is_vw_mqb(self) -> bool:
    from iqdbc.car.volkswagen.values import VolkswagenFlags
    flags = self._vw_flags()
    return not bool(flags & (VolkswagenFlags.PQ | VolkswagenFlags.MLB | VolkswagenFlags.MEB | VolkswagenFlags.MEB_GEN2 | VolkswagenFlags.MQB_EVO))

  def _supports_vw_lateral_when_faulted(self) -> bool:
    from iqdbc.car.volkswagen.values import VolkswagenFlags
    # PQ, MEB, MQB_EVO and base MQB all implement cruiseFaultLateralMode in carstate.py.
    # MLB does not.
    return not bool(self._vw_flags() & VolkswagenFlags.MLB)

  def _pretty_name(self, platform: str) -> str:
    for name, v in self._platforms.items():
      if v.get("platform") == platform:
        make = v.get("make", "")
        if make and name.lower().startswith(make.lower() + " "):
          return name[len(make) + 1:]
        return name
    return _ascii_safe(platform).replace("_", " ").title()

  def _vehicle_status(self) -> str:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      name = _ascii_safe(bundle.get("name", "?"))
      make = bundle.get("make", "")
      if make and name.lower().startswith(make.lower() + " "):
        name = name[len(make) + 1:]
      return name[:1].upper() + name[1:]
    if ui_state.CP and ui_state.CP.carFingerprint not in ("", "MOCK"):
      return self._pretty_name(ui_state.CP.carFingerprint)
    return "tap to select"

  def _on_vehicle_clicked(self):
    if ui_state.params.get("CarPlatformBundle"):
      ui_state.params.remove("CarPlatformBundle")
      self._refresh()
    else:
      self._open_make_picker()

  def _open_make_picker(self):
    makes = sorted({v.get("make", "") for v in self._platforms.values() if v.get("make")})
    label_to_make = {_ascii_safe(m): m for m in makes}
    gui_app.push_widget(_VerticalPicker(list(label_to_make.keys()),
                                        lambda lbl: self._open_model_picker(label_to_make.get(lbl, ""))))

  def _open_model_picker(self, make: str):
    if not make:
      return
    prefix = make + " "
    label_to_key: dict = {}
    for key in sorted(p for p, v in self._platforms.items() if v.get("make") == make):
      label = key[len(prefix):] if key.lower().startswith(prefix.lower()) else key
      label_to_key[_ascii_safe(label)] = key
    gui_app.push_widget(_VerticalPicker(list(label_to_key.keys()),
                                        lambda lbl: self._select_platform(label_to_key.get(lbl, ""))))

  def _select_platform(self, key: str):
    if key and (data := self._platforms.get(key)):
      ui_state.params.put("CarPlatformBundle", {**data, "name": key})
    gui_app.pop_widgets_to(self)
    self._refresh()

  def _on_toyota_long(self, checked: bool):
    if checked and ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      ui_state.params.put_bool("AlphaLongitudinalEnabled", False)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _refresh(self):
    self._vehicle_btn.set_value(self._vehicle_status())

    brand = self._get_current_brand()
    offroad = ui_state.is_offroad()
    is_pq = self._is_vw_pq()
    is_mqb = self._is_vw_mqb()
    supports_lateral_when_faulted = self._supports_vw_lateral_when_faulted()
    visible = set(self._brand_widgets.get(brand, []))
    for w in self._all_brand_widgets:
      show = w in visible
      if w is self._vw_pq_hca:
        show = show and is_pq
      elif w in (self._vw_mqb_acc_resume, self._vw_mqb_steering_lockout):
        show = show and is_mqb
      elif w is self._vw_lateral:
        show = show and supports_lateral_when_faulted
      w.set_visible(show)
      if show:
        w.refresh()
    for w in (self._toyota_long, self._subaru_snag, self._subaru_manual, self._tesla_vtb):
      w.set_enabled(offroad)

  def _update_state(self):
    super()._update_state()
    self._vehicle_btn.set_value(self._vehicle_status())

  def show_event(self):
    super().show_event()
    self._refresh()
