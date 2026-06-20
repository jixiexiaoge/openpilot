"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from cereal import log, custom
from opendbc.car import structs

from opendbc.car.chrysler.values import RAM_DT
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.iqpilot.selfdrive.selfdrived.events import IQEvents

EventName = log.OnroadEvent.EventName
EventNameIQ = custom.IQOnroadEvent.EventName
GearShifter = structs.CarState.GearShifter


class CarSpecificIQEvents:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.CP = CP
    self.CP_IQ = CP_IQ

    self.low_speed_alert = False

  def update(self, CS: structs.CarState, events: Events):
    events_iq = IQEvents()

    if self.CP.brand == 'chrysler':
      if self.CP.carFingerprint in RAM_DT:
        # remove belowSteerSpeed event from CarSpecificEvents as RAM_DT uses a different logic
        if events.has(EventName.belowSteerSpeed):
          events.remove(EventName.belowSteerSpeed)

        # TODO-IQ: use if/elif to have the gear shifter condition takes precedence over the speed condition
        # TODO-IQ: add 1 m/s hysteresis
        if CS.vEgo >= self.CP.minEnableSpeed:
          self.low_speed_alert = False
        if self.CP.minEnableSpeed >= 14.5 and CS.gearShifter != GearShifter.drive:
          self.low_speed_alert = True
      if self.low_speed_alert:
        events.add(EventName.belowSteerSpeed)

    elif self.CP.brand == 'toyota':
      if self.CP.openpilotLongitudinalControl:
        if CS.cruiseState.standstill and not CS.brakePressed and self.CP_IQ.enableGasInterceptor:
          if events.has(EventName.resumeRequired):
            events.remove(EventName.resumeRequired)

    return events_iq
