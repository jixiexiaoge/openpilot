from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import insort
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import IntEnum

import cereal.messaging as messaging
from cereal import car, log
from openpilot.common.realtime import DT_CTRL
from openpilot.system.hardware import HARDWARE

AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert


def _frames_for(seconds: float) -> int:
  return int(seconds / DT_CTRL)


class Tier(IntEnum):
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5


class Tags:
  ENABLE = "enable"
  PRE_ENABLE = "preEnable"
  OVERRIDE_LATERAL = "overrideLateral"
  OVERRIDE_LONGITUDINAL = "overrideLongitudinal"
  NO_ENTRY = "noEntry"
  WARNING = "warning"
  USER_DISABLE = "userDisable"
  SOFT_DISABLE = "softDisable"
  IMMEDIATE_DISABLE = "immediateDisable"
  PERMANENT = "permanent"


@dataclass(slots=True)
class AlertCard:
  alert_text_1: str
  alert_text_2: str
  alert_status: log.SelfdriveState.AlertStatus
  alert_size: log.SelfdriveState.AlertSize
  priority: Tier
  visual_alert: car.CarControl.HUDControl.VisualAlert
  audible_alert: car.CarControl.HUDControl.AudibleAlert
  duration: int
  creation_delay: float = 0.0
  alert_type: str = field(default="", init=False)
  event_type: str | None = field(default=None, init=False)

  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status: log.SelfdriveState.AlertStatus,
               alert_size: log.SelfdriveState.AlertSize,
               priority: Tier,
               visual_alert: car.CarControl.HUDControl.VisualAlert,
               audible_alert: car.CarControl.HUDControl.AudibleAlert,
               duration: float,
               creation_delay: float = 0.0):
    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.priority = priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert
    self.duration = _frames_for(duration)
    self.creation_delay = creation_delay
    self.alert_type = ""
    self.event_type = None

  def __str__(self) -> str:
    return f"{self.alert_text_1}/{self.alert_text_2} {self.priority} {self.visual_alert} {self.audible_alert}"


AlertFactory = Callable[[car.CarParams, car.CarState, messaging.SubMaster, bool, int, log.ControlsState], AlertCard]


def car_mode_entry_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int, personality) -> AlertCard:
  del CS, sm, metric, soft_disable_time, personality
  headline = "Enable Adaptive Cruise to Engage"
  if CP.brand == "honda":
    headline = "Enable Main Switch to Engage"
  return NoEntryCard(headline)


class EventBook(ABC):
  def __init__(self):
    self._live_names: list[int] = []
    self._latched_names: list[int] = []
    self.event_counters: dict[int, int] = {}

  @property
  def events(self) -> list[int]:
    return self._live_names

  @events.setter
  def events(self, values: list[int]) -> None:
    self._live_names = values

  @property
  def static_events(self) -> list[int]:
    return self._latched_names

  @static_events.setter
  def static_events(self, values: list[int]) -> None:
    self._latched_names = values

  @property
  def names(self) -> list[int]:
    return list(self._live_names)

  def __len__(self) -> int:
    return len(self._live_names)

  def add(self, event_name: int, static: bool = False) -> None:
    if static:
      insort(self._latched_names, event_name)
    insort(self._live_names, event_name)

  def clear(self) -> None:
    refreshed: dict[int, int] = {}
    for event_name, frames_seen in self.event_counters.items():
      refreshed[event_name] = frames_seen + 1 if event_name in self._live_names else 0
    self.event_counters = refreshed
    self._live_names = list(self._latched_names)

  def contains(self, event_type: str) -> bool:
    board = self.get_events_mapping()
    return any(event_type in board.get(event_name, {}) for event_name in self._live_names)

  def has(self, event_name: int) -> bool:
    return event_name in self._live_names

  def contains_in_list(self, events_list: list[int]) -> bool:
    return any(event_name in self._live_names for event_name in events_list)

  def remove(self, event_name: int, static: bool = False) -> None:
    if static and event_name in self._latched_names:
      self._latched_names.remove(event_name)

    if event_name in self._live_names:
      self.event_counters[event_name] = self.event_counters.get(event_name, 0) + 1
      self._live_names.remove(event_name)

  def add_from_msg(self, events: Iterable) -> None:
    for event in events:
      insort(self._live_names, event.name.raw)

  def to_msg(self):
    board = self.get_events_mapping()
    outbound = []
    for event_name in self._live_names:
      msg = self.get_event_msg_type().new_message()
      msg.name = event_name
      for event_kind in board.get(event_name, {}):
        setattr(msg, event_kind, True)
      outbound.append(msg)
    return outbound

  def create_alerts(self, event_types: list[str], callback_args=None):
    callback_args = [] if callback_args is None else callback_args
    board = self.get_events_mapping()
    spawned: list[AlertCard] = []
    for event_name in self._live_names:
      variants = board.get(event_name, {})
      for event_type in event_types:
        chosen = variants.get(event_type)
        if chosen is None:
          continue
        alert = self._realize(chosen, callback_args)
        age_frames = self.event_counters.get(event_name, 0) + 1
        if age_frames * DT_CTRL < alert.creation_delay:
          continue
        alert.alert_type = f"{self.get_event_name(event_name)}/{event_type}"
        alert.event_type = event_type
        spawned.append(alert)
    return spawned

  @staticmethod
  def _realize(candidate: AlertCard | AlertFactory, callback_args: list) -> AlertCard:
    return candidate if isinstance(candidate, AlertCard) else candidate(*callback_args)

  @abstractmethod
  def get_events_mapping(self) -> dict[int, dict[str, AlertCard | AlertFactory]]:
    raise NotImplementedError

  @abstractmethod
  def get_event_name(self, event: int) -> str:
    raise NotImplementedError

  @abstractmethod
  def get_event_msg_type(self):
    raise NotImplementedError


def _mici_reframe(primary: str, secondary: str) -> tuple[str, str, log.SelfdriveState.AlertSize]:
  if HARDWARE.get_device_type() == "mici":
    return secondary, primary, AlertSize.small
  return primary, secondary, AlertSize.mid


class NoEntryCard(AlertCard):
  def __init__(self,
               alert_text_2: str,
               alert_text_1: str = "openpilot Unavailable",
               visual_alert: car.CarControl.HUDControl.VisualAlert = VisualAlert.none,
               priority: Tier = Tier.LOW):
    primary, secondary, size = _mici_reframe(alert_text_1, alert_text_2)
    super().__init__(primary, secondary, AlertStatus.normal, size, priority, visual_alert, AudibleAlert.refuse, 3.0)


class GentleDisableCard(AlertCard):
  def __init__(self, alert_text_2: str):
    super().__init__(
      "TAKE CONTROL IMMEDIATELY",
      alert_text_2,
      AlertStatus.userPrompt,
      AlertSize.full,
      Tier.MID,
      VisualAlert.steerRequired,
      AudibleAlert.warningSoft,
      2.0,
    )


class PendingDisableCard(GentleDisableCard):
  def __init__(self, alert_text_2: str):
    super().__init__(alert_text_2)
    self.alert_text_1 = "openpilot will disengage"


class HardDisableCard(AlertCard):
  def __init__(self, alert_text_2: str):
    super().__init__(
      "TAKE CONTROL IMMEDIATELY",
      alert_text_2,
      AlertStatus.critical,
      AlertSize.full,
      Tier.HIGHEST,
      VisualAlert.steerRequired,
      AudibleAlert.warningImmediate,
      4.0,
    )


class ChimeCard(AlertCard):
  def __init__(self, audible_alert: car.CarControl.HUDControl.AudibleAlert):
    super().__init__("", "", AlertStatus.normal, AlertSize.none, Tier.MID, VisualAlert.none, audible_alert, 0.2)


class BannerCard(AlertCard):
  def __init__(self, alert_text_1: str, alert_text_2: str = "", duration: float = 0.2, priority: Tier = Tier.LOWER, creation_delay: float = 0.0):
    size = AlertSize.mid if alert_text_2 else AlertSize.small
    super().__init__(alert_text_1, alert_text_2, AlertStatus.normal, size, priority, VisualAlert.none, AudibleAlert.none, duration, creation_delay)


class BootCard(AlertCard):
  def __init__(self, alert_text_1: str, alert_text_2: str = "Always keep hands on wheel and eyes on road", alert_status=AlertStatus.normal):
    if HARDWARE.get_device_type() == "mici":
      compact_secondary = "" if alert_text_2 == "Always keep hands on wheel and eyes on road" else alert_text_2
      super().__init__(alert_text_1, compact_secondary, alert_status, AlertSize.small, Tier.LOWER, VisualAlert.none, AudibleAlert.none, 5.0)
    else:
      super().__init__(alert_text_1, alert_text_2, alert_status, AlertSize.mid, Tier.LOWER, VisualAlert.none, AudibleAlert.none, 5.0)


class AlertBase(AlertCard):
  pass


NULL_ALERT = AlertCard("", "", AlertStatus.normal, AlertSize.none, Tier.LOWEST, VisualAlert.none, AudibleAlert.none, 0.0)
