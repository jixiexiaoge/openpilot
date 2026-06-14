"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import log

from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL


class LaneSwapPreset:
  DISABLED = -1
  STEERING_NUDGE = 0
  DIRECT = 1
  DELAY_HALF = 2
  DELAY_ONE = 3
  DELAY_TWO = 4
  DELAY_THREE = 5
  OFF = DISABLED
  NUDGE = STEERING_NUDGE
  NUDGELESS = DIRECT
  HALF_SECOND = DELAY_HALF
  ONE_SECOND = DELAY_ONE
  TWO_SECONDS = DELAY_TWO
  THREE_SECONDS = DELAY_THREE


PRESET_SECONDS = {
  LaneSwapPreset.DISABLED: 0.0,
  LaneSwapPreset.STEERING_NUDGE: 0.0,
  LaneSwapPreset.DIRECT: 0.05,
  LaneSwapPreset.DELAY_HALF: 0.5,
  LaneSwapPreset.DELAY_ONE: 1.0,
  LaneSwapPreset.DELAY_TWO: 2.0,
  LaneSwapPreset.DELAY_THREE: 3.0,
}

LANE_SWAP_SECONDS = dict(PRESET_SECONDS)
BLINDSPOT_WAIT_OFFSET = -1


class LaneSwapEngine:
  def __init__(self, desire_hub):
    self._hub = desire_hub
    self._kv = Params()
    self._mem = {
      "sec": 0.0,
      "tick": 0,
      "gate": 0.0,
      "preset": self._kv.get("AutoLaneChangeTimer", return_default=True),
      "bsm_hold": False,
      "braked": False,
      "ready": False,
      "used": False,
    }
    self.reload_setup()

  def _pull_setup(self) -> None:
    self._mem["bsm_hold"] = self._kv.get_bool("AutoLaneChangeBsmDelay")
    self._mem["preset"] = self._kv.get("AutoLaneChangeTimer", return_default=True)

  def _idle_phase(self) -> bool:
    return (
      self._hub.lane_change_state == log.LaneChangeState.off and
      self._hub.lane_change_direction == log.LaneChangeDirection.none
    )

  def _seconds_for_preset(self) -> float:
    picked = self._mem["preset"]
    return PRESET_SECONDS.get(picked, PRESET_SECONDS[LaneSwapPreset.STEERING_NUDGE])

  def _auto_preset_active(self) -> bool:
    picked = self._mem["preset"]
    return picked not in (LaneSwapPreset.DISABLED, LaneSwapPreset.STEERING_NUDGE)

  def _advance_clock(self, blindspot_now: bool) -> None:
    wait_s = self._seconds_for_preset()
    self._mem["gate"] = wait_s
    self._mem["sec"] += DT_MDL
    if self._mem["bsm_hold"] and blindspot_now and wait_s > 0.0:
      if wait_s == PRESET_SECONDS[LaneSwapPreset.DIRECT]:
        self._mem["sec"] = BLINDSPOT_WAIT_OFFSET
      else:
        self._mem["sec"] = wait_s + BLINDSPOT_WAIT_OFFSET

  def _ready_to_fire(self) -> bool:
    return (
      self._auto_preset_active() and
      (not self._mem["braked"]) and
      (not self._mem["used"]) and
      (self._mem["sec"] > self._mem["gate"])
    )

  def reload_setup(self) -> None:
    self._pull_setup()

  def heartbeat(self) -> None:
    if (self._mem["tick"] % 50) == 0:
      self._pull_setup()
    self._mem["tick"] += 1

  def sample(self, blindspot_now: bool = False, brake_now: bool = False, **legacy) -> None:
    blindspot_now = bool(legacy.get("blindspot_detected", blindspot_now))
    brake_now = bool(legacy.get("brake_pressed", brake_now))
    self._mem["braked"] = self._mem["braked"] or brake_now
    self._advance_clock(blindspot_now)
    self._mem["ready"] = self._ready_to_fire()

  def finalize(self) -> None:
    started = self._hub.lane_change_state == log.LaneChangeState.laneChangeStarting
    self._mem["used"] = self._mem["used"] or started
    if self._idle_phase():
      self._mem["sec"] = 0.0
      self._mem["braked"] = False
      self._mem["used"] = False

  @property
  def ready(self):
    return self._mem["ready"]

  @property
  def delay(self):
    return self._mem["gate"]

  @property
  def elapsed(self):
    return self._mem["sec"]

  @property
  def preset(self):
    return self._mem["preset"]

  @preset.setter
  def preset(self, value):
    self._mem["preset"] = value

  @property
  def bsm_hold(self):
    return self._mem["bsm_hold"]

  @bsm_hold.setter
  def bsm_hold(self, value):
    self._mem["bsm_hold"] = bool(value)

  @property
  def braked(self):
    return self._mem["braked"]

  @braked.setter
  def braked(self, value):
    self._mem["braked"] = bool(value)

  @property
  def used(self):
    return self._mem["used"]

  @used.setter
  def used(self, value):
    self._mem["used"] = bool(value)


AutoLaneChangeMode = LaneSwapPreset
AUTO_LANE_CHANGE_TIMER = LANE_SWAP_SECONDS
ONE_SECOND_DELAY = BLINDSPOT_WAIT_OFFSET


class AutoLaneChangeController(LaneSwapEngine):
  def __init__(self, desire_helper):
    super().__init__(desire_helper)

  def reset(self) -> None:
    self.finalize()

  def update_params(self) -> None:
    self.heartbeat()

  def update_lane_change(self, blindspot_detected: bool, brake_pressed: bool) -> None:
    self.sample(blindspot_now=blindspot_detected, brake_now=brake_pressed)

  def update_state(self) -> None:
    self.finalize()

  @property
  def lane_change_wait_timer(self):
    return self.elapsed

  @lane_change_wait_timer.setter
  def lane_change_wait_timer(self, value):
    self._mem["sec"] = float(value)

  @property
  def lane_change_delay(self):
    return self.delay

  @lane_change_delay.setter
  def lane_change_delay(self, value):
    self._mem["gate"] = float(value)

  @property
  def lane_change_set_timer(self):
    return self.preset

  @lane_change_set_timer.setter
  def lane_change_set_timer(self, value):
    self.preset = value

  @property
  def lane_change_bsm_delay(self):
    return self.bsm_hold

  @lane_change_bsm_delay.setter
  def lane_change_bsm_delay(self, value):
    self.bsm_hold = value

  @property
  def prev_brake_pressed(self):
    return self.braked

  @prev_brake_pressed.setter
  def prev_brake_pressed(self, value):
    self.braked = value

  @property
  def auto_lane_change_allowed(self):
    return self.ready

  @auto_lane_change_allowed.setter
  def auto_lane_change_allowed(self, value):
    self._mem["ready"] = bool(value)

  @property
  def prev_lane_change(self):
    return self.used

  @prev_lane_change.setter
  def prev_lane_change(self, value):
    self.used = value
