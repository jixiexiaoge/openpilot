#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.mazda.values import CAR, LKAS_LIMITS, MazdaFlags, get_car_from_vin
from opendbc.car.interfaces import CarInterfaceBase


class CarInterface(CarInterfaceBase):
  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams:
    # 简化调试信息
    print("==== 马自达车辆接口初始化 ====")
    print(f"车型: {candidate}")

    # 尝试从VIN识别车型
    if car_fw is not None and len(car_fw) > 0:
      vin = None
      for fw in car_fw:
        if fw.ecu == structs.CarParams.Ecu.fwdCamera and fw.address == 2024:
          if hasattr(fw, "vin") and fw.vin:
            vin = fw.vin
            print(f"检测到VIN: {vin}")
            break

      if vin and candidate is None:
        detected_car = get_car_from_vin(vin)
        if detected_car is not None:
          candidate = detected_car
          print(f"通过VIN选择车型: {candidate}")

    # 基本品牌设置
    ret.brand = "mazda"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.mazda)]

    # 如果无法识别车型，使用默认车型
    if candidate is None:
      print("警告: 无法识别车型. 使用 MAZDA_CX5_2022 作为默认值.")
      candidate = CAR.MAZDA_CX5_2022

    # 完全禁用雷达功能
    ret.radarUnavailable = True

    # 设置其他基本参数
    ret.openpilotLongitudinalControl = experimental_long
    ret.experimentalLongitudinalAvailable = True

    # 纵向PID控制参数
    if experimental_long:
      ret.longitudinalTuning.kpBP = [0., 5., 35.]
      ret.longitudinalTuning.kpV = [1.2, 0.8, 0.5]
      ret.longitudinalTuning.kiBP = [0., 35.]
      ret.longitudinalTuning.kiV = [0.18, 0.12]

    ret.dashcamOnly = candidate not in (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021)
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8

    try:
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    except Exception as e:
      print(f"警告: 配置转向扭矩时出错: {e}")

    if candidate not in (CAR.MAZDA_CX5_2022,):
      ret.minSteerSpeed = LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS

    ret.centerToFront = ret.wheelbase * 0.41

    print(f"==== 马自达车辆接口初始化完成: {candidate} ====")
    return ret
