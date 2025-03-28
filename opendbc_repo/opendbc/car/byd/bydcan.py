#!/usr/bin/env python3
from opendbc.can.packer import CANPacker
from selfdrive.car.byd.values import DBC
import numpy as np

class BYDCAN:
  def __init__(self, CP):
    self.CP = CP
    self.packer = CANPacker(DBC[CP.carFingerprint]['dbc'])
    
    # CAN协议配置
    self.steer_id = 0x320       # 转向控制报文ID
    self.accel_id = 0x321       # 纵向控制报文ID
    self.heartbeat_id = 0x3E8   # 心跳报文ID
    self.counter = 0            # 报文计数器
    
    # 校验参数
    self.checksum_type = 'xor'  # BYD常用XOR校验
    
  # ------------------------
  # 校验和计算
  # ------------------------
  def _calc_checksum(self, data):
    """BYD典型校验算法（8位XOR）"""
    if self.checksum_type == 'xor':
      checksum = 0
      for byte in data[:-1]:  # 假设最后一个字节为校验位
        checksum ^= byte
      return checksum & 0xFF
    else:
      return 0  # 其他校验类型可扩展

  # ------------------------
  # 转向控制报文生成
  # ------------------------
  def create_steering_control(self, angle_deg, enabled):
    """
    生成转向控制报文 (ID:0x320)
    参数:
      angle_deg: 目标转向角（度）
      enabled:   是否激活控制
    """
    # 信号转换（参考DBC定义）
    angle_raw = int(np.clip(angle_deg / 0.1, -1000, 1000))  # 缩放因子0.1
    ctrl_status = 0x1 if enabled else 0x0
    
    # 报文数据构造
    dat = bytearray(8)
    dat[0:2] = angle_raw.to_bytes(2, 'little', signed=True)  # 小端格式
    dat[2] = ctrl_status
    dat[7] = self._calc_checksum(dat)  # 校验位在最后
    
    return self._finalize_frame(self.steer_id, dat)

  # ------------------------
  # 纵向控制报文生成
  # ------------------------
  def create_accel_control(self, accel_mps2, speed_mps, enabled):
    """
    生成纵向控制报文 (ID:0x321)
    参数:
      accel_mps2: 目标加速度（m/s2）
      speed_mps:  目标车速（m/s）
      enabled:    是否激活控制
    """
    # 信号转换（参考DBC定义）
    accel_raw = int(np.clip(accel_mps2 / 0.001, -2000, 2000))
    speed_raw = int(np.clip(speed_mps / 0.01, 0, 300))  # 0-300 km/h
    
    dat = bytearray(8)
    dat[0:2] = accel_raw.to_bytes(2, 'little', signed=True)
    dat[2:4] = speed_raw.to_bytes(2, 'little')
    dat[4] = 0x1 if enabled else 0x0
    dat[7] = self._calc_checksum(dat)
    
    return self._finalize_frame(self.accel_id, dat)

  # ------------------------
  # 心跳报文生成
  # ------------------------
  def create_heartbeat(self):
    """生成心跳报文 (ID:0x3E8)"""
    dat = bytearray(8)
    dat[0] = self.counter % 0xFF  # 计数器循环
    dat[1] = 0xAA                # 固定标识
    dat[7] = self._calc_checksum(dat)
    self.counter += 1
    return self._finalize_frame(self.heartbeat_id, dat)

  # ------------------------
  # 通用报文封装
  # ------------------------
  def _finalize_frame(self, can_id, dat):
    """封装为CAN报文对象"""
    return [can_id, 0, bytes(dat), 0]  # [id, addr, data, bus]

  # ------------------------
  # 信号解析工具
  # ------------------------
  @staticmethod
  def parse_vehicle_status(data):
    """解析车辆状态信号（示例）"""
    status = {}
    status['power_mode'] = (data[0] >> 4) & 0x0F  # 高4位
    status['fault_code'] = data[1] & 0x7F         # 低7位
    return status

# ------------------------
# 单元测试用例
# ------------------------
if __name__ == "__main__":
  # 测试校验和计算
  can = BYDCAN(None)
  test_data = bytes([0x12, 0x34, 0x56, 0x78])
  assert can._calc_checksum(test_data) == 0x12 ^ 0x34 ^ 0x56
  
  # 测试转向报文生成
  frame = can.create_steering_control(15.5, True)
  assert frame[0] == 0x320
  assert frame[2][0:2] == bytes([0xF4, 0x01])  # 155 = 0x9B -> little-endian