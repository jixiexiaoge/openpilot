import math
import numpy as np

from cereal import car
from openpilot.common.constants import CV
from cereal import car, custom
from iqdbc.car import structs
from openpilot.common.params import Params
from openpilot.iqpilot.selfdrive.car.long_increments import LongIncrementConfig, read_long_increment_config, resolve_button_step


# ===== VCruiseHelperIQ (dissolved from iqpilot vcruise_helper_iq) =====

ButtonType = car.CarState.ButtonEvent.Type
SpeedLimitAssistState = custom.IQPlan.SpeedLimit.AssistState
SPEED_LIMIT_CONTROL_ACTIVE_STATES = (SpeedLimitAssistState.active, SpeedLimitAssistState.adapting)


def compare_cluster_target(v_cruise_cluster: float, target_set_speed: float, is_metric: bool) -> tuple[bool, bool]:
  """Whether the cluster set-speed needs +/- presses to reach the target, in display units."""
  to_shown = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
  now = round(v_cruise_cluster * to_shown)
  goal = round(target_set_speed * to_shown)
  return now < goal, now > goal


CRUISE_BUTTON_TIMER = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0,
                       ButtonType.setCruise: 0, ButtonType.resumeCruise: 0,
                       ButtonType.cancel: 0, ButtonType.mainCruise: 0}

V_CRUISE_MIN = 8
V_CRUISE_MAX = 200  # ~ 124 mph
V_CRUISE_UNSET = 255
IQ_SET_SPEED_MODE_OFF = 0
IQ_SET_SPEED_MODE_FIXED = 1
IQ_SET_SPEED_MPH_DEFAULT = 65
IQ_SET_SPEED_MPH_MIN = 20
IQ_SET_SPEED_MPH_MAX = 120


def get_minimum_set_speed_kph(_is_metric: bool) -> float:
  # IQ minimum set speed floor, expressed in kph for VCruiseHelper integration.
  return float(V_CRUISE_MIN)


def update_manual_button_timers(CS: car.CarState, button_timers: dict[car.CarState.ButtonEvent.Type, int]) -> None:
  # age any button that's currently held (nonzero timer)
  for btn, held_frames in button_timers.items():
    if held_frames > 0:
      button_timers[btn] = held_frames + 1

  # a press/release edge (re)starts the timer at 1 or clears it to 0
  for event in CS.buttonEvents:
    raw = event.type.raw
    if raw in button_timers:
      button_timers[raw] = 1 if event.pressed else 0


class VCruiseHelperIQ:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams) -> None:
    self.CP = CP
    self.CP_IQ = CP_IQ
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.params = Params()
    self.v_cruise_min = 0
    self.enabled_prev = False

    self.long_increment_config: LongIncrementConfig = read_long_increment_config(self.params)
    self.set_speed_to_limit = self._read_set_speed_to_limit()
    self.iq_set_speed_mode = self._read_iq_set_speed_mode()
    self.iq_set_speed_use_current = self._read_iq_set_speed_use_current()
    self.iq_set_speed_mph = self._read_iq_set_speed_mph()

    self.enable_button_timers = CRUISE_BUTTON_TIMER

    # Speed Limit Assist
    self.speed_limit_state = SpeedLimitAssistState.disabled
    self.prev_speed_limit_state = SpeedLimitAssistState.disabled
    self.has_speed_limit = False
    self.speed_limit_final_last = 0.
    self.speed_limit_final_last_kph = 0.
    self.prev_speed_limit_final_last_kph = 0.
    self.req_plus = False
    self.req_minus = False

  def _read_set_speed_to_limit(self) -> bool:
    try:
      return self.params.get_bool("SLCSetSpeedToLimit")
    except Exception:
      return False

  def _read_iq_set_speed_mode(self) -> int:
    try:
      return int(self.params.get("IQE2ESetSpeedMode", return_default=True) or IQ_SET_SPEED_MODE_OFF)
    except Exception:
      return IQ_SET_SPEED_MODE_OFF

  def _read_iq_set_speed_use_current(self) -> bool:
    try:
      return bool(self.params.get_bool("IQE2ESetSpeedUseCurrent"))
    except Exception:
      return False

  def _read_iq_set_speed_mph(self) -> int:
    try:
      value = int(self.params.get("IQE2ESetSpeedMph", return_default=True) or IQ_SET_SPEED_MPH_DEFAULT)
    except Exception:
      value = IQ_SET_SPEED_MPH_DEFAULT
    return int(np.clip(value, IQ_SET_SPEED_MPH_MIN, IQ_SET_SPEED_MPH_MAX))

  def read_custom_set_speed_params(self) -> None:
    self.long_increment_config = read_long_increment_config(self.params)
    self.set_speed_to_limit = self._read_set_speed_to_limit()
    self.iq_set_speed_mode = self._read_iq_set_speed_mode()
    self.iq_set_speed_use_current = self._read_iq_set_speed_use_current()
    self.iq_set_speed_mph = self._read_iq_set_speed_mph()

  def get_iq_mode_initial_set_speed_kph(self, current_speed_kph: float, fallback_kph: float) -> float:
    if self.iq_set_speed_mode != IQ_SET_SPEED_MODE_FIXED:
      return fallback_kph

    if self.iq_set_speed_use_current:
      return float(np.clip(round(current_speed_kph, 1), self.v_cruise_min, V_CRUISE_MAX))

    fixed_kph = float(self.iq_set_speed_mph) * CV.MPH_TO_KPH
    return float(np.clip(round(fixed_kph, 1), self.v_cruise_min, V_CRUISE_MAX))

  def update_v_cruise_delta(self, long_press: bool, v_cruise_delta: float) -> tuple[bool, float]:
    return resolve_button_step(self.long_increment_config, long_press, v_cruise_delta)

  def get_minimum_set_speed(self, is_metric: bool) -> None:
    if self.CP_IQ.pcmCruiseSpeed:
      self.v_cruise_min = V_CRUISE_MIN
      return

    self.v_cruise_min = get_minimum_set_speed_kph(is_metric)

  def update_enabled_state(self, CS: car.CarState, enabled: bool) -> bool:
    # pcmCruiseSpeed cars keep the stock enabled flag; others gate engagement on button release
    if self.CP_IQ.pcmCruiseSpeed:
      return enabled

    update_manual_button_timers(CS, self.enable_button_timers)
    button_pressed = any(t > 0 for t in self.enable_button_timers.values())

    if enabled and not self.enabled_prev:
      # first engage frame while the button is still down: hold off until it's let go
      self.enabled_prev = not button_pressed
      return False
    if not enabled:
      self.enabled_prev = False

    return enabled and self.enabled_prev

  def update_speed_limit_assist(self, is_metric, LP_IQ: custom.IQPlan) -> None:
    resolver = LP_IQ.speedLimit.resolver
    self.has_speed_limit = resolver.speedLimitValid or resolver.speedLimitLastValid
    self.speed_limit_final_last = LP_IQ.speedLimit.resolver.speedLimitFinalLast
    self.speed_limit_final_last_kph = self.speed_limit_final_last * CV.MS_TO_KPH
    self.speed_limit_state = LP_IQ.speedLimit.assist.state
    self.req_plus, self.req_minus = compare_cluster_target(self.v_cruise_cluster_kph * CV.KPH_TO_MS,
                                                           self.speed_limit_final_last, is_metric)

  @property
  def update_speed_limit_final_last_changed(self) -> bool:
    if not self.has_speed_limit:
      return False
    return self.speed_limit_final_last_kph != self.prev_speed_limit_final_last_kph

  def update_speed_limit_assist_v_cruise_non_pcm(self) -> None:
    if self.set_speed_to_limit and \
       self.speed_limit_state in SPEED_LIMIT_CONTROL_ACTIVE_STATES and \
       (self.prev_speed_limit_state not in SPEED_LIMIT_CONTROL_ACTIVE_STATES or self.update_speed_limit_final_last_changed):
      self.v_cruise_kph = np.clip(round(self.speed_limit_final_last_kph, 1), self.v_cruise_min, V_CRUISE_MAX)

    self.prev_speed_limit_state = self.speed_limit_state
    self.prev_speed_limit_final_last_kph = self.speed_limit_final_last_kph

  def update_speed_limit_assist_v_cruise_op_long(self) -> None:
    if not self.CP.openpilotLongitudinalControl or not self.set_speed_to_limit:
      return

    if self.speed_limit_state == SpeedLimitAssistState.disabled:
      self.prev_speed_limit_state = self.speed_limit_state
      self.prev_speed_limit_final_last_kph = self.speed_limit_final_last_kph
      return

    if not self.has_speed_limit or self.speed_limit_final_last_kph <= 0:
      self.prev_speed_limit_state = self.speed_limit_state
      self.prev_speed_limit_final_last_kph = self.speed_limit_final_last_kph
      return

    target_kph = float(np.clip(round(self.speed_limit_final_last_kph, 1), self.v_cruise_min, V_CRUISE_MAX))
    # OP Long uses planner min(v_cruise, slc target) to enforce limits.
    # Do not clamp the user's max (v_cruise) here, or they cannot raise/lower it.
    # Only sync on initial activation or when the resolved limit changes.
    if (self.v_cruise_kph == V_CRUISE_UNSET and self.speed_limit_state in SPEED_LIMIT_CONTROL_ACTIVE_STATES) or \
       self.update_speed_limit_final_last_changed:
      self.v_cruise_kph = target_kph
      self.v_cruise_cluster_kph = target_kph

    self.prev_speed_limit_state = self.speed_limit_state
    self.prev_speed_limit_final_last_kph = self.speed_limit_final_last_kph



# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 200  # ~ 124 mph
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105
IMPERIAL_INCREMENT = round(CV.MPH_TO_KPH, 1)  # round here to avoid rounding errors incrementing set speed

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}


class VCruiseHelper(VCruiseHelperIQ):
  def __init__(self, CP, CP_IQ):
    VCruiseHelperIQ.__init__(self, CP, CP_IQ)
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.button_timers = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0}
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  @property
  def volkswagen_standby_set_speed(self) -> bool:
    return self.CP.brand == "volkswagen" and self.CP.openpilotLongitudinalControl and not self.CP.pcmCruise

  def update_v_cruise(self, CS, enabled, is_metric):
    self.v_cruise_kph_last = self.v_cruise_kph

    self.get_minimum_set_speed(is_metric)

    if CS.cruiseState.available:
      _enabled = self.update_enabled_state(CS, enabled)
      if not self.CP.pcmCruise or (not self.CP_IQ.pcmCruiseSpeed and _enabled):
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, _enabled, is_metric, self.volkswagen_standby_set_speed)
        self.update_speed_limit_assist_v_cruise_non_pcm()
        self.v_cruise_cluster_kph = self.v_cruise_kph
        self.update_button_timers(CS, enabled)
      else:
        self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
        if CS.cruiseState.speed == 0:
          self.v_cruise_kph = V_CRUISE_UNSET
          self.v_cruise_cluster_kph = V_CRUISE_UNSET
        elif CS.cruiseState.speed == -1:
          self.v_cruise_kph = -1
          self.v_cruise_cluster_kph = -1
        else:
          self.update_speed_limit_assist_v_cruise_op_long()
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET

  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric, allow_standby_adjustment=False):
    # handle button presses. TODO: this should be in state_control, but a decelCruise press
    # would have the effect of both enabling and changing speed is checked after the state transition
    if not enabled and not allow_standby_adjustment:
      return

    long_press = False
    button_type = None

    v_cruise_delta = 1. if is_metric else IMPERIAL_INCREMENT

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers and not b.pressed:
        if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
          return  # end long press
        button_type = b.type.raw
        break
    else:
      for k, timer in self.button_timers.items():
        if timer and timer % CRUISE_LONG_PRESS == 0:
          button_type = k
          long_press = True
          break

    if button_type is None:
      return

    # Don't adjust speed when pressing resume to exit standstill
    cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
    if button_type == ButtonType.accelCruise and cruise_standstill:
      return

    # Don't adjust speed if we've enabled since the button was depressed (some ports enable on rising edge)
    if enabled and not self.button_change_states[button_type]["enabled"]:
      return

    long_press, v_cruise_delta = VCruiseHelperIQ.update_v_cruise_delta(self, long_press, v_cruise_delta)
    if long_press and self.v_cruise_kph % v_cruise_delta != 0:  # partial interval
      self.v_cruise_kph = CRUISE_NEAREST_FUNC[button_type](self.v_cruise_kph / v_cruise_delta) * v_cruise_delta
    else:
      self.v_cruise_kph += v_cruise_delta * CRUISE_INTERVAL_SIGN[button_type]

    # If set is pressed while overriding, clip cruise speed to minimum of vEgo
    if enabled and CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
      self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)

    self.v_cruise_kph = np.clip(round(self.v_cruise_kph, 1), self.v_cruise_min, V_CRUISE_MAX)

  def update_button_timers(self, CS, enabled):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        self.button_timers[b.type.raw] = 1 if b.pressed else 0
        self.button_change_states[b.type.raw] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}

  def initialize_v_cruise(self, CS, experimental_mode: bool, iq_dynamic_mode: bool) -> None:
    # initializing is handled by the PCM
    if self.CP.pcmCruise or self.v_cruise_initialized:
      return

    initial_experimental_mode = experimental_mode and not iq_dynamic_mode
    initial = V_CRUISE_INITIAL_EXPERIMENTAL_MODE if initial_experimental_mode else V_CRUISE_INITIAL
    if initial_experimental_mode:
      initial = self.get_iq_mode_initial_set_speed_kph(CS.vEgo * CV.MS_TO_KPH, initial)

    if any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents) and self.v_cruise_initialized:
      self.v_cruise_kph = self.v_cruise_kph_last
    else:
      self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, initial, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph
