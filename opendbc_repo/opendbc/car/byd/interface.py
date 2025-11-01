#!/usr/bin/env python3
import os
from math import fabs, exp

from opendbc.car import get_safety_config, get_friction, structs
from opendbc.car.common.conversions import Conversions as CV
from openpilot.common.params import Params
from opendbc.car.byd.carcontroller import CarController
from opendbc.car.byd.carstate import CarState
from opendbc.car.byd.radar_interface import RadarInterface
from opendbc.car.interfaces import CarInterfaceBase, TorqueFromLateralAccelCallbackType, FRICTION_THRESHOLD, LatControlInputs, NanoFFModel
from opendbc.car.byd.values import CanBus, BydFlags, BydSafetyFlags, MPC_ACC_CAR, TORQUE_LAT_CAR, EXP_LONG_CAR, PT_RADAR_CAR, RADAR_CAR,\
                PLATFORM_TANG_DMI, PLATFORM_SONG_PLUS_DMI, PLATFORM_QIN_PLUS_DMI, PLATFORM_YUAN_PLUS_DMI_ATTO3, PLATFORM_SEAL, PLATFORM_HAN_DMI
from opendbc.car.byd.tuning import Tuning

ButtonType = structs.CarState.ButtonEvent.Type
GearShifter = structs.CarState.GearShifter
TransmissionType = structs.CarParams.TransmissionType
NetworkLocation = structs.CarParams.NetworkLocation

class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  def torque_from_lateral_accel_siglin(self, latcontrol_inputs: LatControlInputs, torque_params: structs.CarParams.LateralTorqueTuning,
                    lateral_accel_error: float, lateral_accel_deadzone: float, friction_compensation: bool, gravity_adjusted: bool) -> float:
    friction = get_friction(lateral_accel_error, lateral_accel_deadzone, FRICTION_THRESHOLD, torque_params, friction_compensation)

    def sig(val):
      # https://timvieira.github.io/blog/post/2014/02/11/exp-normalize-trick
      if val >= 0:
        return 1 / (1 + exp(-val)) - 0.5
      else:
        z = exp(val)
        return z / (1 + z) - 0.5

    # The "lat_accel vs torque" relationship is assumed to be the sum of "sigmoid + linear" curves
    # An important thing to consider is that the slope at 0 should be > 0 (ideally >1)
    # This has big effect on the stability about 0 (noise when going straight)
    #non_linear_torque_params = NON_LINEAR_TORQUE_PARAMS.get(self.CP.carFingerprint)
    #assert non_linear_torque_params, "The params are not defined"
    a, b, c = Tuning.LAT_SIGLIN_TABLE
    steer_torque = (sig(latcontrol_inputs.lateral_acceleration * a) * b) + (latcontrol_inputs.lateral_acceleration * c)
    return float(steer_torque / torque_params.latAccelFactor + friction)

  def torque_from_lateral_accel(self) -> TorqueFromLateralAccelCallbackType:
    if Params().get_bool("BydLatUseSiglin"):
      return self.torque_from_lateral_accel_siglin
    else:
      return self.torque_from_lateral_accel_linear

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "byd"

    if Params().get_bool("UseRedPanda"):
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.noOutput),get_safety_config(structs.CarParams.SafetyModel.byd)]
    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.byd)]

    ret.dashcamOnly = False

    radar_car = candidate in (PT_RADAR_CAR | RADAR_CAR)
    ret.radarUnavailable = not radar_car

    ret.enableBsm = 0x418 in fingerprint[CanBus.ESC]
    ret.transmissionType = TransmissionType.direct

    valid_safety_index = 1 if Params().get_bool("UseRedPanda") else 0
    if candidate in PLATFORM_TANG_DMI:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.TANG_DMI.value

    elif candidate in PLATFORM_HAN_DMI:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.HAN_DMI.value
      ret.flags |= BydFlags.CANFD.value

    elif candidate in PLATFORM_SONG_PLUS_DMI:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.SONG_PLUS_DMI.value

    elif candidate in PLATFORM_QIN_PLUS_DMI:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.QIN_PLUS_DMI.value

    elif candidate in PLATFORM_YUAN_PLUS_DMI_ATTO3:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.YUAN_PLUS_DMI_ATTO3.value

    elif candidate in PLATFORM_SEAL:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.SEAL.value
      ret.flags |= BydFlags.CANFD.value

    else: #汉dm，唐dm，宋Pro
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.HAN_TANG_DMEV.value

    if candidate in MPC_ACC_CAR:
      ret.networkLocation = NetworkLocation.fwdCamera

    if candidate in TORQUE_LAT_CAR:
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    else:
      ret.steerControlType = structs.CarParams.SteerControlType.angle
      ret.flags |= BydFlags.ANGLE_CONTROL.value

    ret.openpilotLongitudinalControl = candidate in EXP_LONG_CAR

    ret.pcmCruise = Params().get_bool("BydModifiedStockLong")

    ret.longitudinalTuning.kpBP, ret.longitudinalTuning.kiBP = [[0.],  [0.]]
    ret.longitudinalTuning.kpV, ret.longitudinalTuning.kiV   = [[1.],  [0.]]
    ret.longitudinalTuning.kf = 1.0

    #car specified settings
    if candidate in TORQUE_LAT_CAR:
      ret.minEnableSpeed = -1.
      ret.minSteerSpeed = 0.1 * CV.KPH_TO_MS
      ret.autoResumeSng = True
      ret.startingState = True
      ret.startAccel = 0.8
      ret.stopAccel = -0.5
      ret.vEgoStarting = 0.1
      ret.vEgoStopping = 0.1
      ret.longitudinalActuatorDelay = 0.5
      ret.steerActuatorDelay = 0.2  # 转向执行器延迟，测量是0.4，但是在torqued.py里55行会加上0.2
      ret.steerLimitTimer = 0.4
    elif candidate in PLATFORM_SEAL:
      ret.minEnableSpeed = -1.
      ret.minSteerSpeed = 0.1 * CV.KPH_TO_MS
      ret.autoResumeSng = True
      ret.startingState = True
      ret.startAccel = 0.8
      ret.stopAccel = -0.5
      ret.vEgoStarting = 0.1
      ret.vEgoStopping = 0.1
      ret.longitudinalActuatorDelay = 0.5
      ret.steerActuatorDelay = 0.1  # 转向执行器延迟，测量是0.4，但是在torqued.py里55行会加上0.2
      ret.steerLimitTimer = 1.0
    else:
      ret.dashcamOnly = True


    return ret
