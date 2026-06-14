"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem, IQToggleAction, IQLineSeparator
from openpilot.system.ui.iqpilot.widgets.option_control import OptionControl
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller


def _toggle_item(title: str, description: str, param: str) -> IQListItem:
  return IQListItem(
    title=lambda t=title: tr(t),
    description=lambda d=description: tr(d),
    action_item=IQToggleAction(
      initial_state=Params().get_bool(param),
      callback=lambda state, p=param: Params().put_bool(p, state),
      param=param,
    ),
  )


def _option_item(title: str, description: str, param: str, minimum: int, maximum: int,
                 step: int = 1, label_callback=None, use_float_scaling: bool = False) -> IQListItem:
  return IQListItem(
    title=lambda t=title: tr(t),
    description=lambda d=description: tr(d),
    action_item=OptionControl(
      param=param,
      min_value=minimum,
      max_value=maximum,
      value_change_step=step,
      use_float_scaling=use_float_scaling,
      label_callback=label_callback,
    ),
  )


class IQDynamicLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._params = Params()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    ms_to_mph = 2.23694

    def speed_label(value: float | int) -> str:
      try:
        speed_ms = float(value)
      except (TypeError, ValueError):
        return "-- mph"
      return f"{int(round(speed_ms * ms_to_mph))} mph"

    def distance_label(value: float | int) -> str:
      try:
        distance_m = float(value)
      except (TypeError, ValueError):
        return "-- m"
      if self._params.get_bool("IsMetric"):
        return f"{distance_m:.1f} m"
      return f"{distance_m * 3.28084:.0f} ft"

    def seconds_label(value: float | int) -> str:
      try:
        seconds = float(value)
      except (TypeError, ValueError):
        return "--.-s"
      return f"{seconds:.1f}s"

    return [
      _toggle_item(
        "IQ.Dynamic Curves",
        "Allow IQ.Dynamic to enter blended control for curves and strong vision slowdown cues.",
        "IQDynamicConditionalCurves",
      ),
      _toggle_item(
        "IQ.Dynamic Slower Lead",
        "Allow IQ.Dynamic to switch toward blended control when a slower lead vehicle is detected.",
        "IQDynamicConditionalSlowerLead",
      ),
      _toggle_item(
        "IQ.Dynamic Stopped Lead",
        "Allow IQ.Dynamic to react more aggressively when a lead vehicle is nearly stopped.",
        "IQDynamicConditionalStoppedLead",
      ),
      _toggle_item(
        "IQ.Dynamic Model Stops",
        "Allow IQ.Dynamic to switch toward blended control for stop-sign and stop-light style vision stops.",
        "IQDynamicConditionalModelStops",
      ),
      _toggle_item(
        "IQ.Dynamic SLC Fallback",
        "Allow IQ.Dynamic to request blended control when Speed Limit Controller has no usable target.",
        "IQDynamicConditionalSLCFallback",
      ),
      IQLineSeparator(40),
      _option_item(
        "IQ.Dynamic Low Speed",
        "Below this speed, IQ.Dynamic prefers blended control when no lead is present.",
        "IQDynamicConditionalSpeed",
        500, 3500, step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      _option_item(
        "IQ.Dynamic Lead Speed",
        "Below this speed, IQ.Dynamic prefers blended control even with a tracked lead.",
        "IQDynamicConditionalLeadSpeed",
        500, 4000, step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      IQLineSeparator(40),
      _toggle_item(
        "IQ Force Stops",
        "Use the model stop prediction to force a stop for stop signs and stop lights while IQ.Dynamic is active "
        "in blended mode, unless overridden with the accelerator.",
        "IQForceStops",
      ),
      _option_item(
        "IQ.Dynamic Model Stop Time",
        "Shorter values make vision-based stop detection react later. Longer values react earlier. "
        "When IQ Force Stops is enabled, this also sets the force-stop ramp time.",
        "IQDynamicModelStopTime",
        100, 600, step=25,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      _option_item(
        "IQ.Dynamic Min Force Stop Length",
        "When IQ Force Stops is enabled, keep at least this much stopping distance in the force-stop ramp. "
        "Set to 0 to disable the minimum.",
        "IQDynamicMinimumForceStopLength",
        0, 5000, step=50,
        use_float_scaling=True,
        label_callback=distance_label,
      ),
    ]

  def _render(self, rect: rl.Rectangle):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    content_rect = rl.Rectangle(
      rect.x,
      rect.y + self._back_button.rect.height + 40,
      rect.width,
      rect.height - self._back_button.rect.height - 40,
    )
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()
