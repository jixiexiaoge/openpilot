"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from typing import Any

from opendbc.car import structs
from opendbc.car.interfaces import CarInterfaceBase
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot.selfdrive.controls.lib.neural_network_feed_forward.locator import get_nn_model_path
from openpilot.iqpilot.selfdrive.controls.lib.speed_limit.helpers import set_speed_limit_controller_availability

import openpilot.system.sentry as sentry


def log_fingerprint(CP: structs.CarParams) -> None:
  if CP.carFingerprint == "MOCK":
    sentry.capture_fingerprint_mock()
  else:
    sentry.capture_fingerprint(CP.carFingerprint, CP.brand)


def _enforce_torque_lateral_control(CP: structs.CarParams, params: Params = None, enabled: bool = False) -> bool:
  if params is None:
    params = Params()

  if CP.steerControlType != structs.CarParams.SteerControlType.angle:
    enabled = params.get_bool("EnforceTorqueControl")

  return enabled


def _initialize_neural_network_feed_forward(CP: structs.CarParams, CP_IQ: structs.IQCarParams,
                                            params: Params = None, enabled: bool = False) -> bool:
  if params is None:
    params = Params()

  nnff_model_path, nnff_model_name, exact_match = get_nn_model_path(CP)

  if nnff_model_name == "MOCK":
    cloudlog.error({"nnff event": "car doesn't match any Neural Network model"})

  if nnff_model_name != "MOCK" and CP.steerControlType != structs.CarParams.SteerControlType.angle:
    enabled = params.get_bool("NeuralNetworkFeedForward")

  CP_IQ.neuralNetworkFeedForward.model.path = nnff_model_path
  CP_IQ.neuralNetworkFeedForward.model.name = nnff_model_name
  CP_IQ.neuralNetworkFeedForward.fuzzyFingerprint = not exact_match

  return enabled


def _initialize_torque_lateral_control(CI: CarInterfaceBase, CP: structs.CarParams, enforce_torque: bool, nnff_enabled: bool) -> None:
  if nnff_enabled or enforce_torque:
    CI.configure_torque_tune(CP.carFingerprint, CP.lateralTuning)


def _cleanup_unsupported_params(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params: Params = None) -> None:
  if params is None:
    params = Params()

  if CP.steerControlType == structs.CarParams.SteerControlType.angle:
    cloudlog.warning("SteerControlType is angle, cleaning up params")
    params.remove("NeuralNetworkFeedForward")
    params.remove("EnforceTorqueControl")

  if not CP.openpilotLongitudinalControl and CP_IQ.pcmCruiseSpeed:
    cloudlog.warning("openpilot Longitudinal Control not available, cleaning up params")
    params.remove("CustomAccIncrementsEnabled")

  set_speed_limit_controller_availability(CP, CP_IQ, params)


def setup_interfaces(CI: CarInterfaceBase, params: Params = None) -> None:
  CP = CI.CP
  CP_IQ = CI.CP_IQ

  enforce_torque = _enforce_torque_lateral_control(CP, params)
  nnff_enabled = _initialize_neural_network_feed_forward(CP, CP_IQ, params)
  _initialize_torque_lateral_control(CI, CP, enforce_torque, nnff_enabled)
  _cleanup_unsupported_params(CP, CP_IQ, params)


def initialize_params(params) -> list[dict[str, Any]]:
  keys: list = []

  # hyundai
  keys.extend([
    "HyundaiLongitudinalTuning",
  ])

  # subaru
  keys.extend([
    "SubaruStopAndGo",
    "SubaruStopAndGoManualParkingBrake",
  ])

  # tesla
  keys.extend([
    "TeslaCoopSteering",
  ])

  # toyota
  keys.extend([
    "ToyotaEnforceStockLongitudinal",
    "ToyotaSnGHack",
  ])

  return [{k: params.get(k, return_default=True)} for k in keys]
