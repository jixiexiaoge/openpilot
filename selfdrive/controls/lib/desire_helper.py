from cereal import log
from openpilot.common.conversions import Conversions as CV
from openpilot.common.realtime import DT_MDL
import numpy as np
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.common.params import Params
from collections import deque
#new
from openpilot.selfdrive.selfdrived.events import Events
import time

EventName = log.OnroadEvent.EventName
LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
TurnDirection = log.Desire

LANE_CHANGE_SPEED_MIN = 30 * CV.KPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.

BLINKER_NONE = 0
BLINKER_LEFT = 1
BLINKER_RIGHT = 2
BLINKER_BOTH = 3

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.none,
    LaneChangeState.laneChangeFinishing: log.Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeRight,
  },
}
TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}

def calculate_lane_width_frog(lane, current_lane, road_edge):
  lane_x, lane_y = np.array(lane.x), np.array(lane.y)
  edge_x, edge_y = np.array(road_edge.x), np.array(road_edge.y)
  current_x, current_y = np.array(current_lane.x), np.array(current_lane.y)

  lane_y_interp = np.interp(current_x, lane_x[lane_x.argsort()], lane_y[lane_x.argsort()])
  road_edge_y_interp = np.interp(current_x, edge_x[edge_x.argsort()], edge_y[edge_x.argsort()])

  distance_to_lane = np.mean(np.abs(current_y - lane_y_interp))
  distance_to_road_edge = np.mean(np.abs(current_y - road_edge_y_interp))

  return min(distance_to_lane, distance_to_road_edge), distance_to_road_edge

def calculate_lane_width(lane, lane_prob, current_lane, road_edge):
  t = 1.0 # 约1秒前的车道
  current_lane_y = np.interp(t, ModelConstants.T_IDXS, current_lane.y)
  lane_y = np.interp(t, ModelConstants.T_IDXS, lane.y)
  distance_to_lane = abs(current_lane_y - lane_y)
  #if lane_prob < 0.3:# 차선이 없으면 없는것으로 간주시킴.
  #  distance_to_lane = min(2.0, distance_to_lane)
  road_edge_y = np.interp(t, ModelConstants.T_IDXS, road_edge.y)
  distance_to_road_edge = abs(current_lane_y - road_edge_y)
  distance_to_road_edge_far = abs(current_lane_y - np.interp(2.0, ModelConstants.T_IDXS, road_edge.y))
  return min(distance_to_lane, distance_to_road_edge), distance_to_road_edge, distance_to_road_edge_far, lane_prob > 0.5

def calculate_lane_width_only(lane, current_lane, t_offset):
  t = 1.0 + max(0, min(1, t_offset)) # 把t_offset限制[0,1]之间
  current_lane_y = np.interp(t, ModelConstants.T_IDXS, current_lane.y)
  lane_y = np.interp(t, ModelConstants.T_IDXS, lane.y)
  distance_to_lane = abs(current_lane_y - lane_y)
  return distance_to_lane

class ExistCounter:
  def __init__(self):
    self.counter = 0
    self.true_count = 0
    self.false_count = 0
    self.threshold = int(0.2 / DT_MDL)  # 노이즈를 무시하기 위한 임계값 설정

  def update(self, exist_flag):
    if exist_flag:
      self.true_count += 1
      self.false_count = 0  # false count 초기화
      if self.true_count >= self.threshold:
          self.counter = max(self.counter + 1, 1)
    else:
      self.false_count += 1
      self.true_count = 0  # true count 초기화
      if self.false_count >= self.threshold:
          self.counter = min(self.counter - 1, -1)

    return self.true_count

class DesireHelper:
  def __init__(self):
    self.params = Params()
    self.frame = 0
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.lane_change_ll_prob = 1.0
    self.keep_pulse_timer = 0.0
    self.prev_desire_enabled = False
    self.desire = log.Desire.none
    self.turn_direction = TurnDirection.none
    self.enable_turn_desires = True
    self.atc_active = 0
    self.desireLog = ""
    self.lane_width_left = 0
    self.lane_width_right = 0
    self.lane_width_left_diff = 0
    self.lane_width_right_diff = 0
    #self.lane_width_left_far = 0
    #self.lane_width_right_far = 0
    self.lane_width_left_far_diff = 0
    self.lane_width_right_far_diff = 0
    self.lane_width_curr = 0
    self.lane_width_left_curr_diff = 3.5
    self.lane_width_right_curr_diff = 3.5
    self.distance_to_road_edge_left = 0
    self.distance_to_road_edge_right = 0
    self.distance_to_road_edge_left_avg = 0
    self.distance_to_road_edge_right_avg = 0
    self.distance_to_road_edge_left_far = 0
    self.distance_to_road_edge_right_far = 0
    self.blinker_ignore = False
    self.blinker_ignore_last = False

    self.lane_exist_left_count = ExistCounter()
    self.lane_exist_right_count = ExistCounter()
    self.lane_exist_curr_count = ExistCounter()
    self.lane_width_left_count = ExistCounter()
    self.lane_width_right_count = ExistCounter()
    self.road_edge_left_count = ExistCounter()
    self.road_edge_right_count = ExistCounter()
    self.available_left_lane = False
    self.available_right_lane = False
    self.available_left_edge = False
    self.available_right_edge = False
    self.lane_width_left_queue = deque(maxlen=int(1.0/DT_MDL))
    self.lane_width_right_queue = deque(maxlen=int(1.0/DT_MDL))
    self.lane_width_curr_queue = deque(maxlen=int(1.0 / DT_MDL))
    self.lane_width_left_far_queue = deque(maxlen=int(1.0/DT_MDL))
    self.lane_width_right_far_queue = deque(maxlen=int(1.0/DT_MDL))
    self.distance_to_road_edge_left_queue = deque(maxlen=int(1.0 / DT_MDL))
    self.distance_to_road_edge_right_queue = deque(maxlen=int(1.0 / DT_MDL))

    self.lane_available_last = False
    self.edge_available_last = False
    self.object_detected_count = 0
    self.lane_available_trigger = False #
    self.lane_appeared = False #

    self.laneChangeNeedTorque = 0
    self.laneChangeBsd = 0
    self.laneChangeDelay = 0
    self.lane_change_delay = 0.0
    self.driver_blinker_state = BLINKER_NONE
    self.atc_type = ""
    self.atc_blinker_state = BLINKER_NONE

    self.carrot_lane_change_count = 0
    self.carrot_cmd_index_last = 0
    self.carrot_blinker_state = BLINKER_NONE
    self.carrot_overtake_cmd = False

    self.turn_desire_state = False
    self.desire_disable_count = 0
    self.turn_disable_count = 0 #
    self.blindspot_detected_counter = 0
    self.auto_lane_change_enable = False
    #self.next_lane_change = False #

    #new
    self.allowContinuousLaneChange = 0
    self.autoTurnInNotRoadEdge = 0
    self.continuousLaneChangeCnt = 0
    self.continuousLaneChangeInterval = 5
    self.atc_turn_cnt = 0
    #self.autoDoForkCheckDist = 10
    #self.autoDoForkCheckDistH = 20
    self.roadType = -1
    self.autoTurnLeft = 0
    self.showDebugLog = 0
    self.autoNaviCountDownMode = 0
    self.lane_change_disable_count = self.continuousLaneChangeInterval
    self.lane_change_disable = False
    self.lane_cnt_time = -1
    self.lane_count_last = -1
    self.lane_count_stab_cnt = int(1 / DT_MDL)
    self.trigger_name = ""
    self.trigger_type = 0
    self.newLaneWidthDiff = 0.8
    self.autoEnTurnNewLaneTimeH = 0
    self.autoEnTurnNewLaneTime = 0
    self.events = Events()
    self.event_type = 0
    self.event_type_id = 0
    self.left_sec = 100
    self.max_left_sec = 100
    self.dh_left_sec = 100
    self.lane_change_delay_start = 0
    self.event_test_frame = 0
    self.lane_change_audio_delay = 0
    self.atc_resume = -1
    self.object_detected_count_new = 0
    self.min_object_detected_count = int(-60.0 / DT_MDL)  # 最小计时
    self.min_object_detected_count_thr = int(-2.0 / DT_MDL)  # 判断是否无障碍的持续时间
    self.side_object_detected = False
    self.min_drel_vego_time = 1.0
    self.min_vrel_vego_time = 1.0
    self.bsdDelayTime = 2.
    self.sideBsdDelayTime = 2.
    self.sideRelDistTime = 1.
    self.sidevRelDistTime = 1.
    self.atc_cancel = False
    self.atc_cancel_delay = 0
    self.leftFrontBlind = 0
    self.rightFrontBlind = 0
    self.xroadcate = -1
    self.last_lane_count = 0
    self.blinker = "none"
    self.blinker_val = BLINKER_NONE
    self.stockBlinkerCtrl = 0
    self.blinkerMode = 0
    self.autoLaneChangeMinSpeed = 0
    self.lane_change_state_last = LaneChangeState.off
    self.lane_change_state_prev = LaneChangeState.off
    self.driver_lane_change_delay = 0.0
    #new

  def lane_change_audio(self, enable, turn_type, param=0):
    if not enable:
      return
    if turn_type == 1: #准备变道
      #self.events.add(EventName.audioPreLaneChange)
      pass
    elif turn_type == 2: #变道
      #self.events.add(EventName.audioLaneChange)
      pass
    elif turn_type == 3: #转弯
      #self.events.add(EventName.audioTurn)
      pass
    elif turn_type == 4: #领航已退出
      pass
    #保存事件类型
    self.event_type = turn_type
    self.event_type_id += 1
    if self.event_type_id > 255:
      self.event_type_id = 0

  # self.distance_to_road_edge_left/self.distance_to_road_edge_right 车辆当前位置到1秒前方车道中心线到道路边缘的距离。
  # self.distance_to_road_edge_left_far/self.distance_to_road_edge_right_far 车辆当前位置到2秒前方车道中心线到道路边缘的距离
  # modeldata.laneLines[0] - 左侧外车道线（左侧车道的外边界）
  # modeldata.laneLines[1] - 当前车道的左边界线
  # modeldata.laneLines[2] - 当前车道的右边界线
  # modeldata.laneLines[3] - 右侧外车道线（右侧车道的外边界）
  # modeldata.roadEdges[0] - 左侧道路边缘数据
  # modeldata.roadEdges[1] - 右侧道路边缘数据
  # modeldata.laneLineProbs[x]为车道线的置信度，一般大于0.5则认为有车道线
  # 置信度大于0.5，则lane_prob_left/lane_prob_right为True
  def check_lane_state(self, modeldata, v_ego):
    #根据距离计算需要提前的时间
    #if 0 <= self.roadType <= 1:
    #  do_fork_dist = self.autoDoForkCheckDistH
    #else:
    #  do_fork_dist = self.autoDoForkCheckDist
    #if do_fork_dist == 0:
    #  t_offset = 0
    #else:
    #  t_offset = min(float(do_fork_dist) / max(1., v_ego), 1.) if v_ego > 0 else 1.0
    t_offset = 1

    lane_width_left, self.distance_to_road_edge_left, self.distance_to_road_edge_left_far, lane_prob_left = calculate_lane_width(modeldata.laneLines[0], modeldata.laneLineProbs[0],
                                                                                                 modeldata.laneLines[1], modeldata.roadEdges[0])
    lane_width_right, self.distance_to_road_edge_right, self.distance_to_road_edge_right_far, lane_prob_right = calculate_lane_width(modeldata.laneLines[3], modeldata.laneLineProbs[3],
                                                                                                    modeldata.laneLines[2], modeldata.roadEdges[1])
    lane_width_curr = calculate_lane_width_only(modeldata.laneLines[1], modeldata.laneLines[2], 0)
    if t_offset > 0:
      lane_width_left_far = calculate_lane_width_only(modeldata.laneLines[0], modeldata.laneLines[1], t_offset)
      lane_width_right_far = calculate_lane_width_only(modeldata.laneLines[2], modeldata.laneLines[3], t_offset)
    else:
      lane_width_left_far = lane_width_left
      lane_width_right_far = lane_width_right

    #左右侧车道存在计数
    self.lane_exist_left_count.update(lane_prob_left)
    self.lane_exist_right_count.update(lane_prob_right)
    self.lane_exist_curr_count.update(modeldata.laneLineProbs[1] > 0.5 and modeldata.laneLineProbs[2] > 0.5)

    #对左右车道的宽度进行滤波
    self.lane_width_left_queue.append(lane_width_left)
    self.lane_width_right_queue.append(lane_width_right)
    self.lane_width_curr_queue.append(lane_width_curr)
    if t_offset > 0:
      self.lane_width_left_far_queue.append(lane_width_left_far)
      self.lane_width_right_far_queue.append(lane_width_right_far)
    self.distance_to_road_edge_left_queue.append(self.distance_to_road_edge_left)
    self.distance_to_road_edge_right_queue.append(self.distance_to_road_edge_right)

    self.lane_width_left = np.mean(self.lane_width_left_queue)
    self.lane_width_right = np.mean(self.lane_width_right_queue)
    self.lane_width_curr = np.mean(self.lane_width_curr_queue)
    #self.lane_width_left_far = np.mean(self.lane_width_left_far_queue)
    #self.lane_width_right_far = np.mean(self.lane_width_right_far_queue)
    self.distance_to_road_edge_left_avg = np.mean(self.distance_to_road_edge_left_queue)
    self.distance_to_road_edge_right_avg = np.mean(self.distance_to_road_edge_right_queue)

    #self.lane_width_left_diff - 左侧车道宽度的变化量
    #[-1]为最新的入列的车道宽度，[0]为最旧的车道宽度，一般width_left_diff>0.5表示车道正在变宽(一般这种情况是出现了新的车道)
    self.lane_width_left_diff = self.lane_width_left_queue[-1] - self.lane_width_left_queue[0]
    self.lane_width_right_diff = self.lane_width_right_queue[-1] - self.lane_width_right_queue[0]
    if t_offset > 0:
      self.lane_width_left_far_diff = self.lane_width_left_far_queue[-1] - self.lane_width_left_far_queue[0]
      self.lane_width_right_far_diff = self.lane_width_right_far_queue[-1] - self.lane_width_right_far_queue[0]
    else:
      self.lane_width_left_far_diff = self.lane_width_left_diff
      self.lane_width_right_far_diff = self.lane_width_right_diff

    #当前车道和侧面车道宽度的差值
    self.lane_width_left_curr_diff =  self.lane_width_curr - self.lane_width_left
    self.lane_width_right_curr_diff = self.lane_width_curr - self.lane_width_right

    #车道宽度和到路沿距离大于2.5m的次数
    min_lane_width = 2.5
    self.lane_width_left_count.update(self.lane_width_left > min_lane_width)
    self.lane_width_right_count.update(self.lane_width_right > min_lane_width)
    self.road_edge_left_count.update(self.distance_to_road_edge_left > min_lane_width)
    self.road_edge_right_count.update(self.distance_to_road_edge_right > min_lane_width)
    #当大于2.5米的次数超过0.2秒时，则认为车道或路沿存在
    available_count = int(0.2 / DT_MDL)
    self.available_left_lane = self.lane_width_left_count.counter > available_count
    self.available_right_lane = self.lane_width_right_count.counter > available_count
    self.available_left_edge = self.road_edge_left_count.counter > available_count and self.distance_to_road_edge_left_far > min_lane_width
    self.available_right_edge = self.road_edge_right_count.counter > available_count and self.distance_to_road_edge_right_far > min_lane_width

  def check_desire_state(self, modeldata, carstate):
    #这个机制确保车辆在完成转向操作后有一个安全的缓冲期，避免在转向过程中或刚完成转向时进行车道变更
    #desire_state[1] - 左转意图 (desireStateTurnLeft)
    #desire_state[2] - 右转意图 (desireStateTurnRight)
    desire_state  = modeldata.meta.desireState
    self.turn_desire_state = (desire_state[1] + desire_state[2]) > 0.1 #两个值之和大于0.1表示检测到转向意图
    if self.turn_desire_state:
      self.desire_disable_count = int(2.0/DT_MDL) #转向2秒后才允许变道
    else:
      self.desire_disable_count = max(0, self.desire_disable_count - 1)

    if abs(carstate.steeringAngleDeg) > 80:
      self.turn_disable_count = int(10.0/DT_MDL)
    else:
      self.turn_disable_count = max(0, self.turn_disable_count - 1)
    #print(f"desire_state = {desire_state}, turn_desire_state = {self.turn_desire_state}, disable_count = {self.desire_disable_count}")

  def update(self, carstate, modeldata, lateral_active, lane_change_prob, carrotMan, radarState):
    if self.frame % 100 == 0:
      self.laneChangeNeedTorque = self.params.get_int("LaneChangeNeedTorque")
      self.laneChangeBsd = self.params.get_int("LaneChangeBsd")
      self.laneChangeDelay = self.params.get_float("LaneChangeDelay") * 0.1
      #new
      self.allowContinuousLaneChange = self.params.get_int("ContinuousLaneChange")
      self.autoTurnInNotRoadEdge = self.params.get_int("AutoTurnInNotRoadEdge")
      self.continuousLaneChangeCnt = self.params.get_int("ContinuousLaneChangeCnt")
      self.continuousLaneChangeInterval = self.params.get_int("ContinuousLaneChangeInterval")
      #self.autoDoForkCheckDist = self.params.get_int("AutoDoForkCheckDist")
      #self.autoDoForkCheckDistH = self.params.get_int("AutoDoForkCheckDistH")
      self.roadType = self.params.get_int("RoadType")
      self.autoTurnLeft = self.params.get_int("AutoTurnLeft")
      self.showDebugLog = self.params.get_int("ShowDebugLog")
      self.autoNaviCountDownMode = self.params.get_int("AutoNaviCountDownMode")
      self.newLaneWidthDiff = self.params.get_float("NewLaneWidthDiff") * 0.1
      self.autoEnTurnNewLaneTimeH = self.params.get_int("AutoEnTurnNewLaneTimeH")
      self.autoEnTurnNewLaneTime = self.params.get_int("AutoEnTurnNewLaneTime")
      self.bsdDelayTime = self.params.get_float("BsdDelayTime") * 0.1
      self.sideBsdDelayTime = self.params.get_int("SideBsdDelayTime") * 0.1
      self.sideRelDistTime = self.params.get_int("SideRelDistTime") * 0.1
      self.sidevRelDistTime = self.params.get_int("SidevRelDistTime") * 0.1
      self.min_drel_vego_time = self.sideRelDistTime
      self.min_vrel_vego_time = self.sidevRelDistTime
      self.min_object_detected_count_thr = int(-1*self.sideBsdDelayTime/DT_MDL)
      self.lane_count_stab_cnt = int(self.params.get_float("LaneStabTime") * 0.1/DT_MDL)
      self.stockBlinkerCtrl = self.params.get_int("StockBlinkerCtrl")
      self.blinkerMode = self.params.get_int("BlinkerMode")
      self.autoLaneChangeMinSpeed = self.params.get_int("AutoLaneChangeMinSpeed")
      #new
    self.frame += 1
    lane_change_state = self.lane_change_state
    blinker_val = self.blinker_val

    self.xroadcate = carrotMan.roadCate
    #if self.roadType >= 0: #大于0表示用户指定道路类型
    #  self.xroadcate = self.roadType

    # new
    if 0 <= self.xroadcate <= 1: #高速
      autoEnTurnNewLaneTime = self.autoEnTurnNewLaneTimeH
    else:
      autoEnTurnNewLaneTime = self.autoEnTurnNewLaneTime
    # new

    carrot_lane_change_count = self.carrot_lane_change_count
    self.carrot_lane_change_count = max(0, self.carrot_lane_change_count - 1)
    if carrot_lane_change_count != self.carrot_lane_change_count and carrot_lane_change_count == 0:
      print(f"---[{time.strftime('%H:%M:%S')}]carrot_lane_change_count=0")
    self.driver_lane_change_delay = max(0, self.driver_lane_change_delay - DT_MDL)
    self.lane_change_delay = max(0, self.lane_change_delay - DT_MDL)
    self.lane_change_audio_delay = max(0, self.lane_change_audio_delay - DT_MDL)
    if self.lane_change_delay_start:
      left_sec = min(10, int(self.lane_change_delay)) # 计算倒时计时间
      if self.left_sec != left_sec and self.lane_change_audio_delay <= 0:
        self.dh_left_sec = left_sec
        self.left_sec = left_sec

    #延时自动变道倒计时
    if self.lane_change_disable:
      self.lane_change_disable_count = max(0, self.lane_change_disable_count - DT_MDL)
      left_sec = min(10, int(self.lane_change_disable_count)) # 计算倒时计时间
      if self.left_sec != left_sec and self.lane_change_audio_delay <= 0:
        self.dh_left_sec = left_sec
        self.left_sec = left_sec

    v_ego = carstate.vEgo
    if self.autoLaneChangeMinSpeed < 0:
      below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN
    else:
      below_lane_change_speed = v_ego < (self.autoLaneChangeMinSpeed * CV.KPH_TO_MS)

    ##### check lane state
    self.check_lane_state(modeldata, v_ego)
    self.check_desire_state(modeldata, carstate) #此函数会控制 self.desire_disable_count 的数值

    #### check driver's blinker state
    driver_blinker_state = carstate.leftBlinker * 1 + carstate.rightBlinker * 2 #来自车辆的转向灯数据，1-左转身灯，2-右转向灯，3左右均有
    driver_blinker_changed = driver_blinker_state != self.driver_blinker_state
    self.driver_blinker_state = driver_blinker_state #驾驶员转向灯状态
    driver_desire_enabled = driver_blinker_state in [BLINKER_LEFT, BLINKER_RIGHT] #driver_desire_enabled表示司机有手动打灯
    if self.laneChangeNeedTorque < 0: # "变道扭矩需求"如果设置为-1，即使打灯了也不会变更车道。
      driver_desire_enabled = False

    if driver_blinker_changed:
      print(f"---[{time.strftime('%H:%M:%S')}]driver blinker change: {driver_blinker_state}")

    #盲区检查状态处理
    ignore_bsd = True if self.laneChangeBsd < 0 else False #laneChangeBsd设置为-1表示忽略BSD盲区检测
    block_lanechange_bsd = True if self.laneChangeBsd == 1 else False #检查是否设置了盲区阻止变道

    self.blindspot_detected_counter = max(0, self.blindspot_detected_counter - 1) #BSD盲区检测倒计时计数

    #new 检查可变道的延时时间
    left_turn_sec = max(0, carrotMan.xLeftTurnSec)  # 到转弯点还需要的时间
    turn_need_time = (self.continuousLaneChangeCnt+1)*self.continuousLaneChangeInterval + 20  # 计算所有次数需要的延时时间,预留20秒的时间
    turn_need_time = max(min(left_turn_sec, turn_need_time) - 20, 0)
    lane_change_interval = min(turn_need_time/(self.continuousLaneChangeCnt+1), self.continuousLaneChangeInterval)
    if lane_change_interval < 2: #限制最小的变道延时时间
      lane_change_interval = 2 if self.continuousLaneChangeInterval >= 2 else self.continuousLaneChangeInterval

    ##### check ATC's blinker state
    atc_left_right = False
    fork_left_right = False
    turn_left_right = False
    fork_now = False
    xDistToTurn = carrotMan.xDistToTurn
    atc_type = carrotMan.atcType #carrotMan.atcType来自carrot_man.py的update_auto_turn函数状态
    atc_blinker_state = BLINKER_NONE
    if self.carrot_lane_change_count > 0: #carrotCmd为"LANECHANGE"是的0.2秒计数
      atc_blinker_state = self.carrot_blinker_state
      # 2025.10.19
      below_lane_change_speed = False
      if self.carrot_overtake_cmd:
        atc_left_right = True
      #在变道期间不再接受下一条变道命令，防止结束当前变道后再一次变道
      if carrotMan.carrotCmdIndex != self.carrot_cmd_index_last and (carrotMan.carrotCmd == "LANECHANGE" or carrotMan.carrotCmd == "OVERTAKE"):
        self.carrot_cmd_index_last = carrotMan.carrotCmdIndex
    elif carrotMan.carrotCmdIndex != self.carrot_cmd_index_last and (carrotMan.carrotCmd == "LANECHANGE" or carrotMan.carrotCmd == "OVERTAKE"): #来自app的变道命令
      self.carrot_cmd_index_last = carrotMan.carrotCmdIndex
      self.carrot_lane_change_count = int(LANE_CHANGE_TIME_MAX*2 / DT_MDL)
      self.carrot_blinker_state = BLINKER_LEFT if carrotMan.carrotArg == "LEFT" else BLINKER_RIGHT
      print(f"---[{time.strftime('%H:%M:%S')}]Desire lanechange: {carrotMan.carrotArg},counter={self.carrot_lane_change_count},blinker={self.carrot_blinker_state},"
            f"state={self.lane_change_state},prev_desire_enabled={self.prev_desire_enabled},"
            f"driver_blinker_changed={driver_blinker_changed},driver_desire_enabled={driver_desire_enabled}")
      atc_blinker_state = self.carrot_blinker_state #new
      # 2025.10.19
      self.atc_turn_cnt = self.continuousLaneChangeCnt #重置允许连续变道次数
      self.lane_change_disable_count = lane_change_interval  # 重置连续变道延时
      self.lane_change_disable = False # 重置禁止变道的标志
      self.lane_cnt_time = self.lane_count_stab_cnt
      self.lane_count_last = -1
      if carrotMan.carrotCmd == "OVERTAKE":
        self.carrot_overtake_cmd = True
    elif atc_type in ["turn left", "turn right"]: #来自carrot_man.py的update_auto_turn函数，转弯请求
      if self.atc_active != 2:
        below_lane_change_speed = True
        self.lane_change_timer = 0.0
        atc_blinker_state = BLINKER_LEFT if "left" in atc_type else BLINKER_RIGHT
        self.atc_active = 1
        self.blinker_ignore = False
        turn_left_right = True
    elif atc_type in ["fork left", "fork right"]: #来自carrot_man.py的update_auto_turn函数，变道请求
      if self.atc_active != 2:
        below_lane_change_speed = False
        atc_blinker_state = BLINKER_LEFT if "left" in atc_type else BLINKER_RIGHT
        self.atc_active = 1
        fork_left_right = True
    elif atc_type in ["fork left now", "fork right now"]: #立即变道请求
      if self.atc_active != 2:
        below_lane_change_speed = False
        atc_blinker_state = BLINKER_LEFT if "left" in atc_type else BLINKER_RIGHT
        self.atc_active = 1
        fork_now = True
        fork_left_right = True
    elif atc_type in ["atc left", "atc right"]: #来自carrot_man.py的update_auto_turn函数，变道请求
      if self.atc_active != 2:
        below_lane_change_speed = False
        atc_blinker_state = BLINKER_LEFT if "left" in atc_type else BLINKER_RIGHT
        self.atc_active = 1
        atc_left_right = True
    else:
      self.atc_active = 0

    #atc_blinker_state_org = atc_blinker_state
    #自动转弯方向和驾驶员打的转向灯不同，则优先驾驶员
    if driver_blinker_state != BLINKER_NONE and atc_blinker_state != BLINKER_NONE and driver_blinker_state != atc_blinker_state:
      atc_blinker_state = BLINKER_NONE
      if self.atc_active != 2:
        print(f"---[{time.strftime('%H:%M:%S')}]driver_blinker({driver_blinker_state})!=atc_blinker({atc_blinker_state}),set atc_active=2")
      self.atc_active = 2
    elif driver_blinker_state != BLINKER_NONE and driver_blinker_state == atc_blinker_state and driver_blinker_changed: #如果用户打了与自动转身一样的灯，可恢复自动转向
      if self.atc_active == 2:
        self.atc_active = 0
        print(f"---[{time.strftime('%H:%M:%S')}]driver_blinker({driver_blinker_state})==atc_blinker({atc_blinker_state}),reset atc_active 2->0")
    atc_desire_enabled = atc_blinker_state in [BLINKER_LEFT, BLINKER_RIGHT] #自动转弯控制需求

    if driver_blinker_state == BLINKER_NONE: #驾驶员未打灯或者打了之后关闭了转向灯时，则清除反方向盘标志
      if self.blinker_ignore and atc_left_right:# and atc_type in ["atc left", "atc right"]: #如果在是atc_left/right期间用户反向干预了方向盘，则设置标志self.blinker_ignore_last
        print(f"---[{time.strftime('%H:%M:%S')}]atc_left_right, blinker_ignore=true, set blinker_ignore_last=true")
        self.blinker_ignore_last = True
      self.blinker_ignore = False
    if self.blinker_ignore: #如果用户反方向打了方向盘，而且用户打了灯，则会持续清除转向灯的状态，禁止变道
      driver_blinker_state = BLINKER_NONE
      atc_blinker_state = BLINKER_NONE
      driver_desire_enabled = False

    if self.atc_type != atc_type: #为里的判断主要是用于在atc_type类型变化时用于重置状态
      atc_desire_enabled = False #atc类型不同时，重置自动转弯需求
      if fork_now:
        self.atc_turn_cnt = 0 #立即变道请求，只允许变道一次
      else:
        self.atc_turn_cnt = self.continuousLaneChangeCnt #重置允许连续变道次数
      self.lane_change_disable_count = lane_change_interval  # 重置连续变道延时
      self.lane_change_disable = False # 重置禁止变道的标志
      self.lane_cnt_time = self.lane_count_stab_cnt
      self.lane_count_last = -1
      if self.blinker_ignore_last:
        print(f"---[{time.strftime('%H:%M:%S')}]clear blinker_ignore_last")
      self.blinker_ignore_last = False
      print(f"---[{time.strftime('%H:%M:%S')}]atc_type change, curr:{atc_type}, prev:{self.atc_type}")

    self.atc_type = atc_type
    self.atc_blinker_state = atc_blinker_state

    desire_enabled = driver_desire_enabled or atc_desire_enabled #变道请求
    blinker_state = driver_blinker_state if driver_desire_enabled else atc_blinker_state #根据是谁打的灯选择转向灯状态

    if atc_blinker_state == BLINKER_NONE:
      self.blinker_val = BLINKER_NONE
    elif turn_left_right:
      self.blinker_val = atc_blinker_state

    #目前只有现代的carState里有这个leftLaneLine/rightLaneLine，但是大部车没有这个信息，包括Santa Fe，所以lane_line_info为0
    lane_line_info = carstate.leftLaneLine if blinker_state == BLINKER_LEFT else carstate.rightLaneLine

    if desire_enabled:
      lane_exist_counter = self.lane_exist_left_count.counter if blinker_state == BLINKER_LEFT else self.lane_exist_right_count.counter #左侧或右侧车道存在的时间
      lane_available = self.available_left_lane if blinker_state == BLINKER_LEFT else self.available_right_lane #车道存在标志
      edge_available = self.available_left_edge if blinker_state == BLINKER_LEFT else self.available_right_edge #路缘存在标志
      #self.lane_appeared = lane_exist_counter == int(0.2 / DT_MDL) #车道线存在时间等于0.2秒代表有新车道线出现
      self.lane_appeared = self.lane_appeared or lane_exist_counter == int(0.2 / DT_MDL) #
      curr_lane_width_diff = self.lane_width_left_curr_diff if blinker_state == BLINKER_LEFT else self.lane_width_right_curr_diff #当前车道宽度和旁边车道宽度的差值

      carrot_left_blind = carrotMan.leftBlind
      carrot_right_blind = carrotMan.rightBlind
      carrot_blind = carrot_left_blind if blinker_state == BLINKER_LEFT else carrot_right_blind

      radar = radarState.leadLeft if blinker_state == BLINKER_LEFT else radarState.leadRight
      side_object_dist = radar.dRel + radar.vLead * 3.0 if radar.status else 255
      if radar.status:
        object_detected = ((side_object_dist < v_ego * (3.0 + self.min_vrel_vego_time)) or (radar.dRel < (v_ego*self.min_drel_vego_time))) and abs(radar.vLead) > 2.8
      else:
        object_detected = False
      #self.object_detected_count = max(1, self.object_detected_count + 1) if object_detected else min(-1, self.object_detected_count - 1)
      if object_detected or carrot_blind: #检测到
        self.object_detected_count = 1
      else:
        self.object_detected_count -= 1
        if self.object_detected_count < self.min_object_detected_count:
          self.object_detected_count = self.min_object_detected_count

      if object_detected or carrot_blind:
        self.object_detected_count_new = 1
      else:
        self.object_detected_count_new -= 1
        if self.object_detected_count_new < self.min_object_detected_count:
          self.object_detected_count_new = self.min_object_detected_count
    else:
      lane_exist_counter = 0
      lane_available = True
      edge_available = True
      #self.lane_appeared = False
      self.lane_appeared = False #
      self.lane_available_trigger = False #
      self.object_detected_count = 0
      self.object_detected_count_new = 0
      self.side_object_detected = False
      curr_lane_width_diff = 3.5

    #雷达调试信息
    debugText = ""
    vego4x = v_ego * (3.0 + self.min_vrel_vego_time)
    radar_left = radarState.leadLeft
    radar_right = radarState.leadRight
    if radar_left.status or radar_right.status:
      if (self.showDebugLog & 16) > 0:
        debugText = "---Radar,"
      if radar_left.status:
        side_object_dist = radar_left.dRel + radar_left.vLead * 3.0
        side_object_block = (side_object_dist < vego4x or radar_left.dRel < (v_ego*self.min_drel_vego_time)) and abs(radar_left.vLead) > 2.8
        if (self.showDebugLog & 16) > 0:
          debugText += f"L:{radar_left.status}"
          debugText += f",dRel={radar_left.dRel:.1f},V={radar_left.vLead:.1f},sDist={side_object_dist:.1f},block={side_object_block},"
      else:
        side_object_block = False

      self.leftFrontBlind = 1 if side_object_block else 0

      if radar_right.status:
        side_object_dist = radar_right.dRel + radar_right.vLead * 3.0
        side_object_block = (side_object_dist < vego4x or radar_right.dRel < (v_ego*self.min_drel_vego_time))  and abs(radar_right.vLead) > 2.8
        if (self.showDebugLog & 16) > 0:
          debugText += f"R:{radar_right.status}"
          debugText += f",dRel={radar_right.dRel:.1f},V={radar_right.vLead:.1f},sDist={side_object_dist:.1f},block=={side_object_block}"
      else:
        side_object_block = False

      self.rightFrontBlind = 1 if side_object_block else 0

      if (self.showDebugLog & 16) > 0:
        debugText += f",v_ego*4={vego4x:.1f},cnt={self.object_detected_count},{self.object_detected_count_new}"
        print(debugText)
    else:
      self.leftFrontBlind = 0
      self.rightFrontBlind = 0

    #self.lane_available_trigger = not self.lane_available_last and lane_available
    lane_change_available = (lane_available or edge_available) and lane_line_info < 20 # lane_line_info小于20为白色虚线(注：SantaFe没有这个车道线识别功能)。
    #self.lane_available_trigger = False
    self.lane_available_trigger = False #
    lane_width_diff = self.lane_width_left_diff if atc_blinker_state == BLINKER_LEFT else self.lane_width_right_diff #lane_width_diff为1秒内侧面车道变宽的宽度，说明可能的新的车道增加
    lane_width_far_diff = self.lane_width_left_far_diff if atc_blinker_state == BLINKER_LEFT else self.lane_width_right_far_diff
    distance_to_road_edge = self.distance_to_road_edge_left if atc_blinker_state == BLINKER_LEFT else self.distance_to_road_edge_right #当前车道线到道路边缘的距离
    lane_width_side = self.lane_width_left if atc_blinker_state == BLINKER_LEFT else self.lane_width_right #左侧或右侧车道的宽度
    distance_to_road_edge_avg = self.distance_to_road_edge_left_avg if atc_blinker_state == BLINKER_LEFT else self.distance_to_road_edge_right_avg  # 当前车道线到道路边缘的平均值距离

    #判断侧面是否为最后一条车道
    last_lane = True
    if desire_enabled and lane_available and edge_available: #有变道请求，并且有检测到路沿
      road_edge_width_diff = distance_to_road_edge_avg - lane_width_side #计算距离边缘的宽度与侧面车道宽度的差值，如果大于2.5m则认为侧面不止一条车道
      if road_edge_width_diff > 1.5: #到路沿的距离比侧面车道还宽1.5米，说明侧面除了正常车道外，还有一条应急车道或正常道路
        self.last_lane_count += 1
        if self.last_lane_count > int(0.5/DT_MDL): #稳定检测时间超过0.5秒
          last_lane = False #侧面非最后一条车道
      else:
        self.last_lane_count = 0
    else:
      self.last_lane_count = -1

    #在有应急车道的高速公路，侧面只剩最后一条车道(也可能是应急车道)，则清除需要变道的次数
    if desire_enabled: #如果没有检测到路沿，那有可以车辆在离路沿最远的车道上，edge_available成立的标志为宽度大于2.5m
      if lane_available and edge_available: #侧面车道和路沿均有时，通过宽度计算侧面的车道数量，lane_available和edge_available成立的标志为宽度大于2.5m
        road_edge_width_diff = distance_to_road_edge_avg - lane_width_side  # 计算距离边缘的宽度与侧面车道宽度的差值
        if road_edge_width_diff > 1.5: #路沿宽度和车道大1.5米时，可以认为是两条车道
          lane_count = 2
        else:
          lane_count = 1
      elif lane_available: #侧面有车道或路沿，算1条车道
        lane_count = 1
      elif (self.lane_change_state != LaneChangeState.laneChangeStarting
            and self.lane_change_state != LaneChangeState.laneChangeFinishing): #没有车道也没有路沿，并且不是在变道中
        lane_count = 0
      else: #当路宽和路沿距离都小于2.5时，lane_available和edge_available两个标志都不会成立
        lane_count = 10
        self.lane_cnt_time = self.lane_count_stab_cnt #变道中不稳定的情况下重置车道计时时间
        self.lane_count_last = -1

      # 车道数量稳定时间倒计时
      if self.lane_count_last == lane_count:
        self.lane_cnt_time = max(int(-60 / DT_MDL), self.lane_cnt_time - 1)
      else:
        self.lane_cnt_time = self.lane_count_stab_cnt

      #根据车道数量稳定倒计时时间来决定是否要关闭自动变道次数
      if atc_desire_enabled and atc_left_right and (atc_blinker_state == BLINKER_RIGHT or atc_blinker_state == BLINKER_LEFT): #属于自动提变道类型atc_left或atc_right
        if self.lane_cnt_time <= -1: #倒计时已结束
          if self.atc_turn_cnt < 0 < autoEnTurnNewLaneTime and self.lane_cnt_time < int((-1) * autoEnTurnNewLaneTime / DT_MDL): #如果自动变道次数已用完，并且车道数量稳定时间超过10秒后(这个时间可以调大，用来过滤汇入车道)
            if self.xroadcate == 1 and atc_blinker_state == BLINKER_RIGHT: #带应急车道的高速公路右变道
              if 2 <= lane_count < 10: #稳定的车道数量大于等于2条，说明有车道可以变道了
                if self.atc_turn_cnt < 0:
                  self.lane_change_audio(True, 11, 0)  # 出现新车道
                self.atc_turn_cnt = 0
            else: #不带应急车道的高速公路或者普通公路
              if 1 <= lane_count < 10: #稳定的车道数量大于等于1条，说明有车道可以变道了
                self.atc_turn_cnt = 0
        elif self.lane_cnt_time <= 0: #倒计时为0
          if self.xroadcate == 1 and atc_blinker_state == BLINKER_RIGHT: #带应急车道的高速公路右变道
            if lane_count < 2:   #如果侧面只剩一条应急车道时，关闭自动变道功能
              if self.atc_turn_cnt >= 0:
                self.lane_change_audio(True, 10, 0)  # 车辆已靠边
              self.atc_turn_cnt = -1
          else: #不带应急车道的高速公路或者普通公路
            if lane_count < 1: #如果侧面无任何车道时，关闭自动变道功能
              if self.atc_turn_cnt >= 0:
                self.lane_change_audio(True, 10, 0)  # 车辆已靠边
              self.atc_turn_cnt = -1
      else: #不是左右自动变道类型atc_left或atc_right
        self.lane_cnt_time = self.lane_count_stab_cnt
        self.lane_count_last = -1

      self.lane_count_last = lane_count
    else:
      self.lane_cnt_time = self.lane_count_stab_cnt
      self.lane_count_last = -1

    # 侧面车道的宽度小于距离道路边缘的宽度，并且宽度在1少内变宽了0.8米以上(说明可能有新车道出现，即新车道在变大)
    #if lane_width_diff > 0.8 and (lane_width_side < distance_to_road_edge):
    if lane_width_diff > self.newLaneWidthDiff and (lane_width_side < distance_to_road_edge): #所有变道类型，只要出现新车道，则允许变道，且不受变道次数的限制
      if not atc_left_right: #非提前自动左右变道类型
        self.lane_available_trigger = True #
      #2025.09.02删除，提前自动左右变道类型不以车道宽度变大作为变道条件
      #elif self.atc_turn_cnt >= 0: #还有剩余变道次数
      #  self.lane_available_trigger = True
    #if (lane_width_diff > 0.5 or (self.autoTurnInNotRoadEdge > 0 and round(curr_lane_width_diff,1) < 0.3 )) and (lane_width_side < distance_to_road_edge):
    elif (atc_left_right #为左右提前变道请求
          and (self.autoTurnInNotRoadEdge > 0 #允许在非侧边车道变道
               and curr_lane_width_diff < 0.3 #旁边车道不能比当前车道小于0.3m
               and lane_width_diff >= -0.1 #旁边车道不允许在变小
               and self.atc_turn_cnt >= 0 #还有剩余变道次数
               and ((atc_blinker_state == BLINKER_RIGHT and self.xroadcate == 1 and not last_lane) #有应急车道的高速右变道限制，不允许变道到最后一条车道(应急车道)上
                    or (atc_blinker_state != BLINKER_RIGHT or self.xroadcate != 1)) #不是右变道或者在无应急车道的道路则允许变道
               )
          and (lane_width_side < distance_to_road_edge) #侧面车道的宽度要大于路沿宽度
         ):
      self.lane_available_trigger = True
    elif fork_now and self.atc_turn_cnt >= 0: #立即变道的请求，强制设置self.lane_available_trigger为True
      self.lane_available_trigger = True
    edge_availabled = not self.edge_available_last and edge_available
    #side_object_detected = self.object_detected_count > -0.3 / DT_MDL
    #侧面车道障碍物判断
    if self.side_object_detected:
      if self.object_detected_count_new <= self.min_object_detected_count_thr:
        self.side_object_detected = False
    elif self.object_detected_count_new > 0:
      self.side_object_detected = True
    side_object_detected = self.side_object_detected
    self.lane_appeared = self.lane_appeared and distance_to_road_edge < 4.0 #新车道出现还要附加个距离道路边缘小于4米的条件

    if self.carrot_lane_change_count > 0: #些计数为carrorMan发送过来的LANECHANGE触发的变道
      auto_lane_change_blocked = False
      auto_lane_change_trigger = lane_change_available
    else:
      self.carrot_blinker_state = BLINKER_NONE #new
      #如果自动转弯要求是左变道，但是用户没有打左转向灯，那么会阻止自动变道
      auto_lane_change_blocked = ((atc_blinker_state == BLINKER_LEFT) and (driver_blinker_state != BLINKER_LEFT) and (self.autoTurnLeft == 0 or self.xroadcate < 0 or self.xroadcate > 1)) #增加可以设置允许左变道
      #auto_lane_change_trigger = not auto_lane_change_blocked and edge_available and (self.lane_available_trigger or edge_availabled or self.lane_appeared) and not side_object_detected
      auto_lane_change_trigger = self.auto_lane_change_enable and not auto_lane_change_blocked and edge_available and (self.lane_available_trigger or self.lane_appeared) and not side_object_detected
      self.desireLog = f"D:{self.lane_width_curr:.1f},{lane_width_side:.1f},{distance_to_road_edge_avg:.1f},{lane_width_diff:.1f},{lane_width_far_diff:.1f},{lane_line_info}={auto_lane_change_trigger},T:{self.atc_turn_cnt},S:{self.lane_change_state},L:{self.auto_lane_change_enable},{auto_lane_change_blocked},E:{lane_available},{edge_available},A:{self.lane_available_trigger},{self.lane_appeared}"
      if (self.showDebugLog & 2) > 0:
        print(f"---xDist:{xDistToTurn},desire:{desire_enabled}({driver_desire_enabled},{atc_desire_enabled}),"
              f"lane_available:{lane_available},cur={self.lane_width_curr:.1f},side={lane_width_side:.1f},"
              f"edge={distance_to_road_edge_avg:.1f},diff={lane_width_diff:.1f},far_diff:{lane_width_far_diff:.1f},road_type={self.xroadcate}")
        print(f"---State:{self.lane_change_state},turn: {self.atc_turn_cnt},trig:{auto_lane_change_trigger}="
              f"lane_change_enable'{self.auto_lane_change_enable}'&&!blocked'{auto_lane_change_blocked}'&&edge_available'{edge_available}'&&"
              f"(lane_available_trig'{self.lane_available_trigger}'||self.lane_appeared'{self.lane_appeared}')&!object_detected'{side_object_detected}' "
              f"obj_cnt={self.object_detected_count:.1f},{self.object_detected_count_new},active={self.atc_active},last_lane={last_lane} time:{self.last_lane_count}")
        print(f"---blinker_state={blinker_state},atc_blinker_state={atc_blinker_state},driver_blinker_state={driver_blinker_state},esp32 blinker={self.blinker}")

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX: #横向未激活或变道时间超过10秒时，退出变道控制
      if self.lane_change_state != LaneChangeState.off:
        if atc_desire_enabled and (fork_left_right or atc_left_right):
          self.lane_change_audio(True, 4, 0)  # 播报领航已退出
          print(f"---[{time.strftime('%H:%M:%S')}]Desire canceled, play audio, atc_desire_enabled={atc_desire_enabled},fork_left_right={fork_left_right},atc_left_right={atc_left_right}")
        else:
          print(f"---[{time.strftime('%H:%M:%S')}]Desire canceled")
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.turn_direction = TurnDirection.none
    elif ( (self.blinkerMode == 0 or not driver_desire_enabled or turn_left_right) and
           desire_enabled and ((below_lane_change_speed and not carstate.standstill and self.enable_turn_desires) or self.turn_desire_state)): #激活转弯控制模式（并不走变道流程）
      if self.lane_change_state != LaneChangeState.off:
        print(f"---[{time.strftime('%H:%M:%S')}]Desire Turning")
        #if atc_desire_enabled and (fork_left_right or atc_left_right):
        #  self.lane_change_audio(True, 4, 0)  # 播报领航已退出
      self.lane_change_state = LaneChangeState.off
      if self.turn_disable_count > 0:
        self.turn_direction = TurnDirection.none
        self.lane_change_direction = LaneChangeDirection.none
      else:
        self.turn_direction = TurnDirection.turnLeft if blinker_state == BLINKER_LEFT else TurnDirection.turnRight #转弯方向
        self.lane_change_direction = self.turn_direction #LaneChangeDirection.none
      desire_enabled = False
    elif self.desire_disable_count > 0: # Turn后一段时间内无法变更车道,此变量在check_desire_state函数里计算，如果车辆在转弯，则一直把desire_disable_count设置为2秒的计数值
      if self.lane_change_state != LaneChangeState.off:
        print(f"---[{time.strftime('%H:%M:%S')}]Desire after turning")
        #if atc_desire_enabled and (fork_left_right or atc_left_right):
        #  self.lane_change_audio(True, 4, 0)  # 播报领航已退出
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.turn_direction = TurnDirection.none
    else:
      if (self.showDebugLog & 8) > 0:
        print(f"---turn:{atc_type},state={self.lane_change_state},desire_enabled={desire_enabled},prev={self.prev_desire_enabled},exist={lane_exist_counter},below={below_lane_change_speed}")
      self.turn_direction = TurnDirection.none
      # =============LaneChangeState.off=============
      # 不管是驾驶员还是系统自动打的灯，流程都会到这里，desire_enabled为True
      #if self.lane_change_state == LaneChangeState.off and desire_enabled and not self.prev_desire_enabled and not below_lane_change_speed:
      if ((self.lane_change_state == LaneChangeState.off and desire_enabled
           and (not self.prev_desire_enabled or (driver_blinker_changed and driver_desire_enabled)) #从打灯变成未打灯状态，可以不受prev_desire_enabled的影响
           and not below_lane_change_speed)):
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_ll_prob = 1.0
        self.lane_change_delay = self.laneChangeDelay

        # 如果不是最后车道(如果侧面有车道)，ATC就不会自动启动。
        #self.auto_lane_change_enable = False if lane_exist_counter > 0 else True
        # new修改自动变道启用逻辑，lane_exist_counter表示车道线存在的时间，lane_change_available表示可以变道
        if self.autoTurnInNotRoadEdge > 0:
          #self.auto_lane_change_enable = True if lane_change_available else False #符合虚线变道条件
          self.auto_lane_change_enable = True
        else:
          self.auto_lane_change_enable = False if lane_exist_counter > 0 or lane_change_available else True

        self.lane_change_disable_count = lane_change_interval #重置连续变道延时
        self.lane_change_disable = False
        #self.next_lane_change = False

        #提示领航已恢复
        if (desire_enabled and self.prev_desire_enabled and driver_blinker_changed and
            driver_desire_enabled and atc_desire_enabled and driver_blinker_state == atc_blinker_state and
            atc_blinker_state != BLINKER_NONE):
          self.atc_resume = 1
          #self.lane_change_audio(True, 5, 0)  # 播报领航已恢复
        elif desire_enabled and not self.prev_desire_enabled and atc_blinker_state != BLINKER_NONE: #自动变道成立的条件
          self.atc_resume = 2
        else:
          self.atc_resume = 0

        print(f"---[{time.strftime('%H:%M:%S')}]init: auto_enable={self.auto_lane_change_enable},atc_resume={self.atc_resume},"
              f"exist cnt={lane_exist_counter},lane_change_available={lane_change_available}")
        print(f"---[{time.strftime('%H:%M:%S')}]init: desire_enabled={desire_enabled},prev_desire_enabled={self.prev_desire_enabled},"
              f"driver_blinker_changed={driver_blinker_changed},driver_desire_enabled={driver_desire_enabled},"
              f"atc_desire_enabled={atc_desire_enabled}")
        #new
        self.lane_change_state_last = self.lane_change_state
        self.lane_change_state_prev = LaneChangeState.off

      # =============LaneChangeState.preLaneChange==============
      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Set lane change direction
        self.lane_change_direction = LaneChangeDirection.left if \
          blinker_state == BLINKER_LEFT else LaneChangeDirection.right

        dir_map = {
            LaneChangeDirection.left:  (carstate.steeringTorque > 0, carstate.leftBlindspot),
            LaneChangeDirection.right: (carstate.steeringTorque < 0, carstate.rightBlindspot),
        }
        torque_cond, blindspot_cond = dir_map.get(self.lane_change_direction, (False, False))
        torque_applied = carstate.steeringPressed and torque_cond
        blindspot_detected = blindspot_cond

        #int(2.0 / DT_MDL) 实际上是 2秒内连续帧的计数阈值, 如果 lane_exist_counter < 2秒的帧数 → 说明侧边车道线检测不到或存在不稳定
        #说明车道线不可见或者车道线不稳定，则允许自动变道
        if not lane_available or lane_exist_counter < int(2.0 / DT_MDL): #lane_exist_counter > int(0.2 / DT_MDL) and not lane_change_available:
          self.auto_lane_change_enable = True

        if blindspot_detected and not ignore_bsd: #检测到盲区有车并且不忽略BSD，否则self.blindspot_detected_counter为0
          self.blindspot_detected_counter = int(self.bsdDelayTime / DT_MDL) #盲区检测1.5秒

        trigger_type = 0
        trigger_name = "none"
        if not desire_enabled or below_lane_change_speed:
          print(f"---[{time.strftime('%H:%M:%S')}]Pre:desire_enabled={desire_enabled} or below_lane_change_speed={below_lane_change_speed}")
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          trigger_type = -1
          trigger_name = "desire disable"
        else:
          # 手动打灯(或者resp32控制的原车打灯)，不再通过外控制转身灯
          if ((not driver_desire_enabled or self.stockBlinkerCtrl == 1) and self.atc_turn_cnt >= 0) or self.carrot_blinker_state != BLINKER_NONE:
            self.blinker_val = atc_blinker_state
          else:
            self.blinker_val = BLINKER_NONE
          if self.lane_change_state_prev != self.lane_change_state:
            self.lane_change_state_prev = self.lane_change_state
            print(f"---[{time.strftime('%H:%M:%S')}]Pre:ext_blinker state:{self.blinker_val},driver_desire_enabled={driver_desire_enabled},"
                  f"stockBlinkerCtrl={self.stockBlinkerCtrl},turn_cnt={self.atc_turn_cnt},carrot_blinker_state={self.carrot_blinker_state}")
          #此处根据条件决定是否进入开始变道或转弯的流程，lane_change_available为真时表示旁边车道或者路沿的宽度稳定大于2.5米
          if lane_change_available and self.lane_change_delay == 0: #允许变道并且没有延时时间要求
            self.lane_change_delay_start = False
            if (self.blindspot_detected_counter > 0 or side_object_detected) and not ignore_bsd:  # 有盲区（包括后盲区，侧盲区，前盲区）
              if torque_applied and not block_lanechange_bsd: #没有设置有盲区轻方向盘不允许变道
                self.lane_change_state = LaneChangeState.laneChangeStarting
                trigger_type = 1
                trigger_name = "torque bsd"
              else:
                trigger_type = -2
                trigger_name = "bsd block"
                # 播报盲区有车
                if 0 == (self.frame % int(2 / DT_MDL)):
                  self.lane_change_audio(True, 6, 0)
              #盲区有车时重置变道延时计数器
              self.lane_change_disable_count = lane_change_interval
            elif self.laneChangeNeedTorque > 0:# or self.next_lane_change: # 需要轻推方向盘变道
              if torque_applied:
                self.lane_change_state = LaneChangeState.laneChangeStarting
                trigger_type = 2
                trigger_name = "torque ok"
              else:
                trigger_type = -3
                trigger_name = "no torque"
            elif ((driver_desire_enabled and  #驾驶员打灯变道
                   self.driver_lane_change_delay == 0 and #没有命令打灯后的延时
                  (self.stockBlinkerCtrl == 0 or #未通过外挂控制原车Blinker
                    self.blinker_val == BLINKER_NONE or not atc_desire_enabled or #没有esp32打灯或不在自动变道情况下
                    (atc_desire_enabled and driver_blinker_state != atc_blinker_state)  #或者用户打的灯和自动变道的方向相反
                     or torque_applied #或者用户施加了方向盘扭矩
                     or (auto_lane_change_trigger and (lane_change_interval < 0.5 or self.lane_change_disable_count == 0 or not atc_left_right))) #或符合了自动变道条件
                ) #or (self.carrot_blinker_state != BLINKER_NONE)
                ):
              self.lane_change_state = LaneChangeState.laneChangeStarting
              trigger_type = 3
              if self.carrot_blinker_state == BLINKER_NONE:
                trigger_name = "driver"
              else:
                trigger_name = "cmd"
            elif torque_applied or auto_lane_change_trigger: #auto_lane_change_trigger在self.auto_lane_change_enable成立并且无其实阻止条件是则会为True
              if torque_applied: #如果用户施加了扭矩，则立即变道（不执行延时）
                self.lane_change_state = LaneChangeState.laneChangeStarting
                if auto_lane_change_trigger:
                  trigger_type = 4
                  trigger_name = "torque auto"
                else:
                  trigger_type = 5
                  trigger_name = "torque"
              else:
                if lane_change_interval < 0.5 or self.lane_change_disable_count == 0 or not atc_left_right: #变道不延时或者延时已结束或者为非act_left_right，则立即变道
                  self.lane_change_state = LaneChangeState.laneChangeStarting
                  trigger_name = "auto"
                elif not self.lane_change_disable: #没有设置过延时
                  self.lane_change_disable_count = lane_change_interval
                  self.lane_change_disable = True
                  #self.lane_change_audio(True, 1, 0) #播报准备变道
                  if blinker_state == BLINKER_LEFT:
                    self.lane_change_audio(True, 7, 0) #准备左变道
                  else:
                    self.lane_change_audio(True, 8, 0)  # 准备右变道
                  self.lane_change_audio_delay = 2 #延时2秒后再播报倒计时
                  trigger_type = -4
                  trigger_name = "auto timer"
                  #计算倒时计时间
                  left_sec = min(10, int(lane_change_interval))
                  self.left_sec = left_sec
                elif self.lane_change_disable_count == 0: #延时已结束，立即变道
                  self.lane_change_state = LaneChangeState.laneChangeStarting
                  trigger_type = 7
                  trigger_name = "timeout"
            else:
              trigger_type = -5
              trigger_name = "no trig"
              if (self.blindspot_detected_counter > 0 or side_object_detected) and (0 == (self.frame % int(2/DT_MDL))):
                self.lane_change_audio(True, 6, 0)  # 播报盲区有车

            if self.lane_change_state == LaneChangeState.laneChangeStarting:
              self.lane_change_disable_count = lane_change_interval
              self.lane_change_disable = False
              #语音播报
              if atc_left_right or fork_left_right or (not turn_left_right and driver_desire_enabled) or self.carrot_blinker_state != BLINKER_NONE:
                self.lane_change_audio(True, 2, 0)  # 变道
              else:
                self.lane_change_audio(True, 3, 0)  # 转弯
          elif lane_change_available and self.lane_change_delay > 0: #播报打灯提示和倒计时
            if not self.lane_change_delay_start:
              self.lane_change_delay_start = True
              #self.lane_change_audio(True, 1, 0)  # 播报准备变道
              if blinker_state == BLINKER_LEFT:
                self.lane_change_audio(True, 7, 0)  # 准备左变道
              else:
                self.lane_change_audio(True, 8, 0)  # 准备右变道
              self.lane_change_audio_delay = 2  # 延时2秒后再播报倒计时
              left_sec = min(10, int(self.lane_change_delay)) #倒计时时间
              self.left_sec = left_sec
              trigger_type = -7
              trigger_name = "delay"
          else:
            trigger_type = -6
            trigger_name = "none"

        if self.lane_change_state == LaneChangeState.laneChangeStarting:
          self.trigger_type = trigger_type
          self.trigger_name = trigger_name
          if not driver_desire_enabled:
            self.blinker_val = atc_blinker_state
          print(f"---[{time.strftime('%H:%M:%S')}]Pre:lane_change_state:{LaneChangeState.preLaneChange}->{LaneChangeState.laneChangeStarting},ext_blinker state:{self.blinker_val}")
          self.lane_change_state_prev = LaneChangeState.preLaneChange

        if (self.showDebugLog & 4) > 0 or self.lane_change_state_last != self.lane_change_state:
          print(f"---{'[' + time.strftime('%H:%M:%S') + ']' if self.lane_change_state_last != self.lane_change_state else ''}Pre:lane_change_available={lane_change_available},lane_change_trig={auto_lane_change_trigger},"
                f"trig_name={trigger_name},atc_left_right={atc_left_right},disable_count={self.lane_change_disable_count:.1f},"
                f"change_disable={self.lane_change_disable},interval={lane_change_interval:.1f}, torque={torque_applied},"
                f"blindspot={blindspot_cond},{blindspot_detected},L:{carstate.leftBlindspot},R:{carstate.rightBlindspot},cnt={self.blindspot_detected_counter:.1f}")

        self.lane_change_state_last = self.lane_change_state

      # =============LaneChangeState.laneChangeStarting=============
      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        # fade out over .5s
        self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2 * DT_MDL, 0.0)

        # 98% certainty
        if lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
          self.lane_change_state = LaneChangeState.laneChangeFinishing

        if (self.showDebugLog & 4) > 0 or self.lane_change_state_last != self.lane_change_state:
          print(f"---{'[' + time.strftime('%H:%M:%S') + ']' if self.lane_change_state_last != self.lane_change_state else ''}Starting: ll_prob={self.lane_change_ll_prob:.1f},prob={lane_change_prob:.1f};trig:name={self.trigger_name},type={self.trigger_type}")

        self.lane_change_state_last = self.lane_change_state

      # =============LaneChangeState.laneChangeFinishing=============
      elif self.lane_change_state == LaneChangeState.laneChangeFinishing:
        # fade in laneline over 1s
        self.lane_change_ll_prob = min(self.lane_change_ll_prob + DT_MDL, 1.0)

        if self.lane_change_ll_prob > 0.99:
          print(f"---[{time.strftime('%H:%M:%S')}]Finishing: old state={self.lane_change_state},atc_resume={self.atc_resume},turn cnt={self.atc_turn_cnt},"
                f"atc_blinker={atc_blinker_state},driver_blinker={driver_blinker_state},blinker_val={self.blinker_val},fork_now={fork_now}")

          self.lane_change_direction = LaneChangeDirection.none
          if desire_enabled: #如果变道需求还在，则重新进入preLaneChange状态
            self.lane_change_state = LaneChangeState.preLaneChange
            #self.next_lane_change = True
          else:
            self.lane_change_state = LaneChangeState.off

          #是否有打灯恢复领航状态的标志，如果不允许恢复，则状态机设置为0ff
          if self.atc_resume == 0:
            self.lane_change_state = LaneChangeState.off
          elif self.atc_resume == 1:
            self.lane_change_audio(True, 5, 0)  # 播报领航已恢复
          self.atc_resume = -1

          #new 如果不允许连续变道，则清空变道次数self.atc_turn_cnt
          if atc_left_right: #属于变道
            #if self.autoTurnInNotRoadEdge > 0 and (not driver_desire_enabled and atc_desire_enabled): #属于系统自动变道
            if self.autoTurnInNotRoadEdge > 0:
              if self.allowContinuousLaneChange == 0: #不允许连续变道
                self.atc_turn_cnt = -1
              else:
                if self.atc_turn_cnt >= 0 and 5 <= self.trigger_type <= 7:
                  self.atc_turn_cnt -= 1
          elif fork_now: #立即变道请求，只允许执行一次
            self.atc_turn_cnt = -1

          self.lane_change_disable_count = lane_change_interval #重置连续变道延时
          self.lane_change_disable = False
          self.lane_change_delay = self.laneChangeDelay #重置打灯延时
          self.lane_change_delay_start = False
          if self.carrot_lane_change_count > 0 or self.carrot_blinker_state != BLINKER_NONE:
            if self.carrot_blinker_state != BLINKER_NONE and self.stockBlinkerCtrl == 1:
              self.driver_lane_change_delay = int(2.0 / DT_MDL)
            print(f"---[{time.strftime('%H:%M:%S')}]Finishing: reset carrot_lane_change_count {self.carrot_lane_change_count}->0,"
                  f"carrot_blinker_state {self.carrot_blinker_state}->0")
            self.carrot_lane_change_count = 0
            self.carrot_blinker_state = BLINKER_NONE

          # 是否有被用户反向方向盘干预的自动变道
          if self.blinker_ignore_last:
            if atc_left_right and atc_blinker_state != BLINKER_NONE: #有自动左右变道和自动打灯状态
              if driver_blinker_state == atc_blinker_state:  # 用户的打灯方向与自动变道方向一致
                print(f"---[{time.strftime('%H:%M:%S')}]blinker_ignore resume,old state:prev_desire_enabled={self.prev_desire_enabled},turn_cnt={self.atc_turn_cnt}")
                self.prev_desire_enabled = False
                self.atc_turn_cnt = self.continuousLaneChangeCnt
                self.blinker_ignore_last = False
                print(f"---[{time.strftime('%H:%M:%S')}]blinker_ignore resume,new state:prev_desire_enabled={self.prev_desire_enabled},turn_cnt={self.atc_turn_cnt}")

          if self.atc_turn_cnt < 0:
            self.lane_change_audio(True, 9, 0) #变道已结束

          if self.lane_change_state == LaneChangeState.off or self.atc_turn_cnt < 0:
            if self.blinker_val != BLINKER_NONE:
              print(f"---[{time.strftime('%H:%M:%S')}]Finishing: clear ext_blinker_val")
            self.blinker_val = BLINKER_NONE

          print(f"---[{time.strftime('%H:%M:%S')}]Finishing: new state={self.lane_change_state},atc resume={self.atc_resume},"
                f"turn cnt={self.atc_turn_cnt},prev_desire_enabled={self.prev_desire_enabled}")
          self.lane_change_state_prev = LaneChangeState.laneChangeFinishing
        elif (self.showDebugLog & 4) > 0 or self.lane_change_state_last != self.lane_change_state:
          print(f"---{'[' + time.strftime('%H:%M:%S') + ']' if self.lane_change_state_last != self.lane_change_state else ''}Finishing: ll_prob={self.lane_change_ll_prob:.1f};dir={self.lane_change_direction};trig:name={self.trigger_name},type={self.trigger_type}")

        self.lane_change_state_last = self.lane_change_state

    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.preLaneChange):
      self.lane_change_timer = 0.0
    else:
      self.lane_change_timer += DT_MDL


    self.lane_available_last = lane_available
    self.edge_available_last = edge_available

    self.prev_desire_enabled = desire_enabled

    #驾驶员往反方向打了方向盘后，自动变道状态机变为Off
    steering_pressed = carstate.steeringPressed and \
                     ((carstate.steeringTorque < 0 and blinker_state == BLINKER_LEFT) or (carstate.steeringTorque > 0 and blinker_state == BLINKER_RIGHT))
    if steering_pressed and self.lane_change_state != LaneChangeState.off:
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_state = LaneChangeState.off
      self.blinker_ignore = True
      print("---steering_pressed, set LaneChangeState.off")
      if atc_desire_enabled:
        self.atc_cancel = True
        self.atc_cancel_delay = int(2.0 / DT_MDL)
        print(f"---set atc_cancel=true, delay={self.atc_cancel_delay}")
        #self.lane_change_audio(True, 4, 0) #播报领航已退出
    elif steering_pressed and self.atc_cancel:
      self.atc_cancel_delay = int(2.0/DT_MDL)

    self.atc_cancel_delay = min(-1, self.atc_cancel_delay - 1)
    if self.atc_cancel_delay == 0:
      if self.atc_cancel:
        self.lane_change_audio(True, 4, 0)  # 播报领航已退出
        print("---play atc_cancel audio")
      self.atc_cancel = False

    if self.turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.turn_direction]
      self.lane_change_direction = self.turn_direction
    else:
      self.desire = DESIRES[self.lane_change_direction][self.lane_change_state]

    #print(f"desire = {self.desire}")
    #self.desireLog = f"desire = {self.desire}"
    #self.desireLog = f"rlane={self.distance_to_road_edge_right:.1f},{self.distance_to_road_edge_right_far:.1f}"

    # Send keep pulse once per second during LaneChangeStart.preLaneChange
    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.laneChangeStarting):
      self.keep_pulse_timer = 0.0
    elif self.lane_change_state == LaneChangeState.preLaneChange:
      self.keep_pulse_timer += DT_MDL
      if self.keep_pulse_timer > 1.0:
        self.keep_pulse_timer = 0.0
      elif self.desire in (log.Desire.keepLeft, log.Desire.keepRight):
        self.desire = log.Desire.none

    if not turn_left_right and self.lane_change_state == LaneChangeState.off:
      if self.blinker_val != BLINKER_NONE:
        print(f"---[{time.strftime('%H:%M:%S')}]not turn_left_right and LaneChangeState.off: clear ext_blinker_val")
      self.blinker_val = BLINKER_NONE
    if self.stockBlinkerCtrl == 1:
      self.blinker = "stockleft" if self.blinker_val == BLINKER_LEFT else "stockright" if self.blinker_val == BLINKER_RIGHT else "none"
    else:
      self.blinker = "left" if self.blinker_val == BLINKER_LEFT else "right" if self.blinker_val == BLINKER_RIGHT else "none"
    if self.lane_change_state == LaneChangeState.off:
      if self.carrot_lane_change_count > 0 or self.carrot_blinker_state != BLINKER_NONE:
        print(f"---[{time.strftime('%H:%M:%S')}]LaneChangeState.off,reset carrot_lane_change_count {self.carrot_lane_change_count}->0,"
              f"carrot_blinker_state {self.carrot_blinker_state}->0")
        self.carrot_blinker_state = BLINKER_NONE
        self.carrot_lane_change_count = 0
    if lane_change_state != self.lane_change_state:
      print(f"---[{time.strftime('%H:%M:%S')}]End:lane_change_state change: {lane_change_state}->{self.lane_change_state}")
