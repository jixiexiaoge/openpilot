"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pyray as rl
from cereal import car
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.iqpilot.onroad.developer_ui.elements import (
  UiElement, SteeringAngleElement, DesiredLateralAccelElement, ActualLateralAccelElement,
  DesiredSteeringAngleElement, AEgoElement, LeadSpeedElement, DesiredSteeringPIDElement
)
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets import Widget


class DeveloperUiRenderer(Widget):
  DEV_UI_OFF = 0
  DEV_UI_RIGHT = 1
  DEV_UI_BOTTOM = 2
  DEV_UI_BOTH = 3
  BOTTOM_BAR_HEIGHT = 61

  def __init__(self):
    super().__init__()
    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self.dev_ui_mode = self.DEV_UI_OFF

    self.steering_angle_elem = SteeringAngleElement()
    self.desired_lat_accel_elem = DesiredLateralAccelElement()
    self.actual_lat_accel_elem = ActualLateralAccelElement()
    self.desired_steer_elem = DesiredSteeringAngleElement()
    self.desired_pid_steer_elem = DesiredSteeringPIDElement()
    self.a_ego_elem = AEgoElement()
    self.lead_speed_elem = LeadSpeedElement()

  @staticmethod
  def get_bottom_dev_ui_offset():
    if ui_state.developer_ui != DeveloperUiRenderer.DEV_UI_OFF:
      return DeveloperUiRenderer.BOTTOM_BAR_HEIGHT
    return 0

  def _update_state(self) -> None:
    self.dev_ui_mode = ui_state.developer_ui

  def _render(self, rect: rl.Rectangle) -> None:
    if self.dev_ui_mode == self.DEV_UI_OFF:
      return

    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return

    if self.dev_ui_mode in (self.DEV_UI_RIGHT, self.DEV_UI_BOTTOM, self.DEV_UI_BOTH):
      self._draw_bottom_dev_ui(rect)

  def _draw_bottom_dev_ui(self, rect: rl.Rectangle) -> None:
    sm = ui_state.sm
    bar_height = 61
    y = int(rect.y + rect.height - bar_height)

    rl.draw_rectangle(int(rect.x), y, int(rect.width), bar_height,
                      rl.Color(0, 0, 0, 100))

    lateral_mode = sm['controlsState'].lateralControlState.which()
    show_desired_angle = (
      ui_state.CP is not None and
      ui_state.CP.steerControlType in (
        car.CarParams.SteerControlType.angle,
        car.CarParams.SteerControlType.curvatureDEPRECATED,
      )
    )
    desired_element: UiElement
    if lateral_mode == 'angleState' or show_desired_angle:
      desired_element = self.desired_steer_elem.update(sm, ui_state.is_metric)
    elif lateral_mode == 'pidState':
      desired_element = self.desired_pid_steer_elem.update(sm, ui_state.is_metric)
    else:
      desired_element = self.desired_lat_accel_elem.update(sm, ui_state.is_metric)

    elements = [
      desired_element,
      self.actual_lat_accel_elem.update(sm, ui_state.is_metric),
      self.steering_angle_elem.update(sm, ui_state.is_metric),
      self.a_ego_elem.update(sm, ui_state.is_metric),
      self.lead_speed_elem.update(sm, ui_state.is_metric),
    ]

    font_size = 38
    element_widths = []
    for element in elements:
      element.measure(self._font_bold, font_size)
      element_widths.append(element.total_width)

    total_element_width = sum(element_widths)
    num_gaps = len(elements) + 1
    available_width = rect.width
    gap_width = (available_width - total_element_width) / num_gaps

    center_y = y + bar_height // 2
    current_x = rect.x + gap_width

    for i, element in enumerate(elements):
      element_center_x = int(current_x + element_widths[i] / 2)
      self._draw_bottom_dev_ui_element(element_center_x, center_y, element)
      current_x += element_widths[i] + gap_width

  def _draw_bottom_dev_ui_element(self, center_x: int, y: int, element: UiElement) -> None:
    font_size = 38
    start_x = center_x - element.total_width / 2

    rl.draw_text_ex(self._font_bold, element.label_text, rl.Vector2(start_x, y - font_size // 2), font_size, 0, rl.WHITE)
    rl.draw_text_ex(self._font_bold, element.val_text, rl.Vector2(start_x + element.label_width, y - font_size // 2), font_size, 0, element.color)

    if element.unit:
      rl.draw_text_ex(self._font_bold, element.unit_text, rl.Vector2(start_x + element.label_width + element.val_width, y - font_size // 2),
                      font_size, 0, rl.WHITE)
