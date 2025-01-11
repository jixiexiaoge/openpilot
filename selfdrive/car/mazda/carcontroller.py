# 导入必要的模块
from cereal import car  # 导入车辆相关定义
from opendbc.can.packer import CANPacker  # 导入CAN打包器
from openpilot.selfdrive.car import apply_driver_steer_torque_limits  # 导入转向扭矩限制函数
from openpilot.selfdrive.car.interfaces import CarControllerBase  # 导入车辆控制器基类
from openpilot.selfdrive.car.mazda import mazdacan  # 导入马自达CAN通信模块
from openpilot.selfdrive.car.mazda.values import CarControllerParams, Buttons  # 导入控制参数和按钮定义
from openpilot.common.params import Params  # 导入参数管理模块
from openpilot.selfdrive.controls.lib.drive_helpers import V_CRUISE_MAX  # 导入最大巡航速度
from openpilot.common.conversions import Conversions as CV  # 导入单位转换工具

# 初始化共享内存参数
params_memory = Params("/dev/shm/params")

# 定义视觉警告类型
VisualAlert = car.CarControl.HUDControl.VisualAlert

class CarController(CarControllerBase):
  """马自达车辆控制器类"""
  def __init__(self, dbc_name, CP, VM):
    """初始化车辆控制器"""
    self.CP = CP  # 车辆参数
    self.apply_steer_last = 0  # 上一次应用的转向值
    self.packer = CANPacker(dbc_name)  # CAN消息打包器
    self.brake_counter = 0  # 制动计数器
    self.frame = 0  # 帧计数器

  def update(self, CC, CS, now_nanos, frogpilot_variables):
    """更新车辆控制"""
    # 获取HUD控制相关参数
    hud_control = CC.hudControl
    hud_v_cruise = hud_control.setSpeed  # 设定的巡航速度
    if hud_v_cruise > 70:
      hud_v_cruise = 0  # 限制巡航速度显示
    actuators = CC.actuators  # 获取执行器
    accel = actuators.accel  # 获取加速度值

    can_sends = []  # CAN发送消息列表

    apply_steer = 0  # 初始化转向控制值

    if CC.latActive:  # 如果横向控制激活
      # 计算转向值并应用驾驶员扭矩限制
      new_steer = int(round(CC.actuators.steer * CarControllerParams.STEER_MAX))
      apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last,
                                                    CS.out.steeringTorque, CarControllerParams)

    if CC.cruiseControl.cancel:  # 如果需要取消巡航控制
      # 如果踩下制动踏板，等待>70ms再尝试禁用巡航控制
      # 这是为了避免与车辆原厂系统的竞争条件，其中openpilot的第二次取消
      # 将禁用巡航控制的'主开关'。巡航控制消息以50Hz运行。
      # 70ms允许我们在尝试取消之前读取3条消息并很可能同步状态。
      self.brake_counter = self.brake_counter + 1
      if self.frame % 10 == 0 and not (CS.out.brakePressed and self.brake_counter < 7):
        # 当OP未接管时，如果启用了原厂ACC则取消它
        # 以10Hz的频率发送，直到与原厂ACC状态同步
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.CANCEL))
    else:
      self.brake_counter = 0
      if CC.cruiseControl.resume and self.frame % 5 == 0:
        # 如果车辆停止超过3秒，马自达停走功能需要按下RES按钮（或油门）
        # 当规划器希望车辆移动时发送Resume按钮信号
        can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.RESUME))
      # ACC控制信息发送
      elif frogpilot_variables.CSLC:
        if CC.enabled and self.frame % 10 == 0 and CS.cruise_buttons == Buttons.NONE and not CS.out.gasPressed and not CS.distance_button:
          slcSet = get_set_speed(self, hud_v_cruise)  # 获取设定速度
          can_sends.extend(mazdacan.create_mazda_acc_spam_command(self.packer, self, CS, slcSet, CS.out.vEgo, frogpilot_variables, accel))

    self.apply_steer_last = apply_steer  # 保存本次转向值

    # 发送HUD警告
    if self.frame % 50 == 0:
      ldw = CC.hudControl.visualAlert == VisualAlert.ldw  # 车道偏离警告
      steer_required = CC.hudControl.visualAlert == VisualAlert.steerRequired  # 需要转向警告
      # TODO: 找到一种方法来消除声音警告，这样我们就可以添加更多的HUD警告
      steer_required = steer_required and CS.lkas_allowed_speed
      can_sends.append(mazdacan.create_alert_command(self.packer, CS.cam_laneinfo, ldw, steer_required))

    # 发送转向控制命令
    can_sends.append(mazdacan.create_steering_control(self.packer, self.CP,
                                                     self.frame, apply_steer, CS.cam_lkas))

    # 更新执行器状态
    new_actuators = CC.actuators.copy()
    new_actuators.steer = apply_steer / CarControllerParams.STEER_MAX
    new_actuators.steerOutputCan = apply_steer

    self.frame += 1  # 更新帧计数器
    return new_actuators, can_sends

def get_set_speed(self, hud_v_cruise):
  """获取设定速度"""
  # 限制巡航速度不超过最大值
  v_cruise = min(hud_v_cruise, V_CRUISE_MAX * CV.KPH_TO_MS)

  # 获取CSLC（自定义速度限制控制）速度
  v_cruise_slc: float = 0.
  v_cruise_slc = params_memory.get_float("CSLCSpeed")

  # 如果有CSLC速度设定，则使用CSLC速度
  if v_cruise_slc > 0.:
    v_cruise = v_cruise_slc
  return v_cruise
