"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import messaging
from numpy import interp
from opendbc.car import structs
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.controls.lib.iq_dynamic.imahelper import (
  IQConstants,
  IQFilterEngine,
  IQModeEngine,
  IQ_DYNAMIC_CONDITIONAL_CURVES_PARAM,
  IQ_DYNAMIC_CONDITIONAL_LEAD_SPEED_PARAM,
  IQ_DYNAMIC_CONDITIONAL_MODEL_STOPS_PARAM,
  IQ_DYNAMIC_CONDITIONAL_SLC_FALLBACK_PARAM,
  IQ_DYNAMIC_CONDITIONAL_SLOWER_LEAD_PARAM,
  IQ_DYNAMIC_CONDITIONAL_SPEED_PARAM,
  IQ_DYNAMIC_CONDITIONAL_STOPPED_LEAD_PARAM,
  IQ_DYNAMIC_MODE_PARAM,
  IQ_DYNAMIC_MODEL_STOP_TIME_PARAM,
  IQ_FORCE_STOPS_PARAM,
  compute_slowdown_need,
)

S_Y = 33


class IQDynamicController:
  def __init__(self, CP: structs.CarParams, mpc, params=None):
    self.IQS = CP
    self._mpc = mpc
    self.IQParams = params or Params()

    self.IQDynamicStatus = False
    self.IQDynamicA = False
    self.IQDynamicF = 0
    self.IQDynamicU = 0.0
    self.IQEngineManager = IQModeEngine()

    self.IQFilterL = IQFilterEngine(measurement_noise=0.17, process_noise=0.04, process_decay=1.03, smoothing_floor=0.9)
    self.IQFilterSDL = IQFilterEngine(measurement_noise=0.12, process_noise=0.098, process_decay=1.01, smoothing_floor=0.8)
    self.IQFilterSFL = IQFilterEngine(measurement_noise=0.11, process_noise=0.06, process_decay=1.000, smoothing_floor=0.90)
    self.IQFilterFCW = IQFilterEngine(measurement_noise=0.19, process_noise=0.11, process_decay=1.11, smoothing_floor=0.4)
    self.IQFilterSlowLead = IQFilterEngine(measurement_noise=0.15, process_noise=0.08, process_decay=1.02, smoothing_floor=0.75)
    self.IQFilterModelStop = IQFilterEngine(measurement_noise=0.15, process_noise=0.06, process_decay=1.01, smoothing_floor=0.7)

    self.hasIQFilterLED = False
    self.hasIQSDL = False
    self.hasIQSFL = False
    self.hasIQL = False
    self.curve_detected = False
    self.slow_lead_detected = False
    self.stop_light_detected = False
    self.low_speed_detected = False
    self.low_speed_lead_detected = False
    self.model_stopped = False
    self.tracking_lead = False
    self.force_stops_enabled = True
    self.slc_experimental_mode = False

    self.kph = 0.0
    self.cruise_kph = 0.0
    self.aeb = 0
    self.aeb_c = 0
    self.ss_c = 0
    self.e_x = float('inf')
    self.e_d = 0.0
    self.model_length = 0.0
    self.lead_speed = 0.0

    self.conditional_curves = True
    self.conditional_slower_lead = True
    self.conditional_stopped_lead = True
    self.conditional_model_stops = True
    self.conditional_slc_fallback = True
    self.conditional_speed = IQConstants.CONDITIONAL_SPEED_DEFAULT
    self.conditional_lead_speed = IQConstants.CONDITIONAL_LEAD_SPEED_DEFAULT
    self.model_stop_time = IQConstants.MODEL_STOP_TIME_DEFAULT

  def _read_bool(self, key: str, default: bool) -> bool:
    value = self.IQParams.get_bool(key)
    return default if value is None else bool(value)

  def _read_float(self, key: str, default: float) -> float:
    value = self.IQParams.get(key)
    if value is None:
      return default
    if isinstance(value, bytes):
      value = value.decode('utf-8')
    try:
      return float(value)
    except (TypeError, ValueError):
      return default

  def _readIQParams(self) -> None:
    if self.IQDynamicF % int(1. / DT_MDL) != 0:
      return
    self.IQDynamicStatus = self._read_bool(IQ_DYNAMIC_MODE_PARAM, False)
    self.conditional_curves = self._read_bool(IQ_DYNAMIC_CONDITIONAL_CURVES_PARAM, True)
    self.conditional_slower_lead = self._read_bool(IQ_DYNAMIC_CONDITIONAL_SLOWER_LEAD_PARAM, True)
    self.conditional_stopped_lead = self._read_bool(IQ_DYNAMIC_CONDITIONAL_STOPPED_LEAD_PARAM, True)
    self.conditional_model_stops = self._read_bool(IQ_DYNAMIC_CONDITIONAL_MODEL_STOPS_PARAM, True)
    self.conditional_slc_fallback = self._read_bool(IQ_DYNAMIC_CONDITIONAL_SLC_FALLBACK_PARAM, True)
    self.conditional_speed = self._read_float(IQ_DYNAMIC_CONDITIONAL_SPEED_PARAM, IQConstants.CONDITIONAL_SPEED_DEFAULT)
    self.conditional_lead_speed = self._read_float(IQ_DYNAMIC_CONDITIONAL_LEAD_SPEED_PARAM, IQConstants.CONDITIONAL_LEAD_SPEED_DEFAULT)
    self.model_stop_time = self._read_float(IQ_DYNAMIC_MODEL_STOP_TIME_PARAM, IQConstants.MODEL_STOP_TIME_DEFAULT)
    self.force_stops_enabled = self._read_bool(IQ_FORCE_STOPS_PARAM, True)

  def set_slc_experimental_mode(self, active: bool) -> None:
    self.slc_experimental_mode = bool(active)

  def mode(self) -> str:
    return self.IQEngineManager.get_mode()

  def enabled(self) -> bool:
    return self.IQDynamicStatus

  def active(self) -> bool:
    return self.IQDynamicA

  def force_stop_requested(self) -> bool:
    return bool(self.force_stops_enabled and self.stop_light_detected and self.model_stopped and not self.tracking_lead)

  def setaeb(self) -> None:
    self.aeb = self.aeb_c

  def IQDynamicEngine(self, sm: messaging.SubMaster) -> None:
    car_state = sm['carState']
    radar_state = sm['radarState']
    model = sm['modelV2']

    self.kph = car_state.vEgo * 3.6
    self.cruise_kph = car_state.vCruise
    self.ss_c = min(20, self.ss_c + 1) if car_state.standstill else max(0, self.ss_c - 1)

    lead_status = float(getattr(radar_state.leadOne, "status", False))
    self.IQFilterL.push(lead_status)
    self.hasIQFilterLED = (self.IQFilterL.value() or 0.0) > IQConstants.LEAD_LOCK_GATE
    self.tracking_lead = self.hasIQFilterLED
    self.lead_speed = float(getattr(radar_state.leadOne, "vLead", 0.0))

    prev_fcw = self.IQFilterFCW.value() or 0.0
    self.IQFilterFCW.push(float(self.aeb > 0))
    self.hasIQL = prev_fcw > 0.5

    valid_model = len(model.position.x) == S_Y and len(model.orientation.x) == S_Y
    if valid_model:
      self.model_length = float(model.position.x[S_Y - 1])
      self.e_x = self.model_length
      self.e_d = interp(self.kph, IQConstants.BRAKE_CURVE_SPEED_AXIS, IQConstants.BRAKE_CURVE_DISTANCE_AXIS)
      need = compute_slowdown_need(self.kph, self.model_length, self.e_d)
    else:
      self.model_length = 0.0
      self.e_x = float('inf')
      self.e_d = 0.0
      need = 0.3 if self.kph > 20.0 else 0.0
    self.IQFilterSDL.push(need)
    self.IQDynamicU = self.IQFilterSDL.value() or 0.0
    self.hasIQSDL = self.IQDynamicU > (IQConstants.BRAKE_CURVE_GATE * 0.8)
    self.curve_detected = self.hasIQSDL

    if self.ss_c <= 5 and not self.hasIQSDL:
      slowness_observed = float(self.kph <= (self.cruise_kph * IQConstants.CRUISE_LAG_RATIO_GATE))
      self.IQFilterSFL.push(slowness_observed)
      threshold = IQConstants.CRUISE_LAG_GATE * (0.8 if self.hasIQSFL else 1.1)
      self.hasIQSFL = (self.IQFilterSFL.value() or 0.0) > threshold

    v_ego = float(car_state.vEgo)
    self.low_speed_detected = not self.tracking_lead and IQConstants.CRUISING_SPEED <= v_ego < self.conditional_speed
    self.low_speed_lead_detected = self.tracking_lead and IQConstants.CRUISING_SPEED <= v_ego < self.conditional_lead_speed

    if self.tracking_lead:
      slower_lead = (v_ego - self.lead_speed) > IQConstants.CRUISING_SPEED and self.conditional_slower_lead
      stopped_lead = self.lead_speed < 1.0 and self.conditional_stopped_lead
      self.IQFilterSlowLead.push(float(slower_lead or stopped_lead))
      self.slow_lead_detected = (self.IQFilterSlowLead.value() or 0.0) >= IQConstants.SLOW_LEAD_THRESHOLD
    else:
      self.IQFilterSlowLead.reset()
      self.slow_lead_detected = False

    should_stop = bool(getattr(getattr(model, "action", None), "shouldStop", False))
    model_stopping = self.model_length > 0.0 and self.model_length < max(v_ego * self.model_stop_time, IQConstants.CRUISING_SPEED)
    self.model_stopped = bool(should_stop or model_stopping)
    self.IQFilterModelStop.push(float(self.model_stopped and not self.tracking_lead))
    self.stop_light_detected = (self.IQFilterModelStop.value() or 0.0) >= IQConstants.MODEL_STOP_THRESHOLD

  def _request_blended(self, urgency: float = 1.0, emergency: bool = False) -> None:
    self.IQEngineManager.request('blended', urgency=urgency, emergency=emergency)

  def _request_acc(self, urgency: float = 0.8) -> None:
    self.IQEngineManager.request('acc', urgency=urgency)

  def IQStateEngine(self) -> None:
    if self.hasIQL:
      self._request_blended(1.0, True)
    elif self.stop_light_detected and self.conditional_model_stops:
      self._request_blended(1.0, self.model_stopped)
    elif self.low_speed_detected or self.low_speed_lead_detected:
      self._request_blended(0.95)
    elif self.slow_lead_detected:
      self._request_blended(0.9)
    elif self.conditional_curves and self.hasIQSDL:
      self._request_blended(max(0.8, min(1.0, self.IQDynamicU * 1.5)))
    elif self.conditional_slc_fallback and self.slc_experimental_mode:
      self._request_blended(0.8)
    elif self.ss_c > 3:
      self._request_blended(0.9)
    elif self.hasIQSFL and not self.hasIQSDL:
      self._request_acc(0.8)
    else:
      self._request_acc(0.7)

  def IQStateEngine_R(self) -> None:
    if self.hasIQL:
      self._request_blended(1.0, True)
    elif self.stop_light_detected and self.conditional_model_stops:
      self._request_blended(1.0, self.model_stopped)
    elif self.low_speed_detected or self.low_speed_lead_detected:
      self._request_blended(0.95)
    elif self.slow_lead_detected:
      self._request_blended(0.9)
    elif self.conditional_curves and self.hasIQSDL:
      self._request_blended(max(0.8, min(1.0, self.IQDynamicU * 1.3)))
    elif self.conditional_slc_fallback and self.slc_experimental_mode:
      self._request_blended(0.8)
    elif self.hasIQFilterLED and not (self.ss_c > 3):
      self._request_acc(1.0)
    elif self.ss_c > 3:
      self._request_blended(0.9)
    elif self.hasIQSFL and not self.hasIQSDL:
      self._request_acc(0.8)
    else:
      self._request_acc(0.7)

  def update(self, sm: messaging.SubMaster) -> None:
    self._readIQParams()
    self.setaeb()
    self.IQDynamicEngine(sm)
    if self.IQS.radarUnavailable:
      self.IQStateEngine()
    else:
      self.IQStateEngine_R()
    self.IQEngineManager.update()
    self.IQDynamicA = sm['selfdriveState'].experimentalMode and self.IQDynamicStatus
    self.IQDynamicF += 1
