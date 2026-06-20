"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass
from enum import IntEnum

import pyray as rl
from openpilot.selfdrive.ui.layouts.settings import settings as OP
from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from .developer import IQDeveloperLayout
from .device import IQDeviceLayout
from .cruise import CruiseLayout
from .models import ModelsLayout
from .network import IQNetworkUI
from .software import IQSoftwareLayout
from .steering import SteeringLayout
from .vehicle import VehicleLayout
from .visuals import VisualsLayout
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.iqpilot.lib.styles import style
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller

# from openpilot.selfdrive.ui.iqpilot.layouts.settings.navigation import NavigationLayout

OP.PANEL_COLOR = rl.Color(10, 10, 10, 255)
ICON_SIZE = 70

OP.PanelType = IntEnum(
  "PanelType",
  [es.name for es in OP.PanelType] + [
    "MODELS",
    "CRUISE",
    "STEERING",
    "VISUALS",
    "NAVIGATION",
    "VEHICLE",
  ],
  start=0,
)


@dataclass
class PanelInfo(OP.PanelInfo):
  icon: str = ""


class NavButton(Widget):
  def __init__(self, parent, p_type, p_info):
    super().__init__()
    self.parent = parent
    self.panel_type = p_type
    self.panel_info = p_info

  def _render(self, rect):
    is_selected = self.panel_type == self.parent._current_panel
    text_color = OP.TEXT_SELECTED if is_selected else OP.TEXT_NORMAL
    content_x = rect.x + 90
    text_size = measure_text_cached(self.parent._font_medium, self.panel_info.name, 65)

    # Draw background if selected
    if is_selected:
      self.container_rect = rl.Rectangle(
        content_x - 50, rect.y, OP.SIDEBAR_WIDTH - 50, OP.NAV_BTN_HEIGHT
      )
      rl.draw_rectangle_rounded(self.container_rect, 0.2, 5, OP.CLOSE_BTN_COLOR)

    if self.panel_info.icon:
      icon_texture = gui_app.texture(self.panel_info.icon, ICON_SIZE, ICON_SIZE, keep_aspect_ratio=True)
      rl.draw_texture(icon_texture, int(content_x), int(rect.y + (OP.NAV_BTN_HEIGHT - icon_texture.height) / 2),
                      rl.WHITE)
      content_x += ICON_SIZE + 20

    # Draw button text (right-aligned)
    text_pos = rl.Vector2(
      content_x,
      rect.y + (OP.NAV_BTN_HEIGHT - text_size.y) / 2
    )
    rl.draw_text_ex(self.parent._font_medium, self.panel_info.name, text_pos, 55, 0, text_color)

    # Store button rect for click detection
    self.panel_info.button_rect = rect


class IQSettingsLayout(OP.SettingsLayout):
  def __init__(self):
    OP.SettingsLayout.__init__(self)
    self._nav_items: list[Widget] = []
    self._hidden_from_sidebar: set = set()

    # Create sidebar scroller
    self._sidebar_scroller = Scroller([], spacing=0, line_separator=False, pad_end=False)

    # Panel configuration
    wifi_manager = WifiManager()
    wifi_manager.set_active(False)

    self._panels = {
      OP.PanelType.DEVICE: PanelInfo(tr_noop("Device"), IQDeviceLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_home.png"),
      OP.PanelType.NETWORK: PanelInfo(tr_noop("Network"), IQNetworkUI(wifi_manager), icon="icons/network.png"),
      OP.PanelType.TOGGLES: PanelInfo(tr_noop("Toggles"), TogglesLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_toggle.png"),
      OP.PanelType.SOFTWARE: PanelInfo(tr_noop("Software"), IQSoftwareLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_software.png"),
      OP.PanelType.MODELS: PanelInfo(tr_noop("Models"), ModelsLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_models.png"),
      OP.PanelType.CRUISE: PanelInfo(tr_noop("Cruise"), CruiseLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_longitudinal.png"),
      OP.PanelType.STEERING: PanelInfo(tr_noop("Steering"), SteeringLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_lateral.png"),
      OP.PanelType.VISUALS: PanelInfo(tr_noop("Visuals"), VisualsLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_visuals.png"),
      # OP.PanelType.NAVIGATION: PanelInfo(tr_noop("Navigation"), NavigationLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_map.png"),
      OP.PanelType.VEHICLE: PanelInfo(tr_noop("Vehicle"), VehicleLayout(), icon="../../iqpilot/selfdrive/assets/offroad/icon_vehicle.png"),
      OP.PanelType.DEVELOPER: PanelInfo(tr_noop("Developer"), IQDeveloperLayout(), icon="icons/shell.png"),
    }

    # Cruise is hidden from the sidebar; accessible via double-click on IQ.Dynamic in Toggles
    self._hidden_from_sidebar = {OP.PanelType.CRUISE}
    self._panels[OP.PanelType.TOGGLES].instance.set_cruise_panel_callback(
      lambda: self.set_current_panel(OP.PanelType.CRUISE)
    )

  def _draw_sidebar(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, OP.SIDEBAR_COLOR)

    # Close button
    close_btn_rect = rl.Rectangle(
      rect.x + style.ITEM_PADDING * 3, rect.y + style.ITEM_PADDING * 2, style.CLOSE_BTN_SIZE, style.CLOSE_BTN_SIZE
    )

    pressed = (rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and
               rl.check_collision_point_rec(rl.get_mouse_position(), close_btn_rect))
    close_color = OP.CLOSE_BTN_PRESSED if pressed else OP.CLOSE_BTN_COLOR
    rl.draw_rectangle_rounded(close_btn_rect, 1.0, 20, close_color)

    icon_color = rl.Color(255, 255, 255, 255) if not pressed else rl.Color(220, 220, 220, 255)
    icon_dest = rl.Rectangle(
      close_btn_rect.x + (close_btn_rect.width - self._close_icon.width) / 2,
      close_btn_rect.y + (close_btn_rect.height - self._close_icon.height) / 2,
      self._close_icon.width,
      self._close_icon.height,
    )
    rl.draw_texture_pro(
      self._close_icon,
      rl.Rectangle(0, 0, self._close_icon.width, self._close_icon.height),
      icon_dest,
      rl.Vector2(0, 0),
      0,
      icon_color,
    )

    # Store close button rect for click detection
    self._close_btn_rect = close_btn_rect

    # Navigation buttons with scroller
    if not self._nav_items:
      for panel_type, panel_info in self._panels.items():
        if panel_type in self._hidden_from_sidebar:
          continue
        nav_button = NavButton(self, panel_type, panel_info)
        nav_button.rect.width = rect.width - 100  # Full width minus padding
        nav_button.rect.height = OP.NAV_BTN_HEIGHT
        self._nav_items.append(nav_button)
        self._sidebar_scroller.add_widget(nav_button)

    # Draw navigation section with scroller
    nav_rect = rl.Rectangle(
      rect.x,
      self._close_btn_rect.height + style.ITEM_PADDING * 4,  # Starting Y position for nav items
      rect.width,
      rect.height - 300  # Remaining height after close button
    )

    if self._nav_items:
      self._sidebar_scroller.render(nav_rect)
      return

  def _handle_mouse_release(self, mouse_pos: MousePos) -> bool:
    # Check close button
    if rl.check_collision_point_rec(mouse_pos, self._close_btn_rect):
      if self._close_callback:
        self._close_callback()
      return True

    # Check navigation buttons
    for panel_type, panel_info in self._panels.items():
      if panel_type in self._hidden_from_sidebar:
        continue
      if rl.check_collision_point_rec(mouse_pos, panel_info.button_rect) and self._sidebar_scroller.scroll_panel.is_touch_valid():
        self.set_current_panel(panel_type)
        return True

    return False

  def show_event(self):
    super().show_event()
    self._panels[self._current_panel].instance.show_event()
    self._sidebar_scroller.show_event()
