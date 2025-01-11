#!/usr/bin/env python3
# 导入必要的模块
from cereal import car, custom  # 导入车辆和自定义相关模块
from openpilot.common.conversions import Conversions as CV  # 导入单位转换工具
from openpilot.selfdrive.car.mazda.values import CAR, LKAS_LIMITS, Buttons  # 导入马自达相关常量
from openpilot.selfdrive.car import create_button_events, get_safety_config  # 导入按钮事件和安全配置
from openpilot.selfdrive.car.interfaces import CarInterfaceBase  # 导入车辆接口基类
from openpilot.common.params import Params  # 导入参数管理模块

params = Params()  # 创建参数实例

# 定义按钮类型常量
ButtonType = car.CarState.ButtonEvent.Type
EventName = car.CarEvent.EventName
FrogPilotButtonType = custom.FrogPilotCarState.ButtonEvent.Type

# 按钮映射字典
BUTTONS_DICT = {Buttons.SET_PLUS: ButtonType.accelCruise, Buttons.SET_MINUS: ButtonType.decelCruise,
                Buttons.RESUME: ButtonType.resumeCruise, Buttons.CANCEL: ButtonType.cancel}

class CarInterface(CarInterfaceBase):
  """马自达车辆接口类"""

  @staticmethod
  def _get_params(ret, params, candidate, fingerprint, car_fw, disable_openpilot_long, experimental_long, docs):
    """获取车辆参数配置"""
    ret.carName = "mazda"  # 设置车辆名称
    ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.mazda)]  # 设置安全配置
    ret.radarUnavailable = True  # 设置雷达不可用

    ret.dashcamOnly = False  # 不是仅限行车记录仪模式

    ret.steerActuatorDelay = 0.1  # 转向执行器延迟
    ret.steerLimitTimer = 0.8  # 转向限制计时器

    # 配置转向扭矩参数
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    # 对于某些车型设置最小转向速度
    if candidate not in (CAR.CX5_2022, ):
      ret.minSteerSpeed = LKAS_LIMITS.DISABLE_SPEED * CV.KPH_TO_MS

    ret.centerToFront = ret.wheelbase * 0.41  # 设置前轮中心到车辆前部的距离

    # 如果启用了CSLC（自定义速度限制控制）
    if params.get_bool("CSLCEnabled"):
        # 用于带CSLC的CEM
        ret.openpilotLongitudinalControl = True  # 启用openpilot纵向控制
        ret.longitudinalTuning.deadzoneBP = [0.]  # 死区断点
        ret.longitudinalTuning.deadzoneV = [0.9]  # 死区值（允许2mph的速度差）
        ret.stoppingDecelRate = 4.5  # 停车减速率（10 mph/s）
        ret.longitudinalActuatorDelayLowerBound = 1.  # 纵向执行器延迟下限
        ret.longitudinalActuatorDelayUpperBound = 2.  # 纵向执行器延迟上限

        # 设置PID控制参数
        ret.longitudinalTuning.kpBP = [8.94, 7.2, 28.]  # 比例增益断点（8.94 m/s = 20 mph）
        ret.longitudinalTuning.kpV = [0., 4., 2.]  # 比例增益值（设置低端为0，因为无法在该速度以下行驶）
        ret.longitudinalTuning.kiBP = [0.]  # 积分增益断点
        ret.longitudinalTuning.kiV = [0.1]  # 积分增益值

    return ret

  def _update(self, c, frogpilot_variables):
    """更新车辆状态"""
    # 获取车辆状态更新
    ret, fp_ret = self.CS.update(self.cp, self.cp_cam, frogpilot_variables)

    # TODO: 添加增加和减少的按钮类型
    # 创建按钮事件列表
    ret.buttonEvents = [
      *create_button_events(self.CS.cruise_buttons, self.CS.prev_cruise_buttons, BUTTONS_DICT),  # 巡航控制按钮事件
      *create_button_events(self.CS.distance_button, self.CS.prev_distance_button, {1: ButtonType.gapAdjustCruise}),  # 车距调节按钮事件
      *create_button_events(self.CS.lkas_enabled, self.CS.lkas_previously_enabled, {1: FrogPilotButtonType.lkas}),  # LKAS启用按钮事件
    ]

    # 处理事件
    events = self.create_common_events(ret)

    # 添加特定事件
    if self.CS.lkas_disabled:
      events.add(EventName.lkasDisabled)  # LKAS禁用事件
    elif self.CS.low_speed_alert:
      events.add(EventName.belowSteerSpeed)  # 低速警告事件

    ret.events = events.to_msg()  # 转换事件为消息格式

    return ret, fp_ret

  def apply(self, c, now_nanos, frogpilot_variables):
    """应用控制命令"""
    return self.CC.update(c, self.CS, now_nanos, frogpilot_variables)
