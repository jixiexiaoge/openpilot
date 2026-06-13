"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.common.params import Params
from openpilot.system.ui.iqpilot.widgets.list_view import IQListItem, IQMultipleButtonAction, IQToggleAction
from openpilot.system.ui.iqpilot.widgets.option_control import OptionControl
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller


class CruiseLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._scroller = Scroller(self._initialize_items(), line_separator=True, spacing=0)

  @staticmethod
  def _toggle_item(title: str, description: str, param: str):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=IQToggleAction(initial_state=Params().get_bool(param), callback=lambda state: Params().put_bool(param, state), param=param),
    )

  @staticmethod
  def _mode_item(title: str, description: str, param: str, labels: list[str], width: int, inline: bool = False):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=IQMultipleButtonAction(buttons=[lambda s=s: tr(s) for s in labels], button_width=width, param=param),
      inline=inline,
    )

  @staticmethod
  def _option_item(title: str, description: str, param: str, minimum: int, maximum: int, step: int = 1,
                   label_callback=None, use_float_scaling: bool = False):
    return IQListItem(
      title=lambda: tr(title),
      description=lambda: tr(description),
      action_item=OptionControl(
        param=param,
        min_value=minimum,
        max_value=maximum,
        value_change_step=step,
        use_float_scaling=use_float_scaling,
        label_callback=label_callback,
      ),
    )

  def _initialize_items(self):
    ms_to_mph = 2.23694

    def speed_label(value: float | int) -> str:
      return f"{int(round(value * ms_to_mph))} mph"

    def seconds_label(value: float | int) -> str:
      return f"{float(value):.1f}s"

    items = [
      self._mode_item(
        "IQ Speed Limit Mode",
        "Choose how IQ.Pilot handles speed limit data. Control adjusts cruise speed. Warning only highlights overspeed.",
        "SpeedLimitMode",
        ["Off", "Info", "Warn", "Control"],
        180,
      ),
      self._mode_item(
        "IQ SLC Policy",
        "Select how IQ.Pilot resolves conflicting speed limit sources.",
        "SLCPolicy",
        ["Map Only", "Map Priority", "Combined"],
        150,
      ),
      self._mode_item(
        "IQ SLC Override",
        "Manual keeps an override while you press the accelerator. Set Speed jumps directly to your cruise setpoint.",
        "SLCOverrideMethod",
        ["Manual", "Set Speed"],
        220,
      ),
      self._toggle_item(
        "IQ SLC Confirm Higher",
        "Require confirmation before IQ.Pilot accepts a higher detected speed limit.",
        "SpeedLimitConfirmationHigher",
      ),
      self._toggle_item(
        "IQ SLC Confirm Lower",
        "Require confirmation before IQ.Pilot accepts a lower detected speed limit.",
        "SpeedLimitConfirmationLower",
      ),
      self._toggle_item(
        "IQ SLC Auto Confirm",
        "Automatically accept speed limit changes after a 5-second timeout without requiring a cruise button press.",
        "SLCAutoConfirm",
      ),
      self._toggle_item(
        "IQ SLC Fallback Set Speed",
        "If no speed limit is available, use the current set speed as the controller target.",
        "SLCFallbackSetSpeed",
      ),
      self._toggle_item(
        "IQ SLC Fallback Previous",
        "If a new limit is denied, reuse the previous accepted speed limit when possible.",
        "SLCFallbackPreviousSpeedLimit",
      ),
      self._toggle_item(
        "IQ SLC Fallback Experimental",
        "When no speed limit is available, let IQ.Dynamic request experimental longitudinal behavior.",
        "SLCFallbackExperimentalMode",
      ),
      self._toggle_item(
        "IQ SLC Mapbox Filler",
        "Use Mapbox to fill in missing speed limits when local map data is unavailable.",
        "SLCMapboxFiller",
      ),
      self._option_item(
        "IQ Map Lookahead Higher",
        "How far ahead IQ.Pilot should apply an upcoming higher map speed limit before the limit changes.",
        "MapSpeedLookaheadHigher",
        100,
        1000,
        step=50,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      self._option_item(
        "IQ Map Lookahead Lower",
        "How far ahead IQ.Pilot should apply an upcoming lower map speed limit before the limit changes.",
        "MapSpeedLookaheadLower",
        100,
        1000,
        step=50,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      self._toggle_item(
        "IQ.Dynamic Curves",
        "Allow IQ.Dynamic to enter blended control for curves and strong vision slowdown cues.",
        "IQDynamicConditionalCurves",
      ),
      self._toggle_item(
        "IQ.Dynamic Slower Lead",
        "Allow IQ.Dynamic to switch toward blended control when a slower lead vehicle is detected.",
        "IQDynamicConditionalSlowerLead",
      ),
      self._toggle_item(
        "IQ.Dynamic Stopped Lead",
        "Allow IQ.Dynamic to react more aggressively when a lead vehicle is nearly stopped.",
        "IQDynamicConditionalStoppedLead",
      ),
      self._toggle_item(
        "IQ.Dynamic Model Stops",
        "Allow IQ.Dynamic to switch toward blended control for stop-sign and stop-light style vision stops.",
        "IQDynamicConditionalModelStops",
      ),
      self._toggle_item(
        "IQ.Dynamic SLC Fallback",
        "Allow IQ.Dynamic to request blended control when Speed Limit Controller has no usable target.",
        "IQDynamicConditionalSLCFallback",
      ),
      self._option_item(
        "IQ.Dynamic Low Speed",
        "Below this speed, IQ.Dynamic prefers blended control when no lead is present.",
        "IQDynamicConditionalSpeed",
        500,
        3500,
        step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      self._option_item(
        "IQ.Dynamic Lead Speed",
        "Below this speed, IQ.Dynamic prefers blended control even with a tracked lead.",
        "IQDynamicConditionalLeadSpeed",
        500,
        4000,
        step=50,
        use_float_scaling=True,
        label_callback=speed_label,
      ),
      self._option_item(
        "IQ.Dynamic Model Stop Time",
        "Sets the vision stop prediction time horizon used by IQ.Dynamic and IQ Force Stops. Shorter values react later. Longer values react earlier.",
        "IQDynamicModelStopTime",
        100,
        600,
        step=25,
        use_float_scaling=True,
        label_callback=seconds_label,
      ),
      self._toggle_item(
        "IQ Force Stops",
        "Use the model stop prediction to force a stop for stop signs and stop lights unless overridden with the accelerator.",
        "IQForceStops",
      ),
    ]
    return items

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
