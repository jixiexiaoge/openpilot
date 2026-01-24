import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_std_steer_angle_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams, CAR
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

    # 发送计数器初始化
    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.last_apply_accel = 0.0
    self.stop_lead_distance = 0.0
    self.last_speed = 0.0

    # 纵向动力学补偿变量
    self.expected_accel = 0.0
    self.actual_accel_filtered = 0.0  # 滤波后的实际加速度
    self.slope_compensation = 0.0      # 动态坡度补偿值

    self.expected_daccel = 0.0
    self.actual_daccel_filtered = 0.0  # 滤波后的实际减速度
    self.slope_daccel = 0.0            # 减速阶段动态补偿值

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl

    # 初始化计数器，从 CarState 获取当前总线值，实现与原车心跳的无缝对接
    if self.first_start:
      self.counter_244 = int(CS.counter_244) & 0xF  # 0x244: ACC 加减速与扭矩控制计数器
      self.counter_1ba = int(CS.counter_1ba) & 0xF  # 0x1BA: 转向角度控制计数器
      self.counter_17e = int(CS.counter_17e) & 0xF  # 0x17E: EPS 控制授权心跳计数器
      self.counter_307 = int(CS.counter_307) & 0xF  # 0x307: 仪表巡航车速同步计数器
      self.counter_31a = int(CS.counter_31a) & 0xF  # 0x31A: 仪表 ADAS 状态及图标计数器
      self.last_angle = CS.out.steeringAngleDeg      # 记录初始角度，作为标准速率限制的起点
      self.first_start = False

    can_sends = []

    # -------------------------------------------------------------------------
    # 1. 横向转向控制逻辑 (Steering Control)
    # -------------------------------------------------------------------------
    self.counter_1ba = (self.counter_1ba + 1) & 0xF
    self.counter_17e = (self.counter_17e + 1) & 0xF

    # 判断转向是否激活（OP 激活且驾驶员未强行压盘）
    lat_active = CC.latActive and not CS.steeringPressed

    if lat_active:
      apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg
      # 应用 standard 变化率限制，防止方向盘打得太突兀
      apply_angle = apply_std_steer_angle_limits(
        apply_angle, self.last_angle, CS.out.vEgoRaw, CS.out.steeringAngleDeg,
        lat_active, self.params.ANGLE_LIMITS
      )
      # Carrot 优化：放宽单帧变化限制为 30 度，在大转角弯道更从容
      apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 30, CS.out.steeringAngleDeg + 30)
      # 物理限位防护 (480度)
      apply_angle = np.clip(apply_angle, -self.params.MAX_STEERING_ANGLE, self.params.MAX_STEERING_ANGLE)
    else:
      # 未激活时跟随原车角度偏移，保持静默
      apply_angle = CS.out.steeringAngleDeg

    self.last_angle = apply_angle

    # 【信号 0x1BA】 向底盘发送转向请求和期望角度信号
    if CS.sigs1ba:
      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs1ba, apply_angle, lat_active, self.counter_1ba))

    # 【信号 0x17E】 告诉底盘 EPS 助力系统横向控制是否可用 (心跳信号)
    if CS.sigs17e:
      can_sends.append(changancan.create_eps_control(self.packer, CS.sigs17e, lat_active, self.counter_17e))

    # -------------------------------------------------------------------------
    # 2. 纵向加减速控制任务 (Longitudinal Control) - 50Hz
    # -------------------------------------------------------------------------
    if self.frame % 2 == 0:
      self.counter_244 = (self.counter_244 + 1) & 0xF
      acctrq = -5000 # 初始扭矩偏移（原车 Baseline）

      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)
      speed_kph = CS.out.vEgoRaw * CV.MS_TO_KPH

      # --- 减速处理阶段 (Brake/Coast) ---
      if accel < 0:
        self.expected_daccel = accel
        self.actual_daccel_filtered = 0.9 * self.actual_daccel_filtered + 0.1 * CS.out.aEgo
        # 如果减速度不够（滑行太快），施加额外的动态补偿
        if self.actual_daccel_filtered > self.expected_daccel * 0.8:
          self.slope_daccel = 0.15
        else:
          self.slope_daccel = 0.0
        accel -= self.slope_daccel

        # 加速度单步变化限制，防止“点头”现象
        accel = np.clip(accel, self.last_apply_accel - 0.2, self.last_apply_accel + 0.10)

        # 如果距离前车过近且之前没在刹车，强行切入一小段负加速度
        if self.last_apply_accel >= 0 and hud_control.leadVisible and hud_control.leadDistanceBars < 30:
          accel = -0.4
        accel = max(accel, -3.5)

        # 停止场景感知逻辑：记录停车位置
        if speed_kph == 0 and self.last_speed > 0 and hud_control.leadVisible and hud_control.leadDistanceBars > 0:
          self.stop_lead_distance = hud_control.leadDistanceBars

        # 起步辅助：如果前车拉开了距离且我们还在静止，提前给个起步推力
        if self.stop_lead_distance != 0 and speed_kph == 0 and self.last_speed == 0 and \
           hud_control.leadVisible and (hud_control.leadDistanceBars - self.stop_lead_distance > 1):
          accel = 0.5

      if speed_kph > 0:
        self.stop_lead_distance = 0 # 只要动起来就重置起步状态

      # --- 加速与扭矩转换阶段 (Gas Control) ---
      if accel > 0:
        # 不同速度区间下的扭矩增益设置，模拟真实油门质感
        if speed_kph > 110:
          offset, gain = 1100, 150
        elif speed_kph > 90:
          offset, gain = 800, 120
        elif speed_kph > 70:
          offset, gain = 800, 100
        elif speed_kph > 50:
          offset, gain = 800, 80
        elif speed_kph > 10:
          offset, gain = 500, 50
        else:
          offset, gain = 400, 50

        base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000

        # Carrot 特色：动态坡度补偿 (避免上坡动力不足)
        self.expected_accel = accel
        self.actual_accel_filtered = 0.9 * self.actual_accel_filtered + 0.1 * CS.out.aEgo
        if self.actual_accel_filtered < self.expected_accel * 0.8:
          self.slope_compensation += 10 # 下一步增加补偿
        else:
          self.slope_compensation = max(self.slope_compensation - 10, 0) # 逐渐衰减

        base_acctrq += self.slope_compensation
        base_acctrq = min(base_acctrq, -10) # 扭矩上限安全锁
        # 限制扭矩跳变率
        acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)

      self.last_speed = speed_kph
      accel = int(accel / 0.05) * 0.05

      # 【信号 0x244】 向底盘发送加速度请求和力矩请求（核心巡航信号）
      if CS.sigs244:
        can_sends.append(changancan.create_acc_control(self.packer, CS.sigs244, accel, self.counter_244, CC.longActive, acctrq))
      else:
        # 安全垫：如果没收到摄像头原始信号，发送“空 Ready 位”防止底盘报 AEB 故障
        can_sends.append(changancan.create_acc_control(self.packer, {}, 0.0, self.counter_244, False, -5000))

      self.last_apply_accel = accel
      self.last_acctrq = acctrq

    # -------------------------------------------------------------------------
    # 3. HUD 界面与仪表面板心跳信号 (10Hz)
    # -------------------------------------------------------------------------
    if self.frame % 10 == 0:
      self.counter_307 = (self.counter_307 + 1) & 0xF
      self.counter_31a = (self.counter_31a + 1) & 0xF

      # 【信号 0x307】 向仪表面板发送当前的 IACC 设置巡航速度
      if CS.sigs307:
        cruise_speed_kph = CS.out.cruiseState.speed * CV.MS_TO_KPH
        can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs307, self.counter_307, cruise_speed_kph))

      # 【信号 0x31A】 向仪表面板发送巡航系统状态图标（绿色/白色/关闭）
      if CS.sigs31a:
        can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs31a, self.counter_31a, CC.longActive, CS.out.steeringPressed))

    # 更新执行器状态回执
    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.last_angle)
    new_actuators.accel = float(self.last_apply_accel)

    self.frame += 1
    return new_actuators, can_sends
