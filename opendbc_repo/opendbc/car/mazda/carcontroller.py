from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_driver_steer_torque_limits, structs, DT_CTRL
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.mazda import mazdacan
from opendbc.car.mazda.values import CarControllerParams, Buttons
from opendbc.car.common.conversions import Conversions as CV
from openpilot.common.params import Params
from openpilot.common.filter_simple import FirstOrderFilter

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


# 实现一个简单的计时器类，替代原有的ControlsTimer
class Timer:
  def __init__(self, duration):
    self.duration = duration
    self.t = 0.0
    self.is_active = False

  def reset(self):
    self.t = 0.0
    self.is_active = True

  def update(self, increment):
    if self.is_active:
      self.t += increment
      if self.t >= self.duration:
        self.is_active = False
        return True
    return False

  def check(self):
    return self.is_active and self.t >= self.duration


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.apply_steer_last = 0
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.brake_counter = 0
    self.frame = 0
    self.speed_from_pcm = 1

    # 上次发送的按钮计数器
    self.last_button_frame = 0
    self.button_counter = 0

    # 增加控制计时器
    self.hold_timer = Timer(6.0)  # 停车时保持6秒
    self.resume_timer = Timer(0.5)  # 恢复巡航0.5秒
    self.hold_delay = Timer(0.5)  # 停车延迟0.5秒
    self.acc_filter = FirstOrderFilter(0.0, .1, DT_CTRL, initialized=False)
    self.filtered_acc_last = 0
    self.resume_count = 0  # 用于跟踪恢复巡航的尝试次数
    self.resume_delay = 0  # 恢复巡航的延迟计数器
    self.set_speed_counter = 0  # 速度调整计数器
    self.last_cruise_enabled = False  # 跟踪上次巡航状态
    self.target_speed = 0  # 缓存目标速度

  def update(self, CC, CS, now_nanos):
    """更新控制逻辑并生成CAN消息

    Args:
        CC: 车辆控制命令
        CS: 当前车辆状态
        now_nanos: 当前时间戳（纳秒）

    Returns:
        元组: (更新后的执行器状态, CAN消息列表)
    """
    # 定期检查参数更新
    if self.frame % 50 == 0:
      try:
        params = Params()
        self.speed_from_pcm = params.get_int("SpeedFromPCM")
      except Exception:
        self.speed_from_pcm = 1  # 出错时默认从PCM获取速度

    can_sends = []

    # 默认无转向
    apply_steer = 0

    # 如果横向控制激活，计算转向力矩
    if CC.latActive:
      # 计算转向力矩并应用驾驶员力矩限制
      new_steer = int(round(CC.actuators.steer * CarControllerParams.STEER_MAX))
      apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last,
                                                   CS.out.steeringTorque, CarControllerParams)

    # 巡航控制取消逻辑
    if CC.cruiseControl.cancel:
      # 如果刹车被按下，等待>70ms再尝试禁用巡航，避免与车辆系统的竞争条件
      # 车辆巡航控制消息以50hz运行，70ms允许我们读取3条消息并在尝试取消前同步状态
      self.brake_counter = self.brake_counter + 1
      if self.frame % 10 == 0 and not (CS.out.brakePressed and self.brake_counter < 7):
        # 当OP未接管时，如果车辆巡航开启则取消
        # 以10hz的频率发送，直到与车辆巡航状态同步
        self.button_counter = (self.button_counter + 1) % 16
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.CANCEL))
        self.last_button_frame = self.frame
    else:
      self.brake_counter = 0

      # 车速控制逻辑 - 当不使用PCM速度时启用
      if self.speed_from_pcm != 1:
        # 确保按钮指令有足够的间隔时间（至少100ms）
        button_interval = self.frame - self.last_button_frame
        can_send_button = button_interval >= 10  # 至少100ms间隔

        # 检测巡航状态变化
        cruise_state_changed = self.last_cruise_enabled != CS.out.cruiseState.enabled
        self.last_cruise_enabled = CS.out.cruiseState.enabled

        # 巡航恢复逻辑 - 处理三种场景
        # 1. 静止状态需要恢复
        # 2. 巡航状态丢失需要恢复
        # 3. 明确要求恢复巡航
        resume_needed = False
        if CS.out.standstill and CC.cruiseControl.resume:
          resume_needed = True
        elif cruise_state_changed and not CS.out.cruiseState.enabled and CC.enabled:
          resume_needed = True
        elif CC.cruiseControl.resume and not CS.out.cruiseState.enabled and CC.enabled:
          resume_needed = True

        # 发送恢复命令（带延迟和计数器限制）
        if resume_needed and can_send_button:
          self.resume_delay += 1
          # 延迟发送以避免过于频繁
          if self.resume_delay >= 5:  # 约50ms * 5 = 250ms
            self.button_counter = (self.button_counter + 1) % 16
            can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.RESUME))
            self.last_button_frame = self.frame
            self.resume_delay = 0
            self.resume_count += 1
        else:
          self.resume_delay = 0

        # 自动调节巡航速度逻辑（降低调整频率）
        if can_send_button and CC.enabled and CS.out.cruiseState.enabled:
          # 每20帧检查一次，且counter为0时才调整
          if self.frame % 20 == 0 and self.set_speed_counter == 0:
            try:
              # 安全获取目标速度
              if hasattr(CC.hudControl, 'setSpeed') and CC.hudControl.setSpeed > 0:
                set_speed_in_units = CC.hudControl.setSpeed
                # 确保单位一致
                conversion = CV.MS_TO_KPH if getattr(CS, 'is_metric', True) else CV.MS_TO_MPH
                set_speed_in_units *= conversion
                target = int(round(set_speed_in_units / 5.0) * 5.0)  # 四舍五入到最近的5

                # 获取当前巡航速度
                if hasattr(CS.out.cruiseState, 'speed') and CS.out.cruiseState.speed > 0:
                  current_speed = CS.out.cruiseState.speed
                  current = int(round(current_speed * conversion / 5.0) * 5.0)

                  # 缓存目标速度
                  self.target_speed = target

                  # 只有当速度差异足够大时才调整
                  speed_diff = abs(target - current)
                  if speed_diff >= 5:  # 至少5单位差异
                    # 根据目标和当前速度决定增减
                    if target < current and current >= 31:
                      self.button_counter = (self.button_counter + 1) % 16
                      can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.SET_MINUS))
                      self.last_button_frame = self.frame
                      self.set_speed_counter = 3  # 限制调整频率
                    elif target > current and current < 160:
                      self.button_counter = (self.button_counter + 1) % 16
                      can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.SET_PLUS))
                      self.last_button_frame = self.frame
                      self.set_speed_counter = 3  # 限制调整频率
            except (TypeError, AttributeError, ValueError):
              # 出现异常时不执行速度调整
              pass

        # 计数器递减
        if self.set_speed_counter > 0:
          self.set_speed_counter -= 1

        # 自动激活巡航功能
        if CC.enabled and not CS.out.cruiseState.enabled and can_send_button:
          # 确保安全获取车速
          v_ego_kph = getattr(CS.out, 'vEgo', 0) * CV.MS_TO_KPH
          cant_activate = getattr(CS.out, 'brakePressed', False) or getattr(CS.out, 'gasPressed', False)

          # 只有当前方有车或速度足够，且未踩刹车和油门时激活
          if (getattr(CC.hudControl, 'leadVisible', False) or v_ego_kph > 10.0) and not cant_activate and self.frame % 50 == 0:
            self.button_counter = (self.button_counter + 1) % 16
            can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.RESUME))
            self.last_button_frame = self.frame

    # 保存上次转向值
    self.apply_steer_last = apply_steer

    # 发送HUD警告（每50帧一次）
    if self.frame % 50 == 0:
      # 安全获取警告类型
      ldw = getattr(CC.hudControl, 'visualAlert', '') == VisualAlert.ldw
      steer_required = getattr(CC.hudControl, 'visualAlert', '') == VisualAlert.steerRequired
      # 只在允许的速度下显示转向要求警告
      steer_required = steer_required and getattr(CS, 'lkas_allowed_speed', True)
      # 安全获取车道信息
      cam_laneinfo = getattr(CS, 'cam_laneinfo', {})
      can_sends.append(mazdacan.create_alert_command(self.packer, cam_laneinfo, ldw, steer_required))

    # 发送转向命令
    cam_lkas = getattr(CS, 'cam_lkas', {})
    can_sends.append(mazdacan.create_steering_control(self.packer, self.CP,
                                                    self.frame, apply_steer, cam_lkas))

    # 更新执行器状态
    new_actuators = CC.actuators.as_builder()
    new_actuators.steer = apply_steer / CarControllerParams.STEER_MAX
    new_actuators.steerOutputCan = apply_steer

    # 增加帧计数
    self.frame += 1
    return new_actuators, can_sends
