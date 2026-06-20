"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/

RadarManager — IQ.Dynamics side of "Blend IQ.Pilot + Stock ACC Radar" (VW PQ only).

Decides the high-level intent for the stock ACC radar and writes it onto iqCarControl for the opendbc
PQRadarHandler to execute on CAN. It does NOT touch CAN or read radar feedback directly: the handler
(car process) owns the bus and the failure latch, and the carcontroller gates radar-accel passthrough
on the live ACS_Sta_ADR. That keeps the desync guard automatic — if chill is requested but the radar
isn't active, the carcontroller simply uses the planner's VoACC accel (standard IQ long).

Intent produced:
  radarBlendActive  feature enabled + PQ + alpha long available
  radarEngageReq    want the radar's cruise engaged (engage same time long control engages)
  radarCancelReq    cancel now (1 kph stop / driver brake / long disengaged / teardown)
  useRadarAccel     chill (acc) mode + engaged -> carcontroller passes radar ACS_Sollbeschl through
  radarSetSpeedKph  OP set speed to sync the radar's ACA_V_Wunsch toward
  radarGapBars      OP follow-distance bars to mirror to the radar
"""
from openpilot.common.constants import CV

CANCEL_CEIL_MS = 1.0 * CV.KPH_TO_MS  # cancel the radar at/below 1 kph (it can still see speed -> would fault)


class RadarManager:
  def __init__(self, CP, params):
    self.CP = CP
    self.params = params
    self.is_pq = self._detect_pq(CP)
    self.enabled_param = False

  @staticmethod
  def _detect_pq(CP) -> bool:
    if getattr(CP, "brand", "") != "volkswagen":
      return False
    try:
      from opendbc.car.volkswagen.values import VolkswagenFlags
      return bool(CP.flags & VolkswagenFlags.PQ)
    except Exception:
      return False

  def read_params(self) -> None:
    if self.is_pq:
      self.enabled_param = self.params.get_bool("IQDynamicBlendStockRadar")

  def update(self, CC_IQ, sm, set_speed_kph: float) -> None:
    blend = bool(self.is_pq and self.enabled_param and self.CP.openpilotLongitudinalControl)
    CC_IQ.radarBlendActive = blend
    if not blend:
      return

    ss = sm['selfdriveState']
    cs = sm['carState']
    iq = sm['iqPlan'].iqDynamic

    long_engaged = bool(ss.enabled) and self.CP.openpilotLongitudinalControl
    iq_engaged = long_engaged and bool(iq.enabled)
    chill = iq_engaged and bool(iq.active) and (iq.state == 'acc')
    brake = bool(cs.brakePressed)
    v_ego = float(cs.vEgo)

    # Engage the radar whenever IQ.Dynamics long is engaged; cancel on stop/brake/teardown.
    # The handler resolves priority (cancel wins) and applies the 1->2 kph engage hysteresis.
    CC_IQ.radarEngageReq = iq_engaged and not brake
    CC_IQ.radarCancelReq = (not iq_engaged) or brake or (v_ego <= CANCEL_CEIL_MS)
    CC_IQ.useRadarAccel = chill
    CC_IQ.radarSetSpeedKph = float(max(set_speed_kph, 0.0))
    CC_IQ.radarGapBars = int(min(3, max(1, ss.personality.raw + 1)))
