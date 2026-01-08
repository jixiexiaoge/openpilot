#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.changan.values import CarControllerParams
from opendbc.car.changan.carcontroller import CarController
from opendbc.car.changan.carstate import CarState
from opendbc.car.changan.radar_interface import RadarInterface

class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    # 动态调整加速和减速限制，根据车速提供更合适的控制
    if current_speed < 10 * CV.KPH_TO_MS:  # 低速区域
      return CarControllerParams.ACCEL_MIN, min(CarControllerParams.ACCEL_MAX * 1.2, 2.5)  # 低速提供更强加速能力
    elif current_speed > 80 * CV.KPH_TO_MS:  # 高速区域
      return max(CarControllerParams.ACCEL_MIN * 0.8, -4.5), CarControllerParams.ACCEL_MAX * 0.8  # 高速降低加减速强度
    else:  # 中速区域
      return CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "changan"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.changan)]
    ret.transmissionType = structs.CarParams.TransmissionType.automatic
    ret.radarUnavailable = True
    ret.enableBsm = True

    # Steering
    ret.steerActuatorDelay = 0.08  # 降低转向延迟以提高响应速度
    ret.steerLimitTimer = 0.5  # 增加转向限制时间，使转向持续时间更长
    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.steerRatio = 15.0
    ret.minSteerSpeed = 0

    # Lateral Tuning
    # ret.lateralParams.torqueBP = [0]
    # ret.lateralParams.torqueV = [480]

    ret.centerToFront = ret.wheelbase * 0.44

    # Longitudinal
    ret.openpilotLongitudinalControl = True
    ret.autoResumeSng = ret.openpilotLongitudinalControl
    ret.alphaLongitudinalAvailable = True
    ret.minEnableSpeed = -1.
    ret.longitudinalActuatorDelay = 0.6  # 降低纵向控制延迟

    ret.vEgoStopping = 0.3  # 降低停车速度阈值
    ret.vEgoStarting = 0.3  # 降低起步速度阈值
    ret.stoppingDecelRate = 0.15  # 降低停车减速率，使停车更平稳
    ret.startingState = True
    ret.startAccel = 0.5  # 提高起步加速度
    ret.stopAccel = -0.3  # 降低停车减速度以使停车更平稳

    # Longitudinal Tuning
    tune = ret.longitudinalTuning
    tune.kpBP = [0., 5., 20., 40.]
    tune.kpV = [1.2, 1.0, 0.7, 0.5]  # 提高低速响应性，降低高速敏感度
    tune.kiBP = [0., 5., 12., 20., 27.]
    tune.kiV = [0.3, 0.25, 0.2, 0.15, 0.1]  # 增加积分增益

    return ret

