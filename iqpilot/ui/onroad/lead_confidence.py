"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app

ACTIVE_TOP = rl.Color(0x22, 0xB8, 0xB9, 255)
ACTIVE_BOTTOM = rl.Color(0x0C, 0x94, 0x96, 255)
MEDIUM_TOP = rl.Color(255, 200, 0, 255)
MEDIUM_BOTTOM = rl.Color(255, 115, 0, 255)
LOW_TOP = rl.Color(255, 0, 21, 255)
LOW_BOTTOM = rl.Color(255, 0, 89, 255)
OVERRIDE_TOP = rl.Color(255, 255, 255, 255)
OVERRIDE_BOTTOM = rl.Color(82, 82, 82, 255)
IDLE_TOP = rl.Color(120, 120, 120, 255)
IDLE_BOTTOM = rl.Color(60, 60, 60, 255)


def _zone_colors(confidence: float) -> tuple[rl.Color, rl.Color]:
  if confidence > 0.5:
    return ACTIVE_TOP, ACTIVE_BOTTOM
  if confidence > 0.2:
    return MEDIUM_TOP, MEDIUM_BOTTOM
  return LOW_TOP, LOW_BOTTOM


class DrivingConfidence:
  def __init__(self):
    self._filter = FirstOrderFilter(-0.5, 0.5, 1 / gui_app.target_fps)
    self._last_frame = -1

  def update(self) -> None:
    frame = ui_state.sm.frame
    if frame == self._last_frame:
      return
    self._last_frame = frame
    try:
      predictions = ui_state.sm['modelV2'].meta.disengagePredictions
    except Exception:
      return

    if ui_state.status == UIStatus.DISENGAGED:
      value = -0.5
    elif ui_state.status == UIStatus.LAT_ONLY:
      value = 1 - max(predictions.steerOverrideProbs or [1])
    elif ui_state.status == UIStatus.LONG_ONLY:
      value = 1 - max(predictions.brakeDisengageProbs or [1])
    else:
      value = (1 - max(predictions.brakeDisengageProbs or [1])) * (1 - max(predictions.steerOverrideProbs or [1]))

    self._filter.update(value)

  @property
  def value(self) -> float:
    return self._filter.x

  def colors(self, demo: bool = False) -> tuple[rl.Color, rl.Color]:
    confidence = self._filter.x
    if ui_state.status == UIStatus.ENGAGED or demo:
      return _zone_colors(confidence)
    if ui_state.status in (UIStatus.LAT_ONLY, UIStatus.LONG_ONLY):
      return _zone_colors(confidence)
    if ui_state.status == UIStatus.OVERRIDE:
      return OVERRIDE_TOP, OVERRIDE_BOTTOM
    return IDLE_TOP, IDLE_BOTTOM


driving_confidence = DrivingConfidence()
