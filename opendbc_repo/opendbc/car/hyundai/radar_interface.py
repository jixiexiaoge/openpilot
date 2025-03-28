import math

from opendbc.can.parser import CANParser
from opendbc.car import Bus, structs
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.hyundai.values import DBC, HyundaiFlags
from openpilot.common.params import Params
from opendbc.car.hyundai.hyundaicanfd import CanBus
from openpilot.common.filter_simple import MyMovingAverage

RADAR_START_ADDR = 0x500
RADAR_MSG_COUNT = 32

# POC for parsing corner radars: https://github.com/commaai/openpilot/pull/24221/

def get_radar_can_parser(CP, radar_tracks):
  if not radar_tracks:
    return None
  #if Bus.radar not in DBC[CP.carFingerprint]:
  #  return None

  messages = [(f"RADAR_TRACK_{addr:x}", 20) for addr in range(RADAR_START_ADDR, RADAR_START_ADDR + RADAR_MSG_COUNT)]
  #return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, 1)
  print("RadarInterface: RadarTracks...")
  return CANParser('hyundai_kia_mando_front_radar_generated', messages, 1)

def get_radar_can_parser_scc(CP):
  CAN = CanBus(CP)
  if CP.flags & HyundaiFlags.CANFD:
    messages = [("SCC_CONTROL", 50)]
    bus = CAN.ACAN if CP.flags & HyundaiFlags.CANFD_HDA2 else CAN.ECAN
  else:
    messages = [("SCC11", 50)]
    bus = CAN.ECAN

  print("$$$$$$$$ ECAN = ", CAN.ECAN)    
  bus = CAN.CAM if CP.flags & HyundaiFlags.CAMERA_SCC else bus
  return CANParser(DBC[CP.carFingerprint][Bus.pt], messages, bus)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.updated_messages = set()
    self.trigger_msg = RADAR_START_ADDR + RADAR_MSG_COUNT - 1
    self.track_id = 0

    self.radar_off_can = CP.radarUnavailable

    self.radar_tracks = Params().get_int("EnableRadarTracks") >= 1
    self.rcp = get_radar_can_parser(CP, self.radar_tracks)

    self.canfd = True if CP.flags & HyundaiFlags.CANFD else False
    if not self.radar_tracks:
      self.rcp = get_radar_can_parser_scc(CP)
      self.trigger_msg = 416 if self.canfd else 0x420

    # 50Hz (SCC), 20Hz (RadarTracks)
    self.vLead_filter = MyMovingAverage(13) # for SCC radar 0.1 unit
    self.vRel_last = 0
    self.dRel_last = 0


  def update(self, can_strings):
    if self.radar_off_can or (self.rcp is None):
      return super().update(None)

    vls = self.rcp.update_strings(can_strings)
    self.updated_messages.update(vls)

    if self.trigger_msg not in self.updated_messages:
      return None

    rr = self._update(self.updated_messages) if self.radar_tracks else self._update_scc(self.updated_messages)
    self.updated_messages.clear()

    return rr

  def _update(self, updated_messages):
    ret = structs.RadarData()
    if self.rcp is None:
      return ret

    errors = []

    if not self.rcp.can_valid:
      errors.append("canError")
    ret.errors = errors

    for addr in range(RADAR_START_ADDR, RADAR_START_ADDR + RADAR_MSG_COUNT):
      msg = self.rcp.vl[f"RADAR_TRACK_{addr:x}"]

      if addr not in self.pts:
        self.pts[addr] = structs.RadarData.RadarPoint()
        self.pts[addr].trackId = self.track_id
        self.track_id += 1

      valid = msg['STATE'] in (3, 4)
      if valid:
        azimuth = math.radians(msg['AZIMUTH'])
        self.pts[addr].measured = True
        self.pts[addr].dRel = math.cos(azimuth) * msg['LONG_DIST']
        self.pts[addr].yRel = 0.5 * -math.sin(azimuth) * msg['LONG_DIST']
        self.pts[addr].vRel = msg['REL_SPEED']
        self.pts[addr].vLead = self.pts[addr].vRel + self.v_ego
        self.pts[addr].aRel = msg['REL_ACCEL']
        self.pts[addr].yvRel = float('nan')

      else:
        del self.pts[addr]

    ret.points = list(self.pts.values())
    return ret


  def _update_scc(self, updated_messages):
    ret = structs.RadarData()
    if self.rcp is None:
      return ret

    errors = []

    if not self.rcp.can_valid:
      errors.append("canError")
    ret.errors = errors

    cpt = self.rcp.vl
    if self.canfd:
      dRel = cpt["SCC_CONTROL"]['ACC_ObjDist']
      vRel = cpt["SCC_CONTROL"]['ACC_ObjRelSpd']
      new_pts = abs(dRel - self.dRel_last) > 3 or abs(vRel - self.vRel_last) > 1
      vLead = vRel + self.v_ego
      valid = 0 < dRel < 150 #cpt["SCC_CONTROL"]['OBJ_STATUS'] and dRel < 150
      for ii in range(1):
        if valid:
          if ii not in self.pts or new_pts:
            self.pts[ii] = structs.RadarData.RadarPoint()
            self.pts[ii].trackId = self.track_id
            self.track_id = min(1 - self.track_id, 1)
            self.vLead_filter.set_all(vLead)
          self.pts[ii].dRel = dRel
          self.pts[ii].yRel = 0
          self.pts[ii].vRel = vRel
          self.pts[ii].vLead = self.vLead_filter.process(vLead)
          self.pts[ii].aRel = 0 #float('nan')
          self.pts[ii].yvRel = float('nan')
          self.pts[ii].measured = True
        else:
          if ii in self.pts:
            del self.pts[ii]
    else:
      dRel = cpt["SCC11"]['ACC_ObjDist']
      vRel = cpt["SCC11"]['ACC_ObjRelSpd']
      new_pts = abs(dRel - self.dRel_last) > 3 or abs(vRel - self.vRel_last) > 1
      vLead = vRel + self.v_ego
      valid = cpt["SCC11"]['ACC_ObjStatus'] and dRel < 150
      for ii in range(1):
        if valid:
          if ii not in self.pts or new_pts:
            self.pts[ii] = structs.RadarData.RadarPoint()
            self.pts[ii].trackId = self.track_id
            self.track_id = min(1 - self.track_id, 1)
            self.vLead_filter.set_all(vLead)
          self.pts[ii].dRel = dRel
          self.pts[ii].yRel = -cpt["SCC11"]['ACC_ObjLatPos']  # in car frame's y axis, left is negative
          self.pts[ii].vRel = vRel
          self.pts[ii].vLead = self.vLead_filter.process(vLead)
          self.pts[ii].aRel = 0 #float('nan')
          self.pts[ii].yvRel = float('nan')
          self.pts[ii].measured = True
        else:
          if ii in self.pts:
            del self.pts[ii]

    self.dRel_last = dRel
    self.vRel_last = vRel
    ret.points = list(self.pts.values())
    ret.errors = errors
    return ret
