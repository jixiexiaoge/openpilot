"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from .base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item
from opendbc.car.volkswagen.values import CAR, VolkswagenFlags


DESCRIPTIONS = {
  'pqhca5or7Toggle': tr_noop(
    'Use HCA Status 7 instead of Status 5 for steering control on PQ platform vehicles. '
    'This may help with compatibility on some older Volkswagen models.'
  ),
  'AllowLateralWhenLongUnavailable': tr_noop(
    'Allow lateral control (steering) to remain active even when longitudinal control (gas/brake) '
    'is temporarily unavailable due to a cruise control fault.'
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

    self.items = [self.pq_hca_toggle, self.lateral_when_long_unavailable]

  def _is_pq(self) -> bool:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle:
      platform = bundle.get("platform")
      if platform:
        try:
          return bool(CAR[platform].config.flags & VolkswagenFlags.PQ)
        except (KeyError, AttributeError):
          return False
    elif ui_state.CP:
      return bool(ui_state.CP.flags & VolkswagenFlags.PQ)
    return False

  def _on_pq_hca_toggle(self, state: bool):
    ui_state.params.put_bool("pqhca5or7Toggle", state)

  def _on_lateral_when_long_unavailable(self, state: bool):
    ui_state.params.put_bool("AllowLateralWhenLongUnavailable", state)

  def update_settings(self):
    is_pq = self._is_pq()
    self.pq_hca_toggle.set_visible(is_pq)
    self.lateral_when_long_unavailable.set_visible(is_pq)
