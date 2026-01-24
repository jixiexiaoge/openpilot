import numpy as np

def crc_calculate_crc8(data):
  crc = 0xFF
  for byte in data:
    crc ^= byte
    for _ in range(8):
      if crc & 0x80:
        crc = ((crc << 1) ^ 0x1D) & 0xFF
      else:
        crc = (crc << 1) & 0xFF
  return crc ^ 0xFF


def create_steering_control(packer, msg, angle, active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_SteeringAngleSub_1BA": angle,
      "ACC_SteeringAngleReq_1BA": active,
      "Counter_1BA": counter,
      "STEER_LIMIT_Down": 9.50,
      "STEER_LIMIT_Up": 9.50,
    }
  )
  dat = packer.make_can_msg("GW_1BA", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_1BA", 0, values)


def create_eps_control(packer, msg, lat_active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "EPS_LatCtrlAvailabilityStatus": 1 if lat_active else 0,
      "EPS_RollingCounter_17E": counter,
    }
  )
  dat = packer.make_can_msg("GW_17E", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_17E", 0, values)


def create_acc_control(packer, msg, accel, counter, enabled, acctrq):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_Acceleration_24E": accel,
      "ACC_RollingCounter_24E": counter,
      "COUNTER_1": counter,
      "ACC_ACCMode": 3 if enabled else 2,
      "ACC_ACCEnable": 1 if enabled else 0,
      "ACC_ACCReq": 1 if enabled else 0,
      "sig_099": acctrq,
    }
  )
  dat = packer.make_can_msg("GW_244", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])
  return packer.make_can_msg("GW_244", 0, values)


def create_acc_set_speed(packer, msg, counter, speed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "vCruise": speed,
      "ACC_DistanceLevel": 3,
      "Counter_35E": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "COUNTER_4": counter,
    }
  )
  dat = packer.make_can_msg("GW_307", 0, values)[1]
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_307", 0, values)


def create_acc_hud(packer, msg, counter, enabled, steering_pressed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "cruiseState": 1 if enabled else 0,
      "steeringPressed": 1 if steering_pressed else 0,
      "ACC_IACCHWAMode": 3 if enabled else 0,
      "Counter_36D": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "COUNTER_4": counter,
    }
  )
  dat = packer.make_can_msg("GW_31A", 0, values)[1]
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_31A", 0, values)
