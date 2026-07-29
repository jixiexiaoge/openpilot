"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot's controls-side extension layer. Controls mixes this in to gain the extra
sub/pub services, the IQ car-control message (radar blend, SLC set-speed sync, AOL
guidance continuity) and the lateral-engage gate, without touching stock controlsd.
"""
import time

import cereal.messaging as messaging
from cereal import log, custom

from iqdbc.car import structs
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.common.steer_delay import resolve_steer_delay
from openpilot.iqpilot.selfdrive.car.enhanced_stock_longitudinal_control import build_iq_control_params_from_plan
from openpilot.iqpilot.selfdrive.iqmodeld.models.inference_state import InferenceStateBase
from openpilot.iqpilot.selfdrive.controls.lib.helpers.blinker_pause import IQSignalPauseController
from openpilot.iqpilot.selfdrive.controls.lib.iq_dynamic.radar_manager import RadarManager

_PARAM_REFRESH_S = 3.0
_LEAD_FIELDS = ("dRel", "yRel", "vRel", "aRel", "vLead", "dPath", "vLat", "vLeadK",
                "aLeadK", "fcw", "status", "aLeadTau", "modelProb", "radar", "radarTrackId")


class IQControlsLayer(InferenceStateBase):
  def __init__(self, CP: structs.CarParams, params: Params):
    InferenceStateBase.__init__(self)
    self.CP = CP
    self.params = params
    self.blinker_pause_lateral = IQSignalPauseController()

    cloudlog.info("IQ controls layer waiting for IQCarParams")
    self.CP_IQ = messaging.log_from_bytes(params.get("IQCarParams", block=True), custom.IQCarParams)
    cloudlog.info("IQ controls layer got IQCarParams")

    self.iq_sub_services = ['radarState', 'iqState', 'iqPlan', 'iqNavState']
    self.iq_pub_services = ['iqCarControl']
    self.radar_manager = RadarManager(CP, params)

    self._next_param_refresh = 0.0
    self._needs_iq_lead_data = CP.brand == "hyundai"
    self._maneuver_mode = params.get_bool("LateralManeuverMode")
    self._sync_set_speed = self._want_set_speed_to_limit()
    self._slc_limit_kph = None
    self._slc_limit_pending_kph = None

  def _want_set_speed_to_limit(self) -> bool:
    try:
      return self.params.get_bool("SLCSetSpeedToLimit")
    except Exception:
      return False

  # --- periodic param refresh (throttled to a few Hz) --------------------------
  def refresh_iq_params(self, sm: messaging.SubMaster) -> None:
    now = time.monotonic()
    if now - self._next_param_refresh <= _PARAM_REFRESH_S:
      return
    self.blinker_pause_lateral.get_params()
    if self.CP.lateralTuning.which() == 'torque':
      self.lat_delay = resolve_steer_delay(self.params, sm["liveDelay"].lateralDelay)
    self._sync_set_speed = self._want_set_speed_to_limit()
    self.radar_manager.read_params()
    self._next_param_refresh = now

  # --- lateral engage gate -----------------------------------------------------
  def iq_lateral_allowed(self, sm: messaging.SubMaster) -> bool:
    if self.blinker_pause_lateral.update(sm['carState']):
      return False

    aol = sm['iqState'].aol
    stock_active = bool(sm['selfdriveState'].active)
    if self._maneuver_mode:
      return stock_active or bool(aol.available and aol.active)
    if aol.available:
      return bool(aol.active)
    return stock_active

  @staticmethod
  def _lead_snapshot(ld: log.RadarState.LeadData) -> dict:
    return {field: getattr(ld, field) for field in _LEAD_FIELDS}

  # --- build + publish the IQ car-control message ------------------------------
  def _compose_iq_carcontrol(self, sm: messaging.SubMaster) -> custom.IQCarControl:
    CC_IQ = custom.IQCarControl.new_message()
    lp = sm['liveParameters']
    CC_IQ.angleOffsetDeg = float(getattr(lp, 'angleOffsetDeg', 0.0))
    CC_IQ.aol = sm['iqState'].aol

    if self._needs_iq_lead_data:
      CC_IQ.leadOne = self._lead_snapshot(sm['radarState'].leadOne)
      CC_IQ.leadTwo = self._lead_snapshot(sm['radarState'].leadTwo)

    if self.CP.openpilotLongitudinalControl:
      cruise = getattr(sm['carState'], 'cruiseState', None)
      set_speed_ms = float(max(getattr(cruise, 'speedCluster', 0.0), getattr(cruise, 'speed', 0.0), 0.0))
      set_speed_kph = set_speed_ms * CV.MS_TO_KPH
      if self._sync_set_speed:
        CC_IQ.params, self._slc_limit_kph, self._slc_limit_pending_kph = build_iq_control_params_from_plan(
          self.CP, sm['iqPlan'], bool(sm['selfdriveState'].enabled), set_speed_kph,
          self._slc_limit_kph, self._slc_limit_pending_kph)
      else:
        self._slc_limit_kph = self._slc_limit_pending_kph = None
      self.radar_manager.update(CC_IQ, sm, set_speed_kph)
    return CC_IQ

  @staticmethod
  def _emit(CC_IQ: custom.IQCarControl, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    envelope = messaging.new_message('iqCarControl')
    envelope.valid = sm['carState'].canValid
    envelope.iqCarControl = CC_IQ
    pm.send('iqCarControl', envelope)

  def publish_iq_state(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    fresh = sm.updated['iqState'] or sm.updated['iqPlan'] or (self._needs_iq_lead_data and sm.updated['radarState'])
    if not fresh:
      return
    self._emit(self._compose_iq_carcontrol(sm), sm, pm)
