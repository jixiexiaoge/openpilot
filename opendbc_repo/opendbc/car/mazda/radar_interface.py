#!/usr/bin/env python3
from cereal import car
from opendbc.car.interfaces import RadarInterfaceBase

# 超简化版雷达接口 - 完全禁用雷达功能
class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    # 绝对最小化初始化
    print("====== 马自达雷达接口初始化 - 完全禁用 ======")
    self.pts = {}

  def update(self, can_strings):
    """
    只返回空的雷达数据，不做任何处理
    """
    # 不处理任何CAN消息，直接返回空对象
    return car.RadarData.new_message()
