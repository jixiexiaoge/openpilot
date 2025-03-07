from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_driver_steer_torque_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.mazda import mazdacan
from opendbc.car.mazda.values import CarControllerParams, Buttons
from opendbc.car.common.conversions import Conversions as CV
from openpilot.common.params import Params
from openpilot.common.realtime import ControlsTimer as Timer, DT_CTRL
from openpilot.common.filter_simple import FirstOrderFilter

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


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

  def update(self, CC, CS, now_nanos):
    if self.frame % 50 == 0:
      params = Params()
      self.speed_from_pcm = params.get_int("SpeedFromPCM")

    can_sends = []

    apply_steer = 0

    if CC.latActive:
      # calculate steer and also set limits due to driver torque
      new_steer = int(round(CC.actuators.steer * CarControllerParams.STEER_MAX))
      apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last,
                                                     CS.out.steeringTorque, CarControllerParams)

    if CC.cruiseControl.cancel:
      # If brake is pressed, let us wait >70ms before trying to disable crz to avoid
      # a race condition with the stock system, where the second cancel from openpilot
      # will disable the crz 'main on'. crz ctrl msg runs at 50hz. 70ms allows us to
      # read 3 messages and most likely sync state before we attempt cancel.
      self.brake_counter = self.brake_counter + 1
      if self.frame % 10 == 0 and not (CS.out.brakePressed and self.brake_counter < 7):
        # Cancel Stock ACC if it's enabled while OP is disengaged
        # Send at a rate of 10hz until we sync with stock ACC state
        self.button_counter = (self.button_counter + 1) % 16
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.CANCEL))
        self.last_button_frame = self.frame
    else:
      self.brake_counter = 0

      # 车速控制逻辑
      if self.speed_from_pcm != 1:  # 当不是从PCM获取速度时，我们可以控制车速
        # 确保按钮指令有足够的间隔时间（至少100ms）
        button_interval = self.frame - self.last_button_frame
        can_send_button = button_interval >= 10  # 至少100ms间隔

        # Mazda Stop and Go需要在车辆停止超过3秒后按下RES按钮
        if CC.cruiseControl.resume and CS.out.standstill and can_send_button:
          self.resume_delay += 1
          # 只有在延迟足够后才发送RESUME按钮，避免过于频繁发送
          if self.resume_delay >= 5:  # 约50ms * 5 = 250ms
            self.button_counter = (self.button_counter + 1) % 16
            can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.RESUME))
            self.last_button_frame = self.frame
            self.resume_delay = 0
            self.resume_count += 1
        else:
          self.resume_delay = 0

        # 自动调节巡航速度，避免频繁发送调整命令
        if can_send_button and CC.enabled and CS.out.cruiseState.enabled:
          # 减少速度调整频率，只在每20帧时检查并且使用计数器限制调整速率
          if self.frame % 20 == 0 and self.set_speed_counter == 0:
            # 获取目标速度和当前速度
            set_speed_in_units = CC.hudControl.setSpeed * (CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH)
            target = int(round(set_speed_in_units / 5.0) * 5.0)  # 四舍五入到最接近的5
            current = int(round(CS.out.cruiseState.speed * CV.MS_TO_KPH / 5.0) * 5.0)

            # 设置速度差阈值，避免小的波动触发调整
            speed_diff = abs(target - current)
            if speed_diff >= 5:  # 至少5km/h差异才调整
              # 根据目标速度和当前速度决定是增加还是减少速度
              if target < current and current >= 31:
                self.button_counter = (self.button_counter + 1) % 16
                can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.SET_MINUS))
                self.last_button_frame = self.frame
                self.set_speed_counter = 3  # 设置计数器，限制调整频率
              elif target > current and current < 160:
                self.button_counter = (self.button_counter + 1) % 16
                can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.SET_PLUS))
                self.last_button_frame = self.frame
                self.set_speed_counter = 3  # 设置计数器，限制调整频率

        # 计数器递减
        if self.set_speed_counter > 0:
          self.set_speed_counter -= 1

      # 自动激活巡航功能
      if CC.enabled and not CS.out.cruiseState.enabled and can_send_button:
        v_ego_kph = CS.out.vEgo * CV.MS_TO_KPH
        cant_activate = CS.out.brakePressed or CS.out.gasPressed

        # 只有当速度足够且没有按下刹车或油门时才尝试激活
        if (CC.hudControl.leadVisible or v_ego_kph > 10.0) and not cant_activate and self.frame % 50 == 0:
          self.button_counter = (self.button_counter + 1) % 16
          can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, self.button_counter, Buttons.RESUME))
          self.last_button_frame = self.frame

    self.apply_steer_last = apply_steer

    # send HUD alerts
    if self.frame % 50 == 0:
      ldw = CC.hudControl.visualAlert == VisualAlert.ldw
      steer_required = CC.hudControl.visualAlert == VisualAlert.steerRequired
      # TODO: find a way to silence audible warnings so we can add more hud alerts
      steer_required = steer_required and CS.lkas_allowed_speed
      can_sends.append(mazdacan.create_alert_command(self.packer, CS.cam_laneinfo, ldw, steer_required))

    # send steering command
    can_sends.append(mazdacan.create_steering_control(self.packer, self.CP,
                                                      self.frame, apply_steer, CS.cam_lkas))

    new_actuators = CC.actuators.as_builder()
    new_actuators.steer = apply_steer / CarControllerParams.STEER_MAX
    new_actuators.steerOutputCan = apply_steer

    self.frame += 1
    return new_actuators, can_sends
