"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from enum import Enum

from cereal import messaging, log, custom
from openpilot.common.params import Params
from openpilot.selfdrive.ui.iqpilot.layouts.settings.display import OnroadBrightness
from openpilot.system.ui.lib.application import gui_app

OpenpilotState = log.SelfdriveState.OpenpilotState
AOLState = custom.AlwaysOnLateral.AlwaysOnLateralState

ONROAD_BRIGHTNESS_TIMER_PAUSED = -1


class OnroadTimerStatus(Enum):
  NONE = 0
  PAUSE = 1
  RESUME = 2


class IQUIState:
  def __init__(self):
    self.params = Params()
    self.sm_services_ext = [
      "iqModelManager", "iqState", "iqPlan", "iqNavState",
      "gpsLocation", "liveTorqueParameters", "iqCarState",
      "iqLiveData", "iqNavRenderState", "iqCarParams", "liveDelay"
    ]

    self.update_params()

    self.onroad_brightness_timer: int = 0
    self.custom_interactive_timeout: int = self.params.get("InteractivityTimeout", return_default=True)
    self.reset_onroad_sleep_timer()

  def update(self) -> None:
    pass

  def onroad_brightness_handle_alerts(self, started: bool, alert):
    has_alert = started and self.onroad_brightness != OnroadBrightness.AUTO and alert is not None

    self.update_onroad_brightness(has_alert)
    if has_alert:
      self.reset_onroad_sleep_timer()

  def update_onroad_brightness(self, has_alert: bool) -> None:
    if has_alert:
      return

    if self.onroad_brightness_timer > 0:
      self.onroad_brightness_timer -= 1

  def reset_onroad_sleep_timer(self, timer_status: OnroadTimerStatus = OnroadTimerStatus.NONE) -> None:
    # Toggling from active state to inactive
    if timer_status == OnroadTimerStatus.PAUSE and self.onroad_brightness_timer != ONROAD_BRIGHTNESS_TIMER_PAUSED:
      self.onroad_brightness_timer = ONROAD_BRIGHTNESS_TIMER_PAUSED
    # Toggling from a previously inactive state or resetting an active timer
    elif (self.onroad_brightness_timer_param >= 0 and self.onroad_brightness != OnroadBrightness.AUTO and
          self.onroad_brightness_timer != ONROAD_BRIGHTNESS_TIMER_PAUSED) or timer_status == OnroadTimerStatus.RESUME:
      if self.onroad_brightness == OnroadBrightness.AUTO_DARK:
        self.onroad_brightness_timer = 15 * gui_app.target_fps
      else:
        self.onroad_brightness_timer = self.onroad_brightness_timer_param * gui_app.target_fps

  @property
  def onroad_brightness_timer_expired(self) -> bool:
    return self.onroad_brightness != OnroadBrightness.AUTO and self.onroad_brightness_timer == 0

  @property
  def auto_onroad_brightness(self) -> bool:
    return self.onroad_brightness in (OnroadBrightness.AUTO, OnroadBrightness.AUTO_DARK)

  @staticmethod
  def update_status(ss, ss_iq, onroad_evt) -> str:
    state = ss.state
    aol = ss_iq.aol
    aol_state = aol.state

    if state == OpenpilotState.preEnabled:
      return "override"

    if state == OpenpilotState.overriding:
      if not aol.available:
        return "override"

      if any(e.overrideLongitudinal for e in onroad_evt):
        return "override"

    if aol_state in (AOLState.paused, AOLState.overriding):
      return "override"

    # AOL-specific statuses
    if not aol.available:
      return "engaged" if ss.enabled else "disengaged"

    if not aol.enabled and not ss.enabled:
      return "disengaged"

    if aol.enabled and ss.enabled:
      return "engaged"

    if aol.enabled:
      return "lat_only"

    if ss.enabled:
      return "long_only"

    return "disengaged"

  def update_params(self) -> None:
    CP_IQ_bytes = self.params.get("IQCarParamsPersistent")
    if CP_IQ_bytes is not None:
      self.CP_IQ = messaging.log_from_bytes(CP_IQ_bytes, custom.IQCarParams)
    self.active_bundle = self.params.get("ModelManager_ActiveBundle")
    self.blindspot = self.params.get_bool("BlindSpot")
    self.chevron_metrics = self.params.get("ChevronInfo")
    self.custom_interactive_timeout = self.params.get("InteractivityTimeout", return_default=True)
    self.developer_ui = self.params.get("DevUIInfo")
    self.onroad_brightness = int(float(self.params.get("OnroadScreenOffBrightness", return_default=True)))
    self.onroad_brightness_timer_param = self.params.get("OnroadScreenOffTimer", return_default=True)
    self.rainbow_path = self.params.get_bool("RainbowMode")
    self.road_name_toggle = self.params.get_bool("RoadNameToggle")
    self.rocket_fuel = self.params.get_bool("RocketFuel")
    self.speed_limit_mode = self.params.get("SpeedLimitMode", return_default=True)
    # Standstill timer feature removed from IQ.Pilot UI.
    self.standstill_timer = False
    self.torque_bar = self.params.get_bool("TorqueBar")
    self.turn_signals = self.params.get_bool("ShowTurnSignals")


class IQDevice:
  def __init__(self):
    self._params = Params()

  def _set_awake(self, on: bool):
    if on and self._params.get("DeviceBootMode", return_default=True) == 1:
      self._params.put_bool("OffroadMode", True)

  @staticmethod
  def set_onroad_brightness(_ui_state, awake: bool, cur_brightness: float) -> float:
    if not awake or not _ui_state.started:
      return cur_brightness

    if _ui_state.onroad_brightness_timer != 0:
      if _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK:
        return max(30.0, cur_brightness)
      # For AUTO (Default) and Manual modes (while timer running), use standard brightness
      return cur_brightness

    # 0: Auto (Default), 1: Auto (Dark)
    if _ui_state.onroad_brightness == OnroadBrightness.AUTO:
      return cur_brightness
    elif _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK:
      return cur_brightness

    # 2-21: 5% - 100%
    return float((_ui_state.onroad_brightness - 1) * 5)

  @staticmethod
  def set_min_onroad_brightness(_ui_state, min_brightness: int) -> int:
    if _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK:
      min_brightness = 10

    return min_brightness

  @staticmethod
  def wake_from_dimmed_onroad_brightness(_ui_state, evs) -> None:
    if _ui_state.started and (_ui_state.onroad_brightness_timer_expired or _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK):
      if any(ev.left_down for ev in evs):
        if _ui_state.onroad_brightness_timer_expired:
          gui_app.mouse_events.clear()
        _ui_state.reset_onroad_sleep_timer()
