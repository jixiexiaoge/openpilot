"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import car
from enum import IntEnum

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item, simple_button_item, IQLineSeparator
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets import Widget
from .steering_sub_layouts.lane_change_settings import LaneChangeSettingsLayout
from .steering_sub_layouts.aol_settings import AolSettingsLayout
from .steering_sub_layouts.torque_settings import TorqueSettingsLayout


class PanelType(IntEnum):
  STEERING = 0
  AOL = 1
  LANE_CHANGE = 2
  TORQUE_CONTROL = 3


class SteeringLayout(Widget):
  def __init__(self):
    super().__init__()

    self._current_panel = PanelType.STEERING
    self._lane_change_settings_layout = LaneChangeSettingsLayout(lambda: self._set_current_panel(PanelType.STEERING))
    self._aol_settings_layout = AolSettingsLayout(lambda: self._set_current_panel(PanelType.STEERING))
    self._torque_control_layout = TorqueSettingsLayout(lambda: self._set_current_panel(PanelType.STEERING))

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._aol_base_desc = tr("Enable Always on Lateral (AOL). " +
                             "Disable toggle to revert back to stock IQ.Pilot engagement/disengagement.")
    self._aol_limited_desc = tr("This platform supports limited AOL settings.")
    self._aol_full_desc = tr("This platform supports all AOL settings.")
    self._aol_check_compat_desc = tr("Start the vehicle to check vehicle compatibility.")

    self._aol_toggle = toggle_item(
      param="AolEnabled",
      title=lambda: tr("Always on Lateral (AOL)"),
      description=self._aol_base_desc,
    )
    self._aol_settings_button = simple_button_item(
      button_text=lambda: tr("Customize AOL"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.AOL)
    )
    self._lane_change_settings_button = simple_button_item(
      button_text=lambda: tr("Customize Lane Change"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.LANE_CHANGE)
    )
    self._torque_control_toggle = toggle_item(
      param="EnforceTorqueControl",
      title=lambda: tr("Torque Auto Tune"),
      description=lambda: tr("Enable this to enforce IQ.Pilot to steer with Torque lateral control."),
    )
    self._torque_customization_button = simple_button_item(
      button_text=lambda: tr("Customize Torque Params"),
      button_width=850,
      callback=lambda: self._set_current_panel(PanelType.TORQUE_CONTROL)
    )
    self._nnff_toggle = toggle_item(
      param="NeuralNetworkFeedForward",
      title=lambda: tr("Neural Network Feed Forward (NNFF)"),
      description=""
    )

    items = [
      self._aol_toggle,
      self._aol_settings_button,
      IQLineSeparator(40),
      self._lane_change_settings_button,
      IQLineSeparator(40),
      self._torque_control_toggle,
      self._torque_customization_button,
      IQLineSeparator(40),
      self._nnff_toggle,
    ]
    return items

  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel

  def _update_state(self):
    super()._update_state()

    torque_allowed = True
    if ui_state.CP is not None:
      aol_main_desc = self._aol_limited_desc if self._aol_settings_layout._aol_limited_settings() else self._aol_full_desc
      self._aol_toggle.set_description(f"<b>{aol_main_desc}</b><br><br>{self._aol_base_desc}")

      if ui_state.CP.steerControlType == car.CarParams.SteerControlType.angle:
        ui_state.params.remove("EnforceTorqueControl")
        ui_state.params.remove("NeuralNetworkFeedForward")
        torque_allowed = False
    else:
      self._aol_toggle.set_description(f"<b>{self._aol_check_compat_desc}</b><br><br>{self._aol_base_desc}")
      ui_state.params.remove("EnforceTorqueControl")
      ui_state.params.remove("NeuralNetworkFeedForward")
      torque_allowed = False

    self._aol_toggle.action_item.set_enabled(ui_state.is_offroad())
    self._aol_settings_button.action_item.set_enabled(ui_state.is_offroad() and self._aol_toggle.action_item.get_state())

    enforce_torque_enabled = self._torque_control_toggle.action_item.get_state()
    nnff_enabled = self._nnff_toggle.action_item.get_state()
    self._nnff_toggle.action_item.set_enabled(ui_state.is_offroad() and torque_allowed and not enforce_torque_enabled)
    self._torque_control_toggle.action_item.set_enabled(ui_state.is_offroad() and torque_allowed and not nnff_enabled)
    self._torque_customization_button.action_item.set_enabled(self._torque_control_toggle.action_item.get_state())

  def _render(self, rect):
    if self._current_panel == PanelType.LANE_CHANGE:
      self._lane_change_settings_layout.render(rect)
    elif self._current_panel == PanelType.AOL:
      self._aol_settings_layout.render(rect)
    elif self._current_panel == PanelType.TORQUE_CONTROL:
      self._torque_control_layout.render(rect)
    else:
      self._scroller.render(rect)

  def show_event(self):
    self._set_current_panel(PanelType.STEERING)
    self._scroller.show_event()
