from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.volkswagen.values import VolkswagenFlags


def create_steering_control(packer, bus, apply_curvature, lkas_enabled, power):
  """HCA_03: MEB curvature-based steering control"""
  values = {
    "Curvature": abs(apply_curvature),
    "Curvature_VZ": 1 if apply_curvature < 0 else 0,
    "RequestStatus": 4 if lkas_enabled else 0,
    "Power": power,
  }
  return packer.make_can_msg("HCA_03", bus, values)


def create_eps_update(packer, bus, eps_stock_values, ea_simulated_torque):
  values = {}
  return []


def create_lka_hud_control(packer, bus, ldw_stock_values, lat_active, steering_pressed, hud_alert, hud_control, sound_alert=0):
  values = {**ldw_stock_values} if ldw_stock_values else {}
  return packer.make_can_msg("LDW_02", bus, values)


def create_acc_buttons_control(packer, bus, gra_stock_values, cancel=False, resume=False, up=False, down=False, set_button=False):
  values = {**gra_stock_values}
  if cancel:
    values["GRA_Abbrechen"] = 1
  if resume:
    values["GRA_Recall"] = 1
  if up:
    values["GRA_Up"] = 1
  if down:
    values["GRA_Down"] = 1
  if set_button:
    values["GRA_Setzen"] = 1
  return packer.make_can_msg("GRA_ACC_01", bus, values)


def create_capacitive_wheel_touch(packer, bus, lat_active, klr_stock_values):
  values = {**klr_stock_values} if klr_stock_values else {}
  return packer.make_can_msg("KLR_01", bus, values)


def acc_control_value(main_switch_on, acc_faulted, long_active, override):
  if not main_switch_on or acc_faulted:
    return 0
  if override:
    return 5
  if long_active:
    return 4
  return 3


def create_acc_accel_control(packer, bus, CP, acc_type, acc_enabled, upper_jerk, lower_jerk,
                              upper_control_limit, lower_control_limit, accel, accel_min, accel_max,
                              stopping, long_active, min_accel_v_below, v_cruise, has_lead):
  """ACC_18: MEB accel command"""
  values = {
    "ACC_Typ": acc_type,
    "ACC_Status_ACC": 2 if acc_enabled else 0,
    "ACC_Sollbeschleunigung_02": accel,
    "ACC_pos_Sollbeschl_Grad_02": upper_jerk,
    "ACC_neg_Sollbeschl_Grad_02": lower_jerk,
    "ACC_zul_Regelabw_oben": upper_control_limit,
    "ACC_zul_Regelabw_unten": lower_control_limit,
    "ACC_Anhalten": 1 if stopping else 0,
  }
  return [packer.make_can_msg("ACC_18", bus, values)]


def acc_hud_status_value(main_switch_on, acc_faulted, long_active, override):
  if not main_switch_on or acc_faulted:
    return 0
  if override:
    return 4
  if long_active:
    return 3
  return 2


def create_acc_hud_control(packer, bus, acc_control, set_speed, lead_visible, distance_bars,
                            show_distance_bars, esp_hold, distance, desired_gap, fcw_alert,
                            acc_event, speed_limit):
  """MEB_ACC_01: MEB ACC HUD"""
  values = {
    "ACC_Wunschgeschw_02": set_speed,
  }
  return packer.make_can_msg("MEB_ACC_01", bus, values)


def create_ea_control(packer, bus):
  return []
