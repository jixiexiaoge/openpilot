import pyray as rl
import numpy as np
import time
import threading
from collections.abc import Callable
from enum import Enum, IntEnum
from cereal import messaging, car, log, custom
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.lib.prime_state import PrimeState
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.hardware import HARDWARE, PC

BACKLIGHT_OFFROAD = 65 if HARDWARE.get_device_type() == "mici" else 50

OpenpilotState = log.SelfdriveState.OpenpilotState
GuidanceState = custom.AlwaysOnLateral.AlwaysOnLateralState

ONROAD_BRIGHTNESS_TIMER_PAUSED = -1


class OnroadTimerStatus(Enum):
  NONE = 0
  PAUSE = 1
  RESUME = 2


class OnroadBrightness(IntEnum):
  AUTO = 0
  AUTO_DARK = 1


class IQUIState:
  def __init__(self):
    self.params = Params()
    self.sm_services_ext = [
      "iqModelManager", "iqState", "iqPlan", "iqNavState",
      "gpsLocation", "liveTorqueParameters",
      "iqLiveData", "iqNavRenderState", "liveDelay"
    ]

    self.update_params()

    self.onroad_brightness_timer: int = 0
    self.custom_interactive_timeout: int = self.params.get("InteractivityTimeout", return_default=True)
    self.reset_onroad_sleep_timer()

  def update(self) -> None:
    pass

  def onroad_brightness_handle_alerts(self, started: bool, alert):
    # while an alert is on screen the dim countdown is frozen and re-armed; otherwise it ticks down
    alert_showing = bool(started and alert is not None and self.onroad_brightness != OnroadBrightness.AUTO)
    self.update_onroad_brightness(alert_showing)
    if alert_showing:
      self.reset_onroad_sleep_timer()

  def update_onroad_brightness(self, has_alert: bool) -> None:
    if not has_alert and self.onroad_brightness_timer > 0:
      self.onroad_brightness_timer -= 1

  def reset_onroad_sleep_timer(self, timer_status: OnroadTimerStatus = OnroadTimerStatus.NONE) -> None:
    paused = self.onroad_brightness_timer == ONROAD_BRIGHTNESS_TIMER_PAUSED

    # an explicit PAUSE latches the timer and never re-arms
    if timer_status == OnroadTimerStatus.PAUSE:
      if not paused:
        self.onroad_brightness_timer = ONROAD_BRIGHTNESS_TIMER_PAUSED
      return

    dimming_active = self.onroad_brightness_timer_param >= 0 and self.onroad_brightness != OnroadBrightness.AUTO
    if timer_status == OnroadTimerStatus.RESUME or (dimming_active and not paused):
      seconds = 15 if self.onroad_brightness == OnroadBrightness.AUTO_DARK else self.onroad_brightness_timer_param
      self.onroad_brightness_timer = seconds * gui_app.target_fps

  @property
  def onroad_brightness_timer_expired(self) -> bool:
    if self.onroad_brightness == OnroadBrightness.AUTO:
      return False
    return self.onroad_brightness_timer == 0

  @property
  def auto_onroad_brightness(self) -> bool:
    return self.onroad_brightness in (OnroadBrightness.AUTO, OnroadBrightness.AUTO_DARK)

  @staticmethod
  def guidance_phase(ss, ss_iq, onroad_evt) -> str:
    state = ss.state
    guidance = ss_iq.aol
    guidance_state = guidance.state

    if state == OpenpilotState.preEnabled:
      return "standby"

    if state == OpenpilotState.overriding and (not guidance.available or any(e.overrideLongitudinal for e in onroad_evt)):
      return "standby"

    if guidance_state in (GuidanceState.paused, GuidanceState.overriding):
      return "standby"

    if guidance.enabled or ss.enabled:
      return "active"

    return "standby"

  @staticmethod
  def update_status(ss, ss_iq, onroad_evt) -> str:
    state = ss.state
    guidance = ss_iq.aol
    guidance_state = guidance.state

    if state == OpenpilotState.preEnabled:
      return "override"

    if state == OpenpilotState.overriding:
      if not guidance.available:
        return "override"

      if any(e.overrideLongitudinal for e in onroad_evt):
        return "override"

    if guidance_state in (GuidanceState.paused, GuidanceState.overriding):
      return "override"

    if not guidance.available:
      return "engaged" if ss.enabled else "disengaged"

    if not guidance.enabled and not ss.enabled:
      return "disengaged"

    if guidance.enabled and ss.enabled:
      return "engaged"

    if guidance.enabled:
      return "lat_only"

    if ss.enabled:
      return "long_only"

    return "disengaged"

  _PARAM_MIRROR = {
    "active_bundle": ("ModelManager_ActiveBundle", "raw"),
    "blindspot": ("BlindSpot", "bool"),
    "chevron_metrics": ("ChevronInfo", "raw"),
    "developer_ui": ("IQDevUIInfo", "raw"),
    "night_mode": ("NightMode", "bool"),
    "rainbow_path": ("RainbowMode", "bool"),
    "road_name_toggle": ("RoadNameToggle", "bool"),
    "rocket_fuel": ("RocketFuel", "bool"),
    "torque_bar": ("TorqueBar", "bool"),
    "turn_signals": ("ShowTurnSignals", "bool"),
    "custom_interactive_timeout": ("InteractivityTimeout", "default"),
    "onroad_brightness_timer_param": ("OnroadScreenOffTimer", "default"),
    "speed_limit_mode": ("IQSpeedAssistMode", "default"),
  }

  def update_params(self) -> None:
    CP_IQ_bytes = self.params.get("IQCarParamsPersistentV2")
    if CP_IQ_bytes is not None:
      self.CP_IQ = messaging.log_from_bytes(CP_IQ_bytes, custom.IQCarParams)

    for attr, (key, kind) in self._PARAM_MIRROR.items():
      if kind == "bool":
        value = self.params.get_bool(key)
      elif kind == "default":
        value = self.params.get(key, return_default=True)
      else:
        value = self.params.get(key)
      setattr(self, attr, value)

    self.is_night = self._compute_is_night() if self.night_mode else False
    self.onroad_brightness = int(float(self.params.get("OnroadScreenOffBrightness", return_default=True)))

  def _compute_is_night(self) -> bool:
    try:
      from openpilot.selfdrive.ui.lib.nav_helpers import current_or_last_gps_position
      from openpilot.selfdrive.ui.lib.solar import is_after_sunset
      lat, lon, _, valid = current_or_last_gps_position(self.params)
      return valid and is_after_sunset(lat, lon)
    except Exception:
      return False


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
      return cur_brightness

    if _ui_state.onroad_brightness == OnroadBrightness.AUTO:
      return cur_brightness
    elif _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK:
      return cur_brightness

    return float((_ui_state.onroad_brightness - 1) * 5)

  @staticmethod
  def set_min_onroad_brightness(_ui_state, min_brightness: int) -> int:
    dark = _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK
    return 10 if dark else min_brightness

  @staticmethod
  def wake_from_dimmed_onroad_brightness(_ui_state, evs) -> None:
    expired = _ui_state.onroad_brightness_timer_expired
    dimmed = expired or _ui_state.onroad_brightness == OnroadBrightness.AUTO_DARK
    if not (_ui_state.started and dimmed):
      return
    if not any(ev.left_down for ev in evs):
      return
    if expired:
      gui_app.mouse_events.clear()
    _ui_state.reset_onroad_sleep_timer()


class UIStatus(Enum):
  DISENGAGED = "disengaged"
  ENGAGED = "engaged"
  OVERRIDE = "override"
  LAT_ONLY = "lat_only"
  LONG_ONLY = "long_only"


class UIState(IQUIState):
  _instance: 'UIState | None' = None

  def __new__(cls):
    if cls._instance is None:
      cls._instance = super().__new__(cls)
      cls._instance._initialize()
    return cls._instance

  def _initialize(self):
    IQUIState.__init__(self)
    self.params = Params()
    self.sm = messaging.SubMaster(
      [
        "modelV2",
        "controlsState",
        "onroadEvents",
        "liveCalibration",
        "radarState",
        "liveTracks",
        "iqVehicleTracks",
        "deviceState",
        "pandaStates",
        "carParams",
        "driverMonitoringState",
        "carState",
        "driverStateV2",
        "roadCameraState",
        "wideRoadCameraState",
        "managerState",
        "selfdriveState",
        "longitudinalPlan",
        "gpsLocationExternal",
        "carOutput",
        "carControl",
        "liveParameters",
      ] + self.sm_services_ext
    )

    self.prime_state = PrimeState()

    # UI Status tracking
    self.status: UIStatus = UIStatus.DISENGAGED
    self.started_frame: int = 0
    self.started_time: float = 0.0
    self._engaged_prev: bool = False
    self._started_prev: bool = False
    self._last_non_disengaged_status: UIStatus = UIStatus.DISENGAGED
    self._last_non_disengaged_time: float = 0.0

    # Core state variables
    self.is_metric: bool = self.params.get_bool("IsMetric")
    self.is_release = self.params.get_bool("IsReleaseBranch")
    self.always_on_dm: bool = self.params.get_bool("AlwaysOnDM")
    self.started: bool = False
    self.ignition: bool = False
    self.recording_audio: bool = False
    self.panda_type: log.PandaState.PandaType = log.PandaState.PandaType.unknown
    self.personality: log.LongitudinalPersonality = log.LongitudinalPersonality.standard
    self.has_longitudinal_control: bool = False
    self.CP: car.CarParams | None = None
    self.light_sensor: float = -1.0
    self._param_update_time: float = 0.0

    # Callbacks
    self._offroad_transition_callbacks: list[Callable[[], None]] = []
    self._engaged_transition_callbacks: list[Callable[[], None]] = []

    self.update_params()

  def add_offroad_transition_callback(self, callback: Callable[[], None]):
    self._offroad_transition_callbacks.append(callback)

  def add_engaged_transition_callback(self, callback: Callable[[], None]):
    self._engaged_transition_callbacks.append(callback)

  @property
  def engaged(self) -> bool:
    ss_ext = self.sm["iqState"]
    return self.started and (self.sm["selfdriveState"].enabled or ss_ext.aol.enabled)

  def is_onroad(self) -> bool:
    return self.started

  def is_offroad(self) -> bool:
    return not self.started

  def update(self) -> None:
    self.prime_state.start()  # start thread after manager forks ui
    self.sm.update(0)
    self._update_state()
    self._update_status()
    if time.monotonic() - self._param_update_time > 5.0:
      self.update_params()
    device.update()
    IQUIState.update(self)

  def _update_state(self) -> None:
    # Handle panda states updates
    if self.sm.updated["pandaStates"]:
      panda_states = self.sm["pandaStates"]

      if len(panda_states) > 0:
        # Get panda type from first panda
        self.panda_type = panda_states[0].pandaType
        # Check ignition status across all pandas
        if self.panda_type != log.PandaState.PandaType.unknown:
          self.ignition = any(state.ignitionLine or state.ignitionCan for state in panda_states)
    elif not self.sm.alive["pandaStates"]:
      # Time-based staleness (SubMaster tracks it against the service rate). The old
      # `5 * rl.get_fps()` frame threshold went near-zero right after the screen woke — rendering
      # had just resumed so raylib's FPS reading was still ~0 — which briefly flagged a perfectly
      # fresh pandaStates as stale, flashing panda_type to unknown ("UNAVAILABLE") for a few seconds.
      self.panda_type = log.PandaState.PandaType.unknown

    # Handle wide road camera state updates
    if self.sm.updated["wideRoadCameraState"]:
      cam_state = self.sm["wideRoadCameraState"]
      self.light_sensor = max(100.0 - cam_state.exposureValPercent, 0.0)
    elif not self.sm.alive["wideRoadCameraState"] or not self.sm.valid["wideRoadCameraState"]:
      self.light_sensor = -1

    # Update started state
    self.started = self.sm["deviceState"].started and self.ignition

    # Update recording audio state
    self.recording_audio = self.params.get_bool("RecordAudio") and self.started

    self.is_metric = self.params.get_bool("IsMetric")
    self.always_on_dm = self.params.get_bool("AlwaysOnDM")

  def _update_status(self) -> None:
    if self.started and self.sm.updated["selfdriveState"]:
      ss = self.sm["selfdriveState"]
      state = ss.state
      iq_state = self.sm["iqState"]

      if state in (log.SelfdriveState.OpenpilotState.preEnabled, log.SelfdriveState.OpenpilotState.overriding):
        self.status = UIStatus.OVERRIDE
      else:
        self.status = UIStatus.ENGAGED if ss.enabled else UIStatus.DISENGAGED

      computed_status = UIStatus(IQUIState.update_status(ss, iq_state, self.sm["onroadEvents"]))
      now = time.monotonic()
      engaged_like_now = bool(ss.enabled or iq_state.aol.enabled)
      if computed_status != UIStatus.DISENGAGED:
        self._last_non_disengaged_status = computed_status
        self._last_non_disengaged_time = now
        self.status = computed_status
      elif engaged_like_now:
        if self._last_non_disengaged_status != UIStatus.DISENGAGED:
          self.status = self._last_non_disengaged_status
        else:
          self.status = UIStatus.ENGAGED if ss.enabled else UIStatus.DISENGAGED
      else:
        self.status = UIStatus.DISENGAGED

    if self.engaged != self._engaged_prev:
      for callback in self._engaged_transition_callbacks:
        callback()
      self._engaged_prev = self.engaged

    if self.started != self._started_prev or self.sm.frame == 1:
      if self.started:
        self.status = UIStatus.DISENGAGED
        self.started_frame = self.sm.frame
        self.started_time = time.monotonic()
        self._last_non_disengaged_status = UIStatus.DISENGAGED
        self._last_non_disengaged_time = 0.0

      for callback in self._offroad_transition_callbacks:
        callback()

      self._started_prev = self.started

  def update_params(self) -> None:
    CP_bytes = self.params.get("CarParamsPersistent")
    if CP_bytes is not None:
      self.CP = messaging.log_from_bytes(CP_bytes, car.CarParams)
      if self.CP.alphaLongitudinalAvailable:
        self.has_longitudinal_control = self.params.get_bool("AlphaLongitudinalEnabled")
      else:
        self.has_longitudinal_control = self.CP.openpilotLongitudinalControl
    IQUIState.update_params(self)
    self._param_update_time = time.monotonic()



class Device(IQDevice):
  def __init__(self):
    IQDevice.__init__(self)
    self._ignition = False
    self._interaction_time: float = -1
    self._override_interactive_timeout: int | None = None
    self._interactive_timeout_callbacks: list[Callable] = []
    self._prev_timed_out = False
    self._awake: bool = True

    self._offroad_brightness: int = BACKLIGHT_OFFROAD
    self._display_brightness_param: int = 0
    self._last_brightness_param_update: float = 0.0
    self._last_brightness: int = 0
    self._brightness_filter = FirstOrderFilter(BACKLIGHT_OFFROAD, 10.00, 1 / gui_app.target_fps)
    self._brightness_thread: threading.Thread | None = None

  @property
  def awake(self) -> bool:
    return self._awake

  def set_override_interactive_timeout(self, timeout: int | None) -> None:
    self._override_interactive_timeout = timeout
    self._reset_interactive_timeout()

  @property
  def interactive_timeout(self) -> int:
    if self._override_interactive_timeout is not None:
      return self._override_interactive_timeout

    if gui_app.iqpilot_ui() and ui_state.custom_interactive_timeout != 0:
      return ui_state.custom_interactive_timeout

    ignition_timeout = 10 if gui_app.big_ui() else 5
    if ui_state.night_mode and ui_state.is_night:
      ignition_timeout = 15
    return ignition_timeout if ui_state.ignition else 30

  def _reset_interactive_timeout(self) -> None:
    self._interaction_time = time.monotonic() + self.interactive_timeout

  def add_interactive_timeout_callback(self, callback: Callable):
    self._interactive_timeout_callbacks.append(callback)

  def update(self):
    if self._interaction_time <= 0:
      self._reset_interactive_timeout()

    self._update_brightness()
    self._update_wakefulness()

  def set_offroad_brightness(self, brightness: int | None):
    if brightness is None:
      brightness = BACKLIGHT_OFFROAD
    self._offroad_brightness = min(max(brightness, 0), 100)

  def _update_display_brightness_param(self):
    now = time.monotonic()
    if now - self._last_brightness_param_update < 1.0:
      return

    try:
      brightness = int(self._params.get("Brightness", return_default=True))
    except (TypeError, ValueError):
      brightness = 0

    self._display_brightness_param = min(max(brightness, 0), 100)
    self._last_brightness_param_update = now

  def _update_brightness(self):
    self._update_display_brightness_param()
    manual_display_brightness = self._display_brightness_param

    clipped_brightness = manual_display_brightness if manual_display_brightness > 0 else self._offroad_brightness

    if ui_state.started and ui_state.light_sensor >= 0:
      clipped_brightness = ui_state.light_sensor

      # CIE 1931 - https://www.photonstophotos.net/GeneralTopics/Exposure/Psychometric_Lightness_and_Gamma.htm
      if clipped_brightness <= 8:
        clipped_brightness = clipped_brightness / 903.3
      else:
        clipped_brightness = ((clipped_brightness + 16.0) / 116.0) ** 3.0

      min_brightness = 30
      if gui_app.iqpilot_ui():
        min_brightness = IQDevice.set_min_onroad_brightness(ui_state, min_brightness)

      clipped_brightness = float(np.interp(clipped_brightness, [0, 1], [min_brightness, 100]))

    brightness = round(self._brightness_filter.update(clipped_brightness))

    if gui_app.iqpilot_ui():
      brightness = IQDevice.set_onroad_brightness(ui_state, self._awake, brightness)

    if manual_display_brightness > 0:
      brightness = min(brightness, manual_display_brightness)

    if not self._awake:
      brightness = 0

    if brightness != self._last_brightness:
      if self._brightness_thread is None or not self._brightness_thread.is_alive():
        self._brightness_thread = threading.Thread(target=HARDWARE.set_screen_brightness, args=(brightness,))
        self._brightness_thread.start()
        self._last_brightness = brightness

  def _update_wakefulness(self):
    # Handle interactive timeout
    ignition_just_turned_off = not ui_state.ignition and self._ignition
    self._ignition = ui_state.ignition

    if ignition_just_turned_off or any(ev.left_down for ev in gui_app.mouse_events):
      if gui_app.iqpilot_ui():
        IQDevice.wake_from_dimmed_onroad_brightness(ui_state, gui_app.mouse_events)

      self._reset_interactive_timeout()

    interaction_timeout = time.monotonic() > self._interaction_time
    if interaction_timeout and not self._prev_timed_out:
      for callback in self._interactive_timeout_callbacks:
        callback()
    self._prev_timed_out = interaction_timeout

    night_active = ui_state.night_mode and ui_state.is_night
    # active screen recording keeps the display on so remote-triggered recordings capture frames
    self._set_awake((ui_state.ignition and not night_active) or not interaction_timeout or PC
                    or gui_app.screen_recorder_active)

  def _set_awake(self, on: bool):
    if on != self._awake:
      IQDevice._set_awake(self, on)
      self._awake = on
      cloudlog.debug(f"setting display power {int(on)}")
      HARDWARE.set_display_power(on)
      gui_app.set_should_render(on)


# Global instance
ui_state = UIState()
device = Device()
