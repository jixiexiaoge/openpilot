def create_hca_steering_control(packer, bus, apply_torque, HCA_Status):
  values = {
    "LM_Offset": abs(apply_torque),
    "LM_OffSign": 1 if apply_torque < 0 else 0,
    "HCA_Status": HCA_Status,
    "Vib_Freq": 16,
  }

  return packer.make_can_msg("HCA_1", bus, values)

def create_lka_hud_control(packer, bus, ldw_stock_values, lat_active, steering_pressed, hud_alert, hud_control, entering, special_mode, special_active):
  values = {}
  if len(ldw_stock_values):
    values = {s: ldw_stock_values[s] for s in [
      "LDW_SW_Warnung_links",   # Blind spot in warning mode on left side due to lane departure
      "LDW_SW_Warnung_rechts",  # Blind spot in warning mode on right side due to lane departure
      "LDW_Seite_DLCTLC",       # Direction of most likely lane departure (left or right)
      "LDW_DLC",                # Lane departure, distance to line crossing
      "LDW_TLC",                # Lane departure, time to line crossing
    ]}

  if entering:
    yellow_led = int(steering_pressed)
    green_led = int(not steering_pressed)
  elif special_mode:
    yellow_led = 1 if (lat_active and (steering_pressed or not special_active)) or not lat_active else 0
    green_led = 1 if lat_active and special_active and not steering_pressed else 0
  else:
    yellow_led = 1 if (lat_active and steering_pressed) or not lat_active else 0
    green_led = 1 if lat_active and not steering_pressed else 0

  values.update({
    "LDW_Kameratyp": 1,
    "LDW_Lampe_gelb": yellow_led,
    "LDW_Lampe_gruen": green_led,
    "LDW_Lernmodus_links": 3 if hud_control.leftLaneDepart else 1 + hud_control.leftLaneVisible,
    "LDW_Lernmodus_rechts": 3 if hud_control.rightLaneDepart else 1 + hud_control.rightLaneVisible,
    "LDW_Textbits": hud_alert,
  })

  return packer.make_can_msg("LDW_Status", bus, values)


def create_acc_buttons_control(packer, bus, gra_stock_values, cancel=False, resume=False, set_button=False):
  values = {s: gra_stock_values[s] for s in [
    "GRA_Hauptschalt",      # ACC button, on/off
    "GRA_Typ_Hauptschalt",  # ACC button, momentary vs latching
    "GRA_Kodierinfo",       # ACC button, configuration
    "GRA_Sender",           # ACC button, CAN message originator
  ]}

  values.update({
    "COUNTER": (gra_stock_values["COUNTER"] + 1) % 16,
    "GRA_Abbrechen": cancel,
    "GRA_Recall": resume,
    "GRA_Neu_Setzen": set_button,
  })

  return packer.make_can_msg("GRA_Neu", bus, values)

def create_gra_neu(packer, bus, gra_stock, longActive):
  values = gra_stock.copy()
  if longActive:
    values.update({
      "GRA_Neu_Setzen": 0,
      "GRA_Recall": 0,
      "GRA_Hauptschalt": 0,
    })
  return packer.make_can_msg("GRA_Neu", bus, values)

def acc_control_value(main_switch_on, long_active, cruiseOverride, accFaulted):
  if long_active or cruiseOverride:
    acc_control = 1
  elif accFaulted:
    acc_control = 3
  elif main_switch_on:
    acc_control = 2
  else:
    acc_control = 0

  return acc_control

def acc_hud_status_value(main_switch_on, acc_faulted, longActive, longOverride):
  if longOverride:
    hud_status = 4
  elif longActive:
    hud_status = 3
  elif acc_faulted:
    hud_status = 6
  elif main_switch_on:
    hud_status = 2
  else:
    hud_status = 0

  return hud_status


def create_acc_accel_control(packer, bus, acc_type, accel, acc_control, stopping, starting, esp_hold, comfortBand, jerkLimit, eBrakeActive):
  commands = []
  acc_enabled = acc_control == 1

  values = {
    "ACS_Sta_ADR": acc_control,
    "ACS_StSt_Info": acc_enabled,
    "ACS_Typ_ACC": acc_type,
    "ACS_Anhaltewunsch": acc_type == 1 and stopping or eBrakeActive,
    "ACS_FreigSollB": acc_enabled,
    "ACS_Sollbeschl": accel if acc_enabled else 3.01,
    "ACS_zul_Regelabw": comfortBand if acc_enabled else 1.27,
    "ACS_max_AendGrad": jerkLimit if acc_enabled else 5.08,
    "ACS_Schubabsch": 1 if acc_enabled and (accel > 0.05) else 0,
    "ACS_MomEingriff": 0,
    "ACS_ADR_Schub": 0,
  }

  commands.append(packer.make_can_msg("ACC_System", bus, values))

  return commands


def create_blinker_control(packer, bus, leftBlinker, rightBlinker):
  values = {
    "BM_rechts": rightBlinker,
    "BM_links": leftBlinker,
  }
  return packer.make_can_msg("Blinkmodi_02", bus, values)


def create_acc_hud_control(packer, bus, acc_hud_status, set_speed, leadDistance, distanceBars, fcw_alert, leadVisible):
  if distanceBars == 1:
    leadDistanceBars = 2
  elif distanceBars == 2:
    leadDistanceBars = 3
  elif distanceBars == 3:
    leadDistanceBars = 4
  else:
    leadDistanceBars = 2
  values = {
    "ACA_StaACC": acc_hud_status,
    "ACA_Zeitluecke": leadDistanceBars,
    "ACA_V_Wunsch": set_speed,
    "ACA_gemZeitl": min(15, max(1, int(round(leadDistance)))) if leadVisible else 0,
    "ACA_PrioDisp": 3,
    "ACA_Akustik2": fcw_alert,
  }

  return packer.make_can_msg("ACC_GRA_Anzeige", bus, values)

def filter_motor2(packer, bus, motor2_stock):
  values = motor2_stock
  values.update({
    "MO2_Sta_GRA": 0,
  })
  return packer.make_can_msg("Motor_2", bus, values)
