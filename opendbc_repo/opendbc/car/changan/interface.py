#!/usr/bin/env python3
from opendbc.car import Bus, get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.changan.values import CarControllerParams, ChanganFlags, ChanganSafetyFlags, EPS_SCALE, NO_STOP_TIMER_CAR
from opendbc.car.changan.carcontroller import CarController
from opendbc.car.changan.carstate import CarState
from opendbc.car.changan.radar_interface import RadarInterface

from opendbc.car.interfaces import CarInterfaceBase

class CarInterface(CarInterfaceBase):

  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    return CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "changan"

    # Safety configuration with proper parameter passing
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.changan)]
    ret.safetyConfigs[0].safetyParam = EPS_SCALE[candidate]

    # Add IDD variant flag to safety param if this is a hybrid model
    if ret.flags & ChanganFlags.IDD:
      ret.safetyConfigs[0].safetyParam |= ChanganSafetyFlags.IDD_VARIANT.value

    ret.transmissionType = structs.CarParams.TransmissionType.automatic

    # Radar integration
    ret.radarUnavailable = True
    ret.enableBsm = True

    # Lateral control configuration
    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8
    ret.steerRatio = 15.0
    ret.minSteerSpeed = 0.1

    ret.centerToFront = ret.wheelbase * 0.44

    # Longitudinal control configuration
    ret.openpilotLongitudinalControl = True
    ret.pcmCruise = False
    ret.autoResumeSng = candidate in NO_STOP_TIMER_CAR
    ret.minEnableSpeed = -1.
    ret.longitudinalActuatorDelay = 0.35

    ret.vEgoStopping = 0.25
    ret.vEgoStarting = 0.25
    ret.stoppingDecelRate = 0.3
    ret.startingState = True
    ret.startAccel = 0.8
    ret.stopAccel = -0.35

    # Longitudinal Tuning (PID)
    tune = ret.longitudinalTuning
    tune.kpBP = [0., 5., 20., 40.]
    tune.kpV = [1.2, 1.0, 0.7, 0.5]
    tune.kiBP = [0., 5., 12., 20., 27.]
    tune.kiV = [0.3, 0.25, 0.2, 0.15, 0.1]

    return ret