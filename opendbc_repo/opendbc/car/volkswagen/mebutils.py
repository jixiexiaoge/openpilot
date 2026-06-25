import numpy as np

from opendbc.car.common.filter_simple import FirstOrderFilter
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.common.pid import PIDController
from opendbc.car import DT_CTRL


class LongControlJerk():
  JERK_LIMIT_MIN = 0.5
  JERK_LIMIT_MIN_NO_LEAD = 0.7
  JERK_LIMIT_MAX = 5.0
  FILTER_GAIN_DISTANCE = [10, 50]
  FILTER_GAIN_DISTANCE_CHANGE = [0, 20]
  FILTER_GAIN_MAX = 0.95
  FILTER_GAIN_MIN = 0.75
  FILTER_GAIN_NO_LEAD = 0.95
  
  def __init__(self, dt=DT_CTRL):
    self.dy_up = 0.
    self.dy_down = 0.
    self.jerk_up = 0.
    self.jerk_down = 0.
    self.dt = dt
    self.accel_last = 0.
    self.distance_last = 0.
    self.jerk_limit_min = self.JERK_LIMIT_MIN_NO_LEAD
    
  def update(self, enabled, override, distance, has_lead, accel, critical_state):
    # jerk limits by accel change and distance are used to improve comfort while ensuring a fast enough car reaction
    # override mechanics reminder:
    # (1) sending accel = 0 and directly setting jerk to zero results in round about steady accel until harder accel pedal press -> lack of control
    # (2) sending accel = 0 and allowing a high jerk results in a abrupt accel cut -> lack of comfort    
    if not enabled:
      self.jerk_up = 0.
      self.jerk_down = 0.
      self.dy_up = 0.
      self.dy_down = 0.
    elif override:
      self.jerk_up = self.JERK_LIMIT_MIN
      self.jerk_down = self.JERK_LIMIT_MIN
      self.dy_up = 0.
      self.dy_down = 0.
    elif critical_state: # force best car reaction
      self.jerk_up = self.JERK_LIMIT_MAX
      self.jerk_down = self.JERK_LIMIT_MAX
      self.dy_up = 0.
      self.dy_down = 0.
    else:
      jerk_limit_min_target = self.JERK_LIMIT_MIN if has_lead else self.JERK_LIMIT_MIN_NO_LEAD # jerk limit min base line
      jerk_limit_min_delta = abs(self.JERK_LIMIT_MIN_NO_LEAD - self.JERK_LIMIT_MIN) * self.dt
      if self.jerk_limit_min < jerk_limit_min_target:
        self.jerk_limit_min = min(self.jerk_limit_min + jerk_limit_min_delta, jerk_limit_min_target)
      elif self.jerk_limit_min > jerk_limit_min_target:
        self.jerk_limit_min = max(self.jerk_limit_min - jerk_limit_min_delta, jerk_limit_min_target)
      
      if has_lead:
        distance_change = (self.distance_last - distance) / self.dt if 0 not in (self.distance_last, distance) else 0
        filter_gain_dist = np.interp(distance, self.FILTER_GAIN_DISTANCE, [self.FILTER_GAIN_MAX, self.jerk_limit_min]) # gain by distance
        filter_gain_dist_change = np.interp(abs(distance_change), self.FILTER_GAIN_DISTANCE_CHANGE, [self.jerk_limit_min, self.FILTER_GAIN_MAX]) # gain by distance change
        filter_gain = max(filter_gain_dist, filter_gain_dist_change) # use highest gain
      else:
        filter_gain = self.FILTER_GAIN_NO_LEAD
      
      j = (accel - self.accel_last) / self.dt
  
      tgt_up = abs(j) if j > 0 else 0.
      tgt_down = abs(j) if j < 0 else 0.
  
      # how fast does the car react to acceleration
      self.dy_up += filter_gain * (tgt_up - self.jerk_up - self.dy_up)
      self.jerk_up += self.dt * self.dy_up
      self.jerk_up = np.clip(self.jerk_up, self.jerk_limit_min, self.JERK_LIMIT_MAX)
  
      # how fast does the car react to braking
      self.dy_down += filter_gain * (tgt_down - self.jerk_down - self.dy_down)
      self.jerk_down += self.dt * self.dy_down
      self.jerk_down = np.clip(self.jerk_down, self.jerk_limit_min, self.JERK_LIMIT_MAX)
  
    self.accel_last = accel
    self.distance_last = distance

  def get_jerk_up(self):
    return self.jerk_up
    
  def get_jerk_down(self):
    return self.jerk_down
    

class LongControlLimit():
  LOWER_LIMIT_FACTOR = 0.024
  LOWER_LIMIT_MAX = LOWER_LIMIT_FACTOR * 8
  LOWER_LIMIT_MIN = LOWER_LIMIT_FACTOR * 2
  UPPER_LIMIT_FACTOR = 0.0625
  UPPER_LIMIT_MAX = UPPER_LIMIT_FACTOR * 3
  LIMIT_MIN = 0.
  LIMIT_DISTANCE = [10, 100] # limit range
  LIMIT_DISTANCE_CHANGE_DOWN = [0, 20] # high precision for worst case high speed approaching a stopped lead
  LIMIT_DISTANCE_CHANGE_UP = [0, 5] # precisely follow an accelerating lead especially from stop
  LIMIT_DISTANCE_CHANGE_UP_ACT = [0, 60]
  DISTANCE_FILTER_RC = [0.15, 0.6] # smooth noisy distance signal for distant leads
  DISTANCE_TIMEOUT = 1. # seconds
  
  def __init__(self, dt=DT_CTRL):
    self.upper_limit = self.LIMIT_MIN
    self.lower_limit = self.LIMIT_MIN
    self.dt = dt
    self.distance_last = 0.
    self.distance_filter = FirstOrderFilter(0.0, rc=self.DISTANCE_FILTER_RC[0], dt=dt, initialized=False)
    self.distance_valid_timer = 0
    
  def update(self, enabled: bool, speed: float, set_speed: float, distance: float, has_lead: bool, critical_state: bool):
    # control limits by distance are used to improve comfort while ensuring precise car reaction if neccessary
    # also used to reduce an effect of decel overshoot when target is breaking
    # limits are controlled mainly by distance of lead car
    if not enabled or critical_state: # force most precise accel command execution
      self.upper_limit = self.LIMIT_MIN
      self.lower_limit = self.LIMIT_MIN
      self.distance_valid_timer = 0
    elif not has_lead: 
      if self.distance_valid_timer < self.DISTANCE_TIMEOUT: # fluctuation block: keep alive
        self.distance_valid_timer += self.dt
      else: # force most precise
        self.upper_limit = self.LIMIT_MIN
        self.lower_limit = self.LIMIT_MIN
    else:
      distance_change_raw = (self.distance_last - distance) / self.dt if 0 not in (self.distance_last, distance) else 0
      distance_filter_rc = np.interp(distance, self.LIMIT_DISTANCE, self.DISTANCE_FILTER_RC)
      if (self.distance_last == 0 or self.distance_valid_timer != 0) and distance != 0: # for new lead detection reset filter and correctly force current state upon next iteration
        self.distance_filter = FirstOrderFilter(0.0, rc=distance_filter_rc, dt=self.dt, initialized=False)
        distance_change = distance_change_raw
      else:
        self.distance_filter.update_alpha(distance_filter_rc)
        distance_change = self.distance_filter.update(distance_change_raw)
      self.distance_valid_timer = 0
        
      # how far can the true accel vary downwards from requested accel
      upper_limit_dist = np.interp(distance, self.LIMIT_DISTANCE, [self.LIMIT_MIN, self.UPPER_LIMIT_MAX]) # base line based on distance
      upper_limit_dist_change = np.interp(-min(0, distance_change), self.LIMIT_DISTANCE_CHANGE_UP, [self.UPPER_LIMIT_MAX, self.LIMIT_MIN]) # limit by distance change up
      upper_limit_dist_change = np.interp(distance, self.LIMIT_DISTANCE_CHANGE_UP_ACT, [upper_limit_dist_change, upper_limit_dist]) # distance change activation
      self.upper_limit = min(upper_limit_dist, upper_limit_dist_change) # use lowest limit
      
      # how far can the true accel vary upwards from requested accel
      set_speed_diff_up = max(0, abs(speed) - abs(set_speed)) # set speed difference down requested by user or speed overshoot (includes hud - real speed difference!)
      set_speed_diff_up_factor = np.interp(set_speed_diff_up, [1, 1.75], [1., 0.]) # faster requested speed decrease and less speed overshoot downhill 
      lower_limit_dist = np.interp(distance, self.LIMIT_DISTANCE, [self.LOWER_LIMIT_MIN, self.LOWER_LIMIT_MAX]) # base line based on distance
      lower_limit_dist_speed = lower_limit_dist * set_speed_diff_up_factor
      lower_limit_dist_change = np.interp(max(0, distance_change), self.LIMIT_DISTANCE_CHANGE_DOWN, [self.LOWER_LIMIT_MAX, self.LIMIT_MIN]) # limit by distance change down
      self.lower_limit = min(lower_limit_dist_speed, lower_limit_dist_change) # use lowest limit

    self.distance_last = distance

  def get_upper_limit(self):
    return self.upper_limit
    
  def get_lower_limit(self):
    return self.lower_limit   


def sigmoid_curvature_boost_meb(kappa: float, v_ego: float, kappa_thresh: float = 0.0) -> float:
  # compensate non linear behaviour: boost low curvatures
  # this is either a model issue (nerfing low curvatures) or a specific steering rack behaviour
  v_points = np.array([20.0, 40.0])
  boost_values = np.array([1.5, 2.1]) # increase boost amplitude with speed
  boost = float(np.interp(v_ego, v_points, boost_values))
  steepness_values = np.array([5000.0, 3200.0]) # increase boost area with speed
  steepness = float(np.interp(v_ego, v_points, steepness_values))

  abs_kappa = abs(kappa)
  boost_factor = 1.0 + (boost - 1.0) / (1 + np.exp(steepness * (abs_kappa - kappa_thresh)))

  return np.sign(kappa) * abs_kappa * boost_factor


def map_speed_to_acc_tempolimit(v_ms):
  acc_tempolimit_kph = { # DBC Mapping
    1: 5, 2: 7, 3: 10, 4: 15, 5: 20, 6: 25, 7: 30, 8: 35,
    9: 40, 10: 45, 11: 50, 12: 55, 13: 60, 14: 65, 15: 70,
    16: 75, 17: 80, 18: 85, 19: 90, 20: 95, 21: 100, 22: 110,
    23: 120, 24: 130, 25: 140, 26: 150, 27: 160, 28: 200,
    30: 250
  }

  v_kph = int(round(v_ms * CV.MS_TO_KPH))
  acc_value = 0

  for val, limit in sorted(acc_tempolimit_kph.items()):
    if v_kph >= limit:
      acc_value = val
    else:
      break

  return acc_value
  
def get_acc_warning_meb(self, acc_hud):
  # this works as long our radar does not fault while using OP
  if (acc_hud["ACC_Status_ACC"] in (3, 4) # ACC active or in override mode
      and acc_hud["ACC_EGO_Fahrzeug"] == 2 # a warning for the lead car is active
      and acc_hud["ACC_Optischer_Fahrerhinweis"] != 0 # there is an optical warning
      and acc_hud["ACC_Akustischer_Fahrerhinweis"] != 0 # there is a sound warning
      and acc_hud["ACC_Display_Prio"] == 0): # this warning has highest priority
    return True
  return False
  
class MultiplicativeUnwindPID(PIDController):
  def __init__(self, k_p, k_i, k_f=0., k_d=0., pos_limit=1e308, neg_limit=-1e308, rate=100, min_cmd=1e-10, ki_red_time=1.0):
    super().__init__(k_p, k_i, k_f=k_f, k_d=k_d, pos_limit=pos_limit, neg_limit=neg_limit, rate=rate)
    self.min_cmd = abs(min_cmd)
    self.ki_red_time = float(ki_red_time)
    self.rate = rate
    self.override_prev = False
    self.i_unwind_factor = 1.0

  def _calc_unwind_factor(self, override):
    if not override or self.override_prev:
      return
    if self.ki_red_time <= 0.0:
      self.i_unwind_factor = 1.0
      return
    if abs(self.i) <= self.min_cmd:
      self.i_unwind_factor = 0.0
      return
    steps = max(int(self.ki_red_time * self.rate), 1)
    factor = (self.min_cmd / abs(self.i)) ** (1.0 / steps)
    self.i_unwind_factor = min(factor, 1.0)
    
  def update(self, error, error_rate=0.0, speed=0.0, override=False, feedforward=0., freeze_integrator=False):
    self.speed = speed

    self.p = float(error) * self.k_p
    self.f = feedforward * self.k_f
    self.d = error_rate * self.k_d

    if override:
      self._calc_unwind_factor(override)
      self.i *= self.i_unwind_factor
      if abs(self.i) < self.min_cmd:
        self.i = 0.0
    else:
      if not freeze_integrator:
        self.i = self.i + error * self.k_i * self.i_rate

        # Clip i to prevent exceeding control limits
        control_no_i = self.p + self.d + self.f
        control_no_i = np.clip(control_no_i, self.neg_limit, self.pos_limit)
        self.i = np.clip(self.i, self.neg_limit - control_no_i, self.pos_limit - control_no_i)

    control = self.p + self.i + self.d + self.f

    self.control = np.clip(control, self.neg_limit, self.pos_limit)
    self.override_prev = override
    return self.control

class LatControlCurvature():
  def __init__(self, pid_params, limit, rate):
    self.pid = MultiplicativeUnwindPID((pid_params.kpBP, pid_params.kpV),
                                       (pid_params.kiBP, pid_params.kiV),
                                       k_f=pid_params.kf, pos_limit=limit, neg_limit=-limit,
                                       rate=rate, min_cmd=6.7e-6, ki_red_time=2.0)
  def reset(self):
    self.pid.reset()
  
  def update(self, CS, CC, desired_curvature):
    actual_curvature_vm    = CC.currentCurvature # includes roll
    actual_curvature_pose  = CC.angularVelocity[2] / max(CS.vEgo, 0.1)
    actual_curvature       = np.interp(CS.vEgo, [2.0, 5.0], [actual_curvature_vm, actual_curvature_pose])
    desired_curvature_corr = desired_curvature - CC.rollCompensation
    error                  = desired_curvature - actual_curvature
    freeze_integrator      = CC.steerLimited or CS.vEgo < 5
    output_curvature       = self.pid.update(error, feedforward=desired_curvature_corr, speed=CS.vEgo,
                                             freeze_integrator=freeze_integrator, override=CS.steeringPressed)
    return output_curvature
