"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from typing import Literal

ModeType = Literal['acc', 'blended']
IQ_DYNAMIC_MODE_PARAM = "IQDynamicMode"
IQ_DYNAMIC_CONDITIONAL_CURVES_PARAM = "IQDynamicConditionalCurves"
IQ_DYNAMIC_CONDITIONAL_SLOWER_LEAD_PARAM = "IQDynamicConditionalSlowerLead"
IQ_DYNAMIC_CONDITIONAL_STOPPED_LEAD_PARAM = "IQDynamicConditionalStoppedLead"
IQ_DYNAMIC_CONDITIONAL_MODEL_STOPS_PARAM = "IQDynamicConditionalModelStops"
IQ_DYNAMIC_CONDITIONAL_SLC_FALLBACK_PARAM = "IQDynamicConditionalSLCFallback"
IQ_DYNAMIC_CONDITIONAL_SPEED_PARAM = "IQDynamicConditionalSpeed"
IQ_DYNAMIC_CONDITIONAL_LEAD_SPEED_PARAM = "IQDynamicConditionalLeadSpeed"
IQ_DYNAMIC_MODEL_STOP_TIME_PARAM = "IQDynamicModelStopTime"
IQ_FORCE_STOPS_PARAM = "IQForceStops"


class IQConstants:
  CRUISING_SPEED = 3.0
  SIGNAL_QUEUE_DEPTH = 6
  LEAD_LOCK_GATE = 0.45
  BRAKE_CURVE_QUEUE_DEPTH = 5
  BRAKE_CURVE_GATE = 0.3
  BRAKE_CURVE_SPEED_AXIS = [0., 10., 20., 30., 40., 50., 55., 60.]
  BRAKE_CURVE_DISTANCE_AXIS = [32., 46., 64., 86., 108., 130., 145., 165.]
  CRUISE_LAG_QUEUE_DEPTH = 10
  CRUISE_LAG_GATE = 0.55
  CRUISE_LAG_RATIO_GATE = 1.025
  CONDITIONAL_SPEED_DEFAULT = 18.0
  CONDITIONAL_LEAD_SPEED_DEFAULT = 24.0
  MODEL_STOP_TIME_DEFAULT = 3.0
  MODEL_STOP_THRESHOLD = 0.55
  SLOW_LEAD_THRESHOLD = 0.55
  FORCE_STOP_PLANNER_TIME = 3.0


def compute_slowdown_need(kph: float, horizon_dist: float, desired_dist: float) -> float:
  if horizon_dist >= desired_dist or desired_dist <= 0.0:
    return 0.0

  shortage = desired_dist - horizon_dist
  shortage_ratio = shortage / desired_dist
  need = min(1.0, shortage_ratio * 2.0)

  if horizon_dist < desired_dist * 0.3:
    need = min(1.0, need * 2.0)

  if kph > 25.0:
    need = min(1.0, need * (1.0 + (kph - 25.0) / 80.0))

  return need


class IQFilterEngine:
  def __init__(self, initial=0.0, measurement_noise=0.1, process_noise=0.01, process_decay=1.0, smoothing_floor=0.85):
    self._value = initial
    self._variance = 1.0
    self._measurement_noise = measurement_noise
    self._process_noise = process_noise
    self._process_decay = process_decay
    self._smoothing_floor = smoothing_floor
    self._initialized = False
    self._samples = []
    self._sample_limit = 10
    self._confidence = 0.0

  def push(self, measurement: float) -> None:
    if len(self._samples) >= self._sample_limit:
      self._samples.pop(0)
    self._samples.append(measurement)

    if not self._initialized:
      self._value = measurement
      self._initialized = True
      self._confidence = 0.1
      return

    self._variance = self._process_decay * self._variance + self._process_noise
    gain = self._variance / (self._variance + self._measurement_noise)
    effective_gain = gain * (1.0 - self._smoothing_floor) + self._smoothing_floor * 0.1

    innovation = measurement - self._value
    self._value = self._value + effective_gain * innovation
    self._variance = (1.0 - effective_gain) * self._variance

    if abs(innovation) < 0.1:
      self._confidence = min(1.0, self._confidence + 0.05)
    else:
      self._confidence = max(0.1, self._confidence - 0.02)

  def value(self):
    return self._value if self._initialized else None

  def confidence(self) -> float:
    return self._confidence

  def reset(self) -> None:
    self._initialized = False
    self._samples = []
    self._confidence = 0.0


class IQModeEngine:
  def __init__(self):
    self._state: ModeType = 'acc'
    self._scores = {'acc': 1.0, 'blended': 0.0}
    self._switching_timer = 0
    self._mode_age = 0
    self._forced_takeover = False

  def request(self, mode: ModeType, urgency: float = 1.0, emergency: bool = False) -> None:
    if emergency:
      self._forced_takeover = True
      self._state = mode
      self._switching_timer = 15
      self._mode_age = 0
      return

    self._scores[mode] = min(1.0, self._scores[mode] + 0.1 * urgency)
    for key in self._scores:
      if key != mode:
        self._scores[key] = max(0.0, self._scores[key] - 0.05)

    if self._mode_age < 10 and not self._forced_takeover:
      return

    threshold = 0.6 if mode != self._state else 0.3
    if self._scores[mode] > threshold and mode != self._state and self._switching_timer == 0:
      self._switching_timer = 15
      self._state = mode
      self._mode_age = 0

  def update(self) -> None:
    if self._switching_timer > 0:
      self._switching_timer -= 1

    self._mode_age += 1
    if self._forced_takeover and self._mode_age > 20:
      self._forced_takeover = False

    for key in self._scores:
      self._scores[key] *= 0.98

  def get_mode(self) -> ModeType:
    return self._state
