import math

from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.hyundai.values import DBC, HyundaiFlags, HyundaiExtFlags, HyundaiFlagsSP
from openpilot.common.params import Params
from opendbc.car.hyundai.hyundaicanfd import CanBus
from openpilot.common.filter_simple import MyMovingAverage

ESCC_TID = 1
SCC_TID = 0
RADAR_START_ADDR = 0x500
RADAR_MSG_COUNT = 32
RADAR_START_ADDR_CANFD1 = 0x210
RADAR_MSG_COUNT1 = 16
RADAR_START_ADDR_CANFD2 = 0x3A5 # Group 2, Group 1: 0x210 2개씩있어서 일단 보류.
RADAR_MSG_COUNT2 = 32

# POC for parsing corner radars: https://github.com/commaai/openpilot/pull/24221/

def get_radar_can_parser(CP, radar_tracks, escc, msg_start_addr, msg_count):
  if escc: #没有雷达DBC或者用户关了雷达跟踪
    lead_src, bus = "ESCC", 0
    messages = [(lead_src, 50)]
    print(f"get_radar_can_parser, lead_src={lead_src},bus={bus}")
    return CANParser(DBC[CP.carFingerprint][Bus.pt], messages, bus)

  if not radar_tracks:
    return None
  #if Bus.radar not in DBC[CP.carFingerprint]:
  #  return None
  print("RadarInterface: RadarTracks...")

  if CP.flags & HyundaiFlags.CANFD:
    CAN = CanBus(CP)
    messages = [(f"RADAR_TRACK_{addr:x}", 20) for addr in range(msg_start_addr, msg_start_addr + msg_count)]
    return CANParser('hyundai_canfd_radar_generated', messages, CAN.ACAN)
  else:
    messages = [(f"RADAR_TRACK_{addr:x}", 20) for addr in range(msg_start_addr, msg_start_addr + msg_count)]
  #return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, 1)
    return CANParser('hyundai_kia_mando_front_radar_generated', messages, 1)

def get_radar_can_parser_scc(CP):
  CAN = CanBus(CP)
  if CP.flags & HyundaiFlags.CANFD:
    messages = [("SCC_CONTROL", 50)]
    bus = CAN.ECAN
  else:
    messages = [("SCC11", 50)]
    bus = CAN.ECAN

  print("$$$$$$$$ ECAN = ", CAN.ECAN)
  bus = CAN.CAM if CP.flags & HyundaiFlags.CAMERA_SCC else bus
  return CANParser(DBC[CP.carFingerprint][Bus.pt], messages, bus)

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)

    self.canfd = True if CP.flags & HyundaiFlags.CANFD else False
    self.radar_group1 = False
    if self.canfd:
      if CP.extFlags & HyundaiExtFlags.RADAR_GROUP1.value:
        self.radar_start_addr = RADAR_START_ADDR_CANFD1
        self.radar_msg_count = RADAR_MSG_COUNT1
        self.radar_group1 = True
      else:
        self.radar_start_addr = RADAR_START_ADDR_CANFD2
        self.radar_msg_count = RADAR_MSG_COUNT2
    else:
      self.radar_start_addr = RADAR_START_ADDR
      self.radar_msg_count = RADAR_MSG_COUNT

    self.params = Params()
    self.radar_tracks = self.params.get_int("EnableRadarTracks") >= 1
    #new
    self.showDebugLog = self.params.get_int("ShowDebugLog")
    self.enhanced_scc = (CP.spFlags & HyundaiFlagsSP.SP_ENHANCED_SCC) and (Bus.radar not in DBC[CP.carFingerprint] or not self.radar_tracks)
    print(f"$$$radar_tracks={self.radar_tracks}, enhanced_scc={self.enhanced_scc}")
    #new
    self.updated_tracks = set()
    self.updated_scc = set()
    self.rcp_tracks = get_radar_can_parser(CP, self.radar_tracks, self.enhanced_scc, self.radar_start_addr, self.radar_msg_count)
    self.rcp_scc = get_radar_can_parser_scc(CP)
    self.trigger_msg_scc = 416 if self.canfd else 0x420

    self.trigger_msg_tracks = self.radar_start_addr + self.radar_msg_count - 1
    self.track_id = 0

    self.radar_off_can = CP.radarUnavailable
    #new
    if self.rcp_tracks is None:
      print("$$$self.rcp_tracks = get_radar_can_parser() is None")
    else:
      print("$$$self.rcp_tracks = get_radar_can_parser() success")
      if self.enhanced_scc:
        self.trigger_msg_tracks = 683
    if self.rcp_scc is None:
      print("$$$self.rcp_scc = get_radar_can_parser_scc() is None")
    else:
      print("$$$self.rcp_scc = get_radar_can_parser_scc() success")
    #new

    self.vRel_last = 0
    self.dRel_last = 0

    # Initialize pts
    total_tracks = self.radar_msg_count * ( 2 if self.radar_group1 else 1)
    for track_id in range(total_tracks):
      t_id = track_id + 32
      self.pts[t_id] = structs.RadarData.RadarPoint()
      self.pts[t_id].measured = False
      self.pts[t_id].trackId = t_id

    self.pts[SCC_TID] = structs.RadarData.RadarPoint()
    self.pts[SCC_TID].trackId = SCC_TID

    self.pts[ESCC_TID] = structs.RadarData.RadarPoint()
    self.pts[ESCC_TID].trackId = ESCC_TID

    self.frame = 0


  def update(self, can_strings):
    self.frame += 1
    if self.radar_off_can or (self.rcp_tracks is None and self.rcp_scc is None):
      return super().update(None)

    if self.rcp_scc is not None:
      vls_s = self.rcp_scc.update(can_strings)
      self.updated_scc.update(vls_s)
      if not self.radar_tracks and not self.enhanced_scc and self.frame % 5 == 0:
        self._update_scc(self.updated_scc)
        self.updated_scc.clear()
        ret = structs.RadarData()
        if not self.rcp_scc.can_valid:
          ret.errors.canError = True
        ret.points = list(self.pts.values())
        return ret
    if (self.radar_tracks or self.enhanced_scc) and self.rcp_tracks is not None:
      vls_t = self.rcp_tracks.update(can_strings)
      self.updated_tracks.update(vls_t)
      if self.trigger_msg_tracks in self.updated_tracks:
        self._update(self.updated_tracks)
        self._update_scc(self.updated_scc)
        self.updated_scc.clear()
        self.updated_tracks.clear()
        ret = structs.RadarData()
        if not self.rcp_tracks.can_valid:
          ret.errors.canError = True
        ret.points = list(self.pts.values())
        return ret

    return None

  def _update(self, updated_messages):
    if self.enhanced_scc:  # 如果检测到ESCC，则使用ESCC的雷达数据
      msg = self.rcp_tracks.vl["ESCC"]
      valid = msg['ACC_ObjStatus'] and msg['ACC_ObjDist'] < 204.6

      ii = ESCC_TID
      if valid:
        self.pts[ii].measured = True
        self.pts[ii].trackId = ESCC_TID
        self.pts[ii].dRel = msg['ACC_ObjDist']
        self.pts[ii].yRel = -msg['ACC_ObjLatPos']
        self.pts[ii].vRel = msg['ACC_ObjRelSpd']
        self.pts[ii].vLead = self.pts[ii].vRel + self.v_ego
        self.pts[ii].aRel = 0.0
        self.pts[ii].yvRel = 0.0

        if (self.showDebugLog & 128) > 0:
          print(f"***update escc: ACC_ObjStatus: {msg['ACC_ObjStatus']}, "
                f"pts[{ii}]: dRel={self.pts[ii].dRel}, yRel={self.pts[ii].yRel}, "
                f"vRel={self.pts[ii].vRel}, aRel={self.pts[ii].aRel}, yvRel={self.pts[ii].yvRel}")
      else:
        # key 已经存在，只需标记为 invalid
        self.pts[ii].measured = False
        self.pts[ii].dRel = 0
        self.pts[ii].yRel = 0
        self.pts[ii].vRel = 0
        self.pts[ii].vLead = 0
        self.pts[ii].aRel = float('nan')
        self.pts[ii].yvRel = 0
        if (self.showDebugLog & 128) > 0:
          print(f"mark pts[{ii}] invalid")

    else: #雷达跟踪数据
      t_id = 32
      for addr in range(self.radar_start_addr, self.radar_start_addr + self.radar_msg_count):

        msg = self.rcp_tracks.vl[f"RADAR_TRACK_{addr:x}"]

        if self.radar_group1:
          valid = msg['VALID_CNT1'] > 10
        elif self.canfd:
          valid = msg['VALID_CNT'] > 10
        else:
          valid = msg['STATE'] in (3, 4)

        self.pts[t_id].measured = bool(valid)
        if not valid:
          self.pts[t_id].dRel = 0
          self.pts[t_id].yRel = 0
          self.pts[t_id].vRel = 0
          self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
          self.pts[t_id].aRel = float('nan')
          self.pts[t_id].yvRel = 0
        elif self.radar_group1:
          self.pts[t_id].dRel = msg['LONG_DIST1']
          self.pts[t_id].yRel = msg['LAT_DIST1']
          self.pts[t_id].vRel = msg['REL_SPEED1']
          self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
          self.pts[t_id].aRel = msg['REL_ACCEL1']
          self.pts[t_id].yvRel = msg['LAT_SPEED1']
        elif self.canfd:
          self.pts[t_id].dRel = msg['LONG_DIST']
          self.pts[t_id].yRel = msg['LAT_DIST']
          self.pts[t_id].vRel = msg['REL_SPEED']
          self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
          self.pts[t_id].aRel = msg['REL_ACCEL']
          self.pts[t_id].yvRel = msg['LAT_SPEED']
        else:
          azimuth = math.radians(msg['AZIMUTH'])
          self.pts[t_id].dRel = math.cos(azimuth) * msg['LONG_DIST']
          self.pts[t_id].yRel = 0.5 * -math.sin(azimuth) * msg['LONG_DIST']
          self.pts[t_id].vRel = msg['REL_SPEED']
          self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
          self.pts[t_id].aRel = msg['REL_ACCEL']
          self.pts[t_id].yvRel = 0.0

        t_id += 1
      # radar group1은 하나의 msg에 2개의 레이더가 들어있음.
      if self.radar_group1:
        for addr in range(self.radar_start_addr, self.radar_start_addr + self.radar_msg_count):
          msg = self.rcp_tracks.vl[f"RADAR_TRACK_{addr:x}"]

          valid = msg['VALID_CNT2'] > 10
          self.pts[t_id].measured = bool(valid)
          if not valid:
            self.pts[t_id].dRel = 0
            self.pts[t_id].yRel = 0
            self.pts[t_id].vRel = 0
            self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
            self.pts[t_id].aRel = float('nan')
            self.pts[t_id].yvRel = 0
          else:
            self.pts[t_id].dRel = msg['LONG_DIST2']
            self.pts[t_id].yRel = msg['LAT_DIST2']
            self.pts[t_id].vRel = msg['REL_SPEED2']
            self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
            self.pts[t_id].aRel = msg['REL_ACCEL2']
            self.pts[t_id].yvRel = msg['LAT_SPEED2']

          t_id += 1

  def _update_scc(self, updated_messages):
    cpt = self.rcp_scc.vl
    t_id = SCC_TID
    if self.canfd:
      dRel = cpt["SCC_CONTROL"]['ACC_ObjDist']
      vRel = cpt["SCC_CONTROL"]['ACC_ObjRelSpd']
      new_pts = abs(dRel - self.dRel_last) > 3 or abs(vRel - self.vRel_last) > 1
      vLead = vRel + self.v_ego
      valid = 0 < dRel < 150 and not new_pts #cpt["SCC_CONTROL"]['OBJ_STATUS'] and dRel < 150
      self.pts[t_id].measured = bool(valid)
      if not valid:
        self.pts[t_id].dRel = 0
        self.pts[t_id].yRel = 0
        self.pts[t_id].vRel = 0
        self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
        self.pts[t_id].aRel = float('nan')
        self.pts[t_id].yvRel = 0
      else:
        self.pts[t_id].dRel = dRel
        self.pts[t_id].yRel = 0
        self.pts[t_id].vRel = vRel
        self.pts[t_id].vLead = vLead
        self.pts[t_id].aRel = float('nan')
        self.pts[t_id].yvRel = 0 #float('nan')
    else:
      dRel = cpt["SCC11"]['ACC_ObjDist']
      vRel = cpt["SCC11"]['ACC_ObjRelSpd']
      new_pts = abs(dRel - self.dRel_last) > 3 or abs(vRel - self.vRel_last) > 1
      vLead = vRel + self.v_ego
      valid = cpt["SCC11"]['ACC_ObjStatus'] and dRel < 150 and not new_pts
      self.pts[t_id].measured = bool(valid)
      if not valid:
        self.pts[t_id].dRel = 0
        self.pts[t_id].yRel = 0
        self.pts[t_id].vRel = 0
        self.pts[t_id].vLead = self.pts[t_id].vRel + self.v_ego
        self.pts[t_id].aRel = float('nan')
        self.pts[t_id].yvRel = 0
      else:
        self.pts[t_id].dRel = dRel
        self.pts[t_id].yRel = -cpt["SCC11"]['ACC_ObjLatPos']  # in car frame's y axis, left is negative
        self.pts[t_id].vRel = vRel
        self.pts[t_id].vLead = vLead
        self.pts[t_id].aRel = float('nan')
        self.pts[t_id].yvRel = 0 #float('nan')

    self.dRel_last = dRel
    self.vRel_last = vRel
