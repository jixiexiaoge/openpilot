from cereal import car
from openpilot.selfdrive.car import radar_helpers
from openpilot.selfdrive.car.interfaces import RadarInterfaceBase
from selfdrive.car.byd.values import get_radar_can_parser

RADAR_MSGS = [0x032F, 0x032E]

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.rcp = get_radar_can_parser(CP)
    self.tracks = {}

  def update(self, can_strings):
    """解析雷达 CAN 数据并返回 RadarData 结构"""
    self.rcp.update_strings(can_strings)
    radar_data = car.RadarData.new_message()
    radar_data.errors = []

    for msg_id in RADAR_MSGS:
      for msg in self.rcp.msgs.get(msg_id, []):
        target_id = msg.get("Target_ID", 0)
        if target_id == 0:
          continue
        
        d_rel = msg.get("Distance", 0)
        v_rel = msg.get("Speed", 0)
        y_rel = msg.get("Angle", 0)
        rcs = msg.get("RCS", 0)

        if rcs < -50:
          continue

        track = radar_helpers.RadarPoint(
          track_id=target_id,
          dRel=d_rel,
          yRel=y_rel,
          vRel=v_rel,
          aRel=0.0,
          vLat=0.0,
          vLon=v_rel,
          measured=True
        )
        self.tracks[target_id] = track

    radar_data.points = list(self.tracks.values())
    return radar_data