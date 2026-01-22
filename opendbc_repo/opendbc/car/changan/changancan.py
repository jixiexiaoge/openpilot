crc8_tab = [
  0x0,
  0x1D,
  0x3A,
  0x27,
  0x74,
  0x69,
  0x4E,
  0x53,
  0xE8,
  0xF5,
  0xD2,
  0xCF,
  0x9C,
  0x81,
  0xA6,
  0xBB,
  0xCD,
  0xD0,
  0xF7,
  0xEA,
  0xB9,
  0xA4,
  0x83,
  0x9E,
  0x25,
  0x38,
  0x1F,
  0x2,
  0x51,
  0x4C,
  0x6B,
  0x76,
  0x87,
  0x9A,
  0xBD,
  0xA0,
  0xF3,
  0xEE,
  0xC9,
  0xD4,
  0x6F,
  0x72,
  0x55,
  0x48,
  0x1B,
  0x6,
  0x21,
  0x3C,
  0x4A,
  0x57,
  0x70,
  0x6D,
  0x3E,
  0x23,
  0x4,
  0x19,
  0xA2,
  0xBF,
  0x98,
  0x85,
  0xD6,
  0xCB,
  0xEC,
  0xF1,
  0x13,
  0xE,
  0x29,
  0x34,
  0x67,
  0x7A,
  0x5D,
  0x40,
  0xFB,
  0xE6,
  0xC1,
  0xDC,
  0x8F,
  0x92,
  0xB5,
  0xA8,
  0xDE,
  0xC3,
  0xE4,
  0xF9,
  0xAA,
  0xB7,
  0x90,
  0x8D,
  0x36,
  0x2B,
  0xC,
  0x11,
  0x42,
  0x5F,
  0x78,
  0x65,
  0x94,
  0x89,
  0xAE,
  0xB3,
  0xE0,
  0xFD,
  0xDA,
  0xC7,
  0x7C,
  0x61,
  0x46,
  0x5B,
  0x8,
  0x15,
  0x32,
  0x2F,
  0x59,
  0x44,
  0x63,
  0x7E,
  0x2D,
  0x30,
  0x17,
  0xA,
  0xB1,
  0xAC,
  0x8B,
  0x96,
  0xC5,
  0xD8,
  0xFF,
  0xE2,
  0x26,
  0x3B,
  0x1C,
  0x1,
  0x52,
  0x4F,
  0x68,
  0x75,
  0xCE,
  0xD3,
  0xF4,
  0xE9,
  0xBA,
  0xA7,
  0x80,
  0x9D,
  0xEB,
  0xF6,
  0xD1,
  0xCC,
  0x9F,
  0x82,
  0xA5,
  0xB8,
  0x3,
  0x1E,
  0x39,
  0x24,
  0x77,
  0x6A,
  0x4D,
  0x50,
  0xA1,
  0xBC,
  0x9B,
  0x86,
  0xD5,
  0xC8,
  0xEF,
  0xF2,
  0x49,
  0x54,
  0x73,
  0x6E,
  0x3D,
  0x20,
  0x7,
  0x1A,
  0x6C,
  0x71,
  0x56,
  0x4B,
  0x18,
  0x5,
  0x22,
  0x3F,
  0x84,
  0x99,
  0xBE,
  0xA3,
  0xF0,
  0xED,
  0xCA,
  0xD7,
  0x35,
  0x28,
  0xF,
  0x12,
  0x41,
  0x5C,
  0x7B,
  0x66,
  0xDD,
  0xC0,
  0xE7,
  0xFA,
  0xA9,
  0xB4,
  0x93,
  0x8E,
  0xF8,
  0xE5,
  0xC2,
  0xDF,
  0x8C,
  0x91,
  0xB6,
  0xAB,
  0x10,
  0xD,
  0x2A,
  0x37,
  0x64,
  0x79,
  0x5E,
  0x43,
  0xB2,
  0xAF,
  0x88,
  0x95,
  0xC6,
  0xDB,
  0xFC,
  0xE1,
  0x5A,
  0x47,
  0x60,
  0x7D,
  0x2E,
  0x33,
  0x14,
  0x9,
  0x7F,
  0x62,
  0x45,
  0x58,
  0xB,
  0x16,
  0x31,
  0x2C,
  0x97,
  0x8A,
  0xAD,
  0xB0,
  0xE3,
  0xFE,
  0xD9,
  0xC4,
]


def crc_calculate_crc8(data):
  crc = 0xFF
  for byte in data:
    crc = crc8_tab[crc ^ byte]
  return crc ^ 0xFF


def xor_checksum(data):
  checksum = 0
  for byte in data:
    checksum ^= byte
  return checksum


def create_steering_control(packer, msg, angle, active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_SteeringAngleSub_1BA": angle,
      "ACC_SteeringAngleReq_1BA": active,
      "ACC_RollingCounter_1BA": counter,
      "COUNTER_1": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "STEER_LIMIT": 9.50,
      "STEER_STATUS": 0,
    }
  )
  dat = packer.make_can_msg("GW_1BA", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_1BA", 0, values)


def create_eps_control(packer, msg, lat_active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "EPS_LatCtrlAvailabilityStatus": 1 if lat_active else 0,
      "EPS_RollingCounter_17E": counter,
    }
  )
  dat = packer.make_can_msg("GW_17E", 2, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_17E", 2, values)


def create_acc_control(packer, msg, accel, counter, enabled, acctrq):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_Acceleration_24E": accel,
      "ACC_RollingCounter_24E": counter,
      "COUNTER_1": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "ACC_ACCMode": 3 if enabled else 2,
      "ACC_ACCEnable": 1 if enabled else 0,
      "ACC_ACCReq": 1 if enabled else 0,
      "sig_099": acctrq,
    }
  )
  dat = packer.make_can_msg("GW_244", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_244", 0, values)


def create_acc_set_speed(packer, msg, counter, speed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_SetSpeed": speed,
      "ACC_DistanceLevel": 3,
      "ACC_RollingCounter_35E": counter,
    }
  )
  for i in range(2, 9):
    values[f"COUNTER_{i}"] = counter

  dat = packer.make_can_msg("GW_307", 0, values)[1]
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  values["CHECKSUM_5"] = crc_calculate_crc8(dat[32:39])
  values["CHECKSUM_6"] = crc_calculate_crc8(dat[40:47])
  values["CHECKSUM_7"] = crc_calculate_crc8(dat[48:55])
  values["CHECKSUM_8"] = crc_calculate_crc8(dat[56:63])
  return packer.make_can_msg("GW_307", 0, values)


def create_acc_hud(packer, msg, counter, enabled, steering_pressed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_IACCHWAEnable": 1 if enabled else 0,
      "STEER_PRESSED": 1 if steering_pressed else 0,
      "ACC_IACCHWAMode": 2 if enabled else 0,
      "ACC_RollingCounter_36D": counter,
    }
  )
  for i in range(2, 9):
    values[f"COUNTER_{i}"] = counter

  dat = packer.make_can_msg("GW_31A", 0, values)[1]
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  values["CHECKSUM_5"] = crc_calculate_crc8(dat[32:39])
  values["CHECKSUM_6"] = crc_calculate_crc8(dat[40:47])
  values["CHECKSUM_7"] = crc_calculate_crc8(dat[48:55])
  values["CHECKSUM_8"] = crc_calculate_crc8(dat[56:63])
  return packer.make_can_msg("GW_31A", 0, values)
