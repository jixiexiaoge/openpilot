#!/usr/bin/env python3
import math

from cereal import car
from opendbc.can.parser import CANParser
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.mazda.values import DBC, MazdaFlags

# Mazda radar track IDs
RADAR_LEAD_TID = 0    # Main radar lead from CRZ_CTRL
CAMERA_LEAD_TID = 1   # Camera distance from CAM_DISTANCE

def get_radar_can_parser(CP):
  if DBC[CP.carFingerprint]['radar'] is None:
    return None

  # Mazda radar messages from DBC file:
  # - CRZ_CTRL (540/0x21C): RADAR_HAS_LEAD, RADAR_LEAD_RELATIVE_DISTANCE, CRZ_ACTIVE, DISTANCE_SETTING
  # - CRZ_INFO (539/0x21B): ACC_ACTIVE, ACC_SET_ALLOWED, ACCEL_CMD
  # - CAM_DISTANCE (580/0x244): DISTANCE (camera-based distance measurement)
  messages = [
    ("CRZ_CTRL", 50),      # Main radar message - higher frequency
    ("CRZ_INFO", 50),      # ACC status and info
    ("CAM_DISTANCE", 20),  # Camera distance measurement
  ]
  return CANParser(DBC[CP.carFingerprint]['radar'], messages, 0)  # Read from bus 0

class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.updated_messages = set()
    self.track_id = 0

    self.radar_off_can = CP.radarUnavailable
    self.rcp = get_radar_can_parser(CP)

    # Initialize last values for change detection (similar to Hyundai)
    self.dRel_last = 0.0
    self.vRel_last = 0.0

    # Initialize radar points with proper structure (similar to Hyundai)
    for tid in [RADAR_LEAD_TID, CAMERA_LEAD_TID]:
      self.pts[tid] = car.RadarData.RadarPoint.new_message()
      self.pts[tid].trackId = tid
      self.pts[tid].measured = False
      self.pts[tid].dRel = 0.0
      self.pts[tid].yRel = 0.0
      self.pts[tid].vRel = 0.0
      self.pts[tid].aRel = float('nan')
      self.pts[tid].yvRel = 0.0

  def update(self, can_strings):
    if self.radar_off_can or (self.rcp is None):
      return super().update(None)

    vls = self.rcp.update_strings(can_strings)
    self.updated_messages.update(vls)

    # Update radar data
    ret = self._update(self.updated_messages)
    self.updated_messages.clear()

    return ret

  def _update(self, updated_messages):
    ret = car.RadarData.new_message()
    if self.rcp is None:
      return ret

    # Check CAN validity
    if not self.rcp.can_valid:
      ret.errors = ["canError"]
    else:
      ret.errors = []

    cpt = self.rcp.vl

    # Distance mapping for RADAR_LEAD_RELATIVE_DISTANCE
    # VAL_ 540 RADAR_LEAD_RELATIVE_DISTANCE 0 "NO LEAD" 1 "FARTHEST" 2 "4" 3 "3" 4 "2" 5 "NEAREST"
    # These are ACC distance bar indicators, mapped to approximate real distances
    distance_map = {
      1: 120.0,  # FARTHEST - Maximum ACC range
      2: 80.0,   # Level 4 - Far
      3: 50.0,   # Level 3 - Medium
      4: 30.0,   # Level 2 - Close
      5: 15.0    # NEAREST - Very close
    }

    # ============================================================
    # Process CRZ_CTRL message - Main radar lead vehicle
    # ============================================================
    if "CRZ_CTRL" in cpt:
      msg = cpt["CRZ_CTRL"]
      tid = RADAR_LEAD_TID

      # Extract signals from DBC
      has_lead = msg['RADAR_HAS_LEAD']              # 0 or 1
      distance_level = msg['RADAR_LEAD_RELATIVE_DISTANCE']  # 0-5
      crz_active = msg['CRZ_ACTIVE']                # ACC active status
      distance_setting = msg['DISTANCE_SETTING']    # ACC distance setting (0-4)

      # Validity check: must have lead detection and valid distance level
      # Similar to Hyundai's validity pattern
      valid = (has_lead == 1) and (distance_level > 0) and (distance_level <= 5)

      # Get mapped distance
      dRel = distance_map.get(int(distance_level), 50.0) if valid else 0.0

      # Check for sudden jumps (similar to Hyundai's new_pts check)
      new_pts = abs(dRel - self.dRel_last) > 50.0
      valid = valid and not new_pts and dRel < 150.0

      # Update radar point
      self.pts[tid].measured = bool(valid)

      if valid:
        self.pts[tid].dRel = dRel
        self.pts[tid].yRel = 0.0  # No lateral position available in Mazda DBC
        self.pts[tid].vRel = 0.0  # No velocity available - could estimate from distance changes
        self.pts[tid].vLead = self.v_ego  # vLead = vRel + v_ego
        self.pts[tid].aRel = float('nan')
        self.pts[tid].yvRel = 0.0
        # Debug output for testing
        # print(f"MAZDA_RADAR: CRZ_CTRL valid - has_lead={has_lead}, dist_level={distance_level}, dRel={dRel:.1f}m, vLead={self.v_ego*3.6:.1f}kph")
      else:
        # Invalid - clear the data but keep the point
        self.pts[tid].dRel = 0.0
        self.pts[tid].yRel = 0.0
        self.pts[tid].vRel = 0.0
        self.pts[tid].vLead = self.v_ego
        self.pts[tid].aRel = float('nan')
        self.pts[tid].yvRel = 0.0
        # print(f"MAZDA_RADAR: CRZ_CTRL invalid - has_lead={has_lead}, dist_level={distance_level}")

      self.dRel_last = dRel

    # ============================================================
    # Process CAM_DISTANCE message - Camera-based distance
    # ============================================================
    if "CAM_DISTANCE" in cpt:
      msg = cpt["CAM_DISTANCE"]
      tid = CAMERA_LEAD_TID

      # Extract distance signal (unit: meters, range 0-255)
      distance = msg['DISTANCE']

      # Validity check: reasonable distance range
      # 0 typically means no detection, 255 might be invalid/max value
      valid = (distance > 0) and (distance < 250) and (distance < 150)

      # Update radar point
      self.pts[tid].measured = bool(valid)

      if valid:
        self.pts[tid].dRel = float(distance)
        self.pts[tid].yRel = 0.0
        self.pts[tid].vRel = 0.0
        self.pts[tid].vLead = self.v_ego
        self.pts[tid].aRel = float('nan')
        self.pts[tid].yvRel = 0.0
        # Debug output for testing
        # print(f"MAZDA_RADAR: CAM_DISTANCE valid - distance={distance:.1f}m, vLead={self.v_ego*3.6:.1f}kph")
      else:
        # Invalid - clear the data
        self.pts[tid].dRel = 0.0
        self.pts[tid].yRel = 0.0
        self.pts[tid].vRel = 0.0
        self.pts[tid].vLead = self.v_ego
        self.pts[tid].aRel = float('nan')
        self.pts[tid].yvRel = 0.0

    # Return all radar points (similar to Hyundai)
    ret.points = list(self.pts.values())
    # Debug output for testing
    # print(f"MAZDA_RADAR: Total points={len(ret.points)}, measured=[{self.pts[0].measured}, {self.pts[1].measured}]")
    return ret
