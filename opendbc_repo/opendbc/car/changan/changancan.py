from opendbc.car import structs

def create_1BA_command(packer, values, angle, active, counter):
  """
  Creates the steering command message (GW_1BA).

  Args:
    packer: CANPacker instance
    values: Dictionary of current signal values (to preserve other signals)
    angle: Steering angle command
    active: Steering active flag (1 or 0)
    counter: Rolling counter

  Returns:
    Packed CAN message tuple (addr, data, bus)
  """
  # Create a copy to not modify the original dict
  values = values.copy()

  values.update({
    "ACC_SteeringAngleCmd": angle,
    "ACC_SteeringActive": active,
    "ACC_RollingCounter_1BA": counter,
  })

  # Note: If the car requires a checksum, it should be calculated here and
  # added to values['Checksum'] (if defined in DBC).
  # Current DBC implementation for Changan Z6 does not specify a checksum signal.

  return packer.make_can_msg("GW_1BA", 0, values)

def create_17E_command(packer, values, active, counter):
  """
  Creates the EPS status message (GW_17E).

  Args:
    packer: CANPacker instance
    values: Dictionary of current signal values
    active: Lateral control availability status (mapped to 1 or 0)
    counter: Rolling counter

  Returns:
    Packed CAN message tuple (addr, data, bus)
  """
  values = values.copy()

  # Map boolean/status to signal value
  # Assuming 1 = Active/Available, 0 = Inactive
  # DBC defines EPS_LatCtrlAvailabilityStatus as 2 bits [0|3]
  status_val = 1 if active else 0

  values.update({
    "EPS_LatCtrlAvailabilityStatus": status_val,
    "EPS_RollingCounter_17E": counter,
  })

  return packer.make_can_msg("GW_17E", 0, values)

def create_244_command(packer, values, accel, counter, enabled, acctrq):
    values = values.copy()
    values.update({
        "ACC_AccelCmd": accel,
        "ACC_RollingCounter_24E": counter,
        "ACC_AccelActive": enabled,
        "ACC_AccelRequest": acctrq,
    })
    return packer.make_can_msg("GW_244", 0, values)

def create_307_command(packer, values, counter, speed):
    values = values.copy()
    values.update({
        "ACC_RollingCounter_35E": counter,
        "ACC_SetSpeed": speed,
    })
    return packer.make_can_msg("GW_307", 0, values)

def create_31A_command(packer, values, counter, enabled, steering_pressed):
    values = values.copy()
    values.update({
        "ACC_RollingCounter_36D": counter,
        "ACC_IACCHWAEnable": enabled,
        "ACC_SteeringPressed": steering_pressed,
    })
    return packer.make_can_msg("GW_31A", 0, values)
