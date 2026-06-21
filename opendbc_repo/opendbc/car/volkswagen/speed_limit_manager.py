import time
import math

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.volkswagen.values import VolkswagenFlags
from opendbc.car.lateral import ISO_LATERAL_ACCEL

NOT_SET = 0
SPEED_SUGGESTED_MAX_HIGHWAY_GER_KPH = 130
STREET_TYPE_URBAN = 1
STREET_TYPE_NONURBAN = 2
STREET_TYPE_HIGHWAY = 3
SANITY_CHECK_DIFF_PERCENT_LOWER = 30
SPEED_LIMIT_UNLIMITED_VZE_KPH = int(round(144 * CV.MS_TO_KPH))
DECELERATION_PREDICATIVE = 1.0
SEGMENT_DECAY = 10
PSD_TYPE_SPEED_LIMIT = 1
PSD_TYPE_CURV_SPEED = 2
PSD_CURV_SPEED_DECAY = 4
PSD_UNIT_KPH = 0
PSD_UNIT_MPH = 1


class SpeedLimitManager:
  def __init__(self, car_params, speed_limit_max_kph=SPEED_SUGGESTED_MAX_HIGHWAY_GER_KPH,
               predicative=False, predicative_speed_limit=False, predicative_curve=False):
    self.CP = car_params
    self.v_limit_psd = NOT_SET
    self.v_limit_psd_next = NOT_SET
    self.v_limit_psd_legal = NOT_SET
    self.v_limit_psd_next_type = NOT_SET
    self.v_limit_vze = NOT_SET
    self.v_limit_speed_unit_psd = PSD_UNIT_KPH
    self.v_limit_vze_sanity_error = False
    self.v_limit_output_last = NOT_SET
    self.v_limit_max = speed_limit_max_kph
    self.predicative = predicative
    self.predicative_speed_limit = predicative_speed_limit
    self.predicative_curve = predicative_curve
    self.predicative_segments = {}
    self.current_predicative_segment = {"ID": NOT_SET, "Length": NOT_SET, "Speed": NOT_SET, "StreetType": NOT_SET, "OnRampExit": NOT_SET}
    self.v_limit_psd_next_last_timestamp = 0
    self.v_limit_psd_next_last = NOT_SET
    self.v_limit_psd_next_decay_time = NOT_SET
    self.v_limit_changed = False

  def _reset_predicative(self):
    self.v_limit_psd_next = NOT_SET
    self.v_limit_psd_next_type = NOT_SET
    self.v_limit_psd_next_last_timestamp = 0
    self.v_limit_psd_next_last = NOT_SET
    self.v_limit_psd_next_decay_time = NOT_SET

  def update(self, v_ego, v_limit_vze, v_limit_psd, v_limit_psd_next, v_limit_psd_next_type,
             v_limit_speed_unit_psd, psd_quality, steer_angle, steering_pressed, lead_distance,
             lead_v_rel, button_events, offroad):
    self._update_vze(v_ego, v_limit_vze, v_limit_speed_unit_psd)
    self._update_psd(v_ego, v_limit_psd, v_limit_psd_next, v_limit_psd_next_type,
                     v_limit_speed_unit_psd, psd_quality, steer_angle, steering_pressed,
                     lead_distance, lead_v_rel, button_events)
    return self._get_output()

  def _update_vze(self, v_ego, v_limit_vze, v_limit_speed_unit_psd):
    if v_limit_vze != NOT_SET:
      self.v_limit_vze = v_limit_vze
      self.v_limit_speed_unit_psd = v_limit_speed_unit_psd

  def _update_psd(self, v_ego, v_limit_psd, v_limit_psd_next, v_limit_psd_next_type,
                   v_limit_speed_unit_psd, psd_quality, steer_angle, steering_pressed,
                   lead_distance, lead_v_rel, button_events):
    if v_limit_psd != NOT_SET:
      self.v_limit_psd = v_limit_psd
      self.v_limit_psd_legal = v_limit_psd
      self.v_limit_speed_unit_psd = v_limit_speed_unit_psd

    if v_limit_psd_next != NOT_SET:
      self.v_limit_psd_next = v_limit_psd_next
      self.v_limit_psd_next_type = v_limit_psd_next_type

  def _get_output(self):
    output = NOT_SET
    if self.v_limit_psd != NOT_SET:
      output = self.v_limit_psd
    elif self.v_limit_vze != NOT_SET:
      output = self.v_limit_vze
    return output
