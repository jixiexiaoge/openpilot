#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.mazda.values import CAR, LKAS_LIMITS
from opendbc.car.interfaces import CarInterfaceBase



class CarInterface(CarInterfaceBase):

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams:
    ret.brand = "mazda"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.mazda)]
    ret.radarUnavailable = True

    ret.dashcamOnly = candidate not in (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021)

    # 增加对纵向控制的支持
    ret.openpilotLongitudinalControl = True

    # 增加纵向控制的调整参数
    ret.longitudinalTuning.kpBP = [0., 5., 35.]
    ret.longitudinalTuning.kpV = [1.3, 1.0, 0.7]
    ret.longitudinalTuning.kiBP = [0., 5., 12., 35.]
    ret.longitudinalTuning.kiV = [0.36, 0.24, 0.18, 0.1]
    ret.stopAccel = -0.5
    ret.vEgoStarting = 0.2
    ret.startingState = True

    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8

    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    if candidate not in (CAR.MAZDA_CX5_2022,):
      ret.minSteerSpeed = LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS

    ret.centerToFront = ret.wheelbase * 0.41

    return ret

  def _update(self, c):
    ret = self.CS.update(self.cp, self.cp_cam, self.cp_body)

    # 事件
    events = self.create_common_events(ret)

    if self.CS.lkas_disabled:
      events.add(structs.CarEvent.EventName.lkasDisabled)
    elif self.CS.low_speed_alert:
      events.add(structs.CarEvent.EventName.belowSteerSpeed)

    ret.events = events.to_msg()

    return ret
