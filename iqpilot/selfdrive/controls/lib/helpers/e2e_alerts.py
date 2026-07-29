"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import messaging, custom

from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents

PARAM_PATH = "EndToEndAlert"
PARAM_LEAD = "EndToEndLeadAlert"
PARAM_STRIDE_S = 2.0

SETTLE_S = 1.0
CONFIRM_S = 0.4
ROLL_MPS = 0.3

HORIZON_TAIL = 5
PATH_SPEED_MPS = 3.0

LEAD_QUEUE_M = 12.0
LEAD_SPEED_MPS = 1.0
LEAD_GAP_M = 0.5


class _Confirm:
  def __init__(self, window_s: float):
    self._window = window_s
    self._held = 0.0
    self._spent = False

  def clear(self) -> None:
    self._held = 0.0
    self._spent = False

  def poll(self, holds: bool) -> bool:
    if self._spent:
      return False
    self._held = self._held + DT_MDL if holds else 0.0
    if self._held < self._window:
      return False
    self._spent = True
    return True


class _Dwell:
  def __init__(self):
    self.seconds = 0.0
    self.lead_floor = float('inf')

  def clear(self) -> None:
    self.seconds = 0.0
    self.lead_floor = float('inf')

  def tick(self, lead_range: float | None) -> None:
    self.seconds += DT_MDL
    if lead_range is not None:
      self.lead_floor = min(self.lead_floor, lead_range)

  @property
  def settled(self) -> bool:
    return self.seconds >= SETTLE_S

  @property
  def queued(self) -> bool:
    return self.lead_floor < LEAD_QUEUE_M


class EndToEndAlertEngine:
  def __init__(self):
    self._params = Params()
    self._on = {"path": False, "lead": False}
    self._elapsed_since_read = PARAM_STRIDE_S
    self._dwell = _Dwell()
    self._confirm = {"path": _Confirm(CONFIRM_S), "lead": _Confirm(CONFIRM_S)}
    self._fired = {"path": False, "lead": False}

  def _refresh_params(self) -> None:
    self._elapsed_since_read += DT_MDL
    if self._elapsed_since_read < PARAM_STRIDE_S:
      return
    self._elapsed_since_read = 0.0
    self._on["path"] = self._params.get_bool(PARAM_PATH)
    self._on["lead"] = self._params.get_bool(PARAM_LEAD)

  @staticmethod
  def _car_holds_long(sm: messaging.SubMaster) -> bool:
    # AOL steers without raising selfdriveState.enabled, so the pair reads as long authority
    return bool(sm['selfdriveState'].enabled or sm['carState'].cruiseState.enabled)

  @staticmethod
  def _halted(cs) -> bool:
    return bool(cs.standstill) or abs(cs.vEgo) < ROLL_MPS

  @staticmethod
  def _horizon_speed(model) -> float:
    # capnp list readers reject slices
    samples = model.velocity.x
    count = len(samples)
    if count < HORIZON_TAIL:
      return 0.0
    return sum(samples[i] for i in range(count - HORIZON_TAIL, count)) / HORIZON_TAIL

  def _rearm(self) -> None:
    self._dwell.clear()
    for gate in self._confirm.values():
      gate.clear()

  def update(self, sm: messaging.SubMaster, iq_events: IQEvents) -> None:
    self._refresh_params()
    self._fired["path"] = self._fired["lead"] = False

    cs = sm['carState']
    lead = sm['radarState'].leadOne
    lead_range = float(lead.dRel) if lead.status else None

    if not self._halted(cs) or cs.gasPressed or self._car_holds_long(sm):
      self._rearm()
      return

    self._dwell.tick(lead_range)
    if not self._dwell.settled:
      return

    if self._on["path"] and lead_range is None:
      opened = self._horizon_speed(sm['modelV2']) > PATH_SPEED_MPS
      self._fired["path"] = self._confirm["path"].poll(opened)

    if self._on["lead"] and lead_range is not None and self._dwell.queued:
      pulling = lead.vLead > LEAD_SPEED_MPS and (lead_range - self._dwell.lead_floor) > LEAD_GAP_M
      self._fired["lead"] = self._confirm["lead"].poll(pulling)

    if self._fired["path"] or self._fired["lead"]:
      iq_events.add(custom.IQOnroadEvent.EventName.e2eChime)

  @property
  def path_alert(self) -> bool:
    return self._fired["path"]

  @property
  def lead_alert(self) -> bool:
    return self._fired["lead"]
