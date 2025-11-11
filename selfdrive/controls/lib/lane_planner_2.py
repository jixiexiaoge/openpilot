import math
import numpy as np
from cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
# from openpilot.common.logger import sLogger
from openpilot.common.params import Params

TRAJECTORY_SIZE = 33
# positive numbers go right
CAMERA_OFFSET = 0 #0.08
MIN_LANE_DISTANCE = 2.6
MAX_LANE_DISTANCE = 3.7
MAX_LANE_CENTERING_AWAY = 1.85
KEEP_MIN_DISTANCE_FROM_LANE = 1.35
KEEP_MIN_DISTANCE_FROM_EDGELANE = 1.15

def clamp(num, min_value, max_value):
  # weird broken case, do something reasonable
  if min_value > num > max_value:
    return (min_value + max_value) * 0.5
  # ok, basic min/max below
  if num < min_value:
    return min_value
  if num > max_value:
    return max_value
  return num

def sigmoid(x, scale=1, offset=0):
  return (1 / (1 + math.exp(x*scale))) + offset

def lerp(start, end, t):
  t = clamp(t, 0.0, 1.0)
  return (start * (1.0 - t)) + (end * t)

def max_abs(a, b):
  return a if abs(a) > abs(b) else b

class LanePlanner:
  def __init__(self):
    self.ll_t = np.zeros((TRAJECTORY_SIZE,))
    self.ll_x = np.zeros((TRAJECTORY_SIZE,))
    self.lll_y = np.zeros((TRAJECTORY_SIZE,))
    self.rll_y = np.zeros((TRAJECTORY_SIZE,))
    self.le_y = np.zeros((TRAJECTORY_SIZE,))
    self.re_y = np.zeros((TRAJECTORY_SIZE,))
    #self.lane_width_estimate = FirstOrderFilter(3.2, 9.95, DT_MDL)
    self.lane_width_estimate = FirstOrderFilter(3.2, 3.0, DT_MDL)
    self.lane_width = 3.2
    self.lane_width_last = self.lane_width
    self.lane_change_multiplier = 1
    #self.lane_width_updated_count = 0

    self.lll_prob = 0.
    self.rll_prob = 0.
    self.d_prob = 0.

    self.lll_std = 0.
    self.rll_std = 0.

    self.l_lane_change_prob = 0.
    self.r_lane_change_prob = 0.

    self.debugText = ""
    self.lane_width_left = 0.0
    self.lane_width_right = 0.0
    self.lane_width_left_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_width_right_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_offset_filtered = FirstOrderFilter(0.0, 2.0, DT_MDL)

    self.lanefull_mode = False
    self.d_prob_count = 0

    # 马自达车道线融合相关变量
    self.mazda_left_lane_line = -1
    self.mazda_right_lane_line = -1
    self.mazda_fusion_enabled = False

    self.params = Params()

  def parse_model(self, md):

    lane_lines = md.laneLines
    edges = md.roadEdges

    if len(lane_lines) >= 4 and len(lane_lines[0].t) == TRAJECTORY_SIZE:
      self.ll_t = (np.array(lane_lines[1].t) + np.array(lane_lines[2].t))/2
      # left and right ll x is the same
      self.ll_x = lane_lines[1].x
      self.lll_y = np.array(lane_lines[1].y)
      self.rll_y = np.array(lane_lines[2].y)
      self.lll_prob = md.laneLineProbs[1]
      self.rll_prob = md.laneLineProbs[2]
      self.lll_std = md.laneLineStds[1]
      self.rll_std = md.laneLineStds[2]

    if len(edges[0].t) == TRAJECTORY_SIZE:
      self.le_y = np.array(edges[0].y) + md.roadEdgeStds[0] * 0.4
      self.re_y = np.array(edges[1].y) - md.roadEdgeStds[1] * 0.4
    else:
      self.le_y = self.lll_y
      self.re_y = self.rll_y

    desire_state = md.meta.desireState
    if len(desire_state) > 2:  # 确保有足够的元素
      self.l_lane_change_prob = desire_state[1]  # 左变道概率
      self.r_lane_change_prob = desire_state[2]  # 右变道概率
    else:
      self.l_lane_change_prob = 0.0
      self.r_lane_change_prob = 0.0

  def update_lane_line_type(self, CS, md):
    """
    融合马自达原车车道线识别结果与openpilot视觉识别结果
    CS: CarState, md: modelV2
    """
    try:
      # 检查是否为马自达车型且有所需数据
      if (not hasattr(CS, 'cam_laneinfo') or
          not hasattr(md, 'laneLineProbs') or
          len(md.laneLineProbs) < 3):
        self.mazda_fusion_enabled = False
        return -1, -1

      # 获取马自达原车识别结果
      mazda_lane_status = CS.cam_laneinfo["LANE_LINES"]

      # 获取openpilot视觉概率
      left_prob = md.laneLineProbs[1]  # 左车道线概率
      right_prob = md.laneLineProbs[2]  # 右车道线概率

      # 融合逻辑
      left_lane_line = -1
      right_lane_line = -1

      # 左车道线
      if mazda_lane_status in [2, 3]:  # 马自达识别到左车道线
        # 马自达识别置信度高时，优先使用马自达结果
        if left_prob > 0.45:  # 提高阈值，需要openpilot有较高置信度
          left_lane_line = 11  # 实线白色（高置信度融合结果）
        elif left_prob > 0.2:  # 中等置信度
          left_lane_line = 10  # 虚线白色（中等置信度融合结果）
        else:
          left_lane_line = 10  # 虚线白色（马自达单独识别）
      elif left_prob > 0.6:  # 只有openpilot识别到，需要更高阈值
        left_lane_line = 10  # 虚线白色

      # 右车道线
      if mazda_lane_status in [2, 4]:  # 马自达识别到右车道线
        # 马自达识别置信度高时，优先使用马自达结果
        if right_prob > 0.45:  # 提高阈值，需要openpilot有较高置信度
          right_lane_line = 11  # 实线白色（高置信度融合结果）
        elif right_prob > 0.2:  # 中等置信度
          right_lane_line = 10  # 虚线白色（中等置信度融合结果）
        else:
          right_lane_line = 10  # 虚线白色（马自达单独识别）
      elif right_prob > 0.6:  # 只有openpilot识别到，需要更高阈值
        right_lane_line = 10  # 虚线白色

      # 保存融合结果
      self.mazda_left_lane_line = left_lane_line
      self.mazda_right_lane_line = right_lane_line
      self.mazda_fusion_enabled = True

      # 记录融合日志
      cloudlog.info(f"MazdaLaneFusion: status={mazda_lane_status}, "
                   f"left_lane={left_lane_line}(prob={left_prob:.2f}), "
                   f"right_lane={right_lane_line}(prob={right_prob:.2f})")

      return left_lane_line, right_lane_line

    except Exception as e:
      # 异常情况下禁用融合
      self.mazda_fusion_enabled = False
      self.mazda_left_lane_line = -1
      self.mazda_right_lane_line = -1
      cloudlog.error(f"MazdaLaneFusion error: {str(e)}")
      return -1, -1

  def get_fused_lane_probs(self):
    """
    获取融合后的车道线概率
    返回: (left_prob, right_prob)
    """
    if not self.mazda_fusion_enabled:
      return self.lll_prob, self.rll_prob

    # 基于融合结果调整概率
    left_prob = self.lll_prob
    right_prob = self.rll_prob

    # 如果马自达融合识别到车道线，提升概率
    if self.mazda_left_lane_line >= 0:
      left_prob = min(left_prob * 1.2, 1.0)
    if self.mazda_right_lane_line >= 0:
      right_prob = min(right_prob * 1.2, 1.0)

    # 如果马自达识别为实线，进一步提升概率
    if self.mazda_left_lane_line == 11:
      left_prob = min(left_prob * 1.1, 1.0)
    if self.mazda_right_lane_line == 11:
      right_prob = min(right_prob * 1.1, 1.0)

    return left_prob, right_prob

  def get_d_path(self, CS, v_ego, path_t, path_xyz, curve_speed, md=None):
    #if v_ego > 0.1:
    #  self.lane_width_updated_count = max(0, self.lane_width_updated_count - 1)

    # 如果提供了模型数据，执行马自达车道线融合
    if md is not None:
      left_type, right_type = self.update_lane_line_type(CS, md)

      # 尝试将融合结果设置回CarState（如果是马自达车型且有set_lane_fusion_result方法）
      try:
        if hasattr(CS, 'set_lane_fusion_result') and self.mazda_fusion_enabled:
          CS.set_lane_fusion_result(left_type, right_type, True)
      except Exception as e:
        # 静默忽略设置失败，可能是其他车型或方法不存在
        pass

    # 使用融合后的概率
    l_prob, r_prob = self.get_fused_lane_probs()
    width_pts = self.rll_y - self.lll_y
    prob_mods = []
    for t_check in (0.0, 1.5, 3.0):
      width_at_t = np.interp(t_check * (v_ego + 7), self.ll_x, width_pts)
      #prob_mods.append(np.interp(width_at_t, [4.0, 5.0], [1.0, 0.0]))
      prob_mods.append(np.interp(width_at_t, [4.5, 6.0], [1.0, 0.0]))
    mod = min(prob_mods)
    l_prob *= mod
    r_prob *= mod

    # Reduce reliance on uncertain lanelines
    l_std_mod = np.interp(self.lll_std, [.15, .3], [1.0, 0.0])
    r_std_mod = np.interp(self.rll_std, [.15, .3], [1.0, 0.0])
    l_prob *= l_std_mod
    r_prob *= r_std_mod

    self.l_prob, self.r_prob = l_prob, r_prob

    # Find current lanewidth
    current_lane_width = abs(self.rll_y[0] - self.lll_y[0])

    max_updated_count = 10.0 * DT_MDL
    both_lane_available = False
    #speed_lane_width = np.interp(v_ego*3.6, [0., 60.], [2.8, 3.5])
    if l_prob > 0.5 and r_prob > 0.5 and self.lane_change_multiplier > 0.5:
      both_lane_available = True
      #self.lane_width_updated_count = max_updated_count
      self.lane_width_estimate.update(current_lane_width)
      self.lane_width_last = self.lane_width_estimate.x
    #elif self.lane_width_updated_count <= 0 and v_ego > 0.1:   # 양쪽차선이 없을때.... 일정시간후(10초)부터 speed차선폭 적용함.
    #  self.lane_width_estimate.update(speed_lane_width)
    else:
      self.lane_width_estimate.update(self.lane_width_last)

    self.lane_width =  self.lane_width_estimate.x
    clipped_lane_width = min(4.0, self.lane_width)
    path_from_left_lane = self.lll_y + clipped_lane_width / 2.0
    path_from_right_lane = self.rll_y - clipped_lane_width / 2.0

    # 가장 차선이 진한쪽으로 골라서..
    self.d_prob = max(l_prob, r_prob) if not both_lane_available else 1.0

    # 좌/우의 차선폭을 필터링.
    if self.lane_width_left > 0:
      self.lane_width_left_filtered.update(self.lane_width_left)
      #self.lane_width_left_filtered.x = self.lane_width_left #바로적용
    if self.lane_width_right > 0:
      self.lane_width_right_filtered.update(self.lane_width_right)
      #self.lane_width_right_filtered.x = self.lane_width_right #바로적용

    self.adjustLaneOffset = float(self.params.get_int("AdjustLaneOffset")) * 0.01
    self.adjustCurveOffset = self.adjustLaneOffset #float(self.params.get_int("AdjustCurveOffset")) * 0.01
    ADJUST_OFFSET_LIMIT = 0.4 #max(self.adjustLaneOffset, self.adjustCurveOffset)
    offset_curve = 0.0
    ## curve offset
    offset_curve = np.interp(abs(curve_speed), [50, 200], [self.adjustCurveOffset, 0.0]) * np.sign(curve_speed)

    offset_lane = 0.0
    if self.lane_width_left_filtered.x > 2.2 and self.lane_width_right_filtered.x > 2.2: #양쪽에 차로가 여유 있는경우
      offset_lane = 0.0
    elif self.lane_width_left_filtered.x < 2.0 and self.lane_width_right_filtered.x < 2.0: #양쪽에 차로가 여유 없는경우
      offset_lane = 0.0
    elif self.lane_width_left_filtered.x > self.lane_width_right_filtered.x:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, self.adjustLaneOffset]) # 차선이 좁으면 안함..
    else:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, -self.adjustLaneOffset]) # 차선이 좁으면 안함..

    #select lane path
    # 차선이 좁아지면, 도로경계쪽에 있는 차선 위주로 따라가도록함.
    if self.lane_width < 2.5:
      if r_prob > 0.5 and self.lane_width_right_filtered.x < self.lane_width_left_filtered.x:
        lane_path_y = path_from_right_lane
      elif l_prob > 0.5 and self.lane_width_left_filtered.x < 2.0:
        lane_path_y = path_from_left_lane
      else:
        lane_path_y = path_from_left_lane if l_prob > 0.5 or l_prob > r_prob else path_from_right_lane
    elif l_prob > 0.7 and r_prob > 0.7:
      lane_path_y = (path_from_left_lane + path_from_right_lane) / 2.
      # lane_width filtering에 의해서, 점점 줄어들때, 중앙선으로 붙어가는 현상이 생김.. 
      #if self.lane_width > 3.2:
      #  lane_path_y = path_from_right_lane
      #else:
      #  lane_path_y = (path_from_left_lane + path_from_right_lane) / 2.
    # 그외 진한차선을 따라가도록함.
    else:
      lane_path_y = (l_prob * path_from_left_lane + r_prob * path_from_right_lane) / (l_prob + r_prob + 0.0001)

    use_laneless_center_adjust = False
    if use_laneless_center_adjust:
      ## 0.5초 앞의 중심을 보도록함.
      lane_path_y_center = np.interp(0.5, path_t, lane_path_y)
      path_xyz_y_center = np.interp(0.5, path_t, path_xyz[:,1])
      #lane_path_y_center = lane_path_y[0]
      #path_xyz_y_center = path_xyz[:,1][0]
      diff_center = (lane_path_y_center - path_xyz_y_center) if not self.lanefull_mode else 0.0
    else:
      diff_center = 0.0
    #print("center = {:.2f}={:.2f}-{:.2f}, lanefull={}".format(diff_center, lane_path_y_center, path_xyz_y_center, self.lanefull_mode))
    #diff_center = lane_path_y[5] - path_xyz[:,1][5] if not self.lanefull_mode else 0.0
    if offset_curve * offset_lane < 0:
      offset_total = np.clip(offset_curve + offset_lane + diff_center, - ADJUST_OFFSET_LIMIT, ADJUST_OFFSET_LIMIT)
    else:
      offset_total = np.clip(max(offset_curve, offset_lane, key=abs) + diff_center, - ADJUST_OFFSET_LIMIT, ADJUST_OFFSET_LIMIT)

    ## self.d_prob = 0 if lane_changing
    self.d_prob *= self.lane_change_multiplier  ## 차선변경중에는 꺼버림.
    if self.lane_change_multiplier < 0.5:
      #self.lane_offset_filtered.x = 0.0
      pass
    else:
      self.lane_offset_filtered.update(np.interp(self.d_prob, [0, 0.3], [0, offset_total]))

    ## laneless at lowspeed
    self.d_prob *= np.interp(v_ego*3.6, [5., 10.], [0.0, 1.0])

    #self.debugText = "OFFSET({:.2f}={:.2f}+{:.2f}+{:.2f}),Vc:{:.2f},dp:{:.1f},lf:{},lrw={:.1f}|{:.1f}|{:.1f}".format(
    #  self.lane_offset_filtered.x,
    #  diff_center, offset_lane, offset_curve,
    #  curve_speed,
    #  self.d_prob, self.lanefull_mode,
    #  self.lane_width_left_filtered.x, self.lane_width, self.lane_width_right_filtered.x)

    adjustLaneTime = self.params.get_float("LatMpcInputOffset") * 0.01 # 0.06 
    laneline_active = False
    self.d_prob_count = self.d_prob_count + 1 if self.d_prob > 0.3 else 0
    if self.lanefull_mode and self.d_prob_count > int(1 / DT_MDL):
      laneline_active = True
      use_dist_mode = False  ## 아무리생각해봐도.. 같은 방법인듯...
      if use_dist_mode:
        lane_path_y_interp = np.interp(path_xyz[:,0] + v_ego * adjustLaneTime, self.ll_x, lane_path_y)
        path_xyz[:,1] = self.d_prob * lane_path_y_interp + (1.0 - self.d_prob) * path_xyz[:,1]
      else:
        safe_idxs = np.isfinite(self.ll_t)
        if safe_idxs[0]:
          lane_path_y_interp = np.interp(path_t * (1.0 + adjustLaneTime), self.ll_t[safe_idxs], lane_path_y[safe_idxs])
          path_xyz[:,1] = self.d_prob * lane_path_y_interp + (1.0 - self.d_prob) * path_xyz[:,1]


    path_xyz[:, 1] += (CAMERA_OFFSET + self.lane_offset_filtered.x)

    self.offset_total = self.lane_offset_filtered.x

    # 添加马自达融合调试信息
    if self.mazda_fusion_enabled:
      fusion_info = f"MAZDA_FUSION: L={self.mazda_left_lane_line},R={self.mazda_right_lane_line},LP={l_prob:.2f},RP={r_prob:.2f}"
      # 可以选择性地将调试信息添加到现有的debugText
      if hasattr(self, 'debugText') and self.debugText:
        self.debugText += f" | {fusion_info}"
      else:
        self.debugText = fusion_info

    return path_xyz, laneline_active

  def get_mazda_fusion_status(self):
    """
    获取马自达融合状态信息
    返回: {
      'enabled': bool,
      'left_lane_line': int,
      'right_lane_line': int,
      'left_prob': float,
      'right_prob': float
    }
    """
    return {
      'enabled': self.mazda_fusion_enabled,
      'left_lane_line': self.mazda_left_lane_line,
      'right_lane_line': self.mazda_right_lane_line,
      'left_prob': self.lll_prob,
      'right_prob': self.rll_prob
    }

  def calculate_plan_yaw_and_yaw_rate(self, path_xyz):
    if path_xyz.shape[0] < 3:
        # 너무 짧으면 직진 가정
        N = path_xyz.shape[0]
        return np.zeros(N), np.zeros(N)

    # x, y 추출
    x = path_xyz[:, 0]
    y = path_xyz[:, 1]

    # 모두 동일한 점인지 확인
    if np.allclose(x, x[0]) and np.allclose(y, y[0]):
        return np.zeros(len(x)), np.zeros(len(x))

    # 안전한 diff 계산
    dx = np.diff(x)
    dy = np.diff(y)
    mask = (dx == 0) & (dy == 0)
    dx[mask] = 1e-4
    dy[mask] = 0.0

    yaw = np.arctan2(dy, dx)
    yaw = np.append(yaw, yaw[-1])  # N-1 → N
    yaw = np.unwrap(yaw)

    dx_full = np.clip(np.diff(x), 1e-4, None)
    yaw_rate = np.diff(yaw) / dx_full
    yaw_rate = np.append(yaw_rate, yaw_rate[-1])
    yaw_rate = np.append(yaw_rate, 0.0)

    # NaN/Inf 방어
    if np.any(np.isnan(yaw_rate)) or np.any(np.isinf(yaw_rate)):
        yaw_rate = np.zeros_like(yaw_rate)
    if np.any(np.isnan(yaw)) or np.any(np.isinf(yaw)):
        yaw = np.zeros_like(yaw)

    return yaw, yaw_rate
