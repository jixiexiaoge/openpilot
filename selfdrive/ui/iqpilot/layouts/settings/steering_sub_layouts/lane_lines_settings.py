"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.iqpilot.lib.styles import style
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item, option_item, IQLineSeparator
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets import Widget
from openpilot.common.constants import CV


class LaneLinesSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._toggle = toggle_item(
      param="IQLanePlanner",
      title=lambda: tr("Lane Lines (IQ Lane Planner)"),
      description=lambda: tr(
        "When enabled and confident lane lines are detected, the planned path is blended toward "
        "lane center and solved through the lateral MPC. Falls back to the stock end-to-end model "
        "path when lane lines aren't confident, during lane changes, or below the min speed."
      ),
    )

    def lp_on() -> bool:
      return self._toggle.action_item.get_state()

    self._speed = option_item(
      tr("Min Lane-Line Speed"), "IQLanePlannerUseLaneLineSpeed", 0, 140,
      tr("Below this speed, planner falls back to the laneless model path."),
      5, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False,
      lambda v: f"{int(round(v * (1 if ui_state.is_metric else CV.KPH_TO_MPH)))} {'km/h' if ui_state.is_metric else 'mph'}"
    )
    self._path_offset = option_item(
      tr("Path Offset"), "IQLanePlannerPathOffset", -50, 50,
      tr("Global lateral path offset. Positive = right, negative = left."),
      1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f} m"
    )
    self._lane_offset = option_item(
      tr("Lane Offset Bias"), "IQLanePlannerAdjustLaneOffset", -50, 50,
      tr("Bias lane-center targeting based on available lane width."),
      1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f} m"
    )
    self._input_offset = option_item(
      tr("Input Time Offset"), "IQLanePlannerInputTimeOffset", 0, 50,
      tr("Time shift for lane-path interpolation."),
      1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f} s"
    )
    self._path_cost = option_item(
      tr("MPC Path Cost"), "IQLanePlannerMpcPathCost", 1, 400,
      tr("Higher values = stronger lane-center tracking."),
      1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f}"
    )
    self._motion_cost = option_item(
      tr("MPC Motion Cost"), "IQLanePlannerMpcMotionCost", 1, 100,
      "", 1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f}"
    )
    self._accel_cost = option_item(
      tr("MPC Accel Cost"), "IQLanePlannerMpcAccelCost", 0, 200,
      "", 1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f}"
    )
    self._jerk_cost = option_item(
      tr("MPC Jerk Cost"), "IQLanePlannerMpcJerkCost", 0, 200,
      "", 1, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v / 100:.2f}"
    )
    self._rate_cost = option_item(
      tr("MPC Steering Rate Cost"), "IQLanePlannerMpcSteeringRateCost", 100, 2000,
      "", 10, None, lp_on, "", style.BUTTON_ACTION_WIDTH, None, False, lambda v: f"{v}"
    )

    return [
      self._toggle,
      IQLineSeparator(40),
      self._speed,
      self._path_offset,
      self._lane_offset,
      self._input_offset,
      IQLineSeparator(40),
      self._path_cost,
      self._motion_cost,
      self._accel_cost,
      self._jerk_cost,
      self._rate_cost,
    ]

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    content_rect = rl.Rectangle(
      rect.x, rect.y + self._back_button.rect.height + 40,
      rect.width, rect.height - self._back_button.rect.height - 40
    )
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()
