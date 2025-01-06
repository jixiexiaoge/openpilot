from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_driver_steer_torque_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.mazda import mazdacan
from opendbc.car.mazda.values import CarControllerParams, Buttons

VisualAlert = structs.CarControl.HUDControl.VisualAlert


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.apply_steer_last = 0
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.brake_counter = 0

  def update(self, CC, CS, now_nanos):
    can_sends = []

    apply_steer = 0

    if CC.latActive:
      # 计算转向并设置由于驾驶员扭矩导致的限制
      new_steer = int(round(CC.actuators.steer * CarControllerParams.STEER_MAX))
      apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last,
                                                     CS.out.steeringTorque, CarControllerParams)

    if CC.cruiseControl.cancel:
      # 如果踩下刹车，让我们等待超过70毫秒再尝试禁用巡航，以避免与原厂系统的竞争条件，
      # 在这种情况下，来自openpilot的第二次取消将禁用巡航“主开”。巡航控制消息以50hz运行。
      # 70毫秒允许我们读取3条消息，并且在我们尝试取消之前很可能同步状态。
      self.brake_counter = self.brake_counter + 1
      if self.frame % 10 == 0 and not (CS.out.brakePressed and self.brake_counter < 7):
        # 如果在openpilot未启用时启用了原厂ACC，则取消原厂ACC
        # 以10hz的频率发送，直到我们与原厂ACC状态同步
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.CANCEL))
    else:
      self.brake_counter = 0
      if CC.cruiseControl.resume and self.frame % 5 == 0:
        # Mazda Stop and Go需要在汽车停止超过3秒时按下RES按钮（或踩油门）
        # 当规划器希望汽车移动时发送恢复按钮
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.RESUME))

    self.apply_steer_last = apply_steer


    # 发送HUD警报
    if self.frame % 50 == 0:
      ldw = CC.hudControl.visualAlert == VisualAlert.ldw
      steer_required = CC.hudControl.visualAlert == VisualAlert.steerRequired
      # TODO: 找到一种方法来静音警告声音，以便我们可以添加更多的HUD警报
      steer_required = steer_required and CS.lkas_allowed_speed
      can_sends.append(mazdacan.create_alert_command(self.packer, CS.cam_laneinfo, ldw, steer_required))

    # 发送转向命令
    can_sends.append(mazdacan.create_steering_control(self.packer, self.CP,
                                                      self.frame, apply_steer, CS.cam_lkas))

    new_actuators = CC.actuators.as_builder()
    new_actuators.steer = apply_steer / CarControllerParams.STEER_MAX
    new_actuators.steerOutputCan = apply_steer

    self.frame += 1
    return new_actuators, can_sends
