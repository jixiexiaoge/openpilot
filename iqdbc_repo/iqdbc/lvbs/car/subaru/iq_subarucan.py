"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Camera-bus message spoofers for Subaru stop-and-go: re-emit the stock Throttle
and Brake_Pedal frames, nudging a single field to trigger an ACC resume from a
standstill. Field sets mirror the DBC message layout.
"""
from iqdbc.car.subaru.values import CanBus, SubaruFlags

_THROTTLE_FIELDS_PREGLOBAL = ("Throttle_Pedal", "Signal1", "Not_Full_Throttle", "Signal2", "Engine_RPM",
                              "Off_Throttle", "Signal3", "Throttle_Cruise", "Throttle_Combo", "Throttle_Body",
                              "Off_Throttle_2", "Signal4")
_THROTTLE_FIELDS_GLOBAL = ("CHECKSUM", "Signal1", "Engine_RPM", "Neutral", "Throttle_Pedal", "Throttle_Cruise",
                           "Throttle_Combo", "Signal3", "Off_Accel")
_BRAKE_FIELDS_PREGLOBAL = ("Speed", "Brake_Pedal", "Signal1")
_BRAKE_FIELDS_GLOBAL = ("CHECKSUM", "Signal1", "Speed", "Signal2", "Brake_Lights", "Signal3", "Brake_Pedal", "Signal4")


def _next_counter(msg):
  return (msg["COUNTER"] + 1) % 0x10


def create_throttle(packer, CP, throttle_msg, send_resume):
  preglobal = bool(CP.flags & SubaruFlags.PREGLOBAL)
  fields = _THROTTLE_FIELDS_PREGLOBAL if preglobal else _THROTTLE_FIELDS_GLOBAL
  values = {name: throttle_msg[name] for name in fields}
  values["COUNTER"] = _next_counter(throttle_msg)
  if send_resume:
    values["Throttle_Pedal"] = 5
  return packer.make_can_msg("Throttle", CanBus.camera, values)


def create_brake_pedal(packer, CP, brake_pedal_msg, send_resume):
  preglobal = bool(CP.flags & SubaruFlags.PREGLOBAL)
  fields = _BRAKE_FIELDS_PREGLOBAL if preglobal else _BRAKE_FIELDS_GLOBAL
  values = {name: brake_pedal_msg[name] for name in fields}
  if not preglobal:
    values["COUNTER"] = _next_counter(brake_pedal_msg)
  if send_resume:
    values["Speed"] = 1 if preglobal else 3
  return packer.make_can_msg("Brake_Pedal", CanBus.camera, values)
