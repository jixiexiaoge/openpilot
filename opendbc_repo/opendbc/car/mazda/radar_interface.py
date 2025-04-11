#!/usr/bin/env python3
import math
import time
from cereal import car
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.can.parser import CANParser
from opendbc.car.mazda.values import (
    DBC, MazdaFlags, Bus, RADAR_LIMITS,
    RADAR_TRACK_RANGE_START, RADAR_TRACK_RANGE_END, RADAR_UPDATE_RATE, RADAR_MAX_TRACKS,
    RADAR_INVALID_DISTANCE, RADAR_INVALID_ANGLE, RADAR_INVALID_SPEED,
    RADAR_ANGLE_SCALE, RADAR_DISTANCE_SCALE, RADAR_SPEED_SCALE,
    RADAR_FAULT_NONE, RADAR_FAULT_TEMPORARY, RADAR_FAULT_PERMANENT, RADAR_BLOCKED,
    RADAR_DISTANCE_ID, RADAR_RELATIVE_SPEED_ID, RADAR_CROSS_TRAFFIC_ID, RADAR_HUD_ID,
    RADAR_TRACK_BASE_ID, RADAR_MIN_TRACK_PROBABILITY, RADAR_MAX_AGE_WITHOUT_UPDATE
)

def get_radar_can_parser(CP):
  """
  获取雷达CAN解析器
  Args:
    CP: 车辆参数
  Returns:
    CANParser: 雷达CAN解析器
  """
  # 先检查是否禁用了雷达
  if CP.radarUnavailable:
    return None

  # 检查DBC文件中是否定义了雷达总线
  # 注意：使用整数值而不是枚举
  if DBC[CP.carFingerprint].get(1) is None:  # 1 = Bus.radar
    radar_bus = 0  # 主总线
  else:
    radar_bus = 1  # 雷达总线

  # 获取对应总线的DBC文件
  dbc_file = DBC[CP.carFingerprint].get(radar_bus)
  if dbc_file is None and radar_bus == 1:
    # 如果雷达总线上没有DBC，尝试使用主总线的DBC
    dbc_file = DBC[CP.carFingerprint].get(0)
    if dbc_file is None:
      # 如果还是没有DBC，返回None
      return None

  # 定义雷达消息列表
  messages = [
    # 基本雷达消息
    ("RADAR_DISTANCE", RADAR_UPDATE_RATE),
    ("RADAR_RELATIVE_SPEED", RADAR_UPDATE_RATE),
    ("RADAR_CROSS_TRAFFIC", RADAR_UPDATE_RATE),
    ("RADAR_HUD", RADAR_UPDATE_RATE),
  ]

  # 添加目标跟踪消息
  for addr in range(RADAR_TRACK_RANGE_START, RADAR_TRACK_RANGE_END):
    messages.append((f"RADAR_TRACK_{addr}", 10))  # 跟踪消息更新率为10Hz

  return CANParser(dbc_file, messages, radar_bus)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.pts = {}  # 雷达点字典
    self.updated_messages = set()
    self.track_id = 0

    # 初始化雷达状态
    self.radar_fault = RADAR_FAULT_NONE
    self.radar_fault_time = 0.0
    self.last_update_time = 0.0
    self.blocked = False

    # 获取雷达解析器
    try:
      self.rcp = get_radar_can_parser(CP)
    except Exception as e:
      print(f"雷达初始化错误: {e}")
      self.rcp = None

  def update(self, can_strings):
    """
    更新雷达数据
    Args:
      can_strings: CAN消息字符串
    Returns:
      RadarData: 雷达数据
    """
    if self.CP.radarUnavailable or self.rcp is None:
      return super().update(can_strings)

    current_time = time.time()

    # 创建默认雷达数据对象
    ret = car.RadarData.new_message()

    try:
      # 更新CAN消息
      vls = self.rcp.update_strings(can_strings)
      self.updated_messages.update(vls)

      # 检查雷达状态
      if not self.rcp.can_valid:
        if self.radar_fault == RADAR_FAULT_NONE:
          self.radar_fault = RADAR_FAULT_TEMPORARY
          self.radar_fault_time = current_time
      elif current_time - self.radar_fault_time > RADAR_MAX_AGE_WITHOUT_UPDATE:
        self.radar_fault = RADAR_FAULT_PERMANENT
      else:
        self.radar_fault = RADAR_FAULT_NONE

      # 添加错误信息
      errors = []
      if self.radar_fault != RADAR_FAULT_NONE:
        errors.append("radarFault")
      if self.blocked:
        errors.append("radarBlocked")
      ret.errors = errors

      # 处理雷达目标
      for addr in range(RADAR_TRACK_RANGE_START, RADAR_TRACK_RANGE_END):
        track_msg_name = f"RADAR_TRACK_{addr}"
        if track_msg_name not in self.rcp.vl:
          continue

        msg = self.rcp.vl[track_msg_name]

        # 验证目标有效性
        valid = False
        if 'DIST_OBJ' in msg and 'ANG_OBJ' in msg and 'RELV_OBJ' in msg:
          valid = (msg['DIST_OBJ'] != RADAR_INVALID_DISTANCE and
                  msg['ANG_OBJ'] != RADAR_INVALID_ANGLE and
                  msg['RELV_OBJ'] != RADAR_INVALID_SPEED)

        if valid:
          # 计算目标参数
          azimuth = math.radians(msg['ANG_OBJ']/RADAR_ANGLE_SCALE)
          distance = msg['DIST_OBJ']/RADAR_DISTANCE_SCALE
          rel_speed = msg['RELV_OBJ']/RADAR_SPEED_SCALE

          # 将目标添加到雷达数据
          if (RADAR_LIMITS.MIN_DISTANCE <= distance <= RADAR_LIMITS.MAX_DISTANCE and
              RADAR_LIMITS.MIN_SPEED_DIFF <= rel_speed <= RADAR_LIMITS.MAX_SPEED_DIFF):

            # 初始化新的跟踪点
            if addr not in self.pts:
              self.pts[addr] = car.RadarData.RadarPoint.new_message()
              self.pts[addr].trackId = self.track_id
              self.track_id += 1

            # 更新点数据
            self.pts[addr].dRel = distance               # 纵向距离
            self.pts[addr].yRel = -math.sin(azimuth) * distance  # 横向距离
            self.pts[addr].vRel = rel_speed              # 相对速度
            self.pts[addr].aRel = float('nan')           # 相对加速度
            self.pts[addr].yvRel = float('nan')          # 相对横向速度
            self.pts[addr].measured = True               # 标记为测量值

      # 添加有效的点到雷达数据
      ret.points = list(self.pts.values())
    except Exception as e:
      print(f"雷达更新错误: {e}")
      # 如果发生错误，返回空的雷达数据
      ret.errors = ["processingError"]

    # 更新时间戳
    self.last_update_time = current_time
    return ret
