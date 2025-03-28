from cereal import car
from selfdrive.car.interfaces import CarInterfaceBase
from selfdrive.car.byd import carstate, carcontroller, values
from selfdrive.car.byd.values import get_can_parser

class CarInterface(CarInterfaceBase):
  @staticmethod
  def get_pid_accel_limits(CP):
    """根据车辆动力性能动态计算纵向控制加速度限制"""
    # 示例值：最大加速3m/s2，紧急制动-5m/s2（需根据电机扭矩和制动系统校准）
    return -5.0, 3.0

  @staticmethod
  def get_params(candidate, fingerprint, car_fw, disable_radar):
    ret = values.get_params(candidate, fingerprint)
    
    # 补充转向系统参数（需根据实车调整）
    ret.steerMaxBP = [0]          # 转向扭矩断点（单位：m/s）
    ret.steerMaxV = [1.0]         # 最大转向扭矩系数（比例因子）
    ret.maxSteeringTorque = 3.0   # 最大允许转向扭矩（Nm）
    
    # 纵向控制参数
    ret.stopAccel = -0.5          # 停止时保持的减速度
    ret.stoppingDecelRate = 0.8   # 减速度变化率
    return ret

  @staticmethod
  def init(CP, logcan, sendcan):
    """初始化CAN解析器，严格关联DBC文件"""
    return get_can_parser(CP)  # 使用values.py中定义的解析器

  def update(self, c):
    """更新车辆状态，并处理故障信号"""
    self.cp.update(int(c.can_valid))  # 更新CAN数据
    self.CS = carstate.CarState(self.CP).update(self.cp)
    
    # 检测关键故障（EPS故障或系统故障）
    self.CS.systemFault = self.CS.systemFault or (self.CS.EPS_Status == 3)
    return self.CS

  def apply(self, c):
    """生成控制指令并确保安全性"""
    # 强制禁用条件：故障状态或驾驶员接管
    if self.CS.systemFault or self.CS.steeringFault or self.CS.brakePressed:
      c.enabled = False
    
    # 计算最终执行器指令（包含超控逻辑）
    actuators = c.actuators
    actuators.accel = self.CI.calc_accel_override(actuators.accel, self.CS.aEgo)
    
    # 发送控制指令
    return carcontroller.CarController(self.CP, self.CS).update(
      c.enabled, self.CS, c.frame, actuators, c.pcm_cancel)