"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

GM torque-space feed-forward for the IQ.Pilot lateral extension: a sigmoid+linear
lat-accel -> torque curve for the tuned platforms, else the linear default.
"""
from math import exp

from iqdbc.car import structs
from iqdbc.car.gm.interface import CAR
from iqdbc.lvbs.car.interfaces import LatControlInputs, TorqueFromLateralAccelCallbackTypeTorqueSpace

_NON_LINEAR_TORQUE_PARAMS = {
  CAR.CHEVROLET_BOLT_EUV: [2.6531724862969748, 1.0, 0.1919764879840985, 0.009054123646805178],
  CAR.GMC_ACADIA: [4.78003305, 1.0, 0.3122, 0.05591772],
  CAR.CHEVROLET_SILVERADO: [3.29974374, 1.0, 0.25571356, 0.0465122],
}


class IQCarInterface:
  def __init__(self, CP: structs.CarParams, CI_Base):
    self.CP = CP
    self.CI_Base = CI_Base

  @staticmethod
  def _centered_sigmoid(val: float) -> float:
    # sigmoid shifted to pass through the origin; branch keeps exp() from overflowing
    if val >= 0:
      return 1.0 / (1.0 + exp(-val)) - 0.5
    z = exp(val)
    return z / (1.0 + z) - 0.5

  def torque_from_lateral_accel_siglin(self, latcontrol_inputs: LatControlInputs,
                                       torque_params: structs.CarParams.LateralTorqueTuning,
                                       gravity_adjusted: bool) -> float:
    a, b, c, _ = _NON_LINEAR_TORQUE_PARAMS[self.CP.carFingerprint]
    lat_accel = latcontrol_inputs.lateral_acceleration
    return float(self._centered_sigmoid(lat_accel * a) * b + lat_accel * c)

  def torque_from_lateral_accel_in_torque_space(self) -> TorqueFromLateralAccelCallbackTypeTorqueSpace:
    if self.CP.carFingerprint in _NON_LINEAR_TORQUE_PARAMS:
      return self.torque_from_lateral_accel_siglin
    return self.CI_Base.torque_from_lateral_accel_linear_in_torque_space
