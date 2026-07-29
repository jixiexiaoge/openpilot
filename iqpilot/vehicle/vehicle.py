"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from cereal import log
from iqdbc.car import structs
from iqdbc.car.chrysler.values import RAM_DT
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents

_E = log.OnroadEvent.EventName
_GEAR = structs.CarState.GearShifter

# RAM_DT trucks with an enable floor at/above this need the gear-gated steer-floor latch
_RAM_STEER_FLOOR_MS = 14.5


class VehicleEvents:
  """Brand-specific corrections layered onto the generic onroad event set.

  openpilot's shared event path doesn't cover a couple of platform quirks: RAM_DT owns its
  own low-speed steering floor, and a gas-interceptor Toyota can creep off a stop without the
  stock resume prompt. Each supported brand gets a small handler that edits the live event set.
  """

  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ
    self._steer_floor_held = False

  def update(self, CS: structs.CarState, events: Events) -> IQEvents:
    handler = self._BRAND_HANDLERS.get(self.CP.brand)
    if handler is not None:
      handler(self, CS, events)
    return IQEvents()

  def _ram_steer_floor(self, CS: structs.CarState, events: Events) -> None:
    if self.CP.carFingerprint in RAM_DT:
      # RAM_DT drives its own steer floor, so drop openpilot's generic alert and latch ours instead.
      # Two independent gates on purpose: clearing above the enable floor, then re-latching when
      # parked out of Drive — the latch wins when both hold at once.
      events.remove(_E.belowSteerSpeed)
      if CS.vEgo >= self.CP.minEnableSpeed:
        self._steer_floor_held = False
      if self.CP.minEnableSpeed >= _RAM_STEER_FLOOR_MS and CS.gearShifter != _GEAR.drive:
        self._steer_floor_held = True
    if self._steer_floor_held:
      events.add(_E.belowSteerSpeed)

  def _toyota_interceptor_resume(self, CS: structs.CarState, events: Events) -> None:
    if not self.CP.openpilotLongitudinalControl:
      return
    stopped_and_coasting = CS.cruiseState.standstill and not CS.brakePressed
    if stopped_and_coasting and self.CP_IQ.enableGasInterceptor:
      events.remove(_E.resumeRequired)

  _BRAND_HANDLERS = {
    'chrysler': _ram_steer_floor,
    'toyota': _toyota_interceptor_resume,
  }
