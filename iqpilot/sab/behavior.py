"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Steering Assistance Behavior (SAB): brand preference resolution, the guidance
state machine and the per-frame event/behaviour engine, together in one module.
"""
from dataclasses import dataclass
from typing import Optional

from openpilot.common.params import Params, UnknownKeyName
from iqdbc.car import structs
from openpilot.common.realtime import DT_CTRL
from iqdbc.safety import ALTERNATIVE_EXPERIENCE
from openpilot.selfdrive.selfdrived.events import ET
from iqdbc.car.hyundai.values import HyundaiFlags, HyundaiFlagsIQ, HyundaiSafetyFlagsIQ
from openpilot.selfdrive.selfdrived.state import SOFT_DISABLE_TIME
from cereal import log, custom

State = custom.AlwaysOnLateral.AlwaysOnLateralState


# ===== preferences =====

class DriverInterventionMode:
  """What a brake press does to steering guidance (AolSteeringMode param values)."""
  CONTINUE = 0
  SUSPEND = 1
  CANCEL = 2


# Per-brand quirks. A brand absent from a set behaves normally.
_FORCED_BRAKE_CANCEL = frozenset({"rivian"})
BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE = ("rivian", "tesla")
_HYUNDAI_MAIN_CRUISE_FLAG_BRANDS = frozenset({"hyundai"})

_EXPERIENCE_BY_BRAKE_MODE = {
  DriverInterventionMode.CANCEL: ALTERNATIVE_EXPERIENCE.AOL_DISENGAGE_LATERAL_ON_BRAKE,
  DriverInterventionMode.SUSPEND: ALTERNATIVE_EXPERIENCE.AOL_PAUSE_LATERAL_ON_BRAKE,
}


def uses_forced_brake_cancel(CP: structs.CarParams, CP_IQ: structs.IQCarParams):
  del CP_IQ
  return CP.brand in _FORCED_BRAKE_CANCEL


def read_aol_enabled_pref(params: Params):
  return params.get_bool("AolEnabled")


def read_main_cruise_pref(params: Params):
  return params.get_bool("AolMainCruiseAllowed")


def read_joint_engagement_pref(params: Params):
  return params.get_bool("AolUnifiedEngagementMode")


def resolve_brake_intervention_mode(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  if uses_forced_brake_cancel(CP, CP_IQ):
    return DriverInterventionMode.CANCEL
  return params.get("AolSteeringMode", return_default=True)


def apply_aol_experience_flags(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  if not read_aol_enabled_pref(params):
    return
  CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_AOL
  mode = resolve_brake_intervention_mode(CP, CP_IQ, params)
  CP.alternativeExperience |= _EXPERIENCE_BY_BRAKE_MODE.get(mode, 0)


def apply_aol_brand_overrides(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params):
  if CP.brand in _HYUNDAI_MAIN_CRUISE_FLAG_BRANDS:
    CP_IQ.flags |= HyundaiFlagsIQ.MAIN_BTN_LONG_TOGGLE.value
    CP_IQ.iqSafetyFlags |= HyundaiSafetyFlagsIQ.MAIN_BTN_LONG_TOGGLE

  if uses_forced_brake_cancel(CP, CP_IQ):
    # the brand can only cancel on brake; pin the params so the UI reflects reality
    params.put("AolSteeringMode", DriverInterventionMode.CANCEL)
    params.put_bool("AolUnifiedEngagementMode", True)

  if CP.brand in BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE:
    params.remove("AolMainCruiseAllowed")

# ===== state_machine =====

EventName = log.OnroadEvent.EventName
EventNameIQ = custom.IQOnroadEvent.EventName
TORQUE_DELIVERING_STATES = (State.overriding, State.enabled, State.softDisabling)
LATERAL_CONTROLLED_STATES = (State.paused, *TORQUE_DELIVERING_STATES)
GUIDANCE_AVAILABLE_SIGNAL = ET.ENABLE
GUIDANCE_GATE_BLOCK_SIGNAL = ET.NO_ENTRY
GUIDANCE_SUPPRESSION_SIGNAL = ET.SOFT_DISABLE
GUIDANCE_OPERATOR_OFF_SIGNAL = ET.USER_DISABLE
GUIDANCE_HARD_CUT_SIGNAL = ET.IMMEDIATE_DISABLE
GUIDANCE_DRIVER_OVERRIDE_SIGNAL = ET.OVERRIDE_LATERAL
GUIDANCE_ACTIVE_ALERT = ET.WARNING

PAUSE_WITH_IQ_EVENTS = (
  EventNameIQ.parkBrakeSilent,
  EventNameIQ.seatbeltUnbuckledSilent,
  EventNameIQ.doorAjarSilent,
  EventNameIQ.brakeHoldSilent,
  EventNameIQ.reverseSilent,
  EventNameIQ.gearNotDriveSilent,
)
PAUSE_WITH_STOCK_EVENTS = (
  EventName.parkBrake,
  EventName.seatbeltNotLatched,
  EventName.doorOpen,
  EventName.brakeHold,
  EventName.reverseGear,
  EventName.wrongGear,
)
GEARS_ALLOW_PAUSED_SILENT = PAUSE_WITH_IQ_EVENTS
GEARS_ALLOW_PAUSED = PAUSE_WITH_STOCK_EVENTS


@dataclass(frozen=True)
class GuidancePulse:
  wake_ping: bool
  gate_closed: bool
  cooldown_call: bool
  driver_kill: bool
  hard_cut: bool
  hands_on_wheel: bool
  hush_cut: bool
  pit_stop_ready: bool


class GuidanceStateMachine:
  def __init__(self, sab):
    self.selfdrive = sab.selfdrive
    self._sm_core = sab.selfdrive.state_machine
    self._events = sab.selfdrive.events
    self._events_iq = sab.selfdrive.events_iq
    self.state = State.disabled

  def _queue_alert_if_solo(self, alert_type: str):
    if not self.selfdrive.enabled:
      self._sm_core.current_alert_types.append(alert_type)

  def _sees_event(self, event_type: str):
    return self._events.contains(event_type) or self._events_iq.contains(event_type)

  def _can_take_pit_stop(self):
    return self._events.contains_in_list(PAUSE_WITH_STOCK_EVENTS) or self._events_iq.contains_in_list(PAUSE_WITH_IQ_EVENTS)

  def _capture_pulse(self) -> GuidancePulse:
    return GuidancePulse(
      wake_ping=self._sees_event(GUIDANCE_AVAILABLE_SIGNAL),
      gate_closed=self._sees_event(GUIDANCE_GATE_BLOCK_SIGNAL),
      cooldown_call=self._sees_event(GUIDANCE_SUPPRESSION_SIGNAL),
      driver_kill=self._sees_event(GUIDANCE_OPERATOR_OFF_SIGNAL),
      hard_cut=self._sees_event(GUIDANCE_HARD_CUT_SIGNAL),
      hands_on_wheel=self._sees_event(GUIDANCE_DRIVER_OVERRIDE_SIGNAL),
      hush_cut=self._events_iq.has(EventNameIQ.alcDisengagedSilent),
      pit_stop_ready=self._can_take_pit_stop(),
    )

  def _start_grace_period(self):
    if not self.selfdrive.enabled:
      self._sm_core.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
      self._sm_core.current_alert_types.append(GUIDANCE_SUPPRESSION_SIGNAL)

  def _run_global_cutoffs(self, pulse: GuidancePulse) -> Optional[object]:
    if pulse.driver_kill:
      self._sm_core.current_alert_types.append(GUIDANCE_OPERATOR_OFF_SIGNAL)
      return State.paused if pulse.hush_cut else State.disabled
    if pulse.hard_cut:
      self._queue_alert_if_solo(GUIDANCE_HARD_CUT_SIGNAL)
      return State.disabled
    return None

  def _handle_disabled(self, pulse: GuidancePulse) -> State:
    if not pulse.wake_ping:
      return State.disabled
    if pulse.gate_closed:
      self._queue_alert_if_solo(GUIDANCE_GATE_BLOCK_SIGNAL)
      return State.paused if pulse.pit_stop_ready else State.disabled
    self._queue_alert_if_solo(GUIDANCE_AVAILABLE_SIGNAL)
    return State.overriding if pulse.hands_on_wheel else State.enabled

  def _handle_enabled(self, pulse: GuidancePulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if pulse.cooldown_call:
      self._start_grace_period()
      return State.softDisabling
    if pulse.hands_on_wheel:
      self._queue_alert_if_solo(GUIDANCE_DRIVER_OVERRIDE_SIGNAL)
      return State.overriding
    return State.enabled

  def _handle_soft_disabling(self, pulse: GuidancePulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if not pulse.cooldown_call:
      return State.enabled
    if self._sm_core.soft_disable_timer > 0:
      self._queue_alert_if_solo(GUIDANCE_SUPPRESSION_SIGNAL)
      return State.softDisabling
    return State.disabled

  def _handle_paused(self, pulse: GuidancePulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if not pulse.wake_ping:
      return State.paused
    if pulse.gate_closed:
      self._queue_alert_if_solo(GUIDANCE_GATE_BLOCK_SIGNAL)
      return State.paused
    self._queue_alert_if_solo(GUIDANCE_AVAILABLE_SIGNAL)
    return State.overriding if pulse.hands_on_wheel else State.enabled

  def _handle_overriding(self, pulse: GuidancePulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if pulse.cooldown_call:
      self._start_grace_period()
      return State.softDisabling
    if pulse.hands_on_wheel:
      self._sm_core.current_alert_types.append(GUIDANCE_DRIVER_OVERRIDE_SIGNAL)
      return State.overriding
    return State.enabled

  def update(self):
    pulse = self._capture_pulse()
    handler = {
      State.disabled: self._handle_disabled,
      State.enabled: self._handle_enabled,
      State.softDisabling: self._handle_soft_disabling,
      State.paused: self._handle_paused,
      State.overriding: self._handle_overriding,
    }[self.state]

    self.state = handler(pulse)
    enabled = self.state in LATERAL_CONTROLLED_STATES
    active = self.state in TORQUE_DELIVERING_STATES
    if active:
      self._queue_alert_if_solo(GUIDANCE_ACTIVE_ALERT)
    return enabled, active

# ===== behavior =====

_E = log.OnroadEvent.EventName
_Q = custom.IQOnroadEvent.EventName
_BTN = structs.CarState.ButtonEvent.Type
_GEAR = structs.CarState.GearShifter

_CRUISE_SET_TAPS = frozenset((_BTN.accelCruise, _BTN.resumeCruise, _BTN.decelCruise, _BTN.setCruise))
_HYUNDAI_LDA_MASK = HyundaiFlags.CANFD

# While a lateral-only session rides through a pause, these stock blockers are
# swapped for their silent IQ twins. Order here is not load-bearing (each row
# guards a distinct event), so it is grouped standstill-first for readability.
#   (silent replacement, stock trigger, only-when-stopped, extra predicate)
_QUIET_SWAPS = (
  (_Q.seatbeltUnbuckledSilent, _E.seatbeltNotLatched, True, None),
  (_Q.doorAjarSilent, _E.doorOpen, True, None),
  (_Q.reverseSilent, _E.reverseGear, False, None),
  (_Q.parkBrakeSilent, _E.parkBrake, False, None),
  (_Q.brakeHoldSilent, _E.brakeHold, False, None),
  (_Q.gearNotDriveSilent, _E.wrongGear, False,
   lambda cs: cs.vEgo < 2.5 or cs.gearShifter == _GEAR.reverse),
)

# Longitudinal-only chatter that must not gate a lateral-only session.
_DROP_ON_ENTRY = (_E.speedTooLow, _E.belowEngageSpeed, _E.preEnableStandstill,
                  _E.manualRestart, _E.cruiseDisabled)
_DROP_ON_EXIT = (_E.wrongCruiseMode, _E.pedalPressed, _E.buttonCancel, _E.pcmDisable)


class SteeringAssistanceBehavior:
  def __init__(self, selfdrive):
    sd = selfdrive
    self.selfdrive = sd
    self.CP, self.CP_IQ, self.params = sd.CP, sd.CP_IQ, sd.params
    self.events, self.events_iq = sd.events, sd.events_iq

    self.enabled = self.active = self.available = False
    sd.enabled_prev = False
    self.state_machine = GuidanceStateMachine(self)

    self.disengage_on_accelerator = self.params.get_bool("DisengageOnAccelerator")
    self._apply_brand_capabilities()
    self._reload_preferences(full=True)

  def _apply_brand_capabilities(self):
    brand = self.CP.brand
    self.no_main_cruise = brand in BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE
    lda_capable = bool(self.CP.flags & _HYUNDAI_LDA_MASK) or bool(self.CP_IQ.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON)
    self.hkg_allow = brand == "hyundai" and lda_capable

  def _reload_preferences(self, full: bool = False):
    self.main_enabled_toggle = read_main_cruise_pref(self.params)
    self.unified_engagement_mode = read_joint_engagement_pref(self.params)
    if full:
      self.enabled_toggle = read_aol_enabled_pref(self.params)
      self.steering_mode_on_brake = resolve_brake_intervention_mode(self.CP, self.CP_IQ, self.params)

  def read_params(self):
    self._reload_preferences()

  # -- event plumbing (thin wrappers over the stock/IQ event queues) -----------
  def _has(self, ev):
    return self.events.has(ev)

  def _drop(self, ev):
    self.events.remove(ev)

  def _raise(self, ev):
    self.events.add(ev)

  def _emit(self, ev):
    self.events_iq.add(ev)

  def _retract(self, ev):
    self.events_iq.remove(ev)

  def _emitted(self, ev):
    return self.events_iq.contains(ev)

  def _emitted_any(self, evs):
    return self.events_iq.contains_in_list(evs)

  def _iq_has(self, ev):
    return self.events_iq.has(ev)

  # -- predicates --------------------------------------------------------------
  def _brake_without_gas(self, cs):
    prev_gas = self.selfdrive.CS_prev.gasPressed
    gas_rising_edge = cs.gasPressed and not prev_gas
    override_via_gas = gas_rising_edge and self.disengage_on_accelerator
    return self._has(_E.pedalPressed) and not override_via_gas

  def _may_silently_resume(self, cs):
    suspend_on_brake = self.steering_mode_on_brake == DriverInterventionMode.SUSPEND
    if suspend_on_brake and self._brake_without_gas(cs):
      return False
    return not self._emitted_any(GEARS_ALLOW_PAUSED_SILENT)

  @property
  def _long_held_two_cycles(self):
    sd = self.selfdrive
    return bool(sd.enabled_prev and sd.enabled)

  def _uem_blocks_engage(self):
    if not self.unified_engagement_mode or self.enabled:
      return True
    return self._long_held_two_cycles

  def _lateral_offered(self, cs):
    return bool(cs.lateralAvailable or cs.cruiseState.available or self.hkg_allow or self.CP.brand == "tesla")

  @staticmethod
  def _main_cruise_live(cs):
    cruise = getattr(cs, 'cruiseState', None)
    if getattr(cruise, 'available', False):
      return True
    return bool(getattr(cs, 'cruiseFaultLateralMode', False))

  # -- event surgery -----------------------------------------------------------
  def _swap_event(self, stock: int, silent: int):
    self._drop(stock)
    self._emit(silent)

  def _flag_pause(self):
    already_held = self.state_machine.state is State.paused
    if not already_held:
      self._emit(_Q.alcDisengagedSilent)

  def _resolve_wrong_mode(self, alert_only: bool):
    if not alert_only:
      self._drop(_E.wrongCarMode)
    elif self._has(_E.wrongCarMode):
      self._swap_event(_E.wrongCarMode, _Q.carModeMismatchNotice)

  # -- joystick/debug hook -----------------------------------------------------
  def _consume_joystick_aol_request(self, cs) -> str | None:
    if not self.params.get_bool("JoystickDebugMode"):
      return None
    try:
      raw = self.params.get("JoystickAolRequest")
    except UnknownKeyName:
      return None
    if not raw:
      return None
    try:
      request = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
      request = ""
    try:
      self.params.remove("JoystickAolRequest")
    except UnknownKeyName:
      return None

    verb = request.strip().lower()
    if verb not in ("enable", "disable"):
      return None
    if not getattr(cs, "started", False):
      return None
    if getattr(cs, "doorOpen", False) or getattr(cs, "seatbeltUnlatched", False):
      return None
    parked_or_reverse = getattr(cs, "gearShifter", _GEAR.unknown) in (_GEAR.park, _GEAR.reverse)
    return None if parked_or_reverse else verb

  # -- pipeline stages ---------------------------------------------------------
  def _phase_joystick(self, cs):
    verb = self._consume_joystick_aol_request(cs)
    if verb is not None:
      self._emit(_Q.alcEngaged if verb == "enable" else _Q.alcDisengaged)

  def _phase_soften_for_lateral_session(self, cs):
    if self.selfdrive.enabled or not self.enabled:
      return

    for silent, stock, standstill_only, extra in _QUIET_SWAPS:
      if standstill_only and not cs.standstill:
        continue
      if not self._has(stock):
        continue
      if extra is not None and not extra(cs):
        continue
      self._swap_event(stock, silent)
      self._flag_pause()

    if self.steering_mode_on_brake == DriverInterventionMode.SUSPEND and self._brake_without_gas(cs):
      self._flag_pause()

    for chatter in _DROP_ON_ENTRY:
      self._drop(chatter)

  _ENGAGE_TRIGGERS = (_E.pcmEnable, _E.buttonEnable)

  def _phase_engagement(self, cs):
    long_engage = any(self._has(trig) for trig in self._ENGAGE_TRIGGERS)
    tapped_set = any(be.type in _CRUISE_SET_TAPS for be in cs.buttonEvents)
    self._resolve_wrong_mode(long_engage or tapped_set)

    if long_engage:
      if self._brake_without_gas(cs):
        self._emit(_Q.pedalHeldNotice)
      if self._uem_blocks_engage():
        self._drop(_E.pcmEnable)
        self._drop(_E.buttonEnable)
      return

    if self.main_enabled_toggle and self._main_cruise_live(cs) and not self._main_cruise_live(self.selfdrive.CS_prev):
      self._emit(_Q.alcEngaged)

  def _phase_buttons(self, cs):
    kill_all = False
    long_dropped_out = self.selfdrive.enabled_prev and not self.selfdrive.enabled
    for be in cs.buttonEvents:
      if be.type == _BTN.cancel and long_dropped_out:
        self._emit(_Q.speedManually)
      if not (be.type == _BTN.lkas and be.pressed and self._lateral_offered(cs)):
        continue
      if not self.enabled:
        self._emit(_Q.alcEngaged)
        continue
      self._emit(_Q.alcDisengaged)
      if self.selfdrive.enabled:
        kill_all = True
    return kill_all

  def _phase_availability(self, cs):
    main_off = self.main_enabled_toggle and not self._main_cruise_live(cs)
    if self.no_main_cruise or (self._lateral_offered(cs) and not main_off):
      return
    self._drop(_E.buttonEnable)
    if self.enabled:
      self._emit(_Q.alcDisengaged)

  def _phase_brake_policy(self, cs):
    if self.steering_mode_on_brake != DriverInterventionMode.CANCEL or not self._brake_without_gas(cs):
      return
    if self.enabled:
      self._emit(_Q.alcDisengaged)
    elif self._emitted(_Q.alcEngaged):
      self._retract(_Q.alcEngaged)
      self._emit(_Q.pedalHeldNotice)

  def _phase_resume_from_pause(self, cs):
    held = self.state_machine.state is State.paused
    if held and self._may_silently_resume(cs):
      self._emit(_Q.alcEngagedSilent)

  def update_events(self, cs):
    self._phase_joystick(cs)
    self._phase_soften_for_lateral_session(cs)
    self._phase_engagement(cs)
    kill_all = self._phase_buttons(cs)
    self._phase_availability(cs)
    self._phase_brake_policy(cs)
    self._phase_resume_from_pause(cs)

    for chatter in _DROP_ON_EXIT:
      self._drop(chatter)

    if kill_all:
      self._raise(_E.buttonCancel)

  def update(self, cs):
    if not self.enabled_toggle and not self.params.get_bool("JoystickDebugMode"):
      return
    self.update_events(cs)
    self.update_state()

  def update_state(self):
    sd = self.selfdrive
    sd.enabled_prev = sd.enabled
    runnable = sd.initialized and not self.CP.passive
    if runnable:
      verdict = self.state_machine.update()
      self.enabled, self.active = verdict
