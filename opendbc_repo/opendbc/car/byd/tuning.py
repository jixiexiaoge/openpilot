#!/usr/bin/env python3
import numpy as np

class Tuning:
  # 是否启用自动调谐功能
  AUTO_TUNING = True  # 设置为True启用自动调谐，False禁用

  # BYD车型的转向力矩参数
  # 这些是默认值，可以通过自动调谐功能进行优化
  LAT_ACCEL_FACTOR = 2.5  # 横向加速度因子
  FRICTION = 0.05  # 摩擦系数

  # 转向力矩控制相关参数
  STEER_MAX = 800  # 最大转向力矩
  STEER_DELTA_UP = 10  # 每个刷新周期转向力矩上升值
  STEER_DELTA_DOWN = 25  # 每个刷新周期转向力矩下降值
  STEER_THRESHOLD = 15  # 转向力矩阈值

  # 辅助过滤参数
  FILTER_LATACCEL = 20.0  # 横向加速度过滤器系数

  @classmethod
  def get_torque_params(cls, car_model):
    """
    根据车型获取特定的转向参数
    Args:
        car_model: 车型名称
    Returns:
        转向参数字典
    """
    # 可以为不同的BYD车型定制不同的参数
    if "HAN" in car_model:
      return {
        "LAT_ACCEL_FACTOR": 2.8,
        "FRICTION": 0.06
      }
    elif "TANG" in car_model:
      return {
        "LAT_ACCEL_FACTOR": 3.0,
        "FRICTION": 0.07
      }
    elif "SONG" in car_model:
      return {
        "LAT_ACCEL_FACTOR": 2.6,
        "FRICTION": 0.055
      }
    elif "SEAL" in car_model:
      return {
        "LAT_ACCEL_FACTOR": 2.5,
        "FRICTION": 0.05
      }
    else:
      # 默认参数
      return {
        "LAT_ACCEL_FACTOR": cls.LAT_ACCEL_FACTOR,
        "FRICTION": cls.FRICTION
      }

  @staticmethod
  def apply_deadzone(torque, deadzone):
    """
    应用死区处理
    Args:
        torque: 原始转向力矩
        deadzone: 死区大小
    Returns:
        应用死区后的转向力矩
    """
    if torque > deadzone:
      return torque - deadzone
    elif torque < -deadzone:
      return torque + deadzone
    else:
      return 0.0

  @staticmethod
  def limit_torque(torque, max_torque):
    """
    限制转向力矩在合理范围内
    Args:
        torque: 原始转向力矩
        max_torque: 最大转向力矩
    Returns:
        限制后的转向力矩
    """
    return np.clip(torque, -max_torque, max_torque)