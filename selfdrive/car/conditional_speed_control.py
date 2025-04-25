import os
import sys
import time
import numpy as np
import traceback
import logging
from cereal import messaging
from common.params import Params

# 设置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("conditional_speed")

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
    try:
      logger.info("Initializing ConditionalSpeedControl")
      self.params = Params()
      self.params_memory = Params("/dev/shm/params")
      self.curve_detected = False
      self.condition_active = False
      self.curvature_mac = MovingAverageCalculator()
      self.status_value = 0
      self.current_curvature = 0.0
      logger.info("ConditionalSpeedControl initialized successfully")
    except Exception as e:
      logger.error(f"Error initializing ConditionalSpeedControl: {e}")
      logger.error(traceback.format_exc())
      raise

  def update(self, carState, enabled, modelData, road_curvature, v_ego):
    try:
      # 检查交通信号灯状态
      traffic_state = 0
      if hasattr(modelData, 'longitudinalPlan') and hasattr(modelData.longitudinalPlan, 'trafficState'):
        traffic_state = modelData.longitudinalPlan.trafficState
        logger.debug(f"Traffic state: {traffic_state}")

      # 获取曲率数据
      self.update_curvature(modelData)

      # 检查弯道状态
      self.check_curve(v_ego)

      # 根据不同条件设置SpeedFromPCM
      if traffic_state == 1:  # 红灯
        logger.info(f"红灯状态，设置SpeedFromPCM=0")
        self.params.put_int_nonblocking("SpeedFromPCM", 0)
        self.params_memory.put_int("ConditionalStatus", 16)  # 红灯状态码
      elif self.curve_detected:  # 弯道建议速度
        logger.info(f"弯道状态，设置SpeedFromPCM=2，曲率={self.current_curvature}")
        self.params.put_int_nonblocking("SpeedFromPCM", 2)
        self.params_memory.put_int("ConditionalStatus", 15)  # 弯道状态码
      else:  # 其他情况
        logger.debug(f"普通状态，设置SpeedFromPCM=1")
        self.params.put_int_nonblocking("SpeedFromPCM", 1)
        self.params_memory.put_int("ConditionalStatus", 0)
    except Exception as e:
      logger.error(f"Error in update: {e}")
      logger.error(traceback.format_exc())

  def update_curvature(self, modelData):
    try:
      # 从视觉模型获取路径预测点
      if hasattr(modelData, 'getPosition') and hasattr(modelData.getPosition(), 'getX'):
        position = modelData.getPosition()
        if position.getX().size() > 10 and position.getY().size() > 10:
          # 使用前方10米处的点来估算曲率
          idx = 10
          dx = position.getX()[idx]
          dy = position.getY()[idx]
          if dx > 0.1:  # 确保分母不为0
            self.current_curvature = abs(dy / (dx * dx))
            logger.debug(f"更新曲率: {self.current_curvature}")
      else:
        logger.debug("无法从modelData获取路径点")
    except Exception as e:
      logger.error(f"Error updating curvature: {e}")
      logger.error(traceback.format_exc())
      self.current_curvature = 0.0

  def check_curve(self, v_ego):
    try:
      # 曲率阈值随速度变化
      curvature_threshold = 0.001 * (1.0 + v_ego * 0.05)

      curve_detected = self.current_curvature > curvature_threshold
      curve_active = curve_detected and self.curve_detected

      self.curvature_mac.add_data(curve_detected or curve_active)
      self.curve_detected = self.curvature_mac.get_moving_average() >= 0.75  # 概率阈值

      if self.curve_detected:
        logger.debug(f"检测到弯道，曲率={self.current_curvature}，阈值={curvature_threshold}")
    except Exception as e:
      logger.error(f"Error checking curve: {e}")
      logger.error(traceback.format_exc())
      self.curve_detected = False

def conditional_speed_control_thread():
  try:
    logger.info("Starting conditional speed control thread...")

    # 初始化消息订阅
    logger.info("Initializing message subscriber...")
    sm = None
    retry_count = 0
    max_retries = 5

    while sm is None and retry_count < max_retries:
      try:
        sm = messaging.SubMaster(['carState', 'controlsState', 'modelV2'])
        logger.info("Successfully initialized message subscriber")
        break
      except Exception as e:
        retry_count += 1
        logger.error(f"Failed to initialize messaging (attempt {retry_count}/{max_retries}): {e}")
        logger.error(traceback.format_exc())
        time.sleep(1)

    if sm is None:
      logger.error("Failed to initialize messaging after max retries")
      return

    controller = ConditionalSpeedControl()
    logger.info("Entering main loop...")

    while True:
      try:
        sm.update()
        if sm.updated['carState']:
          car_state = sm['carState']
          controls_state = sm['controlsState']
          model = sm['modelV2']

          controller.update(
            carState=car_state,
            enabled=controls_state.enabled,
            modelData=model,
            road_curvature=1000.0 if not hasattr(model, 'getRoadCurvature') else model.getRoadCurvature(),
            v_ego=car_state.vEgo
          )
        time.sleep(0.1)
      except Exception as e:
        logger.error(f"Error in main loop: {e}")
        logger.error(traceback.format_exc())
        time.sleep(1)  # 出错时等待较长时间

  except Exception as e:
    logger.error(f"Fatal error in conditional_speed_control_thread: {e}")
    logger.error(traceback.format_exc())
    sys.exit(1)

def main():
  """
  主入口函数，供进程管理器调用
  """
  try:
    logger.info("Starting conditional speed control module...")
    conditional_speed_control_thread()
  except Exception as e:
    logger.error(f"Error in main: {e}")
    logger.error(traceback.format_exc())
    sys.exit(1)

if __name__ == "__main__":
  main()