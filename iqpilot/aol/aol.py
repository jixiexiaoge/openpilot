"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import log, custom
from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from openpilot.common.params import Params, UnknownKeyName
from openpilot.iqpilot.aol.imahelper import BrakeInterventionMode, resolve_brake_intervention_mode, \
  BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE, read_aol_enabled_pref, read_main_cruise_pref, read_joint_engagement_pref
from openpilot.iqpilot.aol.engine import AolStateMachine, GEARS_ALLOW_PAUSED_SILENT

State = custom.AlwaysOnLateral.AlwaysOnLateralState
SelfdriveState = log.SelfdriveState.OpenpilotState
ButtonType = structs.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
EventNameIQ = custom.IQOnroadEvent.EventName
GearShifter = structs.CarState.GearShifter
SafetyModel = structs.CarParams.SafetyModel

SET_SPEED_BUTTONS = (ButtonType.accelCruise, ButtonType.resumeCruise, ButtonType.decelCruise, ButtonType.setCruise)
IGNORED_SAFETY_MODES = (SafetyModel.silent, SafetyModel.noOutput)


class AlwaysOnLateral:
  def __init__(self, selfdrive):
    self.CP = selfdrive.CP
    self.CP_IQ = selfdrive.CP_IQ
    self.params = selfdrive.params

    self.enabled = False
    self.active = False
    self.available = False
    self.hkg_allow = False
    self.no_main_cruise = False
    self.selfdrive = selfdrive
    self.selfdrive.enabled_prev = False
    self.state_machine = AolStateMachine(self)
    self.events = self.selfdrive.events
    self.events_iq = self.selfdrive.events_iq
    self.disengage_on_accelerator = Params().get_bool("DisengageOnAccelerator")

    if self.CP.brand in BRANDS_WITHOUT_MAIN_CRUISE_TOGGLE:
      self.no_main_cruise = True

    self.enabled_toggle = read_aol_enabled_pref(self.params)
    self.main_enabled_toggle = read_main_cruise_pref(self.params)
    self.steering_mode_on_brake = resolve_brake_intervention_mode(self.CP, self.CP_IQ, self.params)
    self.unified_engagement_mode = read_joint_engagement_pref(self.params)

    if self.CP.brand == "hyundai" and self.CP.flags & (HyundaiFlags.HAS_LDA_BUTTON | HyundaiFlags.CANFD):
      self.hkg_allow = True

  def read_params(self):
    self.main_enabled_toggle = read_main_cruise_pref(self.params)
    self.unified_engagement_mode = read_joint_engagement_pref(self.params)

  def _consume_joystick_aol_request(self, CS: structs.CarState) -> str | None:
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
    request = request.strip().lower()
    if request not in ("enable", "disable"):
      return None

    started = getattr(CS, "started", False)
    if not started:
      return None

    if getattr(CS, "doorOpen", False) or getattr(CS, "seatbeltUnlatched", False):
      return None

    if getattr(CS, "gearShifter", GearShifter.unknown) in (GearShifter.park, GearShifter.reverse):
      return None

    return request

  def pedal_pressed_non_gas_pressed(self, CS: structs.CarState) -> bool:
    if self.events.has(EventName.pedalPressed) and not (CS.gasPressed and not self.selfdrive.CS_prev.gasPressed and self.disengage_on_accelerator):
      return True

    return False

  def should_silent_lkas_enable(self, CS: structs.CarState) -> bool:
    if self.steering_mode_on_brake == BrakeInterventionMode.SUSPEND and self.pedal_pressed_non_gas_pressed(CS):
      return False

    if self.events_iq.contains_in_list(GEARS_ALLOW_PAUSED_SILENT):
      return False

    return True

  def block_unified_engagement_mode(self) -> bool:
    if not self.unified_engagement_mode:
      return True

    if self.enabled:
      return True

    if self.selfdrive.enabled and self.selfdrive.enabled_prev:
      return True

    return False

  def get_wrong_car_mode(self, alert_only: bool) -> None:
    if alert_only:
      if self.events.has(EventName.wrongCarMode):
        self.replace_event(EventName.wrongCarMode, EventNameIQ.wrongCarModeAlertOnly)
    else:
      self.events.remove(EventName.wrongCarMode)

  def transition_paused_state(self):
    if self.state_machine.state != State.paused:
      self.events_iq.add(EventNameIQ.silentLkasDisable)

  def replace_event(self, old_event: int, new_event: int):
    self.events.remove(old_event)
    self.events_iq.add(new_event)

  def _has_runtime_lkas_toggle(self, CS: structs.CarState) -> bool:
    lateral_available = getattr(CS, 'lateralAvailable', CS.cruiseState.available)
    if lateral_available:
      return True

    return self.hkg_allow or self.CP.brand == "tesla"

  @staticmethod
  def _cruise_main_available(CS: structs.CarState) -> bool:
    return bool(getattr(getattr(CS, 'cruiseState', None), 'available', False))

  def update_events(self, CS: structs.CarState):
    request = self._consume_joystick_aol_request(CS)
    if request == "enable":
      self.events_iq.add(EventNameIQ.lkasEnable)
    elif request == "disable":
      self.events_iq.add(EventNameIQ.lkasDisable)

    if not self.selfdrive.enabled and self.enabled:
      if CS.standstill:
        if self.events.has(EventName.doorOpen):
          self.replace_event(EventName.doorOpen, EventNameIQ.silentDoorOpen)
          self.transition_paused_state()
        if self.events.has(EventName.seatbeltNotLatched):
          self.replace_event(EventName.seatbeltNotLatched, EventNameIQ.silentSeatbeltNotLatched)
          self.transition_paused_state()
      if self.events.has(EventName.wrongGear) and (CS.vEgo < 2.5 or CS.gearShifter == GearShifter.reverse):
        self.replace_event(EventName.wrongGear, EventNameIQ.silentWrongGear)
        self.transition_paused_state()
      if self.events.has(EventName.reverseGear):
        self.replace_event(EventName.reverseGear, EventNameIQ.silentReverseGear)
        self.transition_paused_state()
      if self.events.has(EventName.brakeHold):
        self.replace_event(EventName.brakeHold, EventNameIQ.silentBrakeHold)
        self.transition_paused_state()
      if self.events.has(EventName.parkBrake):
        self.replace_event(EventName.parkBrake, EventNameIQ.silentParkBrake)
        self.transition_paused_state()

      if self.steering_mode_on_brake == BrakeInterventionMode.SUSPEND:
        if self.pedal_pressed_non_gas_pressed(CS):
          self.transition_paused_state()

      self.events.remove(EventName.preEnableStandstill)
      self.events.remove(EventName.belowEngageSpeed)
      self.events.remove(EventName.speedTooLow)
      self.events.remove(EventName.cruiseDisabled)
      self.events.remove(EventName.manualRestart)

    selfdrive_enable_events = self.events.has(EventName.pcmEnable) or self.events.has(EventName.buttonEnable)
    set_speed_btns_enable = any(be.type in SET_SPEED_BUTTONS for be in CS.buttonEvents)

    self.get_wrong_car_mode(selfdrive_enable_events or set_speed_btns_enable)

    if selfdrive_enable_events:
      if self.pedal_pressed_non_gas_pressed(CS):
        self.events_iq.add(EventNameIQ.pedalPressedAlertOnly)

      if self.block_unified_engagement_mode():
        self.events.remove(EventName.pcmEnable)
        self.events.remove(EventName.buttonEnable)
    else:
      if self.main_enabled_toggle:
        cruise_main_available = self._cruise_main_available(CS)
        cruise_main_available_prev = self._cruise_main_available(self.selfdrive.CS_prev)
        if cruise_main_available and not cruise_main_available_prev:
          self.events_iq.add(EventNameIQ.lkasEnable)

    full_disengage = False
    for be in CS.buttonEvents:
      if be.type == ButtonType.cancel:
        if not self.selfdrive.enabled and self.selfdrive.enabled_prev:
          self.events_iq.add(EventNameIQ.manualLongitudinalRequired)
      if be.type == ButtonType.lkas and be.pressed and self._has_runtime_lkas_toggle(CS):
        if self.enabled:
          self.events_iq.add(EventNameIQ.lkasDisable)
          if self.selfdrive.enabled:
            full_disengage = True  # Fully engaged: 3-finger tap disengages everything
        else:
          self.events_iq.add(EventNameIQ.lkasEnable)

    lateral_available = getattr(CS, 'lateralAvailable', CS.cruiseState.available)
    main_cruise_off = self.main_enabled_toggle and not self._cruise_main_available(CS)
    if (not lateral_available or main_cruise_off) and not self.no_main_cruise:
      self.events.remove(EventName.buttonEnable)
      if self.enabled:
        self.events_iq.add(EventNameIQ.lkasDisable)

    if self.steering_mode_on_brake == BrakeInterventionMode.CANCEL:
      if self.pedal_pressed_non_gas_pressed(CS):
        if self.enabled:
          self.events_iq.add(EventNameIQ.lkasDisable)
        else:
          if self.events_iq.contains(EventNameIQ.lkasEnable):
            self.events_iq.remove(EventNameIQ.lkasEnable)
            self.events_iq.add(EventNameIQ.pedalPressedAlertOnly)

    if self.should_silent_lkas_enable(CS):
      if self.state_machine.state == State.paused:
        self.events_iq.add(EventNameIQ.silentLkasEnable)

    self.events.remove(EventName.pcmDisable)
    self.events.remove(EventName.buttonCancel)
    self.events.remove(EventName.pedalPressed)
    self.events.remove(EventName.wrongCruiseMode)

    if full_disengage:
      self.events.add(EventName.buttonCancel)

  def update(self, CS: structs.CarState):
    joystick_mode = self.params.get_bool("JoystickDebugMode")
    if not self.enabled_toggle and not joystick_mode:
      return

    self.update_events(CS)

    self.update_state()

  def update_state(self):
    if not self.CP.passive and self.selfdrive.initialized:
      self.enabled, self.active = self.state_machine.update()

    self.selfdrive.enabled_prev = self.selfdrive.enabled
