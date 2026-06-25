import time
import math

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.volkswagen.values import VolkswagenFlags
from opendbc.car.lateral import ISO_LATERAL_ACCEL

NOT_SET = 0
SPEED_SUGGESTED_MAX_HIGHWAY_GER_KPH = 130 # 130 kph in germany
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
  def __init__(self, car_params, speed_limit_max_kph=SPEED_SUGGESTED_MAX_HIGHWAY_GER_KPH, predicative=False, predicative_speed_limit=False, predicative_curve=False):
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

  def enable_predicative_speed_limit(self, predicative=False, reaction_to_speed_limits=False, reaction_to_curves=False):
    if self.predicative == predicative and self.predicative_speed_limit == reaction_to_speed_limits and self.predicative_curve == reaction_to_curves:
      return # perf
      
    if not predicative or (not reaction_to_speed_limits and not reaction_to_curves):
      self._reset_predicative()
      self.predicative = False  # fully disable execution
    else:
      self.predicative = predicative
      
    if (not reaction_to_speed_limits and self.predicative_speed_limit) or (not reaction_to_curves and self.predicative_curve):
      self._reset_predicative()  # force reset when disabling
      
    self.predicative_speed_limit = reaction_to_speed_limits
    self.predicative_curve = reaction_to_curves
      
    
  def update(self, current_speed_ms, psd_04, psd_05, psd_06, vze, raining, time_car):
    # try reading speed form traffic sign recognition
    if vze and self.CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      self._receive_speed_limit_vze_meb(vze)

    # read speed unit from PSD_06 and also use it for traffic sign recognition if present (for now always seen on bus 0)
    # the vze location/unit flag is not stable and no corresponding flag has been found yet
    if psd_06:
      self._receive_speed_unit_psd(psd_06)

    # try reading speed from predicative street data
    if psd_04 and psd_05 and psd_06:
      self._receive_current_segment_psd(psd_05)
      self._refresh_current_segment()
      self._build_predicative_segments(psd_04, psd_06, raining, time_car)
      self._receive_speed_limit_psd_legal(psd_06)
      self._get_speed_limit_psd()
      if self.predicative:
        self._get_speed_limit_psd_next(current_speed_ms) # this is very cpu heavy

  def get_speed_limit_predicative(self):
    v_limit_output = self.v_limit_psd_next if self.predicative and self.v_limit_psd_next != NOT_SET and self.v_limit_psd_next < self.v_limit_output_last else NOT_SET
    return v_limit_output * CV.KPH_TO_MS
    
  def get_speed_limit_predicative_type(self):
    return self.v_limit_psd_next_type

  def get_speed_limit(self):
    candidates = {
      "vze": self.v_limit_vze if self.v_limit_vze != NOT_SET and not self.v_limit_vze_sanity_error else NOT_SET,
      "psd": self.v_limit_psd if self.v_limit_psd != NOT_SET else NOT_SET,
      "legal": self.v_limit_psd_legal
    }

    v_limit_output = NOT_SET
    for source in ["vze", "psd", "legal"]:
      v = candidates[source]
      if v != NOT_SET:
        v_limit_output = v
        break
  
    if v_limit_output > self.v_limit_max:
      v_limit_output = self.v_limit_max
    
    self.v_limit_changed = True if self.v_limit_output_last != v_limit_output else False
    self.v_limit_output_last = v_limit_output
  
    return v_limit_output * CV.KPH_TO_MS

  def _speed_limit_vze_sanitiy_check(self, speed_limit_vze_new):
    if self.v_limit_output_last == NOT_SET:
      self.v_limit_vze_sanity_error = False
      return

    diff_p = 100 * speed_limit_vze_new / self.v_limit_output_last
    self.v_limit_vze_sanity_error = True if diff_p < SANITY_CHECK_DIFF_PERCENT_LOWER else False
    if speed_limit_vze_new > SPEED_LIMIT_UNLIMITED_VZE_KPH: # unlimited sign detected: use psd logic for setting maximum speed
      self.v_limit_vze_sanity_error = True

  def _receive_speed_unit_psd(self, psd_06):
    # keep it simple for now, the unit is supplied shortly before the corresponding speed limits are supplied for given segment ID
    if psd_06["PSD_06_Mux"] == 0 and psd_06["PSD_Sys_Segment_ID"] > 1:
      self.v_limit_speed_unit_psd = psd_06["PSD_Sys_Geschwindigkeit_Einheit"]

  def _convert_raw_speed_psd(self, raw_speed, street_type):
    speed = NOT_SET
    
    if self.v_limit_speed_unit_psd == PSD_UNIT_KPH:
      if 0 < raw_speed < 11: # 0 - 45 kph
        speed = (raw_speed - 1) * 5
      elif 11 <= raw_speed < 23: # 50 - 160 kph
        speed = 50 + (raw_speed - 11) * 10
      elif raw_speed == 23: # explicitly no legal speed limit 
        if street_type == STREET_TYPE_HIGHWAY:
          speed = self.v_limit_max

    elif self.v_limit_speed_unit_psd == PSD_UNIT_MPH:
      if 3 < raw_speed < 18:  # 0 - 70 mph
        speed = (5 * (raw_speed - 3)) * CV.MPH_TO_KPH
      elif 18 <= raw_speed < 23: # 75 - 105 mph
        speed = ((5 * (raw_speed - 3)) + 10) * CV.MPH_TO_KPH
      elif raw_speed == 23: # explicitly no legal speed limit 
        if street_type == STREET_TYPE_HIGHWAY:
          speed = self.v_limit_max

    return speed

  def _receive_speed_limit_vze_meb(self, vze):
    v_limit_vze = vze["VZE_Verkehrszeichen_1"] # main traffic sign
    # "VZE_Anzeigemodus" has been seen not being stable for different drives in same USA mph car, no other flag has been found yet
    # for now additionally assume a car with mph speed unit nav data sgements is also supplied with mph converted vze data ("PSD_06" is available on bus 0)
    # mph speed unit set in signal "Einheiten_01" does not mean the speed data being supplied in mph unit!
    v_limit_vze = v_limit_vze * CV.MPH_TO_KPH if vze["VZE_Anzeigemodus"] == 1 or self.v_limit_speed_unit_psd == PSD_UNIT_MPH else v_limit_vze
    self._speed_limit_vze_sanitiy_check(v_limit_vze)
    self.v_limit_vze = v_limit_vze

  def _receive_current_segment_psd(self, psd_05):
    if psd_05["PSD_Pos_Standort_Eindeutig"] == 1 and psd_05["PSD_Pos_Segment_ID"] != NOT_SET:
      self.current_predicative_segment["Length"] = psd_05["PSD_Pos_Segmentlaenge"]
      
      if self.current_predicative_segment["ID"] != psd_05["PSD_Pos_Segment_ID"]:
        self.current_predicative_segment["ID"] = psd_05["PSD_Pos_Segment_ID"]
        self.current_predicative_segment["Speed"] = NOT_SET
        self.current_predicative_segment["StreetType"] = NOT_SET
        self.current_predicative_segment["OnRampExit"] = False
        
  def _get_segment_curvature_psd(self, psd_curvature, psd_sign, scale=2e-5):
    if psd_curvature in (0, 255):
      return NOT_SET

    curvature = (255 - psd_curvature) * scale
    if psd_sign == 1:
      curvature *= -1
      
    return curvature
    
  def _calculate_curve_speed(self, curvature):
    if curvature == NOT_SET:
      return NOT_SET
      
    curv_speed_ms = math.sqrt(ISO_LATERAL_ACCEL / abs(curvature))

    if self.v_limit_speed_unit_psd == PSD_UNIT_MPH:
      curv_speed = int((curv_speed_ms * CV.MS_TO_MPH) // 5 * 5) * CV.MPH_TO_KPH
    else:
      curv_speed = int((curv_speed_ms * CV.MS_TO_KPH) // 5 * 5)
      
    return curv_speed
    
  def _refresh_current_segment(self):
    current_segment = self.current_predicative_segment["ID"]
    if current_segment != NOT_SET:
      seg = self.predicative_segments.get(current_segment)
      if seg:
        self.current_predicative_segment["Speed"] = self.predicative_segments[current_segment]["Speed"]
        self.current_predicative_segment["StreetType"] = self.predicative_segments[current_segment]["StreetType"]
        self.current_predicative_segment["OnRampExit"] = self.predicative_segments[current_segment]["OnRampExit"]

  def _build_predicative_segments(self, psd_04, psd_06, raining, time_car):
    now = time.time()

    # Segment erfassen/aktualisieren
    if (psd_04["PSD_ADAS_Qualitaet"] == 1 and
        psd_04["PSD_wahrscheinlichster_Pfad"] == 1 and
        psd_04["PSD_Segment_ID"] != NOT_SET):

      segment_id = psd_04["PSD_Segment_ID"]
      seg = self.predicative_segments.get(segment_id)
      if seg:
        seg["Length"] = psd_04["PSD_Segmentlaenge"]
        seg["Curvature_Begin"] = self._get_segment_curvature_psd(psd_04["PSD_Anfangskruemmung"], psd_04["PSD_Anfangskruemmung_Vorz"])
        seg["Curvature_End"] = self._get_segment_curvature_psd(psd_04["PSD_Endkruemmung"], psd_04["PSD_Endkruemmung_Vorz"])
        seg["StreetType"] = self._get_street_type(psd_04["PSD_Strassenkategorie"], psd_04["PSD_Bebauung"])
        seg["OnRampExit"] = psd_04["PSD_Rampe"] in (1, 2)
        seg["ID_Prev"] = psd_04["PSD_Vorgaenger_Segment_ID"]
        seg["Curve_Speed_Begin"] = self._calculate_curve_speed(seg["Curvature_Begin"])
        seg["Curve_Speed_End"] = self._calculate_curve_speed(seg["Curvature_End"])
        seg["Timestamp"] = now
      else:
        self.predicative_segments[segment_id] = {
          "ID": segment_id,
          "Length": psd_04["PSD_Segmentlaenge"],
          "Curvature_Begin": self._get_segment_curvature_psd(psd_04["PSD_Anfangskruemmung"], psd_04["PSD_Anfangskruemmung_Vorz"]),
          "Curvature_End": self._get_segment_curvature_psd(psd_04["PSD_Endkruemmung"], psd_04["PSD_Endkruemmung_Vorz"]),
          "StreetType": self._get_street_type(psd_04["PSD_Strassenkategorie"], psd_04["PSD_Bebauung"]),
          "OnRampExit": psd_04["PSD_Rampe"] in (1, 2),
          "ID_Prev": psd_04["PSD_Vorgaenger_Segment_ID"],
          "Speed": NOT_SET,
          "Curve_Speed_Begin": NOT_SET,
          "Curve_Speed_End": NOT_SET,
          "QualityFlag": False,
          "Timestamp": now
        }
        seg = self.predicative_segments.get(segment_id)
        seg["Curve_Speed_Begin"] = self._calculate_curve_speed(seg["Curvature_Begin"])
        seg["Curve_Speed_End"] = self._calculate_curve_speed(seg["Curvature_End"])

    # Schritt 2: Alte Segmente bereinigen
    current_id = self.current_predicative_segment["ID"]
    if current_id != NOT_SET:
      self.predicative_segments = {
        sid: seg for sid, seg in self.predicative_segments.items()
        if now - seg.get("Timestamp", 0) <= SEGMENT_DECAY
      }

    # Geschwindigkeit setzen (speed limits seen for changed limits only)
    if (psd_06["PSD_06_Mux"] == 2 and
        psd_06["PSD_Ges_Typ"] == 1 and
        psd_06["PSD_Ges_Gesetzlich_Kategorie"] == 0 and
        psd_06["PSD_Ges_Segment_ID"] != NOT_SET):

      raw_speed = psd_06["PSD_Ges_Geschwindigkeit"] if self._speed_limit_is_valid_now_psd(psd_06, raining, time_car) else NOT_SET
      segment_id = psd_06["PSD_Ges_Segment_ID"]

      if segment_id in self.predicative_segments:
        speed = self._convert_raw_speed_psd(raw_speed, self.predicative_segments[segment_id]["StreetType"])
        self.predicative_segments[segment_id]["Speed"] = speed
        self.predicative_segments[segment_id]["Speed_Type"] = PSD_TYPE_SPEED_LIMIT
        self.predicative_segments[segment_id]["QualityFlag"] = True

  def _get_time_from_vw_datetime(self, time_car):
    if time_car:
      try:
        t = (time_car["UH_Jahr"], time_car["UH_Monat"], time_car["UH_Tag"], time_car["UH_Stunde"], time_car["UH_Minute"], time_car["UH_Sekunde"], 0, 0, -1)
        local_time = time.mktime(t)
        return time.localtime(local_time)
      except Exception:
        return time.localtime()
    else:
      return time.localtime()
  
  def _speed_limit_is_valid_now_psd(self, psd_06, raining, time_car):
    local_time = self._get_time_from_vw_datetime(time_car)
    
    # by day
    day_start = psd_06["PSD_Ges_Geschwindigkeit_Tag_Anf"]
    day_end = psd_06["PSD_Ges_Geschwindigkeit_Tag_Ende"]
    now_weekday = (local_time.tm_wday + 1)  # Python: 0=Montag → PSD: 1=Montag

    if 1 <= day_start <= 7 and 1 <= day_end <= 7:
      if day_start <= day_end:
        is_valid_by_day = day_start <= now_weekday <= day_end
      else:
        is_valid_by_day = now_weekday >= day_start or now_weekday <= day_end
    else:
      is_valid_by_day = True
  
    # by time
    hour_start = psd_06["PSD_Ges_Geschwindigkeit_Std_Anf"]
    hour_end = psd_06["PSD_Ges_Geschwindigkeit_Std_Ende"]
    now_hour = local_time.tm_hour
    
    if (hour_start != 25 and hour_end != 25):
      if hour_start <= hour_end:
        is_valid_by_time = hour_start <= now_hour < hour_end
      else:
        is_valid_by_time = now_hour >= hour_start or now_hour < hour_end
    else:
      is_valid_by_time = True

    # by weather condition
    weather_condition = psd_06["PSD_Ges_Geschwindigkeit_Witter"]
    is_valid_by_weather_conditions = weather_condition == 0 or ( raining and weather_condition == 1 )

    checks = [
      is_valid_by_time,
      is_valid_by_day,
      is_valid_by_weather_conditions,
    ]
      
    return all(checks)

  def _speed_limit_curve_allowed(self, seg):
    currently_on_ramp = self.current_predicative_segment.get("OnRampExit", False)
    seg_on_ramp = seg.get("OnRampExit", False)
    
    ramp_allowed_on_ramp = currently_on_ramp and seg_on_ramp
    ramp_allowed = ramp_allowed_on_ramp or not seg_on_ramp

    # on ramp is probably type 2 TODO
    # for now only allow non urban, there are problems with highway curvature data
    street_type = seg.get("StreetType", NOT_SET)
    street_type_allowed = True if street_type == STREET_TYPE_NONURBAN or (street_type == STREET_TYPE_HIGHWAY and ramp_allowed_on_ramp) else False
    
    speed_curve = seg.get("Curve_Speed", NOT_SET)

    if NOT_SET not in (self.v_limit_output_last, speed_curve):
      diff_p = 100 * speed_curve / self.v_limit_output_last
      sanity_error = True if diff_p < SANITY_CHECK_DIFF_PERCENT_LOWER else False
    else:
      sanity_error = False
    
    checks = [
      ramp_allowed,
      street_type_allowed,
      not sanity_error,
    ]
      
    return all(checks)

  def _hit_linear_profile(self, v0_ms, a, total_dist_m, L_m, v_b_kmh, v_e_kmh):
    if L_m is None or L_m <= 0:
        return None, None

    v_b = v_b_kmh * CV.KPH_TO_MS
    v_e = v_e_kmh * CV.KPH_TO_MS
    r = (v_e - v_b) / L_m  # m/s pro m

    # Flaches Profil => Standard-Bremsweg gegen v_b am Beginn
    if abs(r) < 1e-9:
        if v0_ms <= v_b:
            return None, None
        brake_dist = (v0_ms**2 - v_b**2) / (2*a)
        if brake_dist >= total_dist_m:
            # Aktivierung am Segmentbeginn
            return 0.0, v_b_kmh
        return None, None

    A = r*r
    B = 2*v_b*r + 2*a
    C = v_b*v_b + 2*a*total_dist_m - v0_ms*v0_ms

    D = B*B - 4*A*C
    if D < 0:
      return None, None

    sqrtD = math.sqrt(D)
    # Kleinste nicht-negative Lösung
    s1 = (-B - sqrtD) / (2*A)
    s2 = (-B + sqrtD) / (2*A)
    s_candidates = [s for s in (s1, s2) if s >= 0.0]

    if not s_candidates:
      return None, None

    s_hit = min(s_candidates)
    if s_hit > L_m:
      return None, None

    v_req_ms = v_b + r * s_hit
    return float(s_hit), (v_req_ms * CV.MS_TO_KPH)

  def _dfs(self, seg_id, total_dist, visited, current_speed_ms, best_result, path):
    if seg_id in visited or seg_id not in path:
      return
    visited.add(seg_id)
  
    seg = self.predicative_segments.get(seg_id)
    if not seg:
      return
      
    candidates = []

    length = seg.get("Length", NOT_SET)

    # Speed-Limit
    if self.predicative_speed_limit:
      sl = seg.get("Speed", NOT_SET)
      if sl != NOT_SET:
        qual_ok = seg.get("QualityFlag", False)
        candidates.append((sl, PSD_TYPE_SPEED_LIMIT, 0.0, qual_ok))
    
    # Curve-Speed
    if self.predicative_curve and self._speed_limit_curve_allowed(seg):
      cs_begin = seg.get("Curve_Speed_Begin", NOT_SET)
      cs_end = seg.get("Curve_Speed_End", NOT_SET)
      
      if cs_begin != NOT_SET:
        candidates.append((cs_begin, PSD_TYPE_CURV_SPEED, 0.0, True))
      
      if cs_end != NOT_SET and length > 0:
        candidates.append((cs_end, PSD_TYPE_CURV_SPEED, length, True))
        
      # Curve-Speed Profile
      if cs_begin != NOT_SET and cs_end != NOT_SET and length > 0:
        s_hit, v_req_kmh = self._hit_linear_profile(v0_ms=current_speed_ms, a=DECELERATION_PREDICATIVE,
                                                    total_dist_m=total_dist, L_m=length, v_b_kmh=cs_begin, v_e_kmh=cs_end)
        if s_hit is not None and v_req_kmh is not None:
          candidates.append((v_req_kmh, PSD_TYPE_CURV_SPEED, s_hit, True))
    
    # check candidates
    for cand_speed_kmh, cand_type, activation_offset, qual_ok in candidates:
      if cand_speed_kmh == NOT_SET:
        continue
        
      if not qual_ok:
        continue
    
      v_target_ms = cand_speed_kmh * CV.KPH_TO_MS
      if not (v_target_ms < current_speed_ms and (cand_speed_kmh < self.v_limit_output_last or self.v_limit_output_last == NOT_SET)):
        continue
    
      brake_dist = (current_speed_ms**2 - v_target_ms**2) / (2 * DECELERATION_PREDICATIVE)
      if brake_dist <= 0:
        continue
    
      dist_to_activation = total_dist + activation_offset
      if dist_to_activation <= brake_dist:
        # choose lowest limit or shorter length when equal
        better = False
        if cand_speed_kmh < best_result["limit"]:
          better = True
        elif cand_speed_kmh == best_result["limit"] and dist_to_activation < best_result["dist"]:
          better = True
    
        if better:
          best_result["limit"] = cand_speed_kmh
          best_result["type"] = cand_type
          best_result["dist"] = dist_to_activation # represents distance to limit
          best_result["length"] = length - activation_offset # represents remaining distance with limit for curves

    children = [sid for sid, s in self.predicative_segments.items() if s.get("ID_Prev") == seg_id]
    if len(children) > 1:
      return  # Split detected, can not decide unique limit on current path
  
    for next_id in children:
      if seg_id == self.current_predicative_segment.get("ID"):
        next_length = self.current_predicative_segment.get("Length", 0)
      else:
        next_length = seg.get("Length", 0)
        
      self._dfs(next_id, total_dist + next_length, visited.copy(), current_speed_ms, best_result, path)

  def _build_path_psd(self, start_seg_id):
    path = []
    current_id = start_seg_id
    visited = set()

    segment_children_map = {}
    for sid, seg in self.predicative_segments.items():
      parent = seg.get("ID_Prev")
      if parent not in (None, NOT_SET):
        segment_children_map.setdefault(parent, []).append(sid)

    while current_id != NOT_SET:
      if current_id in visited:
        break
      visited.add(current_id)
      path.append(current_id)
      children = segment_children_map.get(current_id, [])
      if len(children) != 1:
        break 
      current_id = children[0]

    return path

  def _get_speed_limit_psd_next(self, current_speed_ms):      
    current_id = self.current_predicative_segment.get("ID")
    self.v_limit_psd_next = NOT_SET

    if current_id == NOT_SET:
      return
      
    path = self._build_path_psd(current_id)
    
    if len(path) <= 1:
      return

    best_result = {"limit": float('inf'), "type": NOT_SET, "dist": float('inf'), "length": float('inf')}
    self._dfs(current_id, 0, set(), current_speed_ms, best_result, path)

    now = time.time()
    if best_result["limit"] != float('inf'):
      self.v_limit_psd_next = best_result["limit"]
      self.v_limit_psd_next_type = best_result["type"]
      self.v_limit_psd_next_last = best_result["limit"]
      self.v_limit_psd_next_last_timestamp = now
      self.v_limit_psd_next_decay_time = math.sqrt(2 * best_result["dist"] / DECELERATION_PREDICATIVE)
      if self.v_limit_psd_next_type == PSD_TYPE_CURV_SPEED:
        self.v_limit_psd_next_decay_time += max((best_result["length"] / (self.v_limit_psd_next * CV.KPH_TO_MS)), PSD_CURV_SPEED_DECAY)
    else:
      if now - self.v_limit_psd_next_last_timestamp <= self.v_limit_psd_next_decay_time and self.v_limit_output_last > self.v_limit_psd_next_last and not self.v_limit_changed:
        self.v_limit_psd_next = self.v_limit_psd_next_last
      else:
        self.v_limit_psd_next_last = NOT_SET
        self.v_limit_psd_next_decay_time = NOT_SET
        self.v_limit_psd_next_type = NOT_SET

  def _get_speed_limit_psd(self):
    seg_id = self.current_predicative_segment.get("ID")
    if seg_id == NOT_SET:
      self.v_limit_psd = NOT_SET
      return

    seg = self.predicative_segments.get(seg_id)
    if seg and seg.get("Speed") != NOT_SET:
      self.v_limit_psd = seg.get("Speed")

  def _get_street_type(self, strassenkategorie, bebauung):
    street_type = NOT_SET

    if strassenkategorie == 1: # base type: urban
      street_type = STREET_TYPE_URBAN

    elif strassenkategorie in (2, 3, 4): # base type: non urban
      if bebauung == 1:
        street_type = STREET_TYPE_URBAN
      else:
        street_type = STREET_TYPE_NONURBAN

    elif strassenkategorie == 5: # base type: highway
      street_type = STREET_TYPE_HIGHWAY

    return street_type

  def _receive_speed_limit_psd_legal(self, psd_06):
    if psd_06["PSD_06_Mux"] == 2:
      if psd_06["PSD_Ges_Typ"] == 2:
        street_type = self.current_predicative_segment["StreetType"]
        if ((psd_06["PSD_Ges_Gesetzlich_Kategorie"] == STREET_TYPE_URBAN    and street_type == STREET_TYPE_URBAN) or
            (psd_06["PSD_Ges_Gesetzlich_Kategorie"] == STREET_TYPE_NONURBAN and street_type == STREET_TYPE_NONURBAN) or
            (psd_06["PSD_Ges_Gesetzlich_Kategorie"] == STREET_TYPE_HIGHWAY  and street_type == STREET_TYPE_HIGHWAY)):
          raw_speed = psd_06["PSD_Ges_Geschwindigkeit"]
          self.v_limit_psd_legal = self._convert_raw_speed_psd(raw_speed, street_type)
