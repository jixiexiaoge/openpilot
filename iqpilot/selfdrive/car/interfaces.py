"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from iqdbc.car import structs as _dbc
from openpilot.common.params import Params as _Store
from openpilot.common.swaglog import cloudlog as _log
from openpilot.selfdrive.controls.lib.latcontrol_torque import get_nn_model_path as _resolve_nn

import openpilot.system.sentry as _telemetry

_ANGLE = _dbc.CarParams.SteerControlType.angle

# Port tunables surfaced to the fingerprint step, flat so the read is one pass.
_TUNABLES = (
  "HyundaiLongitudinalTuning",
  "SubaruStopAndGo",
  "SubaruStopAndGoManualParkingBrake",
  "TeslaCoopSteering",
  "ToyotaEnforceStockLongitudinal",
  "ToyotaSnGHack",
)


def initialize_params(store):
  return [{name: store.get(name, return_default=True)} for name in _TUNABLES]


def log_fingerprint(cp) -> None:
  ident = cp.carFingerprint
  if ident == "MOCK":
    _telemetry.capture_fingerprint_mock()
  else:
    _telemetry.capture_fingerprint(ident, cp.brand)


def set_speed_limit_controller_availability(cp, cp_iq, store=None) -> bool:
  """Gate the speed-limit controller off on platforms that can't run it, dropping a
  stuck 'control' mode down to 'warning'."""
  store = store or _Store()
  brand = cp.brand
  off = (brand == "rivian"
         or (brand == "tesla" and store.get_bool("IsReleaseIqBranch"))
         or (not cp.openpilotLongitudinalControl and cp_iq.pcmCruiseSpeed))
  if off and store.get("IQSpeedAssistMode", return_default=True) == 3:  # control -> warning
    store.put("IQSpeedAssistMode", 2)
  return not off


def _stamp_lateral_model(cp, cp_iq, store) -> bool:
  where, label, precise = _resolve_nn(cp)
  nn = cp_iq.iqLateralNet
  nn.model.path, nn.model.name, nn.fuzzyFingerprint = where, label, not precise
  if label == "MOCK":
    _log.error({"nnff event": "car doesn't match any Neural Network model"})
    return False
  return cp.steerControlType != _ANGLE and store.get_bool("NeuralNetworkFeedForward")


def _cleanup_unsupported_params(cp, cp_iq, store=None) -> None:
  store = store or _Store()
  doomed = {
    "NeuralNetworkFeedForward": cp.steerControlType == _ANGLE,
    "LongIncrementsEnabled": not cp.openpilotLongitudinalControl and cp_iq.pcmCruiseSpeed,
  }
  for name, gone in doomed.items():
    if gone:
      _log.warning(f"unsupported on this port, clearing {name}")
      store.remove(name)
  set_speed_limit_controller_availability(cp, cp_iq, store)


def setup_interfaces(ci, store=None) -> None:
  store = store or _Store()
  if _stamp_lateral_model(ci.CP, ci.CP_IQ, store):
    ci.configure_torque_tune(ci.CP.carFingerprint, ci.CP.lateralTuning)
  _cleanup_unsupported_params(ci.CP, ci.CP_IQ, store)
