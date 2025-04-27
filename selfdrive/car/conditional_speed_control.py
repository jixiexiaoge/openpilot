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
      self.curve_detected = False
      self.condition_active = False
      self.curvature_mac = MovingAverageCalculator()
      self.status_value = 0
      self.current_curvature = 0.0
      self.previous_curvature = 0.0  # 添加上一次曲率值
      self.curvature_change = 0.0    # 添加曲率变化值
      self.lead_speed = 0.0          # 添加前车速度变量
      self.blinker_on = False        # 添加转向灯状态变量
      self.current_status = 0        # 当前状态码，不再使用内存参数

      # 记录最近的交通灯状态
      self.last_traffic_state = 0

      # 初始化时设置默认值
      try:
        self.params.put_int("SpeedFromPCM", 1)  # 使用非阻塞型方法可能在某些系统上不可用
        logger.info("成功初始化SpeedFromPCM参数为1")
      except Exception as e:
        logger.error(f"初始化SpeedFromPCM参数失败: {e}")

      logger.info("ConditionalSpeedControl initialized successfully")
    except Exception as e:
      logger.error(f"Error initializing ConditionalSpeedControl: {e}")
      logger.error(traceback.format_exc())
      raise

  def update(self, carState, enabled, modelData, road_curvature, v_ego):
    try:
      # 每次更新打印基本状态信息
      logger.debug(f"车速: {v_ego*3.6:.1f} km/h, 启用状态: {enabled}")

      # 检查交通信号灯状态
      traffic_state = 0

      # 尝试多种可能的数据结构路径来获取交通灯状态
      if hasattr(modelData, 'longitudinalPlan') and hasattr(modelData.longitudinalPlan, 'trafficState'):
        traffic_state = modelData.longitudinalPlan.trafficState
        logger.debug(f"从longitudinalPlan获取到交通灯状态: {traffic_state}")
      elif hasattr(modelData, 'trafficState'):
        traffic_state = modelData.trafficState
        logger.debug(f"直接从modelData获取到交通灯状态: {traffic_state}")

      # 如果交通灯状态变化，记录详细日志
      if traffic_state != self.last_traffic_state:
        logger.info(f"交通灯状态变化: {self.last_traffic_state} -> {traffic_state}")
        self.last_traffic_state = traffic_state

      # 打印整个modelData结构以便调试
      if hasattr(modelData, '__dict__'):
        logger.debug(f"ModelData结构: {modelData.__dict__}")

      # 获取曲率数据
      self.update_curvature(modelData)

      # 获取前车速度
      self.update_lead_vehicle_info(carState)

      # 检查转向灯状态
      self.check_blinker_status(carState)

      # 读取当前的SpeedFromPCM值，用于记录变化
      try:
        current_speed_from_pcm = self.params.get_int("SpeedFromPCM")
        logger.debug(f"当前SpeedFromPCM值: {current_speed_from_pcm}")
      except Exception as e:
        # 如果读取失败，假设为默认值1
        current_speed_from_pcm = 1
        logger.warning(f"无法读取SpeedFromPCM，使用默认值1: {e}")

      # 记录变化前的状态
      previous_status = self.current_status

      # 根据条件判断是否需要设置SpeedFromPCM为0或2

      # 条件1：红灯检测
      red_light_detected = traffic_state == 1
      logger.debug(f"红灯检测状态: {red_light_detected}")

      # 条件2：曲率超出范围 (-50, 50)
      high_curvature_detected = abs(self.current_curvature) > 50
      logger.debug(f"高曲率检测状态: {high_curvature_detected}, 当前曲率: {self.current_curvature:.2f}")

      # 条件3：前车速度低于15km/h
      slow_lead_detected = self.lead_speed < 15.0 / 3.6  # 转换为m/s
      logger.debug(f"前车低速检测状态: {slow_lead_detected}, 前车速度: {self.lead_speed*3.6:.2f} km/h")

      # 条件4：转向灯开启
      blinker_on = self.blinker_on
      logger.debug(f"转向灯状态: {blinker_on}")

      # 确定目标速度值和状态码
      target_speed_from_pcm = 1  # 默认为1
      target_status = 0
      reason = "普通状态"

      # 优先级判断：转向灯 > 红灯 > 高曲率 > 前车低速
      if blinker_on:
        target_speed_from_pcm = 2  # 转向灯开启时设置为2
        target_status = 18  # 转向灯状态码
        reason = "转向灯开启"
      elif red_light_detected:
        target_speed_from_pcm = 0
        target_status = 16  # 红灯状态码
        reason = "红灯状态"
      elif high_curvature_detected:
        target_speed_from_pcm = 0
        target_status = 15  # 曲率状态码
        reason = f"曲率超出范围，当前曲率={self.current_curvature:.2f}"
      elif slow_lead_detected:
        target_speed_from_pcm = 0
        target_status = 17  # 前车慢速状态码
        reason = f"前车低速，速度={self.lead_speed*3.6:.2f}km/h"

      # 只有在值发生变化时才更新并记录日志
      if current_speed_from_pcm != target_speed_from_pcm:
        logger.info(f"SpeedFromPCM变化: {current_speed_from_pcm} -> {target_speed_from_pcm}, 原因: {reason}")
        try:
          self.params.put_int("SpeedFromPCM", target_speed_from_pcm)
          logger.info(f"成功更新SpeedFromPCM为{target_speed_from_pcm}")
        except Exception as e:
          logger.error(f"更新SpeedFromPCM失败: {e}")
          logger.error(traceback.format_exc())
      else:
        logger.debug(f"保持SpeedFromPCM值不变: {current_speed_from_pcm}")

      # 更新状态码
      if previous_status != target_status:
        logger.info(f"状态变化: {previous_status} -> {target_status}, 原因: {reason}")
        self.current_status = target_status

      # 安全检查：如果车辆停止，确保重置状态
      if hasattr(carState, 'standstill') and carState.standstill:
        if current_speed_from_pcm != 1:
          logger.info("车辆停止，重置SpeedFromPCM为1")
          try:
            self.params.put_int("SpeedFromPCM", 1)
            logger.info("成功重置SpeedFromPCM为1")
          except Exception as e:
            logger.error(f"重置SpeedFromPCM失败: {e}")
            logger.error(traceback.format_exc())
        if previous_status != 0:
          self.current_status = 0

    except Exception as e:
      logger.error(f"Error in update: {e}")
      logger.error(traceback.format_exc())
      # 出错时恢复默认值
      try:
        self.params.put_int("SpeedFromPCM", 1)
      except Exception as e:
        logger.error(f"恢复默认值失败: {e}")
        logger.error(traceback.format_exc())

  def check_blinker_status(self, carState):
    try:
      # 检查左右转向灯状态
      left_blinker = False
      right_blinker = False

      if hasattr(carState, 'leftBlinker'):
        left_blinker = carState.leftBlinker

      if hasattr(carState, 'rightBlinker'):
        right_blinker = carState.rightBlinker

      # 更新转向灯状态 - 任一转向灯开启即视为开启
      previous_state = self.blinker_on
      self.blinker_on = left_blinker or right_blinker

      if self.blinker_on != previous_state:
        if self.blinker_on:
          logger.info("转向灯开启")
        else:
          logger.info("转向灯关闭")
    except Exception as e:
      logger.error(f"Error checking blinker status: {e}")
      logger.error(traceback.format_exc())
      self.blinker_on = False

  def update_lead_vehicle_info(self, carState):
    try:
      previous_lead_speed = self.lead_speed

      # 从carState中获取前车信息
      if hasattr(carState, 'leadOne') and hasattr(carState.leadOne, 'status') and carState.leadOne.status:
        # 前车存在且有效
        if hasattr(carState.leadOne, 'vRel'):
          # vRel是相对速度，需要加上自车速度得到绝对速度
          self.lead_speed = max(0.0, carState.vEgo + carState.leadOne.vRel)

          # 当前车速度变化超过5km/h时记录日志
          if abs(self.lead_speed - previous_lead_speed) * 3.6 > 5.0:
            logger.info(f"前车速度变化显著: {previous_lead_speed*3.6:.2f} -> {self.lead_speed*3.6:.2f} km/h")
          else:
            logger.debug(f"前车速度: {self.lead_speed*3.6:.2f} km/h")
        else:
          self.lead_speed = 100.0  # 设置一个大值，表示前车速度不低
          logger.debug("无法获取前车相对速度，假设前车速度不低")
      else:
        # 没有检测到前车
        if self.lead_speed < 50.0:  # 如果之前检测到前车且速度较低
          logger.info("前车不再被检测到")
        self.lead_speed = 100.0  # 设置一个大值，表示前车速度不低
    except Exception as e:
      logger.error(f"Error updating lead vehicle info: {e}")
      logger.error(traceback.format_exc())
      self.lead_speed = 100.0  # 出错时设为一个大值

  def update_curvature(self, modelData):
    try:
      # 保存上一次的曲率值用于计算变化
      self.previous_curvature = self.current_curvature

      # 从视觉模型获取路径预测点
      if hasattr(modelData, 'position') and modelData.position.x is not None and len(modelData.position.x) > 10:
        position = modelData.position
        idx = 10  # 使用前方10米处的点
        if len(position.x) > idx and len(position.y) > idx:
          dx = position.x[idx]
          dy = position.y[idx]
          if dx > 0.1:  # 确保分母不为0
            new_curvature = dy / (dx * dx) * 10000  # 直接计算为我们需要的范围
            self.current_curvature = new_curvature
            # 计算曲率变化
            self.curvature_change = self.current_curvature - self.previous_curvature

            # 当曲率变化显著时记录日志
            if abs(self.curvature_change) > 20:
              logger.info(f"曲率变化显著: {self.previous_curvature:.2f} -> {self.current_curvature:.2f}")
            else:
              logger.debug(f"更新曲率: {self.current_curvature:.2f}, 变化量: {self.curvature_change:.2f}")
      else:
        if hasattr(modelData, 'position'):
          logger.debug(f"路径点信息不完整: x存在={modelData.position.x is not None}, 长度={len(modelData.position.x) if modelData.position.x is not None else 0}")
        else:
          logger.debug("modelData中不包含position属性")
    except Exception as e:
      logger.error(f"Error updating curvature: {e}")
      logger.error(traceback.format_exc())
      self.current_curvature = 0.0

  def check_curve(self, v_ego):
    try:
      # 简化曲率检测，只检查是否超出±50的范围
      previous_curve_detected = self.curve_detected
      self.curve_detected = abs(self.current_curvature) > 50

      if self.curve_detected != previous_curve_detected:
        if self.curve_detected:
          logger.info(f"检测到高曲率弯道，曲率={self.current_curvature:.2f}")
        else:
          logger.info(f"退出高曲率弯道")
    except Exception as e:
      logger.error(f"Error checking curve: {e}")
      logger.error(traceback.format_exc())
      self.curve_detected = False

def conditional_speed_control_thread():
  try:
    # 启动时等待系统稳定，避免消息冲突
    logger.info("等待系统初始化完成...")
    time.sleep(10)

    logger.info("Starting conditional speed control thread...")

    # 初始化消息订阅
    logger.info("Initializing message subscriber...")
    sm = None
    retry_count = 0
    max_retries = 10  # 增加重试次数

    while sm is None and retry_count < max_retries:
      try:
        # 确保只订阅必要的消息
        services = ['carState', 'controlsState', 'modelV2']
        sm = messaging.SubMaster(services, poll=None, ignore_alive=True)
        logger.info("Successfully initialized message subscriber")
        break
      except Exception as e:
        retry_count += 1
        logger.error(f"Failed to initialize messaging (attempt {retry_count}/{max_retries}): {e}")
        logger.error(traceback.format_exc())
        time.sleep(2)  # 增加等待时间

    if sm is None:
      logger.error("Failed to initialize messaging after max retries")
      return

    # 初始化控制器
    controller = ConditionalSpeedControl()
    logger.info("Entering main loop...")

    update_count = 0
    while True:
      try:
        sm.update(1000)  # 设置超时时间，避免无限等待
        update_count += 1

        # 每100次更新记录一次心跳
        if update_count % 100 == 0:
          logger.info(f"模块运行正常，更新计数：{update_count}")

        if sm.updated['carState'] or sm.updated['modelV2']:
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
        time.sleep(0.1)  # 小的延迟，减少CPU使用
      except Exception as e:
        logger.error(f"Error in main loop: {e}")
        logger.error(traceback.format_exc())
        time.sleep(1)  # 出错时等待较长时间

  except Exception as e:
    logger.error(f"Fatal error in conditional_speed_control_thread: {e}")
    logger.error(traceback.format_exc())

def main():
  """
  主入口函数，供进程管理器调用
  """
  try:
    logger.info("Starting conditional speed control module...")
    # 创建一个子线程运行主要逻辑，这样即使出错也不会导致整个进程崩溃
    import threading
    t = threading.Thread(target=conditional_speed_control_thread, daemon=True)
    t.start()

    # 主线程保持运行，以防子线程崩溃
    while True:
      time.sleep(10)
      if not t.is_alive():
        logger.error("Main thread detected that worker thread died, restarting...")
        t = threading.Thread(target=conditional_speed_control_thread, daemon=True)
        t.start()

  except Exception as e:
    logger.error(f"Error in main: {e}")
    logger.error(traceback.format_exc())
  finally:
    # 确保退出时清理参数
    try:
      params = Params()
      params.put_int("SpeedFromPCM", 1)
      logger.info("清理完成，模块正常退出")
    except:
      pass
    sys.exit(0)

if __name__ == "__main__":
  main()