"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import time

from openpilot.selfdrive.ui.layouts.settings.device import DeviceLayout
from .display import DisplayLayout
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.iqpilot.widgets.list_view import (
  option_item as option_item,
  multiple_button_item as multiple_button_item,
  button_item as button_item,
  dual_button_item as dual_button_item,
  Spacer,
)
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog, ConfirmDialog
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.scroller_tici import LineSeparator

offroad_time_options = {
  0: 0,
  1: 5,
  2: 10,
  3: 15,
  4: 30,
  5: 60,
  6: 120,
  7: 180,
  8: 300,
  9: 600,
  10: 1440,
  11: 1800,
}

FORCE_ONROAD_DURATION_SEC = 10 * 60
FORCE_ONROAD_PARAM = "ForceOnroadUntil"


class IQDeviceLayout(DeviceLayout):
  MENU_ROOT = 0
  MENU_SYSTEM = 1
  MENU_MAINTENANCE = 2
  MENU_DISPLAY = 3

  def __init__(self):
    self._display_layout = DisplayLayout()
    DeviceLayout.__init__(self)
    self._scroller._line_separator = None
    self._submenu = self.MENU_ROOT

  def _initialize_items(self):
    DeviceLayout._initialize_items(self)

    # Using dual button with no right button for better alignment
    self._always_offroad_btn = dual_button_item(
      left_text=lambda: tr("Enable Always Offroad"),
      left_callback=self._handle_always_offroad,
      right_text="",
      right_callback=None,
    )
    self._always_offroad_btn.action_item.right_button.set_visible(False)
    self._force_onroad_btn = dual_button_item(
      left_text=lambda: tr("Force On-Road (10 min)"),
      left_callback=self._handle_force_onroad,
      right_text="",
      right_callback=None,
    )
    self._force_onroad_btn.action_item.right_button.set_visible(False)

    self._max_time_offroad = option_item(
      title=lambda: tr("Max Time Offroad"),
      description=lambda: tr("Device will automatically shutdown after set time once the engine is turned off.\n(30h is the default)"),
      param="MaxTimeOffroad",
      min_value=0,
      max_value=11,
      value_change_step=1,
      on_value_changed=None,
      enabled=True,
      icon="",
      value_map=offroad_time_options,
      label_width=360,
      use_float_scaling=False,
      inline=True,
      label_callback=self._update_max_time_offroad_label
    )

    self._device_wake_mode = multiple_button_item(
      title=lambda: tr("Wake Up Behavior"),
      description=self.wake_mode_description,
      param="DeviceBootMode",
      buttons=[lambda: tr("Default"), lambda: tr("Offroad")],
      button_width=364,
      callback=None,
      inline=True,
    )
    self._change_language_btn = button_item(lambda: tr("Change Language"), lambda: tr("CHANGE"), callback=self._show_language_dialog)

    self._quiet_mode_and_dcam = dual_button_item(
      left_text=lambda: tr("Quiet Mode"),
      right_text=lambda: tr("Driver Camera Preview"),
      left_callback=lambda: ui_state.params.put_bool("QuietMode", not ui_state.params.get_bool("QuietMode")),
      right_callback=self._show_driver_camera
    )
    self._quiet_mode_and_dcam.action_item.right_button.set_button_style(ButtonStyle.NORMAL)

    self._reg_and_training = dual_button_item(
      left_text=lambda: tr("Regulatory"),
      left_callback=self._on_regulatory,
      right_text=lambda: tr("Training Guide"),
      right_callback=self._on_review_training_guide
    )
    self._reg_and_training.action_item.right_button.set_button_style(ButtonStyle.NORMAL)

    self._onroad_uploads_and_reset_settings = dual_button_item(
      left_text=lambda: tr("Onroad Uploads"),
      left_callback=lambda: ui_state.params.put_bool("OnroadUploads", not ui_state.params.get_bool("OnroadUploads")),
      right_text=lambda: tr("Reset Settings"),
      right_callback=self._reset_settings
    )

    self._power_buttons = dual_button_item(
      left_text=lambda: tr("Reboot"),
      right_text=lambda: tr("Power Off"),
      left_callback=self._reboot_prompt,
      right_callback=self._power_off_prompt
    )

    self._submenu_system_btn = dual_button_item(
      left_text=lambda: tr("System"),
      left_callback=lambda: self._set_submenu(self.MENU_SYSTEM),
      right_text="",
      right_callback=None,
    )
    self._submenu_system_btn.action_item.right_button.set_visible(False)
    self._submenu_maintenance_btn = dual_button_item(
      left_text=lambda: tr("Maintenance"),
      left_callback=lambda: self._set_submenu(self.MENU_MAINTENANCE),
      right_text="",
      right_callback=None,
    )
    self._submenu_maintenance_btn.action_item.right_button.set_visible(False)
    self._submenu_display_btn = dual_button_item(
      left_text=lambda: tr("Display"),
      left_callback=lambda: self._set_submenu(self.MENU_DISPLAY),
      right_text="",
      right_callback=None,
    )
    self._submenu_display_btn.action_item.right_button.set_visible(False)
    self._submenu_back_btn = dual_button_item(
      left_text=lambda: tr("Back"),
      left_callback=self._go_back,
      right_text="",
      right_callback=None,
    )
    self._submenu_back_btn.action_item.right_button.set_visible(False)

    self._submenu_top_separator = LineSeparator(height=10)
    self._submenu_gap = Spacer(10)
    self._submenu_bottom_separator = LineSeparator(height=10)
    self._system_sep_a = LineSeparator()
    self._system_sep_b = LineSeparator()
    self._system_sep_c = LineSeparator()
    self._system_sep_d = LineSeparator()
    self._display_sep_a = LineSeparator()
    self._display_sep_b = LineSeparator()
    self._display_sep_c = LineSeparator()

    items = [
      text_item(lambda: tr("Dongle ID"), self._params.get("DongleId") or (lambda: tr("N/A"))),
      LineSeparator(),
      text_item(lambda: tr("Serial"), self._params.get("HardwareSerial") or (lambda: tr("N/A"))),
      LineSeparator(),
      self._pair_device_btn,
      self._system_sep_a,
      self._reset_calib_btn,
      self._system_sep_b,
      self._change_language_btn,
      self._system_sep_c,
      self._device_wake_mode,
      self._system_sep_d,
      self._max_time_offroad,
      self._submenu_top_separator,
      self._submenu_system_btn,
      self._submenu_maintenance_btn,
      self._submenu_display_btn,
      self._submenu_back_btn,
      self._quiet_mode_and_dcam,
      self._reg_and_training,
      self._onroad_uploads_and_reset_settings,
      self._submenu_gap,
      self._submenu_bottom_separator,
      self._display_sep_a,
      *self._display_layout._scroller._items[:3],
      self._display_sep_b,
      *self._display_layout._scroller._items[3:],
      self._display_sep_c,
      self._power_buttons,
    ]

    return items

  def _set_submenu(self, submenu: int):
    self._submenu = submenu
    if submenu == self.MENU_DISPLAY:
      self._display_layout.show_event()

  def _go_back(self):
    self._set_submenu(self.MENU_ROOT)

  def _offroad_transition(self):
    self._power_buttons.action_item.right_button.set_visible(ui_state.is_offroad())

  @staticmethod
  def wake_mode_description() -> str:
    def_str = tr("Default: Device will boot/wake-up normally & will be ready to engage.")
    offrd_str = tr("Offroad: Device will be in Always Offroad mode after boot/wake-up.")
    header = tr("Controls state of the device after boot/sleep.")

    return f"{header}\n\n{def_str}\n{offrd_str}"

  @staticmethod
  def _reset_settings():
    def _do_reset(result: int):
      if result == DialogResult.CONFIRM:
        for _key in ui_state.params.all_keys():
          ui_state.params.remove(_key)
        HARDWARE.reboot()

    def _second_confirm(result: int):
      if result == DialogResult.CONFIRM:
        gui_app.set_modal_overlay(ConfirmDialog(
          text=tr("The reset cannot be undone. You have been warned."),
          confirm_text=tr("Confirm")
        ), callback=_do_reset)

    gui_app.set_modal_overlay(ConfirmDialog(
      text=tr("Are you sure you want to reset all IQ.Pilot settings to default? Once the settings are reset, there is no going back."),
      confirm_text=tr("Reset")
    ), callback=_second_confirm)

  @staticmethod
  def _handle_always_offroad():
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Enter Always Offroad Mode")))
      return

    _offroad_mode_state = ui_state.params.get_bool("OffroadMode")
    _offroad_mode_str = tr("Are you sure you want to exit Always Offroad mode?") if _offroad_mode_state else \
                        tr("Are you sure you want to enter Always Offroad mode?")

    def _set_always_offroad(result: int):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        if _offroad_mode_state:
          ui_state.params.put(FORCE_ONROAD_PARAM, 0)
        ui_state.params.put_bool("OffroadMode", not _offroad_mode_state)

    gui_app.set_modal_overlay(ConfirmDialog(_offroad_mode_str, tr("Confirm")), callback=lambda result: _set_always_offroad(result))

  @staticmethod
  def _handle_force_onroad():
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage before forcing on-road")))
      return

    if not ui_state.is_offroad():
      gui_app.set_modal_overlay(alert_dialog(tr("Force On-Road can only be started while offroad")))
      return

    now = int(time.time())
    force_onroad_until = ui_state.params.get(FORCE_ONROAD_PARAM, return_default=True)
    is_active = force_onroad_until > now
    if is_active:
      prompt = tr("Force On-Road is already active. Reset the timer to 10 minutes?")
    else:
      prompt = tr("Force IQ.Pilot on-road for 10 minutes? Always Offroad will be enabled automatically and it will return to offroad after the timer.")

    def _set_force_onroad(result: int):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        # Force On-Road relies on Always Offroad being active so expiry returns to offroad.
        ui_state.params.put_bool("OffroadMode", True)
        ui_state.params.put(FORCE_ONROAD_PARAM, int(time.time()) + FORCE_ONROAD_DURATION_SEC)

    gui_app.set_modal_overlay(ConfirmDialog(prompt, tr("Confirm")), callback=_set_force_onroad)

  @staticmethod
  def _update_max_time_offroad_label(value: int) -> str:
    label = tr("Always On") if value == 0 else f"{value}" + tr("m") if value < 60 else f"{value // 60}" + tr("h")
    label += tr(" (Default)") if value == 1800 else ""
    return label

  def _update_state(self):
    super()._update_state()
    self._display_layout._update_state()

    # Handle Always Offroad button
    always_offroad = ui_state.params.get_bool("OffroadMode")
    now = int(time.time())
    force_onroad_until = ui_state.params.get(FORCE_ONROAD_PARAM, return_default=True)
    force_onroad_active = force_onroad_until > now

    # Text & Color
    offroad_mode_btn_text = tr("Exit Always Offroad") if always_offroad else tr("Enable Always Offroad")
    offroad_mode_btn_style = ButtonStyle.PRIMARY if always_offroad else ButtonStyle.DANGER
    self._always_offroad_btn.action_item.left_button.set_text(offroad_mode_btn_text)
    self._always_offroad_btn.action_item.left_button.set_button_style(offroad_mode_btn_style)

    # Position
    if self._scroller._items.__contains__(self._always_offroad_btn):
      self._scroller._items.remove(self._always_offroad_btn)
    if ui_state.is_offroad() and not always_offroad:
      self._scroller._items.insert(len(self._scroller._items) - 1, self._always_offroad_btn)
    else:
      self._scroller._items.insert(0, self._always_offroad_btn)

    # Force On-Road button is always shown directly under Always Offroad in System menu.
    if self._scroller._items.__contains__(self._force_onroad_btn):
      self._scroller._items.remove(self._force_onroad_btn)
    self._scroller._items.insert(self._scroller._items.index(self._always_offroad_btn) + 1, self._force_onroad_btn)

    if force_onroad_active:
      remaining = force_onroad_until - now
      minutes = remaining // 60
      seconds = remaining % 60
      force_onroad_text = f"{tr('Forced On-Road Active')} ({minutes}:{seconds:02d})"
      force_onroad_style = ButtonStyle.PRIMARY
    else:
      force_onroad_text = tr("Force On-Road (10 min)")
      force_onroad_style = ButtonStyle.NORMAL
    self._force_onroad_btn.action_item.left_button.set_text(force_onroad_text)
    self._force_onroad_btn.action_item.left_button.set_button_style(force_onroad_style)
    self._force_onroad_btn.action_item.left_button.set_enabled(ui_state.is_offroad())

    # Quiet Mode button
    self._quiet_mode_and_dcam.action_item.left_button.set_button_style(ButtonStyle.PRIMARY if ui_state.params.get_bool("QuietMode") else ButtonStyle.NORMAL)

    # Onroad Uploads
    self._onroad_uploads_and_reset_settings.action_item.left_button.set_button_style(
      ButtonStyle.PRIMARY if ui_state.params.get_bool("OnroadUploads") else ButtonStyle.NORMAL
    )

    # Offroad only buttons
    self._quiet_mode_and_dcam.action_item.right_button.set_enabled(ui_state.is_offroad())
    self._reg_and_training.action_item.left_button.set_enabled(ui_state.is_offroad())
    self._reg_and_training.action_item.right_button.set_enabled(ui_state.is_offroad())
    self._onroad_uploads_and_reset_settings.action_item.right_button.set_enabled(ui_state.is_offroad())

    # Group advanced actions under submenu buttons.
    root_menu = self._submenu == self.MENU_ROOT
    system_menu = self._submenu == self.MENU_SYSTEM
    maintenance_menu = self._submenu == self.MENU_MAINTENANCE
    display_menu = self._submenu == self.MENU_DISPLAY

    self._submenu_system_btn.set_visible(root_menu)
    self._submenu_maintenance_btn.set_visible(root_menu)
    self._submenu_display_btn.set_visible(root_menu)
    self._submenu_back_btn.set_visible(not root_menu)

    self._always_offroad_btn.set_visible(system_menu)
    self._force_onroad_btn.set_visible(system_menu)
    self._reset_calib_btn.set_visible(system_menu)
    self._change_language_btn.set_visible(system_menu)
    self._system_sep_a.set_visible(system_menu)
    self._system_sep_b.set_visible(system_menu)
    self._system_sep_c.set_visible(system_menu)
    self._system_sep_d.set_visible(system_menu)
    self._device_wake_mode.set_visible(system_menu)
    self._max_time_offroad.set_visible(system_menu)
    self._quiet_mode_and_dcam.set_visible(system_menu)
    self._reg_and_training.set_visible(system_menu)

    self._onroad_uploads_and_reset_settings.set_visible(maintenance_menu)
    self._submenu_gap.set_visible(maintenance_menu)
    self._submenu_bottom_separator.set_visible(maintenance_menu)
    self._power_buttons.set_visible(maintenance_menu)

    self._display_sep_a.set_visible(display_menu)
    self._display_sep_b.set_visible(display_menu)
    self._display_sep_c.set_visible(display_menu)
    for item in self._display_layout._scroller._items:
      item.set_visible(display_menu)

    show_top_separator = root_menu or system_menu or maintenance_menu or display_menu
    self._submenu_top_separator.set_visible(show_top_separator)
