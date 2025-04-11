#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.mazda.values import CAR, LKAS_LIMITS, MazdaFlags
from opendbc.car.interfaces import CarInterfaceBase



class CarInterface(CarInterfaceBase):

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams:
    ret.brand = "mazda"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.mazda)]

    # 启用雷达和纵向控制功能
    ret.radarUnavailable = False
    ret.openpilotLongitudinalControl = True
    ret.experimentalLongitudinalAvailable = True
    ret.startingState = True

    # 基本纵向控制参数
    ret.longitudinalTuning.kpBP = [0., 5., 30.]
    ret.longitudinalTuning.kpV = [1.3, 1.0, 0.7]
    ret.longitudinalTuning.kiBP = [0., 5., 20., 30.]
    ret.longitudinalTuning.kiV = [0.36, 0.23, 0.17, 0.1]

    # 添加额外的纵向控制参数
    ret.longitudinalTuning.deadzoneBP = [0.0]
    ret.longitudinalTuning.deadzoneV = [0.0]
    ret.stoppingDecelRate = 3.0  # 减速率 m/s^2
    ret.longitudinalActuatorDelayLowerBound = 0.5
    ret.longitudinalActuatorDelayUpperBound = 1.0

    # 首先检查SpeedFromPCM参数，只有当它不等于1时才应用特定设置
    try:
      from openpilot.common.params import Params
      params = Params()
      speed_from_pcm = params.get_int("SpeedFromPCM")

      # 只有当SpeedFromPCM不等于1时才应用特定的纵向控制参数
      if speed_from_pcm != 1:
        # 应用特定的纵向控制调整
        ret.longitudinalTuning.deadzoneBP = [0.]
        ret.longitudinalTuning.deadzoneV = [0.9]  # == 2 mph允许的误差
        ret.stoppingDecelRate = 4.5  # == 10 mph/s
        ret.longitudinalActuatorDelayLowerBound = 1.0
        ret.longitudinalActuatorDelayUpperBound = 2.0

        ret.longitudinalTuning.kpBP = [8.94, 7.2, 28.]  # 8.94 m/s == 20 mph
        ret.longitudinalTuning.kpV = [0., 4., 2.]  # 由于我们不能低于该速度驾驶，因此将低端设置为0
        ret.longitudinalTuning.kiBP = [0.]
        ret.longitudinalTuning.kiV = [0.1]
    except (ImportError, AttributeError):
      pass

    ret.dashcamOnly = candidate not in (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021)

    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8

    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    if candidate not in (CAR.MAZDA_CX5_2022,):
      ret.minSteerSpeed = LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS

    ret.centerToFront = ret.wheelbase * 0.41

    return ret
