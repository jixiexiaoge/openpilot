import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_std_steer_angle_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams, CAR
from openpilot.common.realtime import DT_CTRL
from openpilot.common.conversions import Conversions as CV


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.params = CarControllerParams(self.CP)
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.frame = 0
    self.last_angle = 0
    self.last_acctrq = -5000
    self.first_start = True

    self.steering_smoothing_factor = self.params.STEERING_SMOOTHING_FACTOR
    self.filtered_steering_angle = 0.0
    self.max_steering_angle = self.params.MAX_STEERING_ANGLE

    # 急弯检测相关 (Emergency turn detection)
    self.emergency_turn_threshold_angle = 35.0
    self.emergency_turn_threshold_rate = 60.0
    self.emergency_turn_active = False
    self.emergency_turn_counter = 0
    self.emergency_turn_timeout = 0
    self.last_steering_angle = 0.0
    self.steering_rate = 0.0

    # 大角度转向控制 (Large angle steering)
    self.large_angle_active = False
    self.large_angle_threshold = 40.0
    self.large_angle_counter = 0

    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.last_apply_accel = 0.0
    self.stop_lead_distance = 0.0
    self.last_speed = 0.0

    self.expected_accel = 0.0
    self.actual_accel_filtered = 0.0
    self.slope_compensation = 0.0

    self.expected_daccel = 0.0
    self.actual_daccel_filtered = 0.0
    self.slope_daccel = 0.0

    # 纵向控制限制 (Longitudinal control limits)
    self.last_turn_state = False

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl

    if self.first_start:
      self.counter_244 = int(CS.counter_244) & 0xF
      self.counter_1ba = int(CS.counter_1ba) & 0xF
      self.counter_17e = int(CS.counter_17e) & 0xF
      self.counter_307 = int(CS.counter_307) & 0xF
      self.counter_31a = int(CS.counter_31a) & 0xF
      self.last_angle = CS.out.steeringAngleDeg
      self.first_start = False

    can_sends = []

    # 计数器处理
    self.counter_1ba = (self.counter_1ba + 1) & 0xF
    self.counter_17e = (self.counter_17e + 1) & 0xF

    # 1. 转向控制 (Steering Control)
    # 移除所有自定义滤波和急弯逻辑，信任 Planner
    lat_active = CC.latActive and not CS.steeringPressed

    if lat_active:
      apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg

      # 应用标准速率限制
      apply_angle = apply_std_steer_angle_limits(
        apply_angle, self.last_angle, CS.out.vEgoRaw,
        self.params.ANGLE_LIMITS
      )
      # CAN 协议层面的硬限位 (480度)
      apply_angle = np.clip(apply_angle, -self.params.MAX_STEERING_ANGLE, self.params.MAX_STEERING_ANGLE)
    else:
      apply_angle = CS.out.steeringAngleDeg

    self.last_angle = apply_angle

    # 就算不激活横向，也要发送 1BA 消息以保持心跳（Active=0）
    can_sends.append(changancan.create_steering_control(self.packer, CS.sigs1ba, apply_angle, lat_active, self.counter_1ba))

    # 发送 EPS 状态维持 (17E)
    can_sends.append(changancan.create_eps_control(self.packer, CS.sigs17e, lat_active, self.counter_17e))

    # 2. 纵向控制 (Longitudinal Control)
    if self.frame % 2 == 0:
      self.counter_244 = (self.counter_244 + 1) & 0xF

      # 简单的开环控制，移除复杂的弯道/速度分段逻辑
      # 如果需要精细调优，应该去调整 interface.py 中的 PID/MPC 参数
      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

      # 简单的扭矩映射 (如有必要保留基础映射逻辑)
      acctrq = -5000 # Default

      # 只有在启用时长发控制，否则发空/默认
      if CC.longActive:
        can_sends.append(changancan.create_acc_control(self.packer, CS.sigs244, accel, self.counter_244, CC.longActive, acctrq))
      else:
        # 发送非激活状态的 ACC 消息，保持计数器同步
        can_sends.append(changancan.create_acc_control(self.packer, CS.sigs244, 0.0, self.counter_244, False, -5000))

    # 3. HUD 控制 (10Hz)
    if self.frame % 10 == 0:
      self.counter_307 = (self.counter_307 + 1) & 0xF
      self.counter_31a = (self.counter_31a + 1) & 0xF

      cruise_speed_kph = CS.out.cruiseState.speed * CV.MS_TO_KPH
      can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs307, self.counter_307, cruise_speed_kph))
      can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs31a, self.counter_31a, CC.longActive, CS.out.steeringPressed))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.last_angle)
    new_actuators.accel = float(actuators.accel)

    self.frame += 1
    return new_actuators, can_sends
