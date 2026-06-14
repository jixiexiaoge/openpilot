"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl

from openpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.developer_ui import DeveloperUiRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.nav_map_panel import NavMapPanel
from openpilot.selfdrive.ui.iqpilot.onroad.road_name import RoadNameRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.rocket_fuel import RocketFuel
from openpilot.selfdrive.ui.iqpilot.onroad.speed_limit import SpeedLimitRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.turn_signal import TurnSignalController
from openpilot.selfdrive.ui.iqpilot.onroad.circular_alerts import CircularAlertsRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.speed_renderer import SpeedRenderer
from openpilot.selfdrive.ui.iqpilot.onroad.soft_warning import SoftWarningRenderer

ENABLE_FLOATING_NAV_MAP_PANEL = False
ENABLE_SPLIT_NAV_MAP_PANEL = True


class IQHudRenderer(HudRenderer):
  def __init__(self):
    super().__init__()
    self.developer_ui = DeveloperUiRenderer()
    self.nav_map_panel = NavMapPanel()
    self.road_name_renderer = RoadNameRenderer()
    self.rocket_fuel = RocketFuel()
    self.speed_limit_renderer = SpeedLimitRenderer()
    self.turn_signal_controller = TurnSignalController()
    self.circular_alerts_renderer = CircularAlertsRenderer()
    self.speed_renderer = SpeedRenderer()
    self.soft_warning_renderer = SoftWarningRenderer()
    self._torque_bar = TorqueBar(scale=3.0, always=True)

  def _update_state(self) -> None:
    super()._update_state()
    if ENABLE_FLOATING_NAV_MAP_PANEL or ENABLE_SPLIT_NAV_MAP_PANEL:
      self.nav_map_panel.update()
    self.road_name_renderer.update()
    self.speed_limit_renderer.update()
    has_limit = self.speed_limit_renderer.speed_limit_valid or self.speed_limit_renderer.speed_limit_last_valid
    self.limit_available = has_limit
    self.limit_speed_text = str(round(self.speed_limit_renderer.speed_limit_last)) if has_limit else "---"
    self.turn_signal_controller.update()
    self.circular_alerts_renderer.update()
    self.speed_renderer.update()
    self.soft_warning_renderer.update()

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    self.speed_renderer.render(rect)

  def _render(self, rect: rl.Rectangle) -> None:
    super()._render(rect)

    if ui_state.torque_bar:
      torque_rect = rect
      if ui_state.developer_ui in (DeveloperUiRenderer.DEV_UI_BOTTOM, DeveloperUiRenderer.DEV_UI_BOTH):
        torque_rect = rl.Rectangle(rect.x, rect.y, rect.width, rect.height - DeveloperUiRenderer.BOTTOM_BAR_HEIGHT)
      self._torque_bar.render(torque_rect)

    if not self.split_nav_enabled():
      self.developer_ui.render(rect)
    if ENABLE_FLOATING_NAV_MAP_PANEL:
      self.nav_map_panel.render(rect)
    self.road_name_renderer.render(rect)
    self.turn_signal_controller.render(rect)
    self.circular_alerts_renderer.render(rect)
    self.soft_warning_renderer.render(rect)
    self.rocket_fuel.render(rect, ui_state.sm)

  def split_nav_enabled(self) -> bool:
    if not ENABLE_SPLIT_NAV_MAP_PANEL:
      return False
    if hasattr(self.nav_map_panel, "maps_enabled"):
      return bool(self.nav_map_panel.maps_enabled())
    return bool(getattr(self.nav_map_panel, "_maps_enabled", False))

  def render_split_nav(self, rect: rl.Rectangle) -> None:
    if self.split_nav_enabled():
      self.nav_map_panel.render_split(rect)

  def render_full_width_overlays(self, rect: rl.Rectangle) -> None:
    if self.split_nav_enabled():
      self.developer_ui.render(rect)
