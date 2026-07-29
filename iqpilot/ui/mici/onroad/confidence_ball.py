"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus


ACTIVE_CONFIDENCE_TOP = rl.Color(0x22, 0xB8, 0xB9, 0xFF)
ACTIVE_CONFIDENCE_BOTTOM = rl.Color(0x0C, 0x94, 0x96, 0xFF)
MEDIUM_CONFIDENCE_TOP = rl.Color(255, 200, 0, 255)
MEDIUM_CONFIDENCE_BOTTOM = rl.Color(255, 115, 0, 255)
LOW_CONFIDENCE_TOP = rl.Color(255, 0, 21, 255)
LOW_CONFIDENCE_BOTTOM = rl.Color(255, 0, 89, 255)


class IQConfidenceBall:
  @staticmethod
  def get_animate_status_probs():
    if ui_state.status == UIStatus.LAT_ONLY:
      return ui_state.sm['modelV2'].meta.disengagePredictions.steerOverrideProbs

    # UIStatus.LONG_ONLY
    return ui_state.sm['modelV2'].meta.disengagePredictions.brakeDisengageProbs

  @staticmethod
  def get_lat_long_dot_colors(confidence: float) -> tuple[rl.Color, rl.Color]:
    if confidence > 0.5:
      return ACTIVE_CONFIDENCE_TOP, ACTIVE_CONFIDENCE_BOTTOM
    if confidence > 0.2:
      return MEDIUM_CONFIDENCE_TOP, MEDIUM_CONFIDENCE_BOTTOM
    return LOW_CONFIDENCE_TOP, LOW_CONFIDENCE_BOTTOM
