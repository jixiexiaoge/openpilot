"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import numpy as np
from typing import NamedTuple
from collections.abc import Callable

from iqdbc.car import structs
from iqdbc.car.can_definitions import CanRecvCallable, CanSendCallable
from iqdbc.car.subaru.values import SubaruFlags
from iqdbc.iqpilot.car.subaru.values_ext import SubaruFlagsIQ, SubaruSafetyFlagsIQ
from iqdbc.iqpilot.car.tesla.values import TeslaFlagsIQ
from iqdbc.iqpilot.car.toyota.values import ToyotaFlagsIQ


class LatControlInputs(NamedTuple):
  lateral_acceleration: float
  roll_compensation: float
  vego: float
  aego: float


TorqueFromLateralAccelCallbackTypeTorqueSpace = Callable[[LatControlInputs, structs.CarParams.LateralTorqueTuning, bool], float]


class CarInterfaceBaseIQ:
  @staticmethod
  def torque_from_lateral_accel_linear_in_torque_space(latcontrol_inputs: LatControlInputs, torque_params: structs.CarParams.LateralTorqueTuning,
                                                        gravity_adjusted: bool) -> float:
    # The default is a linear relationship between torque and lateral acceleration (accounting for road roll and steering friction)
    return latcontrol_inputs.lateral_acceleration / float(torque_params.latAccelFactor)

  def torque_from_lateral_accel_in_torque_space(self) -> TorqueFromLateralAccelCallbackTypeTorqueSpace:
    return self.torque_from_lateral_accel_linear_in_torque_space


class NanoFFModel:
  def __init__(self, weights_loc: str, platform: str):
    self.weights_loc = weights_loc
    self.platform = platform
    self.load_weights(platform)

  def load_weights(self, platform: str):
    with open(self.weights_loc) as fob:
      self.weights = {k: np.array(v) for k, v in json.load(fob)[platform].items()}

  def relu(self, x: np.ndarray):
    return np.maximum(0.0, x)

  def forward(self, x: np.ndarray):
    assert x.ndim == 1
    x = (x - self.weights['input_norm_mat'][:, 0]) / (self.weights['input_norm_mat'][:, 1] - self.weights['input_norm_mat'][:, 0])
    x = self.relu(np.dot(x, self.weights['w_1']) + self.weights['b_1'])
    x = self.relu(np.dot(x, self.weights['w_2']) + self.weights['b_2'])
    x = self.relu(np.dot(x, self.weights['w_3']) + self.weights['b_3'])
    x = np.dot(x, self.weights['w_4']) + self.weights['b_4']
    return x

  def predict(self, x: list[float], do_sample: bool = False):
    x = self.forward(np.array(x))
    if do_sample:
      pred = np.random.laplace(x[0], np.exp(x[1]) / self.weights['temperature'])
    else:
      pred = x[0]
    pred = pred * (self.weights['output_norm_mat'][1] - self.weights['output_norm_mat'][0]) + self.weights['output_norm_mat'][0]
    return pred


def setup_interfaces(CI, CP: structs.CarParams, CP_IQ: structs.IQCarParams,
                     params_list: list[dict[str, str]] | None = None,
                     can_recv: CanRecvCallable | None = None, can_send: CanSendCallable | None = None) -> None:
  if params_list is None:
    params_list = []

  params_dict = {k: v for param in params_list for k, v in param.items()}

  _initialize_custom_longitudinal_tuning(CI, CP, CP_IQ, params_dict)
  _initialize_coop_steering(CP, CP_IQ, params_dict)
  _initialize_stop_and_go(CP, CP_IQ, params_dict)
  _initialize_toyota(CP, CP_IQ, params_dict)


def _initialize_custom_longitudinal_tuning(CI, CP: structs.CarParams, CP_IQ: structs.IQCarParams,
                                           params_dict: dict[str, str]) -> None:

  _ = CI.get_longitudinal_tuning_iq(CP, CP_IQ)


def _initialize_coop_steering(CP: structs.CarParams, CP_IQ: structs.IQCarParams,
                              params_dict: dict[str, str]) -> None:
  if CP.brand == 'tesla':
    coop_steering = int(params_dict.get("TeslaCoopSteering", 0)) == 1
    if coop_steering:
      CP_IQ.flags |= TeslaFlagsIQ.COOP_STEERING.value


def _initialize_stop_and_go(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params_dict: dict[str, str]) -> None:
  if CP.brand == 'subaru' and not CP.flags & (SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID):
    stop_and_go = int(params_dict.get("SubaruStopAndGo", 0)) == 1
    stop_and_go_manual_parking_brake = int(params_dict.get("SubaruStopAndGoManualParkingBrake", 0)) == 1

    if stop_and_go:
      CP_IQ.flags |= SubaruFlagsIQ.STOP_AND_GO.value
    if stop_and_go_manual_parking_brake:
      CP_IQ.flags |= SubaruFlagsIQ.STOP_AND_GO_MANUAL_PARKING_BRAKE.value
    if stop_and_go or stop_and_go_manual_parking_brake:
      CP_IQ.safetyParam |= SubaruSafetyFlagsIQ.STOP_AND_GO


def _initialize_toyota(CP: structs.CarParams, CP_IQ: structs.IQCarParams, params_dict: dict[str, str]) -> None:
  if CP.brand == 'toyota':
    toyota_stock_long = int(params_dict.get("ToyotaEnforceStockLongitudinal", 0)) == 1
    toyota_sng_hack = int(params_dict.get("ToyotaSnGHack", 0)) == 1

    if toyota_stock_long:
      CP_IQ.flags |= ToyotaFlagsIQ.STOCK_LONGITUDINAL.value

    if toyota_sng_hack:
      CP_IQ.flags |= ToyotaFlagsIQ.STOP_AND_GO_HACK.value
      CP.minEnableSpeed = -1.
      CP.autoResumeSng = CP.openpilotLongitudinalControl
