#!/usr/bin/env python3
import math
import time
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.can.parser import CANParser
from opendbc.car.mazda.values import (
    DBC, MazdaFlags, Bus, RADAR_LIMITS, RADAR_TRACK_LIMITS,
    RADAR_SIGNALS, RADAR_STATUS, CAN_MESSAGES, RADAR_PARAMS
)

def get_radar_can_parser(CP):
  """
  获取雷达CAN解析器
  Args:
    CP: 车辆参数
  Returns:
    CANParser: 雷达CAN解析器
  """
  if DBC[CP.carFingerprint].get(Bus.radar) is None:
    return None

  # 定义雷达消息列表
  messages = [
    # 基本雷达消息
    ("RADAR_DISTANCE", CAN_MESSAGES.RADAR_BASE["RADAR_DISTANCE"]),
    ("RADAR_RELATIVE_SPEED", CAN_MESSAGES.RADAR_BASE["RADAR_RELATIVE_SPEED"]),
    ("RADAR_CROSS_TRAFFIC", CAN_MESSAGES.RADAR_BASE["RADAR_CROSS_TRAFFIC"]),
    ("RADAR_HUD", CAN_MESSAGES.RADAR_BASE["RADAR_HUD"]),
  ]

  # 添加目标跟踪消息
  messages.extend([
    (f"RADAR_TRACK_{addr}", CAN_MESSAGES.RADAR_TRACK_BASE + addr)
    for addr in range(RADAR_TRACK_LIMITS.TRACK_RANGE_START,
                     RADAR_TRACK_LIMITS.TRACK_RANGE_END)
  ])

  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, 2)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.pts = {}  # 雷达点字典
    self.updated_messages = set()
    self.track_id = 0

    # 初始化雷达状态
    self.radar_fault = RADAR_STATUS.FAULT_NONE
    self.radar_fault_time = 0.0
    self.last_update_time = 0.0
    self.blocked = False

    # 获取雷达解析器
    self.radar_off_can = CP.radarUnavailable
    self.rcp = get_radar_can_parser(CP)

  def update(self, can_strings):
    """
    更新雷达数据
    Args:
      can_strings: CAN消息字符串
    Returns:
      RadarData: 雷达数据
    """
    if self.radar_off_can or (self.rcp is None):
      return super().update(None)

    current_time = time.time()

    # 更新CAN消息
    vls = self.rcp.update_strings(can_strings)
    self.updated_messages.update(vls)

    # 检查雷达状态
    if not self.rcp.can_valid:
      if self.radar_fault == RADAR_STATUS.FAULT_NONE:
        self.radar_fault = RADAR_STATUS.FAULT_TEMPORARY
        self.radar_fault_time = current_time
    elif current_time - self.radar_fault_time > RADAR_PARAMS.MAX_AGE_WITHOUT_UPDATE:
      self.radar_fault = RADAR_STATUS.FAULT_PERMANENT
    else:
      self.radar_fault = RADAR_STATUS.FAULT_NONE

    # 处理雷达数据
    rr = self._update(self.updated_messages)
    self.updated_messages.clear()
    self.last_update_time = current_time

    return rr

  def _update(self, updated_messages):
    """
    处理雷达数据
    Args:
      updated_messages: 更新的消息集合
    Returns:
      RadarData: 处理后的雷达数据
    """
    ret = super()._update(updated_messages)

    if self.rcp is None:
      return ret

    # 检查雷达状态
    errors = []
    if self.radar_fault != RADAR_STATUS.FAULT_NONE:
      errors.append("radarFault")
    if self.blocked:
      errors.append("radarBlocked")
    ret.errors = errors

    # 处理雷达目标
    for addr in range(RADAR_TRACK_LIMITS.TRACK_RANGE_START,
                     RADAR_TRACK_LIMITS.TRACK_RANGE_END):
      track_msg_name = f"RADAR_TRACK_{addr}"
      if track_msg_name not in self.rcp.vl:
        continue

      msg = self.rcp.vl[track_msg_name]

      # 初始化新的跟踪目标
      if addr not in self.pts:
        self.pts[addr] = {
          "trackId": self.track_id,
          "dRel": 0.0,    # 相对距离
          "yRel": 0.0,    # 相对横向位置
          "vRel": 0.0,    # 相对速度
          "aRel": 0.0,    # 相对加速度
          "yvRel": 0.0,   # 相对横向速度
          "measured": True,
          "valid": False,
          "age": 0,
          "probability": 0.0
        }
        self.track_id += 1

      # 验证目标有效性
      valid = (msg['DIST_OBJ'] != RADAR_SIGNALS.INVALID_DISTANCE and
               msg['ANG_OBJ'] != RADAR_SIGNALS.INVALID_ANGLE and
               msg['RELV_OBJ'] != RADAR_SIGNALS.INVALID_SPEED)

      if valid:
        # 计算目标参数
        azimuth = math.radians(msg['ANG_OBJ']/RADAR_SIGNALS.ANGLE_SCALE)
        distance = msg['DIST_OBJ']/RADAR_SIGNALS.DISTANCE_SCALE
        rel_speed = msg['RELV_OBJ']/RADAR_SIGNALS.SPEED_SCALE

        # 验证数值范围
        if (RADAR_LIMITS.MIN_DISTANCE <= distance <= RADAR_LIMITS.MAX_DISTANCE and
            RADAR_LIMITS.MIN_SPEED_DIFF <= rel_speed <= RADAR_LIMITS.MAX_SPEED_DIFF):

          # 更新目标数据
          self.pts[addr].update({
            "dRel": distance,
            "yRel": -math.sin(azimuth) * distance,  # 横向位置
            "vRel": rel_speed,
            "aRel": float('nan'),  # 暂无加速度数据
            "yvRel": float('nan'), # 暂无横向速度数据
            "measured": True,
            "valid": True,
            "age": self.pts[addr]["age"] + 1,
            "probability": msg.get('TRACK_PROB', 0) * RADAR_PARAMS.FUSION_CONFIDENCE_SCALE
          })

          # 检查跟踪年龄和概率
          if (self.pts[addr]["age"] < RADAR_LIMITS.MIN_TRACK_AGE or
              self.pts[addr]["age"] > RADAR_LIMITS.MAX_TRACK_AGE or
              self.pts[addr]["probability"] < RADAR_PARAMS.MIN_TRACK_PROBABILITY):
            self.pts[addr]["valid"] = False
      else:
        # 清除无效目标
        if addr in self.pts:
          del self.pts[addr]

    # 更新雷达数据
    ret.points = [p for p in self.pts.values()
                 if p["valid"] and p["probability"] >= RADAR_PARAMS.MIN_TRACK_PROBABILITY]

    # 更新最近目标信息
    if ret.points:
      closest = min(ret.points, key=lambda p: p["dRel"])
      ret.leadOne = closest
      ret.leadOne.status = True
      ret.leadOne.radar = True

    return ret
