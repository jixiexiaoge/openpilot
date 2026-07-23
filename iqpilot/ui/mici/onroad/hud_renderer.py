"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl

from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer
from openpilot.iqpilot.ui.onroad.hud_overlays import BlindSpotIndicators


class IQMiciHudRenderer(HudRenderer):
  """Stock Mici HUD extended with IQ.Pilot's own onroad overlays.

  Overlays live in a list so the renderer stays overlay-agnostic — each just needs
  update()/render(rect); blind-spot state is surfaced by any overlay that exposes it.
  """

  def __init__(self):
    super().__init__()
    self._overlays = [BlindSpotIndicators()]

  def _update_state(self) -> None:
    super()._update_state()
    for overlay in self._overlays:
      overlay.update()

  def _render(self, rect: rl.Rectangle) -> None:
    super()._render(rect)
    for overlay in self._overlays:
      overlay.render(rect)

  def _has_blind_spot_detected(self) -> bool:
    return any(getattr(overlay, "detected", False) for overlay in self._overlays)
