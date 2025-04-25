import os
import sys
import time
import numpy as np
from cereal import messaging
from common.params import Params

class MovingAverageCalculator:
  def __init__(self, window_size=5):
    self.window_size = window_size
    self.data = []

  def add_data(self, value):
    self.data.append(1.0 if value else 0.0)
    if len(self.data) > self.window_size:
      self.data.pop(0)

  def get_moving_average(self):
    return sum(self.data) / len(self.data) if self.data else 0

  def reset_data(self):
    self.data = []

class ConditionalSpeedControl:
  def __init__(self):
    self.params = Params()
    self.params_memory = Params("/dev/shm/params")
    self.curve_detected = False
    self.condition_active = False
    self.curvature_mac = MovingAverageCalculator()
    self.status_value = 0
    self.current_curvature = 0.0

  def update(self, carState, enabled, modelData, road_curvature, v_ego):
    # 检查交通信号灯状态
    traffic_state = 0
    if hasattr(modelData, 'longitudinalPlan') and hasattr(modelData.longitudinalPlan, 'trafficState'):
      traffic_state = modelData.longitudinalPlan.trafficState

    # 获取曲率数据
    self.update_curvature(modelData)

    # 检查弯道状态
    self.check_curve(v_ego)

    # 根据不同条件设置SpeedFromPCM
    if traffic_state == 1:  # 红灯
      self.params.put_int_nonblocking("SpeedFromPCM", 0)
      self.params_memory.put_int("ConditionalStatus", 16)  # 红灯状态码
    elif self.curve_detected:  # 弯道建议速度
      self.params.put_int_nonblocking("SpeedFromPCM", 2)
      self.params_memory.put_int("ConditionalStatus", 15)  # 弯道状态码
    else:  # 其他情况
      self.params.put_int_nonblocking("SpeedFromPCM", 1)
      self.params_memory.put_int("ConditionalStatus", 0)

  def update_curvature(self, modelData):
    try:
      # 从modelV2获取车道线数据
      if hasattr(modelData, 'getLaneLines'):
        lane_lines = modelData.getLaneLines()
        lane_line_probs = modelData.getLaneLineProbs()

        # 计算平均曲率
        total_curvature = 0.0
        valid_lines = 0

        # 遍历所有车道线
        for i, lane_line in enumerate(lane_lines):
          if lane_line_probs[i] > 0.5:  # 只使用概率大于0.5的车道线
            total_curvature += abs(lane_line.getCurvature())
            valid_lines += 1

        # 更新当前曲率
        if valid_lines > 0:
          self.current_curvature = total_curvature / valid_lines
        else:
          self.current_curvature = 0.0

    except Exception as e:
      print(f"Error updating curvature: {e}")
      self.current_curvature = 0.0

  def check_curve(self, v_ego):
    # 使用实际曲率数据检测弯道
    # 曲率阈值随速度变化
    curvature_threshold = 0.001 * (1.0 + v_ego * 0.05)  # 速度越高，阈值越大

    curve_detected = abs(self.current_curvature) > curvature_threshold
    curve_active = curve_detected and self.curve_detected

    self.curvature_mac.add_data(curve_detected or curve_active)
    self.curve_detected = self.curvature_mac.get_moving_average() >= 0.75  # 概率阈值

def conditional_speed_control_thread():
  try:
    # 初始化消息订阅
    sm = messaging.SubMaster(['carState', 'controlsState', 'modelV2'])
    controller = ConditionalSpeedControl()

    while True:
      sm.update()
      if sm.updated['carState']:
        car_state = sm['carState']
        controls_state = sm['controlsState']
        model = sm['modelV2']

        controller.update(
          carState=car_state,
          enabled=controls_state.enabled,
          modelData=model,
          road_curvature=1000.0 if not hasattr(model, 'roadCurvature') else model.roadCurvature,
          v_ego=car_state.vEgo
        )
      time.sleep(0.1)

  except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

if __name__ == "__main__":
  conditional_speed_control_thread()