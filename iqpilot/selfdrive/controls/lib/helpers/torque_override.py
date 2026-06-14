"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import numpy as np
import cereal.messaging as messaging
from cereal import custom

from openpilot.common.params import Params

TURN_NUDGE_TORQUE = 0.8
EXIT_NUDGE_TORQUE = 0.6
TURN_PULSE_FRAMES = 50
EXIT_PULSE_FRAMES = 75
IQP_NAV_TORQUE_INFLUENCE_ENABLED = False


class LatControlTorqueExtOverride:
  _SYNC_PERIOD = 300

  def __init__(self, lac_torque, CP):
    self._controller = lac_torque
    self._profile = CP
    self._store = Params()
    self._nav_sm = messaging.SubMaster(["iqNavState"], poll="iqNavState")
    self._toggles = {
      "enforce": False,
      "override": False,
    }
    self._tick = -1
    self._nav_key = ""
    self._nav_pulse_sign = 0.0
    self._nav_pulse_value = 0.0
    self._nav_pulse_frames = 0
    self._sync_toggle_bits()

  def _sync_toggle_bits(self) -> None:
    self._toggles["enforce"] = self._store.get_bool("EnforceTorqueControl")
    self._toggles["override"] = self._store.get_bool("TorqueParamsOverrideEnabled")

  @staticmethod
  def _safe_float(raw_value, fallback: float) -> float:
    try:
      return float(raw_value)
    except (TypeError, ValueError):
      return fallback

  def _poll_now(self) -> bool:
    self._tick += 1
    return (self._tick % self._SYNC_PERIOD) == 0

  def _override_allowed(self) -> bool:
    return self._toggles["enforce"] and self._toggles["override"]

  def update_override_torque_params(self, torque_params) -> bool:
    if not self._poll_now():
      return False

    self._sync_toggle_bits()
    if not self._override_allowed():
      return False

    lat_factor_raw = self._store.get("TorqueParamsOverrideLatAccelFactor", return_default=True)
    friction_raw = self._store.get("TorqueParamsOverrideFriction", return_default=True)
    torque_params.latAccelFactor = self._safe_float(lat_factor_raw, torque_params.latAccelFactor)
    torque_params.friction = self._safe_float(friction_raw, torque_params.friction)
    return True

  def _get_nav_pulse(self):
    if not IQP_NAV_TORQUE_INFLUENCE_ENABLED:
      return "", 0.0, 0

    self._nav_sm.update(0)
    nav_state = self._nav_sm["iqNavState"]
    phase = getattr(nav_state, "maneuverPhase", custom.IQNavState.ManeuverPhase.none)
    maneuver_direction = getattr(nav_state, "maneuverDirection", custom.NavDirection.none)

    if phase == custom.IQNavState.ManeuverPhase.turnActive:
      direction = getattr(nav_state, "turnDesireDirection", 0)
      key = f"turn-phase:{direction}"
      return key, -TURN_NUDGE_TORQUE if direction == 1 else TURN_NUDGE_TORQUE, TURN_PULSE_FRAMES

    if phase == custom.IQNavState.ManeuverPhase.highwayCommit and maneuver_direction in (custom.NavDirection.left, custom.NavDirection.right):
      direction = getattr(nav_state, "lanePositioningDirection", 0)
      key = f"highway-phase:{direction}"
      return key, -EXIT_NUDGE_TORQUE if direction == 1 else EXIT_NUDGE_TORQUE, EXIT_PULSE_FRAMES

    if getattr(nav_state, "shouldSendTurnDesire", False):
      direction = getattr(nav_state, "turnDesireDirection", 0)
      key = f"turn:{direction}"
      return key, -TURN_NUDGE_TORQUE if direction == 1 else TURN_NUDGE_TORQUE, TURN_PULSE_FRAMES

    if getattr(nav_state, "shouldSendLanePositioning", False):
      direction = getattr(nav_state, "lanePositioningDirection", 0)
      key = f"keep:{direction}"
      return key, -EXIT_NUDGE_TORQUE if direction == 1 else EXIT_NUDGE_TORQUE, EXIT_PULSE_FRAMES

    return "", 0.0, 0

  def update_nav_torque_nudge(self, active: bool, car_state, output_torque: float) -> float:
    if not IQP_NAV_TORQUE_INFLUENCE_ENABLED:
      self._nav_pulse_frames = 0
      self._nav_key = ""
      return output_torque

    nav_key, pulse_sign, pulse_frames = self._get_nav_pulse()

    if not active or getattr(car_state, "steeringPressed", False):
      self._nav_pulse_frames = 0
      if not nav_key:
        self._nav_key = ""
      return output_torque

    if nav_key and nav_key != self._nav_key:
      self._nav_key = nav_key
      self._nav_pulse_sign = pulse_sign
      self._nav_pulse_value = abs(pulse_sign)
      self._nav_pulse_frames = pulse_frames
    elif not nav_key and self._nav_pulse_frames == 0:
      self._nav_key = ""

    if self._nav_pulse_frames > 0:
      self._nav_pulse_frames -= 1
      steer_max = float(getattr(self._controller, "steer_max", 1.0))
      output_torque = float(np.clip(output_torque + self._nav_pulse_sign, -steer_max, steer_max))

    return output_torque

  @property
  def CP(self):
    return self._profile

  @CP.setter
  def CP(self, payload):
    self._profile = payload

  @property
  def params(self):
    return self._store

  @params.setter
  def params(self, payload):
    self._store = payload

  @property
  def enforce_torque_control_toggle(self):
    return self._toggles["enforce"]

  @enforce_torque_control_toggle.setter
  def enforce_torque_control_toggle(self, payload):
    self._toggles["enforce"] = bool(payload)

  @property
  def torque_override_enabled(self):
    return self._toggles["override"]

  @torque_override_enabled.setter
  def torque_override_enabled(self, payload):
    self._toggles["override"] = bool(payload)

  @property
  def frame(self):
    return self._tick

  @frame.setter
  def frame(self, payload):
    self._tick = int(payload)
