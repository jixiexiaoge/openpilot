def create_steering_control(packer, values, angle, active, counter):
  values = values.copy()
  values.update({
    "STEER_ANGLE_CMD": angle,
    "STEER_REQUEST": active,
    "COUNTER": counter,
  })
  return packer.make_can_msg("STEERING_LKA", 0, values)

def create_eps_control(packer, values, active, counter):
  values = values.copy()
  status_val = 1 if active else 0
  values.update({
    "LKA_STATE": status_val,
    "COUNTER": counter,
  })
  return packer.make_can_msg("STEER_TORQUE_SENSOR", 0, values)

def create_acc_control(packer, values, accel, counter, enabled, acctrq):
  values = values.copy()
  values.update({
    "ACCEL_CMD": accel,
    "COUNTER": counter,
    "ACCEL_ACTIVE": enabled,
    "ACCEL_REQUEST": acctrq,
  })
  return packer.make_can_msg("ACC_CONTROL", 0, values)

def create_acc_set_speed(packer, values, counter, speed):
  values = values.copy()
  values.update({
    "COUNTER": counter,
    "SET_SPEED": speed,
  })
  return packer.make_can_msg("ACC_HUD", 0, values)

def create_acc_hud(packer, values, counter, enabled, steering_pressed):
  values = values.copy()
  values.update({
    "COUNTER": counter,
    "ACC_IACC_HWA_ENABLE": enabled,
    "STEER_PRESSED": steering_pressed,
  })
  return packer.make_can_msg("ACC_STATE", 0, values)
