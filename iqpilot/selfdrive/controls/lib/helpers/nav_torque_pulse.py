"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Short, decaying steering-torque nudges that lean the car through navigation
turns and highway exits. This is a lateral-control add-on driven by iqNavState;
it is independent of the feed-forward model and is off by default.
"""
import numpy as np
import cereal.messaging as messaging
from cereal import custom

TURN_NUDGE_TORQUE = 0.8
EXIT_NUDGE_TORQUE = 0.6
TURN_PULSE_FRAMES = 50
EXIT_PULSE_FRAMES = 75

# Master switch — nav torque influence is experimental and shipped off.
IQP_NAV_TORQUE_INFLUENCE_ENABLED = False

_LEFT = 1   # turnDesireDirection / lanePositioningDirection: 1 == left


class NavTorquePulseBrain:
  def __init__(self, lac_torque):
    self._controller = lac_torque
    self._nav_sm = messaging.SubMaster(["iqNavState"], poll="iqNavState")
    self._nav_key = ""
    self._nav_pulse_sign = 0.0
    self._nav_pulse_frames = 0

  def _lookup_nav_pulse(self):
    if not IQP_NAV_TORQUE_INFLUENCE_ENABLED:
      return "", 0.0, 0

    self._nav_sm.update(0)
    nav_state = self._nav_sm["iqNavState"]
    phase = getattr(nav_state, "maneuverPhase", custom.IQNavState.ManeuverPhase.none)
    maneuver_direction = getattr(nav_state, "maneuverDirection", custom.NavDirection.none)

    # left nudges negative, otherwise positive
    def turn(tag, direction):
      return f"turn{tag}:{direction}", -TURN_NUDGE_TORQUE if direction == _LEFT else TURN_NUDGE_TORQUE, TURN_PULSE_FRAMES

    def keep(tag, direction):
      return f"{tag}:{direction}", -EXIT_NUDGE_TORQUE if direction == _LEFT else EXIT_NUDGE_TORQUE, EXIT_PULSE_FRAMES

    if phase == custom.IQNavState.ManeuverPhase.turnActive:
      return turn("-phase", getattr(nav_state, "turnDesireDirection", 0))
    if phase == custom.IQNavState.ManeuverPhase.highwayCommit and maneuver_direction in (custom.NavDirection.left, custom.NavDirection.right):
      return keep("highway-phase", getattr(nav_state, "lanePositioningDirection", 0))
    if getattr(nav_state, "shouldSendTurnDesire", False):
      return turn("", getattr(nav_state, "turnDesireDirection", 0))
    if getattr(nav_state, "shouldSendLanePositioning", False):
      return keep("keep", getattr(nav_state, "lanePositioningDirection", 0))
    return "", 0.0, 0

  def nudge_output_torque(self, active: bool, car_state, output_torque: float) -> float:
    if not IQP_NAV_TORQUE_INFLUENCE_ENABLED:
      self._nav_pulse_frames = 0
      self._nav_key = ""
      return output_torque

    nav_key, pulse_sign, pulse_frames = self._lookup_nav_pulse()

    if not active or getattr(car_state, "steeringPressed", False):
      self._nav_pulse_frames = 0
      if not nav_key:
        self._nav_key = ""
      return output_torque

    if nav_key and nav_key != self._nav_key:
      self._nav_key = nav_key
      self._nav_pulse_sign = pulse_sign
      self._nav_pulse_frames = pulse_frames
    elif not nav_key and self._nav_pulse_frames == 0:
      self._nav_key = ""

    if self._nav_pulse_frames > 0:
      self._nav_pulse_frames -= 1
      steer_max = float(getattr(self._controller, "steer_max", 1.0))
      output_torque = float(np.clip(output_torque + self._nav_pulse_sign, -steer_max, steer_max))

    return output_torque
