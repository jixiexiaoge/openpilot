from cereal import car
from opendbc.can.packer import CANPacker
from selfdrive.car.interfaces import CarControllerBase
from selfdrive.car.byd.values import DBC

class CarController(CarControllerBase):
  def __init__(self, CP, CarState):
    super().__init__(CP, CarState)
    self.CP = CP
    self.packer = CANPacker(DBC[CP.carFingerprint]["dbc"])  # 使用DBC文件初始化CAN打包器
    self.steer_angle_prev = 0.0  # 用于计算转向角变化率
    self.frame = 0

  def _compute_checksum(self, data):
    """示例校验和算法（需根据车辆实际逻辑实现）"""
    return sum(data) % 256  # 简单累加取模，实际可能用XOR或其他算法

  def update(self, enabled, CS, frame, actuators, pcm_cancel, ldw):
    can_sends = []

    # 每10ms发送一次控制报文（100Hz）
    if self.frame % 1 == 0:  # 假设主循环运行频率为100Hz
      # --- 生成MPC_CONTROL_OUTPUT报文（ID 808）---
      # 应用DBC缩放因子和范围限制
      desired_steer_deg = actuators.steerAngleDeg  # 直接使用角度指令
      desired_steer_raw = int(desired_steer_deg / 0.1)  # DBC缩放因子0.1（反向计算原始值）
      desired_steer_raw = clip(desired_steer_raw, -1000, 1000)  # 限制在DBC定义的范围

      # 计算转向角变化率（示例）
      steer_rate = (desired_steer_deg - self.steer_angle_prev) / 0.01  # 100Hz周期
      self.steer_angle_prev = desired_steer_deg

      # 构建CAN信号字典
      mpc_control_signals = {
        "MPC_Steering_Angle": desired_steer_raw,
        "MPC_Target_Speed": int(actuators.accel * 100),  # 假设accel单位为m/s，DBC缩放因子0.01
        "MPC_Acceleration": int(actuators.accel / 0.001),  # DBC缩放因子0.001
        "MPC_Control_Active": 1 if enabled else 0,
        "MPC_Control_Ready": 1,
      }

      # 生成原始CAN数据并计算校验和
      dat = self.packer.make_can_msg("MPC_CONTROL_OUTPUT", 0, mpc_control_signals)[2]
      mpc_control_signals["MPC_Checksum"] = self._compute_checksum(dat)
      
      # 添加到发送列表
      can_sends.append(self.packer.make_can_msg("MPC_CONTROL_OUTPUT", 0, mpc_control_signals))

    # --- 其他控制报文（如油门、刹车）---
    # 示例：发送油门指令（THROTTLE_POSITION ID 803）
    throttle_percent = int(actuators.gas * 100 / 0.4)  # DBC缩放因子0.4（0-100%对应0-40）
    can_sends.append(self.packer.make_can_msg("THROTTLE_POSITION", 0, {
      "Throttle_Percent": clip(throttle_percent, 0, 255),
      "Throttle_Valid": 1 if enabled else 0,
    }))

    self.frame += 1
    return can_sends