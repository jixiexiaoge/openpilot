"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from .base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.iqpilot.widgets.list_view import toggle_item

COOP_STEERING_MIN_KMH = 23
OEM_STEERING_MIN_KMH = 48
KM_TO_MILE = 0.621371


class TeslaSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.coop_steering_toggle = toggle_item(tr("VTB (Virtual Torque Blending)"), "", param="TeslaCoopSteering")
    self.items = [self.coop_steering_toggle]

  def update_settings(self):
    is_metric = ui_state.is_metric
    unit = "km/h" if is_metric else "mph"

    display_value_coop = COOP_STEERING_MIN_KMH if is_metric else round(COOP_STEERING_MIN_KMH * KM_TO_MILE)
    display_value_oem = OEM_STEERING_MIN_KMH if is_metric else round(OEM_STEERING_MIN_KMH * KM_TO_MILE)

    vtb_disabled_msg = tr("Enable \"Always Offroad\" in Device panel, or turn vehicle off to toggle.")
    vtb_warning = tr(f"Warning: May experience steering oscillations below {display_value_oem} {unit} during turns, " +
                     "recommend disabling this feature if you experience these.")
    vtb_desc = (
      f"<b>{vtb_warning}</b><br><br>" +
      f"{tr('Allows the driver to provide limited steering input while openpilot is engaged.')}<br>" +
      f"{tr(f'Only works above {display_value_coop} {unit}.')}"
    )

    if not ui_state.is_offroad():
      vtb_desc = f"<b>{vtb_disabled_msg}</b><br><br>{vtb_desc}"

    self.coop_steering_toggle.set_description(vtb_desc)
    self.coop_steering_toggle.action_item.set_enabled(ui_state.is_offroad())
