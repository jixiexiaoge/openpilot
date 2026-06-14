"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass
from typing import Optional
from cereal import log, custom
State = custom.AlwaysOnLateral.AlwaysOnLateralState
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.events import ET
from openpilot.selfdrive.selfdrived.state import SOFT_DISABLE_TIME
EventName = log.OnroadEvent.EventName
EventNameIQ = custom.IQOnroadEvent.EventName
TORQUE_DELIVERING_STATES = (State.enabled, State.softDisabling, State.overriding)
LATERAL_CONTROLLED_STATES = (State.paused, *TORQUE_DELIVERING_STATES)
AOL_ENABLE_SIGNAL = ET.ENABLE
AOL_ENTRY_BLOCK_SIGNAL = ET.NO_ENTRY
AOL_GRACEFUL_DISABLE_SIGNAL = ET.SOFT_DISABLE
AOL_OPERATOR_DISABLE_SIGNAL = ET.USER_DISABLE
AOL_IMMEDIATE_DISABLE_SIGNAL = ET.IMMEDIATE_DISABLE
AOL_OVERRIDE_SIGNAL = ET.OVERRIDE_LATERAL
AOL_ACTIVE_ALERT = ET.WARNING

PAUSE_WITH_IQ_EVENTS = (
  EventNameIQ.silentWrongGear,
  EventNameIQ.silentReverseGear,
  EventNameIQ.silentBrakeHold,
  EventNameIQ.silentDoorOpen,
  EventNameIQ.silentSeatbeltNotLatched,
  EventNameIQ.silentParkBrake,
)
PAUSE_WITH_STOCK_EVENTS = (
  EventName.wrongGear,
  EventName.reverseGear,
  EventName.brakeHold,
  EventName.doorOpen,
  EventName.seatbeltNotLatched,
  EventName.parkBrake,
)
GEARS_ALLOW_PAUSED_SILENT = PAUSE_WITH_IQ_EVENTS
GEARS_ALLOW_PAUSED = PAUSE_WITH_STOCK_EVENTS


@dataclass(frozen=True)
class AolPulse:
  wake_ping: bool
  gate_closed: bool
  cooldown_call: bool
  driver_kill: bool
  hard_cut: bool
  hands_on_wheel: bool
  hush_cut: bool
  pit_stop_ready: bool


class AolStateMachine:
  def __init__(self, aol):
    self.selfdrive = aol.selfdrive
    self.ss_state_machine = aol.selfdrive.state_machine
    self._events = aol.selfdrive.events
    self._events_iq = aol.selfdrive.events_iq
    self.state = State.disabled

  def _queue_alert_if_solo(self, alert_type: str) -> None:
    if not self.selfdrive.enabled:
      self.ss_state_machine.current_alert_types.append(alert_type)

  def _sees_event(self, event_type: str) -> bool:
    return self._events.contains(event_type) or self._events_iq.contains(event_type)

  def _can_take_pit_stop(self) -> bool:
    return self._events.contains_in_list(PAUSE_WITH_STOCK_EVENTS) or self._events_iq.contains_in_list(PAUSE_WITH_IQ_EVENTS)

  def _capture_pulse(self) -> AolPulse:
    return AolPulse(
      wake_ping=self._sees_event(AOL_ENABLE_SIGNAL),
      gate_closed=self._sees_event(AOL_ENTRY_BLOCK_SIGNAL),
      cooldown_call=self._sees_event(AOL_GRACEFUL_DISABLE_SIGNAL),
      driver_kill=self._sees_event(AOL_OPERATOR_DISABLE_SIGNAL),
      hard_cut=self._sees_event(AOL_IMMEDIATE_DISABLE_SIGNAL),
      hands_on_wheel=self._sees_event(AOL_OVERRIDE_SIGNAL),
      hush_cut=self._events_iq.has(EventNameIQ.silentLkasDisable),
      pit_stop_ready=self._can_take_pit_stop(),
    )

  def _start_grace_period(self) -> None:
    if not self.selfdrive.enabled:
      self.ss_state_machine.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
      self.ss_state_machine.current_alert_types.append(AOL_GRACEFUL_DISABLE_SIGNAL)

  def _run_global_cutoffs(self, pulse: AolPulse) -> Optional[object]:
    if pulse.driver_kill:
      self.ss_state_machine.current_alert_types.append(AOL_OPERATOR_DISABLE_SIGNAL)
      return State.paused if pulse.hush_cut else State.disabled
    if pulse.hard_cut:
      self._queue_alert_if_solo(AOL_IMMEDIATE_DISABLE_SIGNAL)
      return State.disabled
    return None

  def _handle_disabled(self, pulse: AolPulse) -> State:
    if not pulse.wake_ping:
      return State.disabled
    if pulse.gate_closed:
      self._queue_alert_if_solo(AOL_ENTRY_BLOCK_SIGNAL)
      return State.paused if pulse.pit_stop_ready else State.disabled
    self._queue_alert_if_solo(AOL_ENABLE_SIGNAL)
    return State.overriding if pulse.hands_on_wheel else State.enabled

  def _handle_enabled(self, pulse: AolPulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if pulse.cooldown_call:
      self._start_grace_period()
      return State.softDisabling
    if pulse.hands_on_wheel:
      self._queue_alert_if_solo(AOL_OVERRIDE_SIGNAL)
      return State.overriding
    return State.enabled

  def _handle_soft_disabling(self, pulse: AolPulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if not pulse.cooldown_call:
      return State.enabled
    if self.ss_state_machine.soft_disable_timer > 0:
      self._queue_alert_if_solo(AOL_GRACEFUL_DISABLE_SIGNAL)
      return State.softDisabling
    return State.disabled

  def _handle_paused(self, pulse: AolPulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if not pulse.wake_ping:
      return State.paused
    if pulse.gate_closed:
      self._queue_alert_if_solo(AOL_ENTRY_BLOCK_SIGNAL)
      return State.paused
    self._queue_alert_if_solo(AOL_ENABLE_SIGNAL)
    return State.overriding if pulse.hands_on_wheel else State.enabled

  def _handle_overriding(self, pulse: AolPulse) -> State:
    forced_state = self._run_global_cutoffs(pulse)
    if forced_state is not None:
      return forced_state
    if pulse.cooldown_call:
      self._start_grace_period()
      return State.softDisabling
    if pulse.hands_on_wheel:
      self.ss_state_machine.current_alert_types.append(AOL_OVERRIDE_SIGNAL)
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
      self._queue_alert_if_solo(AOL_ACTIVE_ALERT)
    return enabled, active
