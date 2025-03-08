#!/usr/bin/env python3
from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.mazda.values import CAR, LKAS_LIMITS
from opendbc.car.interfaces import CarInterfaceBase



class CarInterface(CarInterfaceBase):

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams:
    """获取车辆参数配置

    Args:
        ret: 车辆参数对象
        candidate: 车型候选
        fingerprint: 车辆特征码
        car_fw: 车辆固件信息
        experimental_long: 是否启用实验性纵向控制
        docs: 文档信息

    Returns:
        structs.CarParams: 配置好的车辆参数对象
    """
    ret.brand = "mazda"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.mazda)]
    ret.radarUnavailable = True

    ret.dashcamOnly = candidate not in (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021)

    # 允许实验性纵向控制
    ret.experimentalLongitudinalAvailable = True

    # 增加对纵向控制的支持，根据experimental_long参数决定是否启用
    ret.openpilotLongitudinalControl = experimental_long

    # 增加纵向控制的调整参数 - 优化PID参数
    ret.longitudinalTuning.kpBP = [0., 5., 15., 35.]
    ret.longitudinalTuning.kpV = [1.2, 0.9, 0.7, 0.6]
    ret.longitudinalTuning.kiBP = [0., 5., 12., 35.]
    ret.longitudinalTuning.kiV = [0.32, 0.22, 0.16, 0.09]
    ret.longitudinalTuning.kdBP = [0., 5., 35.]  # 更精细的kd控制
    ret.longitudinalTuning.kdV = [0.5, 0.4, 0.3]  # 较低速度时更高的微分增益以提高稳定性

    # 调整停车和起步参数
    ret.stopAccel = -0.7  # 更积极的停车减速度
    ret.vEgoStarting = 0.2
    ret.startingState = True
    ret.stoppingControl = True
    ret.startAccel = 1.0  # 更自然的起步加速度

    # 限速和加速度参数
    ret.vCruisekph = 90.0  # 默认巡航速度 - 90 km/h
    ret.minEnableSpeed = 0.0  # 允许低速启用

    # 加速度限制
    ret.longitudinalActuatorDelayLowerBound = 0.2
    ret.longitudinalActuatorDelayUpperBound = 0.2

    # 调整横向控制参数
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.8

    # 配置转向力矩参数
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    # 设置最小转向速度（部分车型）
    if candidate not in (CAR.MAZDA_CX5_2022,):
      ret.minSteerSpeed = LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS

    # 车辆重心位置（相对于车轮轴）
    ret.centerToFront = ret.wheelbase * 0.41

    return ret

  def _update(self, c, frogpilot_toggles=None):
    """更新车辆状态信息和事件

    参数:
        c: 控制命令
        frogpilot_toggles: frogpilot切换状态，默认为None

    返回:
        ret: 车辆状态信息
        fp_ret: frogpilot状态信息，默认为None
    """
    try:
      # 确保正确处理frogpilot_toggles参数
      if frogpilot_toggles is None:
        frogpilot_toggles = {}

      # 获取车辆状态
      ret = self.CS.update(self.cp, self.cp_cam, self.cp_body)
      fp_ret = None  # 初始化fp_ret为None

      # 事件处理
      events = self.create_common_events(ret)

      # 检查LKAS状态
      if hasattr(self.CS, 'lkas_disabled') and self.CS.lkas_disabled:
        events.add(structs.CarEvent.EventName.lkasDisabled)
      elif hasattr(self.CS, 'low_speed_alert') and self.CS.low_speed_alert:
        events.add(structs.CarEvent.EventName.belowSteerSpeed)

      # 添加事件到返回值
      ret.events = events.to_msg()

      return ret, fp_ret
    except Exception as e:
      # 捕获任何异常，确保不会导致系统崩溃
      # 在生产环境中应记录异常信息
      import traceback
      print(f"Mazda interface update error: {e}")
      print(traceback.format_exc())

      # 返回一个基本的CarState对象以保持系统运行
      ret = structs.CarState.new_message()
      fp_ret = None

      # 添加错误事件，通知驾驶员
      events = self.create_common_events(ret)
      events.add(structs.CarEvent.EventName.canError)
      ret.events = events.to_msg()

      return ret, fp_ret
