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
  【信号 0x1BA】 生成转向控制报文
  angle: 期望方向盘转角 (单位：度)
  active: 转向系统接管标志 (1=接管, 0=旁路)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_SteeringAngleSub_1BA": angle,
      "ACC_SteeringAngleReq_1BA": active,
      "Counter_1BA": counter,
      "STEER_LIMIT_Down": 9.50, # 转向限制斜率
      "STEER_LIMIT_Up": 9.50,
    }
  )
  # 先打包前 7 字节
  dat = packer.make_can_msg("GW_1BA", 0, values)[1]
  # 按照 DBC 定义：校验位在第 8 字节 (Byte 7)
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_1BA", 0, values)


def create_eps_control(packer, msg, lat_active, counter):
  """
  【信号 0x17E】 生成 EPS 状态授权报文 (转向控制的影子心跳)
  lat_active: 是否正在进行车道保持/转向辅助
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "EPS_LatCtrlAvailabilityStatus": 1 if lat_active else 0, # 1=可用, 0=关闭
      "EPS_RollingCounter_17E": counter,
    }
  )
  dat = packer.make_can_msg("GW_17E", 0, values)[1]
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  return packer.make_can_msg("GW_17E", 0, values)


def create_acc_control(packer, msg, accel, counter, enabled, acctrq):
  """
  【信号 0x244】 生成 ACC 加减速与扭矩控制核心指令 (32 字节报文)
  accel: 加速度请求 (m/s2)
  acctrq: 扭矩转换请求 (对应 sig_099 信号)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "ACC_Acceleration_24E": accel,
      "ACC_RollingCounter_24E": counter,
      "COUNTER_1": counter, # DBC 中的冗余计数位
      "ACC_ACCMode": 3 if enabled else 2, # 3=Active(绿屏), 2=Ready(白图标)
      "ACC_ACCEnable": 1 if enabled else 0,
      "ACC_ACCReq": 1 if enabled else 0,
      "sig_099": acctrq, # 扭矩主信号，对 iDD 车型平顺性至关重要
    }
  )
  dat = packer.make_can_msg("GW_244", 0, values)[1]
  # 32 字节报文通常有多段校验和，依照 DBC 定义填充前两段即可
  values["CHECKSUM"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[8:15])
  return packer.make_can_msg("GW_244", 0, values)


def create_acc_set_speed(packer, msg, counter, speed):
  """
  【信号 0x307】 同步界面设置车速到仪表盘 (64 字节报文)
  speed: 巡航设定时速 (km/h)
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "vCruise": speed,
      "ACC_DistanceLevel": 3, # 默认三格跟车距离
      "Counter_35E": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "COUNTER_4": counter,
    }
  )
  dat = packer.make_can_msg("GW_307", 0, values)[1]
  # 64 字节报文实施分段校验 (8 字节一周期)
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_307", 0, values)


def create_acc_hud(packer, msg, counter, enabled, steering_pressed):
  """
  【信号 0x31A】 生成仪表状态图标信号 (64 字节报文)
  steering_pressed: 用于在仪表同步显示“手离开方向盘”或“压盘中”警告
  """
  values = {s: msg[s] for s in msg} if msg else {}
  values.update(
    {
      "cruiseState": 1 if enabled else 0,
      "steeringPressed": 1 if steering_pressed else 0,
      "ACC_IACCHWAMode": 3 if enabled else 0, # 模式 3 开启 IACC 图标
      "Counter_36D": counter,
      "COUNTER_2": counter,
      "COUNTER_3": counter,
      "COUNTER_4": counter,
    }
  )
  dat = packer.make_can_msg("GW_31A", 0, values)[1]
  # 同 0x307 进行分段校验填充
  values["CHECKSUM_1"] = crc_calculate_crc8(dat[:7])
  values["CHECKSUM_2"] = crc_calculate_crc8(dat[8:15])
  values["CHECKSUM_3"] = crc_calculate_crc8(dat[16:23])
  values["CHECKSUM_4"] = crc_calculate_crc8(dat[24:31])
  return packer.make_can_msg("GW_31A", 0, values)
