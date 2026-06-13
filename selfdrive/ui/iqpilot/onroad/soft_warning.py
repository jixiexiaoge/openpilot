"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from cereal import log

from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.onroad.driver_state import BTN_SIZE
from openpilot.system.ui.lib.application import gui_app

EventName = log.OnroadEvent.EventName

# Events that trigger the soft warning triangle instead of a disruptive alert
SOFT_WARNING_EVENTS = {
  EventName.commIssue,
  EventName.commIssueAvgFreq,
  EventName.selfdrivedLagging,
}

ICON_SIZE = 96

# Speed box geometry (mirrors hud_renderer._draw_set_speed)
_SPEED_BOX_X_OFFSET = 60
_SPEED_BOX_Y_OFFSET = 45
_SPEED_BOX_WIDTH = 180   # midpoint between metric (186) and imperial (174)
_SPEED_BOX_HEIGHT = 228

_DM_OFFSET = UI_BORDER_SIZE + BTN_SIZE // 2  # = 126


class SoftWarningRenderer:
  def __init__(self):
    self._icon = gui_app.texture("icons_mici/offroad_alerts/orange_warning.png", ICON_SIZE, ICON_SIZE)
    self._active = False

  def update(self) -> None:
    sm = ui_state.sm
    self._active = any(e.name in SOFT_WARNING_EVENTS for e in sm['onroadEvents'])

  def render(self, rect: rl.Rectangle) -> None:
    if not self._active:
      return

    # Centre of speed box (top-left of screen)
    speed_cx = rect.x + _SPEED_BOX_X_OFFSET + _SPEED_BOX_WIDTH / 2
    speed_cy = rect.y + _SPEED_BOX_Y_OFFSET + _SPEED_BOX_HEIGHT / 2

    # Centre of driver monitoring icon (bottom-left of screen, LHD)
    dm_cx = rect.x + _DM_OFFSET
    dm_cy = rect.y + rect.height - _DM_OFFSET

    # Midpoint between the two
    mid_x = (speed_cx + dm_cx) / 2
    mid_y = (speed_cy + dm_cy) / 2

    draw_x = int(mid_x - ICON_SIZE / 2)
    draw_y = int(mid_y - ICON_SIZE / 2)

    rl.draw_texture(self._icon, draw_x, draw_y, rl.WHITE)
