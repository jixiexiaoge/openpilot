
def xor_checksum(data):
  checksum = 0
  for byte in data:
    checksum ^= byte
  return checksum

def create_steering_control(packer, msg, angle, active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update({
    "ACC_SteeringAngleSub_1BA": angle,
    "ACC_SteeringAngleReq_1BA": active,
    "ACC_RollingCounter_1BA": counter,
    "COUNTER_1": counter,
    "COUNTER_2": counter,
    "COUNTER_3": counter,
    "STEER_LIMIT": 9.50,
    "STEER_STATUS": 0,
  })
  for i in range(4):
    dat = packer.make_can_msg("GW_1BA", 0, values)[1]
    name = "CHECKSUM" if i == 0 else f"CHECKSUM_{i}"
    values[name] = xor_checksum(dat[i*8 : i*8 + 7])
  return packer.make_can_msg("GW_1BA", 0, values)

def create_eps_control(packer, msg, active, counter):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update({
    "EPS_LatCtrlAvailabilityStatus": 1 if active else 0,
    "EPS_RollingCounter_17E": counter,
  })
  dat = packer.make_can_msg("GW_17E", 2, values)[1]
  values["CHECKSUM"] = xor_checksum(dat[:7])
  return packer.make_can_msg("GW_17E", 2, values)

def create_acc_control(packer, msg, accel, counter, enabled, acctrq):
  values = {s: msg[s] for s in msg} if msg else {}

  values.update({
    "ACC_Acceleration_24E": accel,
    "ACC_RollingCounter_24E": counter,
    "COUNTER_1": counter,
    "COUNTER_2": counter,
    "COUNTER_3": counter,
    "ACC_ACCMode": 3 if enabled else 2,
    "ACC_ACCEnable": 1 if enabled else 0,
    "ACC_ACCReq": 1 if enabled else 0,
    "sig_099": acctrq,
  })

  for i in range(4):
    dat = packer.make_can_msg("GW_244", 0, values)[1]
    name = "CHECKSUM" if i == 0 else f"CHECKSUM_{i}"
    values[name] = xor_checksum(dat[i*8 : i*8 + 7])
  return packer.make_can_msg("GW_244", 0, values)

def create_acc_set_speed(packer, msg, counter, speed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update({
    "ACC_SetSpeed": speed,
    "ACC_DistanceLevel": 3,
    "ACC_RollingCounter_35E": counter,
  })
  for i in range(2, 9):
    values[f"COUNTER_{i}"] = counter

  for i in range(1, 9):
    dat = packer.make_can_msg("GW_307", 0, values)[1]
    name = f"CHECKSUM_{i}"
    values[name] = xor_checksum(dat[(i-1)*8 : (i-1)*8 + 7])
  return packer.make_can_msg("GW_307", 0, values)

def create_acc_hud(packer, msg, counter, enabled, steering_pressed):
  values = {s: msg[s] for s in msg} if msg else {}
  values.update({
    "ACC_IACCHWAEnable": 1 if enabled else 0,
    "STEER_PRESSED": 1 if steering_pressed else 0,
    "ACC_IACCHWAMode": 2 if enabled else 0,
    "ACC_RollingCounter_36D": counter,
  })
  for i in range(2, 9):
    values[f"COUNTER_{i}"] = counter

  for i in range(1, 9):
    dat = packer.make_can_msg("GW_31A", 0, values)[1]
    name = f"CHECKSUM_{i}"
    values[name] = xor_checksum(dat[(i-1)*8 : (i-1)*8 + 7])
  return packer.make_can_msg("GW_31A", 0, values)
