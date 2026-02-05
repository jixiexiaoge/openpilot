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


def create_steering_control(packer, msg, angle, active, counter):
  """
  【信号 0x1BA】 生成转向控制报文 (GW_1BA - 8 bytes)

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    angle: 期望方向盘转角 (单位：度)
    active: 转向系统接管标志 (1=接管, 0=旁路)
    counter: 滚动计数器 (0-15)

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
  dat = packer.make_can_msg("GW_1BA", 0, values)[1]
  # sig_080: CRC8 checksum at byte 7
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_1BA", 0, values)


def create_eps_control(packer, msg, lat_active, counter):
  """
  【信号 0x17E】 生成 EPS 状态授权报文 (GW_17E - 8 bytes)

  This is a heartbeat message that tells the EPS system whether lateral control is available.
  Must be sent continuously to maintain steering control authority.

  Args:
    packer: CAN packer instance
    msg: Previous message values to preserve
    lat_active: 是否正在进行车道保持/转向辅助 (1=可用, 0=关闭)
    counter: 滚动计数器 (0-15)

  Returns:
    CAN message tuple (address, data)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "EPS_LatCtrlAvailabilityStatus": 1 if lat_active else 0,  # sig_055: Lateral control status
      "EPS_RollingCounter_17E": counter,                         # sig_042: Rolling counter
    }
  )
  dat = packer.make_can_msg("GW_17E", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])  # sig_043: CRC8 checksum
  return packer.make_can_msg("GW_17E", 0, values)


def create_acc_control(packer, msg, accel, counter, enabled, acctrq):
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
    acctrq: 扭矩转换请求 (sig_099), range: -10000 to +10000, offset: -5000

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
      "sig_084": 1,                                     # Control active flag
      "sig_088": 1 if accel < -0.1 else 0,             # Brake activation flag
      "sig_099": acctrq,                                # Torque signal (critical for iDD smoothness)
      "sig_100": 1 if enabled else 0,                   # Longitudinal control active
    }
  )
  dat = packer.make_can_msg("GW_244", 0, values)[1]
  # 32-byte message has multiple CRC segments
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])      # sig_093: First segment CRC
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])  # sig_104: Second segment CRC
  return packer.make_can_msg("GW_244", 0, values)


def create_acc_set_speed(packer, msg, counter, speed):
  """
  【信号 0x307】 同步界面设置车速到仪表盘 (GW_307 - 64 bytes)

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
  dat = packer.make_can_msg("GW_307", 0, values)[1]
  # 64-byte message has 4 CRC segments (8 bytes each)
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])      # sig_343: Segment 1 CRC
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])    # sig_347: Segment 2 CRC
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])   # sig_349: Segment 3 CRC
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])   # sig_355: Segment 4 CRC
  return packer.make_can_msg("GW_307", 0, values)


def create_acc_hud(packer, msg, counter, enabled, steering_pressed):
  """
  【信号 0x31A】 生成仪表状态图标信号 (64 字节报文)
  steering_pressed: 用于在仪表同步显示“手离开方向盘”或“压盘中”警告
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "cruiseState": 1 if enabled else 0,              # Cruise state flag
      "steeringPressed": 1 if steering_pressed else 0, # Steering pressure warning
      "ACC_IACCHWAMode": 3 if enabled else 0,          # sig_408: IACC mode (3=Active icon)
      "ACC_IACCHWAEnable": 1,                          # sig_390: Always-on signal 1
      "sig_398": 1,                                    # Always-on signal 2
      "sig_410": 1,                                    # Control state 1
      "sig_411": 2 if enabled else 0,                  # Control state 2
      "Counter_36D": counter,                          # sig_395: Rolling counter (segment 1)
      "COUNTER_2": counter,                            # sig_406: Rolling counter (segment 2)
      "COUNTER_3": counter,                            # sig_415: Rolling counter (segment 3)
      "COUNTER_4": counter,                            # sig_422: Rolling counter (segment 4)
    }
  )
  dat = packer.make_can_msg("GW_31A", 0, values)[1]
  # 同 0x307 进行分段校验填充
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_31A", 0, values)
