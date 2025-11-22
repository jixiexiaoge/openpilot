import numpy as np
from opendbc.car import structs
from opendbc.car.byd.values import  CanBus, CarControllerParams
from opendbc.car.byd.tuning import Tuning

GearShifter = structs.CarState.GearShifter
VisualAlert = structs.CarControl.HUDControl.VisualAlert

def byd_checksum(byte_key, dat):
  first_bytes_sum = sum(byte >> 4 for byte in dat)
  second_bytes_sum = sum(byte & 0xF for byte in dat)
  remainder = second_bytes_sum >> 4
  second_bytes_sum += byte_key >> 4
  first_bytes_sum += byte_key & 0xF
  first_part = ((-first_bytes_sum + 0x9) & 0xF)
  second_part = ((-second_bytes_sum + 0x9) & 0xF)
  return (((first_part + (-remainder + 5)) << 4) + second_part) & 0xFF

# MPC -> Panda -> EPS
def create_steering_control(packer, CP, cam_msg: dict, req_torque, req_prepare, active, hud_control, keep_lkas_passive, counter):
  values = {}
  values = {s: cam_msg[s] for s in [
    "sig_blhzkt",
    "sig_xncfwm",
    "sig_jpejsb",
    "sig_hnvcoz",
    "sig_dgabuz",
    "sig_dhzbjn",
    "sig_acljem",
    "sig_dhpdlz",
    "sig_mtvear",
    "sig_iqnige",
    "sig_veewby",
    "sig_svxlkf",
    "sig_ewlilf",
    "sig_nqnxwq",
    "sig_rswabp",
    "sig_emcfnl",
    "sig_ylmsdh",
  ]}

  values["sig_rwxpii"] = 0
  values["sig_ryesga"] = req_prepare
  values["sig_fkhfuz"] = counter

  if active:
    mpc_state = values["sig_dgabuz"] #2: Cancelling lkas control
    values.update({
      "sig_acljem" : req_torque,
      "sig_dhpdlz" : 1,
      "sig_nqnxwq" : 0 if keep_lkas_passive else 1 if mpc_state == 2 else 2,
      "sig_xncfwm":  3 if hud_control.leftLaneDepart  else int(hud_control.leftLaneVisible) + 1,
      "sig_ewlilf": 3 if hud_control.rightLaneDepart else int(hud_control.rightLaneVisible) + 1,
    })
  else: # This cancels the stock AEB feature
    values.update({
      "sig_acljem" : 0,
      "sig_dhpdlz" : 0,
    })

  data = packer.make_can_msg("CID_CKFVKC", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_CKFVKC", CanBus.ESC, values)


def create_steering_control_angle_mode(packer, CP, cam_msg: dict, active, hud_control, keep_lkas_passive, counter):
  values = {}
  values = {s: cam_msg[s] for s in [
    "sig_blhzkt",
    "sig_xncfwm",
    "sig_jpejsb",
    "sig_hnvcoz",
    "sig_dgabuz",
    "sig_dhzbjn",
    "sig_acljem",
    "sig_ryesga",
    "sig_dhpdlz",
    "sig_mtvear",
    "sig_iqnige",
    "sig_veewby",
    "sig_svxlkf",
    "sig_ewlilf",
    "sig_nqnxwq",
    "sig_rswabp",
    "sig_emcfnl",
  ]}

  values["sig_ylmsdh"] = 0
  values["sig_rwxpii"] = 0
  values["sig_fkhfuz"] = counter

  if active:
    values.update({
      "sig_nqnxwq" : 0 if keep_lkas_passive else 3,
      "sig_xncfwm":  3 if hud_control.leftLaneDepart  else int(hud_control.leftLaneVisible) + 1,
      "sig_ewlilf": 3 if hud_control.rightLaneDepart else int(hud_control.rightLaneVisible) + 1,
    })

  data = packer.make_can_msg("CID_CKFVKC", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_CKFVKC", CanBus.ESC, values)

# MPC -> Panda -> EPS
def create_angle_control(packer, CP, cam_msg: dict, req_angle, max_torque, active, counter):
  values = {}
  values = {s: cam_msg[s] for s in [
    "sig_rqounr",
    "sig_czcyzi",
    "sig_ryesga",
    "sig_dhpdlz",
    "sig_dxperu",
    "sig_acljem",
    "sig_spcqot",
    "sig_qxelxx",
  ]}

  values["sig_fkhfuz"] = counter

  if active:
    values.update({
      "sig_acljem" : req_angle,
      "sig_dhpdlz" : 1,
      "sig_ryesga" : 0,
      "sig_rqounr" : max_torque,
      "sig_czcyzi" : -max_torque,
    })
  else:
    values.update({
      "sig_dhpdlz" : 0,
      "sig_ryesga" : 1,
    })

  data = packer.make_can_msg("CID_LYVHKX", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_LYVHKX", CanBus.ESC, values)

# modified stock long control
def acc_cmd_modified_stock_long(packer, CP, cam_msg: dict, adas_set_dist, mrr_leaddist, modlongActive, counter):
  values = {}

  values = {s: cam_msg[s] for s in [
    "sig_vgwrtg",
    "sig_gslhux",
    "sig_jhlyxc",
    "sig_sjbqqe",
    "sig_mkkpcc",
    "sig_ylyfyg",
    "sig_yqmigu",
    "sig_ngxiwe",
    "sig_keaynz",
    "sig_eqfgrt",
    "sig_zzfafm",
    "sig_wzwsop",
    "sig_ikvtku",
  ]}

  values["sig_fkhfuz"] = counter


  if modlongActive :
    accel_mpc = values["sig_vgwrtg"]
    jerkupper_mpc = values["sig_sjbqqe"]
    jerklower_mpc = values["sig_ylyfyg"]
    if accel_mpc > 0 : #accel
      if adas_set_dist == 3:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_POS_3BAR)
      elif adas_set_dist == 2:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_POS_2BAR)
      elif adas_set_dist == 1:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_POS_1BAR)
      else:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_POS_4BAR)
    else:
      if adas_set_dist == 3:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_NEG_3BAR)
      elif adas_set_dist == 2:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_NEG_2BAR)
      elif adas_set_dist == 1:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_NEG_1BAR)
      else:
        factor = np.interp(mrr_leaddist, Tuning.K_ACCEL_BP, Tuning.K_ACCEL_NEG_4BAR)

    accel = accel_mpc * factor
    jerkupper = jerkupper_mpc# * factor
    jerklower = jerklower_mpc# * factor
    values.update({
      "sig_vgwrtg" : accel,
      "sig_sjbqqe" : jerkupper,
      "sig_ylyfyg" : jerklower
    })

  data = packer.make_can_msg("CID_GNJIFO", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_GNJIFO", CanBus.ESC, values)

# op long control
def acc_cmd(packer, CP, cam_msg: dict, byd_jerk, accel, rfss, sss, longActive, counter):
  values = {}

  values = {s: cam_msg[s] for s in [
    "sig_vgwrtg",
    "sig_gslhux",
    "sig_jhlyxc",
    "sig_sjbqqe",
    "sig_mkkpcc",
    "sig_ylyfyg",
    "sig_yqmigu",
    "sig_ngxiwe",
    "sig_keaynz",
    "sig_eqfgrt",
    "sig_zzfafm",
    "sig_wzwsop",
    "sig_ikvtku",
  ]}
  values["sig_fkhfuz"] = counter
  #jerk_base_upper = np.interp(mrr_leaddist, CarControllerParams.K_jerk_xp, CarControllerParams.K_jerk_base_upper_fp)
  #jerk_base_lower = np.interp(mrr_leaddist, CarControllerParams.K_jerk_xp, CarControllerParams.K_jerk_base_lower_fp)

  #if (accel < 0): #use lower factor
  #  jerk_upper = jerk_base_upper
  #  jerk_lower = jerk_base_lower + accel * CarControllerParams.K_accel_jerk_lower
  #else:
  #  jerk_upper = jerk_base_upper + accel * CarControllerParams.K_accel_jerk_upper
  #  jerk_lower = jerk_base_lower

  if longActive :
    values.update({
      "sig_vgwrtg" : accel,
      "sig_gslhux" : byd_jerk.cb_upper, #0.05 if mrr_leaddist > 50 else 0.10,
      "sig_jhlyxc" : byd_jerk.cb_lower, #0.05 if mrr_leaddist > 50 else 0.10,
      "sig_sjbqqe" : byd_jerk.jerk_u, #jerk_upper,
      "sig_ylyfyg" : byd_jerk.jerk_l, #jerk_lower,
      "sig_yqmigu" : rfss,
      "sig_ngxiwe" : sss,
    })

  data = packer.make_can_msg("CID_GNJIFO", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_GNJIFO", CanBus.ESC, values)

# send fake torque feedback from eps to trick MPC, preventing DTC, so that safety features such as AEB still working
def create_fake_318(packer, CP, esc_msg: dict, faketorque, laks_reqprepare, laks_active, fake_driver_torque, enabled, counter):
  values = {}

  values = {s: esc_msg[s] for s in [
    "sig_svqgog",
    "sig_ssdjsq",
    "sig_mkkpcc",
    "sig_pmfztj",
    "sig_vigedh",
    "sig_ziwrqf",
    "sig_llbiws",
    "sig_fblcqm",
    "sig_raxtbr",
    "sig_kemcnp",
    "sig_japiza",
  ]}

  values["sig_svshoe"] = 0
  values["sig_fkhfuz"] = counter

  if enabled :
    if laks_active:
      values.update({
        "sig_svqgog" : 2,
        "sig_ziwrqf" : faketorque,
        "sig_raxtbr" : fake_driver_torque,
      })
    elif laks_reqprepare:
      values.update({
        "sig_svqgog" : 1,
        "sig_ziwrqf" : 0,
        "sig_raxtbr" : fake_driver_torque,
      })
    else:
      values.update({
        "sig_svqgog" : 0,
        "sig_ziwrqf" : 0,
      })

  data = packer.make_can_msg("CID_AVHANZ", CanBus.MPC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_AVHANZ", CanBus.MPC, values)

def create_fake_1FC(packer, CP, esc_msg: dict, faketorque, laks_reqprepare, laks_active , enabled, counter):
  values = {}

  values = {s: esc_msg[s] for s in [
    "sig_svqgog",
    "sig_ssdjsq",
    "sig_mkkpcc",
    "sig_raxtbr",
    "sig_bfgogu",
    "sig_ziwrqf",
    "sig_zcmzho",
    "sig_raiang",
    "sig_mefafy",
  ]}

  values["sig_svshoe"] = 0
  values["sig_fkhfuz"] = counter

  if enabled :
    if laks_active:
      values.update({
        "sig_svqgog" : 2,
        "sig_ziwrqf" : faketorque,
      })
    else:
      values.update({
        "sig_svqgog" : 1,
        "sig_ziwrqf" : 0,
      })

  data = packer.make_can_msg("CID_LYGAQH", CanBus.MPC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_LYGAQH", CanBus.MPC, values)

def create_adas_hud(packer, cam_msg: dict, setSpeed, useCustomSpeed, counter):
  values = {}

  values = {s: cam_msg[s] for s in [
    "sig_zvrrzq",
    "sig_jsuvij",
    "sig_lpxwvx",
    "sig_hxibve",
    "sig_qhfxsv",
    "sig_tbigjb",
    "sig_mkkpcc",
    "sig_nglvqc",
    "sig_yghuhi",
    "sig_ezxxoj",
    "sig_hnvcoz",
    "sig_dplmsn",
    "sig_qavxnu",
    "sig_uakuch",
    "sig_qmxals",
  ]}
  values["sig_fkhfuz"] = counter
  if useCustomSpeed:
    values.update({
      "sig_zvrrzq" : setSpeed
    })

  data = packer.make_can_msg("CID_RZVTOX", CanBus.ESC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_RZVTOX", CanBus.ESC, values)

#send fake pcm buttons to MPC
def create_mpc_pcm_button(packer, pt_msg: dict, freeze_updown_input, counter):
  values = {}

  values = {s: pt_msg[s] for s in [
    "sig_yqnydy",
    "sig_bxlcyr",
    "sig_pbnynq",
    "sig_trmxke",
    "sig_gxxhjn",
    "sig_ajimyq",
    "sig_sdqkos",
    "sig_fxxgwq",
    "sig_bohbqo",
    "sig_kfqrly",
    "sig_uomncs",
    "sig_zbwjzs",
    "sig_zndlfc",
    "sig_skgpdn",
    "sig_cbkuwq",
    "sig_ntsbuw",
  ]}
  values["sig_fkhfuz"] = counter

  if freeze_updown_input:
    values.update({
      "sig_pbnynq" : 0
    })

  data = packer.make_can_msg("CID_BPDGFH", CanBus.MPC, values)[1]
  values["sig_waixqt"] = byd_checksum(0xAF, data)
  return packer.make_can_msg("CID_BPDGFH", CanBus.MPC, values)