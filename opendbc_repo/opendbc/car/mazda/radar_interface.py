#!/usr/bin/env python3
import math

from cereal import car
from opendbc.can.parser import CANParser
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.mazda.values import DBC, MazdaFlags, Bus

def get_radar_can_parser(CP):
  if DBC[CP.carFingerprint].get(Bus.radar) is None:
    return None
  # 忽略雷达拦截器标志检查，直接使用雷达DBC
  messages = [(f"RADAR_TRACK_{addr}", 10) for addr in range(361, 367)]
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, 2)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.pts = {}
    self.updated_messages = set()
    self.track_id = 0

    self.radar_off_can = CP.radarUnavailable
    self.rcp = get_radar_can_parser(CP)

  def update(self, can_strings):
    if self.radar_off_can or (self.rcp is None):
      return super().update(None)

    vls = self.rcp.update_strings(can_strings)
    self.updated_messages.update(vls)
    rr = self._update(self.updated_messages)
    self.updated_messages.clear()

    return rr

  def _update(self, updated_messages):
    ret = car.RadarData.new_message()
    if self.rcp is None:
      return ret

    errors = []
    if not self.rcp.can_valid:
      errors.append("canError")
    ret.errors = errors

    for addr in range(361, 367):
      track_msg_name = f"RADAR_TRACK_{addr}"
      if track_msg_name not in self.rcp.vl:
        continue

      msg = self.rcp.vl[track_msg_name]
      if addr not in self.pts:
        self.pts[addr] = car.RadarData.RadarPoint.new_message()
        self.pts[addr].trackId = self.track_id
        self.track_id += 1

      # 从DBC文件看，无效值为DIST_OBJ=4095, ANG_OBJ=2046, RELV_OBJ=-16
      valid = (msg['DIST_OBJ'] != 4095) and (msg['ANG_OBJ'] != 2046) and (msg['RELV_OBJ'] != -16)

      if valid:
        # 计算方位角（以弧度为单位）
        azimuth = math.radians(msg['ANG_OBJ']/64)

        self.pts[addr].measured = True
        # 根据DBC文件中的比例因子转换数据
        self.pts[addr].dRel = msg['DIST_OBJ']/16  # 距离（米）
        self.pts[addr].yRel = -math.sin(azimuth) * msg['DIST_OBJ']/16  # 横向位置（米）
        self.pts[addr].vRel = msg['RELV_OBJ']/16  # 相对速度（米/秒）

        # 暂时没有加速度和横向速度数据
        self.pts[addr].aRel = float('nan')
        self.pts[addr].yvRel = float('nan')
      else:
        del self.pts[addr]

    ret.points = list(self.pts.values())
    return ret
