"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import time

import cereal.messaging as messaging
from cereal import log, custom

from opendbc.car import structs
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot import PARAMS_UPDATE_PERIOD
from openpilot.iqpilot.livedelay.helpers import get_lat_delay
from openpilot.iqpilot.selfdrive.car.enhanced_stock_longitudinal_control import build_iq_control_params_from_plan
from openpilot.iqpilot.modeld.modeld_base import ModelStateBase
from openpilot.iqpilot.selfdrive.controls.lib.helpers.blinker_pause import BlinkerPauseLateral


class ControlsExt(ModelStateBase):
  def __init__(self, CP: structs.CarParams, params: Params):
    ModelStateBase.__init__(self)
    self.CP = CP
    self.params = params
    self._param_update_time: float = 0.0
    self.blinker_pause_lateral = BlinkerPauseLateral()

    cloudlog.info("controlsd_ext is waiting for IQCarParams")
    self.CP_IQ = messaging.log_from_bytes(params.get("IQCarParams", block=True), custom.IQCarParams)
    cloudlog.info("controlsd_ext got IQCarParams")

    self.sm_services_ext = ['radarState', 'iqState', 'iqPlan', 'iqNavState']
    self.pm_services_ext = ['iqCarControl']
    self._needs_iq_lead_data = CP.brand == "hyundai"
    self._last_slc_sync_limit_kph: float | None = None
    self._pending_slc_sync_limit_kph: float | None = None
    self._lateral_maneuver_mode = params.get_bool("LateralManeuverMode")

  def get_params_iq(self, sm: messaging.SubMaster) -> None:
    if time.monotonic() - self._param_update_time > PARAMS_UPDATE_PERIOD:
      self.blinker_pause_lateral.get_params()

      if self.CP.lateralTuning.which() == 'torque':
        self.lat_delay = get_lat_delay(self.params, sm["liveDelay"].lateralDelay)

      self._param_update_time = time.monotonic()

  def get_lat_active(self, sm: messaging.SubMaster) -> bool:
    if self.blinker_pause_lateral.update(sm['carState']):
      return False

    ss_iq = sm['iqState']

    if self._lateral_maneuver_mode:
      return bool(sm['selfdriveState'].active or (ss_iq.aol.available and ss_iq.aol.active))

    if ss_iq.aol.available:
      return bool(ss_iq.aol.active)

    # AOL not available, use stock state to engage
    return bool(sm['selfdriveState'].active)

  @staticmethod
  def get_lead_data(ld: log.RadarState.LeadData) -> dict:
    return {
      "dRel": ld.dRel,
      "yRel": ld.yRel,
      "vRel": ld.vRel,
      "aRel": ld.aRel,
      "vLead": ld.vLead,
      "dPath": ld.dPath,
      "vLat": ld.vLat,
      "vLeadK": ld.vLeadK,
      "aLeadK": ld.aLeadK,
      "fcw": ld.fcw,
      "status": ld.status,
      "aLeadTau": ld.aLeadTau,
      "modelProb": ld.modelProb,
      "radar": ld.radar,
      "radarTrackId": ld.radarTrackId,
    }

  def state_control_ext(self, sm: messaging.SubMaster) -> custom.IQCarControl:
    CC_IQ = custom.IQCarControl.new_message()
    CC_IQ.angleOffsetDeg = float(sm['liveParameters'].angleOffsetDeg)

    if self._needs_iq_lead_data:
      CC_IQ.leadOne = self.get_lead_data(sm['radarState'].leadOne)
      CC_IQ.leadTwo = self.get_lead_data(sm['radarState'].leadTwo)

    # AOL state
    ss_iq = sm['iqState']
    CC_IQ.aol = ss_iq.aol
    lp = sm['liveParameters']
    CC_IQ.angleOffsetDeg = float(getattr(lp, 'angleOffsetDeg', 0.0))
    if self.CP.openpilotLongitudinalControl:
      cruise_state = getattr(sm['carState'], 'cruiseState', None)
      current_set_speed_ms = float(max(getattr(cruise_state, 'speedCluster', 0.0), getattr(cruise_state, 'speed', 0.0), 0.0))
      current_set_speed_kph = current_set_speed_ms * CV.MS_TO_KPH
      CC_IQ.params, self._last_slc_sync_limit_kph, self._pending_slc_sync_limit_kph = build_iq_control_params_from_plan(
        self.CP, sm['iqPlan'], bool(sm['selfdriveState'].enabled), current_set_speed_kph,
        self._last_slc_sync_limit_kph, self._pending_slc_sync_limit_kph
      )
    return CC_IQ

  @staticmethod
  def publish_ext(CC_IQ: custom.IQCarControl, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    iq_cc_send = messaging.new_message('iqCarControl')
    iq_cc_send.valid = sm['carState'].canValid
    iq_cc_send.iqCarControl = CC_IQ
    pm.send('iqCarControl', iq_cc_send)

  def run_ext(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    if not sm.updated['iqState'] and not sm.updated['iqPlan'] and not (self._needs_iq_lead_data and sm.updated['radarState']):
      return

    CC_IQ = self.state_control_ext(sm)
    self.publish_ext(CC_IQ, sm, pm)
