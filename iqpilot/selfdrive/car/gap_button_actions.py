"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Maps the distance/gap steering-wheel button to an IQ.Pilot action: holding it for
long enough toggles Experimental mode exactly once per hold. Only active when
IQ.Pilot owns longitudinal control and cruise is available.
"""
from cereal import car, custom
from iqdbc.car import structs
from openpilot.common.params import Params

_Button = car.CarState.ButtonEvent.Type
_IQEvent = custom.IQOnroadEvent.EventName
_GAP_BUTTON = _Button.gapAdjustCruise

HOLD_FRAMES_TO_TOGGLE = 50


class GapButtonActions:
  def __init__(self, CP: structs.CarParams):
    self._CP = CP
    self._params = Params()
    self._gap_hold_frames = 0
    self._already_toggled = False
    # read (and cleared) by the personality-decrement handler in selfdrived so a
    # release that ends a toggle-hold does not also decrement personality
    self.experimental_mode_switched = False

  def update(self, CS, events, experimental_mode) -> None:
    if not (self._CP.openpilotLongitudinalControl and CS.cruiseState.available):
      return
    self._advance_hold(CS)
    self._toggle_experimental_on_long_hold(events, experimental_mode)

  def _advance_hold(self, CS) -> None:
    # once counting, keep incrementing each frame the hold persists
    if self._gap_hold_frames > 0:
      self._gap_hold_frames += 1
    # a fresh press seeds the counter; a release zeroes it
    for be in CS.buttonEvents:
      if be.type.raw == _GAP_BUTTON:
        self._gap_hold_frames = int(be.pressed)
        if not be.pressed:
          self._already_toggled = False

  def _toggle_experimental_on_long_hold(self, events, experimental_mode) -> None:
    if self._already_toggled or self._gap_hold_frames < HOLD_FRAMES_TO_TOGGLE:
      return
    self._params.put_bool_nonblocking("ExperimentalMode", not experimental_mode)
    events.add(_IQEvent.experimentalToggled)
    self._already_toggled = True
    self.experimental_mode_switched = True
