"""CAN message creation functions for Changan vehicles.

This module handles CAN message packing for Changan Z6/Z6 iDD control messages.
All messages use SAE J1850 CRC8 checksums that must match panda safety implementation.
"""

import numpy as np


def crc_calculate_crc8(data):
  """Calculate SAE J1850 CRC8 checksum.

  Polynomial: 0x1D (x8 + x4 + x3 + x2 + 1)
  Initial value: 0xFF
  Final XOR: 0xFF

  This implementation must exactly match the panda firmware checksum calculation
  to avoid "Controls Mismatch" errors.

  Args:
    data: Bytes to calculate checksum over (typically first 7 bytes of message)

  Returns:
    CRC8 checksum byte
  """
  crc = 0xFF
  for byte in data:
    crc ^= byte
    for _ in range(8):
      if crc & 0x80:
        crc = ((crc << 1) ^ 0x1D) & 0xFF
      else:
        crc = (crc << 1) & 0xFF
  return crc ^ 0xFF


def create_steering_control(packer, msg, angle, active, counter, bus=0):
  """
  【信号 0x1BA】 生成转向控制报文 (GW_1BA - 8 bytes)

  ⚠️ IMPORTANT BUS CONFIGURATION:
  - Default bus=0 (PT-CAN) matches mpCode implementation
  - EPS system expects steering commands on PT-CAN (Bus 0)

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    angle: 期望方向盘转角 (单位：度)
    active: 转向系统接管标志 (1=接管, 0=旁路)
    counter: 滚动计数器 (0-15)
    bus: CAN bus (default 0 for PT-CAN, mpCode uses 0)

  Returns:
    CAN message tuple (address, data)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_SteeringAngleSub_1BA": angle,  # sig_077: Steering angle request
      "ACC_SteeringAngleReq_1BA": active,  # sig_078: Lateral control active
      "Counter_1BA": counter,              # sig_079: Rolling counter
      "STEER_LIMIT_Down": -9.50,          # sig_076: Lower steering rate limit
      "STEER_LIMIT_Up": 9.50,             # sig_075: Upper steering rate limit
    }
  )
  # Pack first 7 bytes for CRC calculation
  dat = packer.make_can_msg("GW_1BA", bus, values)[1]
  # sig_080: CRC8 checksum at byte 7
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_1BA", bus, values)


def create_eps_control(packer, msg, lat_active, counter, bus=0):
  """
  【信号 0x17E】 生成 EPS 状态授权报文 (GW_17E - 8 bytes)

  ⚠️ IMPORTANT BUS CONFIGURATION:
  - Changed to Bus 0 (PT-CAN) to match other control messages and ensure stability


  This is a heartbeat message that tells the EPS system whether lateral control is available.
  Must be sent continuously to maintain steering control authority.

  IMPORTANT: Preserves ALL signals from stock ECU message to maintain compatibility
  with undocumented EPS control bits (matching mpCode behavior).
  """
  # ⚠️ CRITICAL: Preserve ALL unknown bits from msg (mpCode preserves sig_033-041)
  # This ensures we don't break undocumented EPS features
  values = {s: msg[s] for s in msg} if msg else {}

  # Update only the signals we need to control
  values.update(
    {
      "EPS_LatCtrlAvailabilityStatus": 1 if lat_active else 0, # 1=Available, 0=Unavailable
      "EPS_RollingCounter_17E": counter,                        # Rolling counter (0-15)
    }
  )

  # ⚠️ IMPORTANT: CRC must be calculated with Bus 0 packing to match stock ECU expectations
  # even though the message is sent on Bus 2 (CAM-CAN)
  dat = packer.make_can_msg("GW_17E", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_17E", bus, values)


def create_acc_control(packer, msg, accel, counter, enabled, acctrq, bus=0):
  """
  【信号 0x244】 生成 ACC 加减速与扭矩控制核心指令 (GW_244 - 32 bytes)

  This is the primary longitudinal control message containing both acceleration
  requests and torque mapping. Critical for smooth power delivery and stop-and-go.

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    accel: 加速度请求 (m/s²), range: -3.5 to +2.0
    counter: 滚动计数器 (0-15)
    enabled: ACC系统激活状态 (True=Active/Green, False=Ready/White)
    acctrq: 扭矩转换请求 (ACC_TorqueReq), range: -10000 to +10000, offset: -5000

  Returns:
    CAN message tuple (address, data)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_Acceleration_24E": accel,                    # sig_081: Acceleration request (0.05 m/s² scale)
      "ACC_RollingCounter_24E": counter,                # sig_092: Rolling counter (first segment)
      "COUNTER_1": counter,                             # sig_103: Rolling counter (second segment)
      "ACC_ACCMode": 3 if enabled else 2,               # sig_091: ACC mode (3=Active/Green, 2=Ready/White)
      "ACC_ACCEnable": 1 if enabled else 0,             # sig_098: ACC enable flag
      "ACC_ACCReq": 1 if enabled else 0,                # Duplicate enable flag
      "ACC_ControlActive": 1,                           # Control active flag
      # ⚠️ Improved 3-tier brake logic (matching mpCode for better smoothness)
      # Tier 1: -0.1 to -0.5 → No brake light (gradual regen)
      # Tier 2: -0.5 to -1.5 → Brake light (moderate braking)
      # Tier 3: < -1.5 → Brake light (emergency braking)
      "ACC_BrakeActive": 1 if accel < -0.5 else 0,      # Brake activation (improved threshold)
      "ACC_TorqueReq": acctrq,                         # Torque signal (critical for iDD smoothness)
      "ACC_LongControlActive": 1 if enabled else 0,     # Longitudinal control active
      # ⚠️ CRITICAL: AEB/FCW signals - must be set to prevent dashboard warnings
      "ACC_FCWPreWarning": 0,                          # FCW (Forward Collision Warning) - 0 = No Warning
      "ACC_AEBCtrlType": 0,                            # AEB (Automatic Emergency Braking) - 0 = No AEB Active
    }
  )
  dat = packer.make_can_msg("GW_244", bus, values)[1]
  # 32-byte message has multiple CRC segments
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])      # sig_093: First segment CRC
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])  # sig_104: Second segment CRC
  return packer.make_can_msg("GW_244", bus, values)


def create_acc_set_speed(packer, msg, counter, speed, bus=0):
  """
  【信号 0x307】 同步界面设置车速到仪表盘 (GW_307 - 64 bytes)

  ⚠️ IMPORTANT BUS CONFIGURATION:
  - Default bus=0 (PT-CAN) matches mpCode implementation
  - Instrument cluster expects speed info on PT-CAN

  Sends cruise control set speed to instrument cluster for display.
  Also includes following distance level setting.

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    counter: 滚动计数器 (0-15)
    speed: 巡航设定时速 (km/h), range: 0-250

  Returns:
    CAN message tuple (address, data)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "vCruise": speed,                    # sig_336: Cruise set speed (0.0078125 km/h scale)
      "ACC_DistanceLevel": 3,              # sig_339: Following distance (0-3, default 3)
      "Counter_35E": counter,              # sig_342: Rolling counter (segment 1)
      "COUNTER_2": counter,                # sig_346: Rolling counter (segment 2)
      "COUNTER_3": counter,                # sig_348: Rolling counter (segment 3)
      "COUNTER_4": counter,                # sig_354: Rolling counter (segment 4)
    }
  )
  dat = packer.make_can_msg("GW_307", bus, values)[1]
  # 64-byte message has 4 CRC segments (8 bytes each)
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])      # sig_343: Segment 1 CRC
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])    # sig_347: Segment 2 CRC
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])   # sig_349: Segment 3 CRC
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])   # sig_355: Segment 4 CRC
  return packer.make_can_msg("GW_307", bus, values)


def create_acc_hud(packer, msg, counter, enabled, steering_pressed, bus=0):
  """
  【信号 0x31A】 生成仪表状态图标信号 (GW_31A - 64 bytes)

  ⚠️ IMPORTANT BUS CONFIGURATION:
  - Default bus=0 (PT-CAN) matches mpCode implementation
  - Instrument cluster expects HUD status on PT-CAN

  Controls the ACC/iACC icon display on the instrument cluster.
  Icons should display when openpilot is running, with different states for enabled/standby.

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    counter: 滚动计数器 (0-15)
    enabled: 纵向控制激活状态 (True=Green/Active icon, False=White/Standby icon)
    steering_pressed: 方向盘压力状态 (for hands-on-wheel warning)

  Returns:
    CAN message tuple (address, data)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      # ⚠️ CRITICAL: These determine ACC/iACC icon visibility and color
      "ACC_IACCHWAMode": 3 if enabled else 0,         # Mode: 0=Off/Ready, 3=Active(green) - Fixed: 2->0
      "ACC_IACCHWAEnable": 1,                          # System availability (1=icons can show)
      "ACC_IACCHWASignal": 1,                          # Additional availability signal
      "ACC_IACCHWAState1": 1,                          # Control state flag 1
      "ACC_IACCHWAState2": 1 if enabled else 0,        # Control state flag 2 - Fixed: 2->1 to match 1-bit DBC
      "steeringPressed": 1,                            # ⚠️ mpCode: Force 1 to improve handover


      # Supplementary states
      "cruiseState": 1 if enabled else 0,              # Cruise state flag


      # Rolling counters for 4 segments of 64-byte message
      "Counter_36D": counter,                          # Segment 1 counter
      "COUNTER_2": counter,                            # Segment 2 counter
      "COUNTER_3": counter,                            # Segment 3 counter
      "COUNTER_4": counter,                            # Segment 4 counter
    }
  )
  dat = packer.make_can_msg("GW_31A", bus, values)[1]
  # 64-byte message has 4 CRC segments (same pattern as 0x307)
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])      # Segment 1 CRC
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])    # Segment 2 CRC
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])   # Segment 3 CRC
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])   # Segment 4 CRC
  return packer.make_can_msg("GW_31A", bus, values)
