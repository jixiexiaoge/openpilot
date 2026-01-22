#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.changan.values import CarControllerParams, ChanganFlags
from opendbc.car.changan.carcontroller import CarController
from opendbc.car.changan.carstate import CarState
from opendbc.car.changan.radar_interface import RadarInterface

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
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.changan)]


    ret.transmissionType = structs.CarParams.TransmissionType.automatic
    # Radar is present but not used for fusion yet
    ret.radarUnavailable = True
    ret.enableBsm = True

    # Steering
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8
    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.steerRatio = 15.0
    ret.minSteerSpeed = 0.1

    ret.centerToFront = ret.wheelbase * 0.44

    # Longitudinal
    #ret.alphaLongitudinalAvailable = True
    #ret.openpilotLongitudinalControl = True
    #ret.autoResumeSng = ret.openpilotLongitudinalControl

    # 启用 Alpha 纵向模型 (End-to-End Longitudinal) 如果 experimental_long=True
    #if experimental_long:
    #  ret.longitudinalTuning.kpV = [0.0]
    #  ret.longitudinalTuning.kiV = [0.0]

    ret.minEnableSpeed = -1.
    ret.longitudinalActuatorDelay = 0.35

    ret.vEgoStopping = 0.25
    ret.vEgoStarting = 0.25
    ret.stoppingDecelRate = 0.3
    ret.startingState = True
    ret.startAccel = 0.8
    ret.stopAccel = -0.35

    # Longitudinal Tuning (PID)
    # 只有在非 E2E 模式下生效
    tune = ret.longitudinalTuning
    tune.kpBP = [0., 5., 20., 40.]
    tune.kpV = [1.2, 1.0, 0.7, 0.5]
    tune.kiBP = [0., 5., 12., 20., 27.]
    tune.kiV = [0.3, 0.25, 0.2, 0.15, 0.1]

    return ret
