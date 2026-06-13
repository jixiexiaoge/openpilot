#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os
import time
import threading

import cereal.messaging as messaging

from cereal import car, log, custom

from openpilot.common.issue_debug import log_issue_limited
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.realtime import config_realtime_process, Priority, Ratekeeper
from openpilot.common.swaglog import cloudlog, ForwardingHandler

from opendbc.car import DT_CTRL, structs
from opendbc.car.can_definitions import CanData, CanRecvCallable, CanSendCallable
from opendbc.car.carlog import carlog
from opendbc.car.fw_versions import ObdCallback
from opendbc.car.car_helpers import get_car, interfaces
from opendbc.car.interfaces import CarInterfaceBase, RadarInterfaceBase
from openpilot.selfdrive.pandad import can_capnp_to_list, can_list_to_can_capnp
from openpilot.selfdrive.car.cruise import VCruiseHelper
from openpilot.selfdrive.car.helpers import convert_iq_car_control_compact, convert_to_capnp

from openpilot.iqpilot.aol.imahelper import apply_aol_experience_flags, apply_aol_brand_overrides
from openpilot.iqpilot.selfdrive.car import interfaces as iqpilot_interfaces

REPLAY = "REPLAY" in os.environ

EventName = log.OnroadEvent.EventName

# forward
carlog.addHandler(ForwardingHandler(cloudlog))


def obd_callback(params: Params) -> ObdCallback:
  def set_obd_multiplexing(obd_multiplexing: bool):
    if params.get_bool("ObdMultiplexingEnabled") != obd_multiplexing:
      cloudlog.warning(f"Setting OBD multiplexing to {obd_multiplexing}")
      params.remove("ObdMultiplexingChanged")
      params.put_bool("ObdMultiplexingEnabled", obd_multiplexing)
      params.get_bool("ObdMultiplexingChanged", block=True)
      cloudlog.warning("OBD multiplexing set successfully")
  return set_obd_multiplexing


def can_comm_callbacks(logcan: messaging.SubSocket, sendcan: messaging.PubSocket) -> tuple[CanRecvCallable, CanSendCallable]:
  def can_recv(wait_for_one: bool = False) -> list[list[CanData]]:
    """
    wait_for_one: wait the normal logcan socket timeout for a CAN packet, may return empty list if nothing comes

    Returns: CAN packets comprised of CanData objects for easy access
    """
    ret = []
    for can in messaging.drain_sock(logcan, wait_for_one=wait_for_one):
      ret.append([CanData(msg.address, msg.dat, msg.src) for msg in can.can])
    return ret

  def can_send(msgs: list[CanData]) -> None:
    sendcan.send(can_list_to_can_capnp(msgs, msgtype='sendcan'))

  return can_recv, can_send


def run_optional_pre_init(CI: CarInterfaceBase, CP: structs.CarParams, CP_IQ: structs.IQCarParams,
                          can_callbacks: tuple[CanRecvCallable, CanSendCallable]) -> None:
  pre_init = getattr(CI, "pre_init", None)
  if callable(pre_init):
    pre_init(CP, CP_IQ, *can_callbacks)


class Car:
  CI: CarInterfaceBase
  RI: RadarInterfaceBase
  CP: car.CarParams
  CP_IQ: structs.IQCarParams
  CP_IQ_capnp: custom.IQCarParams

  def __init__(self, CI=None, RI=None) -> None:
    self.can_sock = messaging.sub_sock('can', timeout=20)
    self.sm = messaging.SubMaster(['pandaStates', 'carControl', 'onroadEvents', 'testJoystick'] + ['iqCarControl', 'iqPlan'])
    self.pm = messaging.PubMaster(['sendcan', 'carState', 'carParams', 'carOutput', 'liveTracks'] + ['iqCarParams', 'iqCarState'])

    self.can_rcv_cum_timeout_counter = 0

    self.CC_prev = car.CarControl.new_message()
    self.CS_prev = car.CarState.new_message()
    self.CS_IQ_prev = custom.IQCarState.new_message()
    self.initialized_prev = False

    self.last_actuators_output = structs.CarControl.Actuators()

    self.params = Params()
    self.joystick_buttons_prev = [False, False]
    self.joystick_debug_mode = self.params.get_bool("JoystickDebugMode")

    self.can_callbacks = can_comm_callbacks(self.can_sock, self.pm.sock['sendcan'])

    is_release = self.params.get_bool("IsReleaseBranch")
    is_release_iq = self.params.get_bool("IsReleaseIqBranch")

    if CI is None:
      # wait for one pandaState and one CAN packet
      print("Waiting for CAN messages...")
      while True:
        can = messaging.recv_one_retry(self.can_sock)
        if len(can.can) > 0:
          break

      alpha_long_allowed = self.params.get_bool("AlphaLongitudinalEnabled")
      num_pandas = len(messaging.recv_one_retry(self.sm.sock['pandaStates']).pandaStates)

      cached_params = None
      cached_params_raw = self.params.get("CarParamsCache")
      if cached_params_raw is not None:
        with car.CarParams.from_bytes(cached_params_raw) as _cached_params:
          cached_params = _cached_params

      fixed_fingerprint = (self.params.get("CarPlatformBundle") or {}).get("platform", None)
      init_params_list_iq = iqpilot_interfaces.initialize_params(self.params)

      self.CI = get_car(*self.can_callbacks, obd_callback(self.params), alpha_long_allowed, is_release, num_pandas, cached_params,
                        fixed_fingerprint, init_params_list_iq, is_release_iq)
      iqpilot_interfaces.setup_interfaces(self.CI, self.params)
      self.RI = interfaces[self.CI.CP.carFingerprint].RadarInterface(self.CI.CP, self.CI.CP_IQ)
      self.CP = self.CI.CP
      self.CP_IQ = self.CI.CP_IQ

      # continue onto next fingerprinting step in pandad
      self.params.put_bool("FirmwareQueryDone", True)
    else:
      self.CI, self.CP, self.CP_IQ = CI, CI.CP, CI.CP_IQ
      self.RI = RI

    self.CP.alternativeExperience = 0
    # AOL
    apply_aol_experience_flags(self.CP, self.CP_IQ, self.params)
    apply_aol_brand_overrides(self.CP, self.CP_IQ, self.params)

    # IQ.Dynamic control mode
    self.iq_dynamic_mode = self.params.get_bool("IQDynamicMode")

    openpilot_enabled_toggle = self.params.get_bool("OpenpilotEnabledToggle")
    run_optional_pre_init(self.CI, self.CP, self.CP_IQ, self.can_callbacks)
    controller_available = self.CI.CC is not None and openpilot_enabled_toggle and not self.CP.dashcamOnly
    self.CP.passive = not controller_available or self.CP.dashcamOnly
    if self.CP.passive:
      safety_config = structs.CarParams.SafetyConfig()
      safety_config.safetyModel = structs.CarParams.SafetyModel.noOutput
      self.CP.safetyConfigs = [safety_config]

    if self.CP.secOcRequired:
      # Copy user key if available
      try:
        with open("/cache/params/SecOCKey") as f:
          user_key = f.readline().strip()
          if len(user_key) == 32:
            self.params.put("SecOCKey", user_key)
      except Exception:
        pass

      secoc_key = self.params.get("SecOCKey")
      if secoc_key is not None:
        saved_secoc_key = bytes.fromhex(secoc_key.strip())
        if len(saved_secoc_key) == 16:
          self.CP.secOcKeyAvailable = True
          self.CI.CS.secoc_key = saved_secoc_key
          if controller_available:
            self.CI.CC.secoc_key = saved_secoc_key
        else:
          cloudlog.warning("Saved SecOC key is invalid")

    # Write previous route's CarParams
    prev_cp = self.params.get("CarParamsPersistent")
    if prev_cp is not None:
      self.params.put("CarParamsPrevRoute", prev_cp)

    # Write CarParams for controls and radard
    cp_bytes = self.CP.to_bytes()
    self.params.put("CarParams", cp_bytes)
    self.params.put_nonblocking("CarParamsCache", cp_bytes)
    self.params.put_nonblocking("CarParamsPersistent", cp_bytes)

    self.CP_IQ_capnp = convert_to_capnp(self.CP_IQ)
    cp_IQ_bytes = self.CP_IQ_capnp.to_bytes()
    self.params.put("IQCarParams", cp_IQ_bytes)
    self.params.put_nonblocking("IQCarParamsCache", cp_IQ_bytes)
    self.params.put_nonblocking("IQCarParamsPersistent", cp_IQ_bytes)

    self.v_cruise_helper = VCruiseHelper(self.CP, self.CP_IQ)
    self._needs_iq_lead_data = self.CP.brand == "hyundai"

    self.is_metric = self.params.get_bool("IsMetric")
    self.experimental_mode = self.params.get_bool("ExperimentalMode")

    # card is driven by can recv, expected at 100Hz
    self.rk = Ratekeeper(100, print_delay_threshold=None)

    # log fingerprint in sentry
    iqpilot_interfaces.log_fingerprint(self.CP)

  def state_update(self) -> tuple[car.CarState, custom.IQCarState, structs.RadarDataT | None]:
    """carState update loop, driven by can"""

    can_strs = messaging.drain_sock_raw(self.can_sock, wait_for_one=True)
    can_list = can_capnp_to_list(can_strs)

    # Update carState from CAN
    CS, CS_IQ = self.CI.update(can_list)
    CS_IQ = convert_to_capnp(CS_IQ)

    # Update radar tracks from CAN
    RD: structs.RadarDataT | None = self.RI.update(can_list)

    self.sm.update(0)
    self.inject_joystick_buttons(CS)

    can_rcv_valid = len(can_strs) > 0

    # Check for CAN timeout
    if not can_rcv_valid:
      self.can_rcv_cum_timeout_counter += 1

    if can_rcv_valid and REPLAY:
      self.can_log_mono_time = messaging.log_from_bytes(can_strs[0]).logMonoTime

    if self.sm.updated['iqPlan']:
      self.v_cruise_helper.update_speed_limit_assist(self.is_metric, self.sm['iqPlan'])

    self.v_cruise_helper.update_v_cruise(CS, self.sm['carControl'].enabled, self.is_metric)
    if self.sm['carControl'].enabled and not self.CC_prev.enabled:
      # Use CarState w/ buttons from the step selfdrived enables on
      self.v_cruise_helper.initialize_v_cruise(self.CS_prev, self.experimental_mode, self.iq_dynamic_mode)

    # TODO: mirror the carState.cruiseState struct?
    CS.vCruise = float(self.v_cruise_helper.v_cruise_kph)
    CS.vCruiseCluster = float(self.v_cruise_helper.v_cruise_cluster_kph)

    return CS, CS_IQ, RD

  def state_publish(self, CS: car.CarState, CS_IQ: custom.IQCarState, RD: structs.RadarDataT | None):
    """carState and carParams publish loop"""

    # carParams - logged every 50 seconds (> 1 per segment)
    if self.sm.frame % int(50. / DT_CTRL) == 0:
      cp_send = messaging.new_message('carParams')
      cp_send.valid = True
      cp_send.carParams = self.CP
      self.pm.send('carParams', cp_send)

    # publish new carOutput
    co_send = messaging.new_message('carOutput')
    co_send.valid = self.sm.all_checks(['carControl'])
    co_send.carOutput.actuatorsOutput = self.last_actuators_output
    self.pm.send('carOutput', co_send)

    # kick off controlsd step while we actuate the latest carControl packet
    cs_send = messaging.new_message('carState')
    cs_send.valid = CS.canValid
    cs_send.carState = CS
    cs_send.carState.canErrorCounter = self.can_rcv_cum_timeout_counter
    cs_send.carState.cumLagMs = -self.rk.remaining * 1000.
    self.pm.send('carState', cs_send)

    if RD is not None:
      tracks_msg = messaging.new_message('liveTracks')
      tracks_msg.valid = not any(RD.errors.to_dict().values())
      tracks_msg.liveTracks = RD
      self.pm.send('liveTracks', tracks_msg)

    # iqCarParams - logged every 50 seconds (> 1 per segment)
    if self.sm.frame % int(50. / DT_CTRL) == 0:
      iq_cp_send = messaging.new_message('iqCarParams')
      iq_cp_send.valid = True
      iq_cp_send.iqCarParams = self.CP_IQ_capnp
      self.pm.send('iqCarParams', iq_cp_send)

    iq_cs_send = messaging.new_message('iqCarState')
    iq_cs_send.valid = CS.canValid
    iq_cs_send.iqCarState = CS_IQ
    self.pm.send('iqCarState', iq_cs_send)

  def controls_update(self, CS: car.CarState, CC: car.CarControl, CC_IQ: custom.IQCarControl):
    """control update loop, driven by carControl"""

    if not self.initialized_prev:
      # Initialize CarInterface, once controls are ready
      # TODO: this can make us miss at least a few cycles when doing an ECU knockout
      self.CI.init(self.CP, self.CP_IQ, *self.can_callbacks)
      # signal pandad to switch to car safety mode
      self.params.put_bool_nonblocking("ControlsReady", True)

    if self.sm.all_alive(['carControl']):
      # send car controls over can
      now_nanos = self.can_log_mono_time if REPLAY else int(time.monotonic() * 1e9)
      started = time.monotonic()
      cc_iq = convert_iq_car_control_compact(CC_IQ, include_leads=self._needs_iq_lead_data)
      convert_ms = (time.monotonic() - started) * 1000

      started = time.monotonic()
      self.last_actuators_output, can_sends = self.CI.apply(CC, cc_iq, now_nanos)
      apply_ms = (time.monotonic() - started) * 1000

      started = time.monotonic()
      self.pm.send('sendcan', can_list_to_can_capnp(can_sends, msgtype='sendcan', valid=CS.canValid))
      sendcan_ms = (time.monotonic() - started) * 1000

      controls_total_ms = convert_ms + apply_ms + sendcan_ms
      if controls_total_ms > 3.0 or apply_ms > 2.0 or sendcan_ms > 1.0:
        log_issue_limited(
          "card_controls_update_slow",
          "lag",
          f"card controls_update slow total_ms={controls_total_ms:.2f} convert_ms={convert_ms:.2f} "
          f"apply_ms={apply_ms:.2f} sendcan_ms={sendcan_ms:.2f} include_leads={self._needs_iq_lead_data}",
          interval_sec=1.0,
        )

      self.CC_prev = CC


  def step(self):
    started = time.monotonic()
    checkpoint = started

    CS, CS_IQ, RD = self.state_update()
    state_update_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    self.state_publish(CS, CS_IQ, RD)
    state_publish_ms = (time.monotonic() - checkpoint) * 1000
    checkpoint = time.monotonic()

    initialized = (not any(e.name == EventName.selfdriveInitializing for e in self.sm['onroadEvents']) and
                   self.sm.seen['onroadEvents'])
    if not self.CP.passive and initialized:
      self.controls_update(CS, self.sm['carControl'], self.sm['iqCarControl'])
    controls_update_ms = (time.monotonic() - checkpoint) * 1000

    self.initialized_prev = initialized
    self.CS_prev = CS
    self.CS_IQ_prev = CS_IQ

    total_ms = (time.monotonic() - started) * 1000
    if total_ms > 8.0 or state_update_ms > 4.0 or controls_update_ms > 3.0:
      log_issue_limited(
        "card_step_slow",
        "lag",
        f"card step slow total_ms={total_ms:.2f} state_update_ms={state_update_ms:.2f} "
        f"state_publish_ms={state_publish_ms:.2f} controls_update_ms={controls_update_ms:.2f}",
        interval_sec=1.0,
      )

  def inject_joystick_buttons(self, CS: car.CarState) -> None:
    if not self.joystick_debug_mode:
      self.joystick_buttons_prev = [False, False]
      return

    if self.sm.recv_frame['testJoystick'] == 0:
      self.joystick_buttons_prev = [False, False]
      return

    age_s = (self.sm.frame - self.sm.recv_frame['testJoystick']) * DT_CTRL
    buttons = list(getattr(self.sm['testJoystick'], 'buttons', []))
    current = [
      bool(buttons[0]) if len(buttons) > 0 else False,
      bool(buttons[1]) if len(buttons) > 1 else False,
    ]

    if age_s > 0.2:
      current = [False, False]

    engage = current[0] and not self.joystick_buttons_prev[0]
    disengage = current[1] and not self.joystick_buttons_prev[1]
    self.joystick_buttons_prev = current

    if engage:
      try:
        self.params.put("JoystickAolRequest", "enable")
      except UnknownKeyName:
        pass
    if disengage:
      try:
        self.params.put("JoystickAolRequest", "disable")
      except UnknownKeyName:
        pass

  def params_thread(self, evt):
    while not evt.is_set():
      self.is_metric = self.params.get_bool("IsMetric")
      self.experimental_mode = self.params.get_bool("ExperimentalMode") and self.CP.openpilotLongitudinalControl

      # iqpilot
      self.iq_dynamic_mode = self.params.get_bool("IQDynamicMode")
      self.joystick_debug_mode = self.params.get_bool("JoystickDebugMode")
      self.v_cruise_helper.read_custom_set_speed_params()

      time.sleep(0.1)

  def card_thread(self):
    e = threading.Event()
    t = threading.Thread(target=self.params_thread, args=(e, ))
    try:
      t.start()
      while True:
        self.step()
        self.rk.monitor_time()
    finally:
      e.set()
      t.join()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  car = Car()
  car.card_thread()


if __name__ == "__main__":
  main()
