#!/usr/bin/env python3
from opendbc.car.interfaces import RadarInterfaceBase

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.updated_messages = set()
    self.trigger_msg = 0

  def update(self, can_strings):
    return super().update(can_strings)
