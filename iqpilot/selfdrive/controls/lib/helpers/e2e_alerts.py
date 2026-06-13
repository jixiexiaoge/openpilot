"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import messaging, custom

from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents

PATH_QUEUE_GATE = 30
LEAD_GROWTH_GATE = 1.0
TRIGGER_HOLD_S = 0.3


class TriggerPhase:
  IDLE = 0
  ARMED = 1
  FIRED = 2


class StopAndLeadChimeEngine:
  def __init__(self):
    self._frame = -1
    self._toggle = {"path_queue": False, "lead_depart": False}
    self._trigger = {
      "path_queue": {"phase": TriggerPhase.IDLE, "last_phase": TriggerPhase.IDLE, "fired": False, "hold_ticks": 0, "anchor": -1.0},
      "lead_depart": {"phase": TriggerPhase.IDLE, "last_phase": TriggerPhase.IDLE, "fired": False, "hold_ticks": 0, "anchor": -1.0},
    }
    self._standstill_gate = {"open": False, "was_open": False, "moving_frame": -1}
    self._lead_state = {"visible": False, "primed": False, "armed": False, "warmup_ticks": 0}

  def _read_toggles(self) -> None:
    self._toggle["path_queue"] = False
    self._toggle["lead_depart"] = False

  def _mark_motion(self, standstill: bool, speed_mps: float) -> bool:
    is_moving = (not standstill) and speed_mps > 0.1
    if is_moving:
      self._standstill_gate["moving_frame"] = self._frame
    return is_moving

  def _within_motion_grace(self) -> bool:
    stamp = self._standstill_gate["moving_frame"]
    if stamp == -1:
      return True
    return (self._frame - stamp) * DT_MDL < 2.0

  def _update_gate(self, standstill: bool, speed_mps: float, gas_pressed: bool, controls_enabled: bool) -> None:
    moving = self._mark_motion(standstill, speed_mps)
    self._standstill_gate["open"] = (not moving) and (not gas_pressed) and (not controls_enabled) and (not self._within_motion_grace())

  @staticmethod
  def _path_end_x(path_x):
    return float(path_x[-1]) if len(path_x) else 0.0

  def _path_queue_signal(self, path_x) -> bool:
    node = self._trigger["path_queue"]
    if node["phase"] != TriggerPhase.ARMED:
      node["hold_ticks"] = 0
      return False
    node["hold_ticks"] = node["hold_ticks"] + 1 if self._path_end_x(path_x) > PATH_QUEUE_GATE else 0
    return node["hold_ticks"] * DT_MDL > TRIGGER_HOLD_S

  def _update_lead_prime(self, seen: bool, distance_m: float) -> None:
    near_lead = seen and distance_m < 8.0
    opened_now = self._standstill_gate["open"] and not self._standstill_gate["was_open"]

    if opened_now and near_lead:
      self._lead_state["primed"] = True
    elif not self._standstill_gate["open"]:
      self._lead_state["primed"] = False

    if self._standstill_gate["open"] and self._lead_state["primed"] and near_lead:
      self._lead_state["warmup_ticks"] += 1
      self._lead_state["armed"] = self._lead_state["warmup_ticks"] * DT_MDL >= 1.0
      return

    self._lead_state["warmup_ticks"] = 0
    self._lead_state["armed"] = False

  def _lead_depart_signal(self, distance_m: float) -> bool:
    node = self._trigger["lead_depart"]
    if node["phase"] != TriggerPhase.ARMED:
      node["anchor"] = -1.0
      node["hold_ticks"] = 0
      return False

    if node["anchor"] == -1.0 or distance_m < node["anchor"]:
      node["anchor"] = distance_m

    grew = node["anchor"] != -1.0 and (distance_m - node["anchor"]) > LEAD_GROWTH_GATE
    node["hold_ticks"] = node["hold_ticks"] + 1 if grew else 0
    return node["hold_ticks"] * DT_MDL > TRIGGER_HOLD_S

  def _sample_inputs(self, sm: messaging.SubMaster):
    cs = sm['carState']
    cc = sm['carControl']
    lead_one = sm['radarState'].leadOne

    self._lead_state["visible"] = lead_one.status
    lead_distance = lead_one.dRel

    self._update_gate(cs.standstill, cs.vEgo, cs.gasPressed, cc.enabled)
    queue_fire = self._path_queue_signal(sm['modelV2'].position.x)
    self._update_lead_prime(self._lead_state["visible"], lead_distance)
    lead_fire = self._lead_depart_signal(lead_distance)

    self._standstill_gate["was_open"] = self._standstill_gate["open"]
    return queue_fire, lead_fire

  @staticmethod
  def _step_phase(phase: int, enabled: bool, allowed: bool, fired: bool) -> tuple[int, bool]:
    if phase == TriggerPhase.IDLE:
      return (TriggerPhase.ARMED, fired) if (allowed and enabled) else (phase, fired)
    if not allowed or not enabled:
      return TriggerPhase.IDLE, fired
    if phase == TriggerPhase.ARMED and fired:
      return TriggerPhase.FIRED, fired
    return phase, fired

  def _advance_trigger(self, key: str, enabled: bool, allowed: bool, fired: bool) -> None:
    node = self._trigger[key]
    node["last_phase"] = node["phase"]
    node["phase"], node["fired"] = self._step_phase(node["phase"], enabled, allowed, fired)

  def update(self, sm: messaging.SubMaster, iq_events: IQEvents) -> None:
    self._read_toggles()
    queue_fire, lead_fire = self._sample_inputs(sm)

    self._advance_trigger("path_queue", self._toggle["path_queue"], self._standstill_gate["open"] and not self._lead_state["visible"], queue_fire)
    self._advance_trigger("lead_depart", self._toggle["lead_depart"], self._standstill_gate["open"] and self._lead_state["armed"], lead_fire)

    if self._trigger["path_queue"]["fired"] or self._trigger["lead_depart"]["fired"]:
      iq_events.add(custom.IQOnroadEvent.EventName.e2eChime)

    self._frame += 1

  @property
  def queue_alert(self):
    return self._trigger["path_queue"]["fired"]

  @queue_alert.setter
  def queue_alert(self, payload):
    self._trigger["path_queue"]["fired"] = bool(payload)

  @property
  def lead_alert(self):
    return self._trigger["lead_depart"]["fired"]

  @lead_alert.setter
  def lead_alert(self, payload):
    self._trigger["lead_depart"]["fired"] = bool(payload)


E2EAlertsHelper = StopAndLeadChimeEngine
