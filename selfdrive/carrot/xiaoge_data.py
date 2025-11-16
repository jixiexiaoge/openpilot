#!/usr/bin/env python3
"""
小鸽数据广播模块
从系统获取实时数据，通过UDP广播到7701端口
"""

import fcntl
import json
import socket
import struct
import time
import traceback
import zlib
from typing import Dict, Any, List, Tuple

import numpy as np
import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.system.hardware import PC


class XiaogeDataBroadcaster:
    # 常量定义（参考 radard.py:28）
    RADAR_TO_CAMERA = 1.52  # 雷达相对于相机中心的偏移（米）
    RADAR_LAT_FACTOR = 0.5  # 未来位置预测时间因子（秒），参考 radard.py 的 radar_lat_factor
    FILTER_INIT_FRAMES = 3  # 滤波器初始化所需的最小帧数（参考 radard.py:520-546 的 cnt > 3）

    # 优化：车道分类和检测阈值（参考 radard.py:520-546）
    LANE_PROB_THRESHOLD = 0.1  # 车道内概率阈值，用于区分当前车道和侧方车道（参考 radard.py:520）
    CUTIN_PROB_THRESHOLD = 0.1  # Cut-in 检测的车道内概率阈值（参考 radard.py:520）

    # 优化：历史数据配置
    HISTORY_SIZE = 10  # 历史数据保留帧数，用于计算横向速度

    # 优化：动态置信度阈值参数（参考 radard.py:126-157 的匹配逻辑）
    CONFIDENCE_BASE_THRESHOLD = 0.5  # 基础置信度阈值
    CONFIDENCE_DISTANCE_THRESHOLD = 50.0  # 距离阈值（米），超过此距离要求更高置信度
    CONFIDENCE_DISTANCE_BOOST = 0.7  # 距离超过阈值时的置信度提升
    CONFIDENCE_VELOCITY_DIFF_THRESHOLD = 10.0  # 速度差异阈值（m/s）
    CONFIDENCE_VELOCITY_BOOST = 0.6  # 速度差异超过阈值时的置信度提升

    # 优化：侧方车辆筛选参数（参考 radard.py:560-569）
    SIDE_VEHICLE_MIN_DISTANCE = 5.0  # 侧方车辆最小距离（米）
    SIDE_VEHICLE_MAX_DPATH = 3.5  # 侧方车辆最大路径偏移（米）

    # 优化：车道宽度计算参数
    DEFAULT_LANE_HALF_WIDTH = 1.75  # 默认车道半宽 3.5m / 2
    MIN_LANE_HALF_WIDTH = 0.1  # 最小车道半宽阈值（避免除零）
    TARGET_LANE_WIDTH_DISTANCE = 20.0  # 车道宽度计算的目标距离（米）

    def __init__(self):
        self.broadcast_port = 7701
        self.broadcast_ip = None
        self.sequence = 0

        # 初始化UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # 订阅消息（纯视觉数据，不使用雷达）
        self.sm = messaging.SubMaster([
            'carState',
            'modelV2',
            'selfdriveState',
            # 移除 'controlsState' - 不再需要 longControlState
            # 移除 'can' - 盲区数据直接从carState获取
            # 移除 'radarState' - 纯视觉方案，不使用雷达融合数据
        ])

        # 时间滤波：用于平滑侧方车辆数据（指数移动平均）
        # alpha 值：0.3 表示新数据权重 30%，历史数据权重 70%
        self.filter_alpha = 0.3
        self.lead_left_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
        self.lead_right_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
        self.lead_left_count = 0  # 连续检测计数（用于滤波初始化）
        self.lead_right_count = 0

        # 历史数据缓存：用于计算横向速度（yvRel）和滤波器初始化
        # 存储最近几帧的 yRel 和 dRel，用于计算横向速度
        self.lead_left_history: List[Dict[str, float]] = []  # 存储 {'yRel': float, 'dRel': float, 'timestamp': float}
        self.lead_right_history: List[Dict[str, float]] = []

        # 车道线数据缓存：避免重复计算
        # 修复：添加 position_valid 字段，缓存规划路径单调性验证结果
        self._lane_cache = {
            'lane_xs': None,
            'left_ys': None,
            'right_ys': None,
            'position_x': None,
            'position_y': None,
            'position_valid': False,  # 新增：缓存规划路径单调性验证结果
            'cache_valid': False
        }

        # 获取广播地址
        self.broadcast_ip = self.get_broadcast_address()
        if self.broadcast_ip == '255.255.255.255':
            print("Warning: Could not determine network interface, using fallback broadcast address")

    def get_broadcast_address(self):
        """获取广播地址"""
        interfaces = [b'br0', b'eth0', b'enp0s3'] if PC else [b'wlan0', b'eth0']

        for iface in interfaces:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    ip = fcntl.ioctl(
                        s.fileno(),
                        0x8919,  # SIOCGIFADDR
                        struct.pack('256s', iface)
                    )[20:24]
                    broadcast_ip = socket.inet_ntoa(ip)
                    ip_parts = broadcast_ip.split('.')
                    ip_parts[3] = '255'
                    return '.'.join(ip_parts)
            except (OSError, Exception):
                continue

        return '255.255.255.255'


    def collect_car_state(self, carState) -> Dict[str, Any]:
        """收集本车状态数据 - 最小化版本（只保留超车决策必需字段）"""
        # 数据验证：确保 vEgo 为有效值
        vEgo = float(carState.vEgo)
        if vEgo < 0:
            print(f"Warning: Invalid vEgo value: {vEgo}, using 0.0")
            vEgo = 0.0

        return {
            'vEgo': vEgo,  # 实际速度
            'steeringAngleDeg': float(carState.steeringAngleDeg),  # 方向盘角度
            'brakePressed': bool(carState.brakePressed),  # 刹车
            'leftLatDist': float(carState.leftLatDist),  # 车道距离（返回原车道）
            'rightLatDist': float(carState.rightLatDist),  # 车道距离（返回原车道）
            'leftLaneLine': int(carState.leftLaneLine),  # 车道线类型
            'rightLaneLine': int(carState.rightLaneLine),  # 车道线类型
            'standstill': bool(carState.standstill),  # 静止状态
            'leftBlindspot': bool(carState.leftBlindspot) if hasattr(carState, 'leftBlindspot') else False,  # 左盲区
            'rightBlindspot': bool(carState.rightBlindspot) if hasattr(carState, 'rightBlindspot') else False,  # 右盲区
        }

    def _update_lane_cache(self, modelV2):
        """更新车道线数据缓存，避免重复计算"""
        try:
            # 修复：需要至少 3 条线才能访问索引 1 和 2
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                self._lane_cache['cache_valid'] = False
                return

            # 修复：验证索引 1 和 2 是否存在（需要至少 3 个元素才能访问索引 2）
            if len(modelV2.laneLines) <= 2:
                self._lane_cache['cache_valid'] = False
                return

            # 提取车道线数据
            lane_xs = [float(x) for x in modelV2.laneLines[1].x]
            left_ys = [float(y) for y in modelV2.laneLines[1].y]
            right_ys = [float(y) for y in modelV2.laneLines[2].y]

            # 修复：验证长度一致性
            if not (len(lane_xs) == len(left_ys) == len(right_ys)):
                self._lane_cache['cache_valid'] = False
                return

            # 修复：验证 x 坐标是否单调递增（np.interp() 要求）
            if len(lane_xs) < 2 or not all(lane_xs[i] < lane_xs[i+1] for i in range(len(lane_xs)-1)):
                self._lane_cache['cache_valid'] = False
                return

            self._lane_cache['lane_xs'] = lane_xs
            self._lane_cache['left_ys'] = left_ys
            self._lane_cache['right_ys'] = right_ys

            # 更新规划路径数据
            # 修复：在缓存更新时验证单调性，并缓存验证结果，避免在 d_path_interp() 中重复检查
            if hasattr(modelV2, 'position') and len(modelV2.position.x) > 0:
                position_x = [float(x) for x in modelV2.position.x]
                position_y = [float(y) for y in modelV2.position.y]

                # 验证规划路径数据长度一致性和单调性，并缓存验证结果
                if len(position_x) == len(position_y) and len(position_x) >= 2:
                    # 验证 x 坐标单调递增（只验证一次，结果缓存到 position_valid）
                    if all(position_x[i] < position_x[i+1] for i in range(len(position_x)-1)):
                        self._lane_cache['position_x'] = position_x
                        self._lane_cache['position_y'] = position_y
                        self._lane_cache['position_valid'] = True  # 缓存验证结果
                    else:
                        self._lane_cache['position_x'] = None
                        self._lane_cache['position_y'] = None
                        self._lane_cache['position_valid'] = False
                else:
                    self._lane_cache['position_x'] = None
                    self._lane_cache['position_y'] = None
                    self._lane_cache['position_valid'] = False
            else:
                self._lane_cache['position_x'] = None
                self._lane_cache['position_y'] = None
                self._lane_cache['position_valid'] = False

            self._lane_cache['cache_valid'] = (
                len(self._lane_cache['lane_xs']) > 0 and
                len(self._lane_cache['left_ys']) > 0 and
                len(self._lane_cache['right_ys']) > 0
            )
        except (IndexError, AttributeError, ValueError) as e:
            # 修复：使用具体的异常类型
            self._lane_cache['cache_valid'] = False

    def _calculate_dpath(self, dRel: float, yRel: float, yvRel: float = 0.0, vLead: float = 0.0) -> Tuple[float, float, float]:
        """
        计算车辆相对于规划路径的横向偏移 (dPath) 和车道内概率 (in_lane_prob)
        参考 radard.py:74-87 的 d_path() 方法

        参数:
        - dRel: 相对于雷达的距离（已考虑 RADAR_TO_CAMERA 偏移）
        - yRel: 相对于相机的横向位置
        - yvRel: 横向速度（用于未来位置预测，可选）
        - vLead: 前车速度（用于未来位置预测，可选）

        返回: (dPath, in_lane_prob, in_lane_prob_future)
        - dPath: 相对于规划路径的横向偏移
        - in_lane_prob: 当前时刻在车道内的概率
        - in_lane_prob_future: 未来时刻在车道内的概率（用于 Cut-in 检测）
        """
        if not self._lane_cache['cache_valid']:
            return 0.0, 0.0, 0.0

        try:
            # 优化：移除重复的单调性检查，因为 cache_valid 已经保证了数据的有效性
            # 单调性验证已在 _update_lane_cache() 中完成
            lane_xs = self._lane_cache['lane_xs']
            left_ys = self._lane_cache['left_ys']
            right_ys = self._lane_cache['right_ys']

            def d_path_interp(dRel_val: float, yRel_val: float) -> Tuple[float, float]:
                """内部函数：计算指定距离处的 dPath 和 in_lane_prob"""
                # 在距离 dRel_val 处插值计算左右车道线的横向位置
                left_lane_y = np.interp(dRel_val, lane_xs, left_ys)
                right_lane_y = np.interp(dRel_val, lane_xs, right_ys)

                # 计算车道中心位置
                center_y = (left_lane_y + right_lane_y) / 2.0

                # 计算车道半宽
                # 优化：使用类常量替代魔法数字
                lane_half_width = abs(right_lane_y - left_lane_y) / 2.0
                if lane_half_width < self.MIN_LANE_HALF_WIDTH:
                    lane_half_width = self.DEFAULT_LANE_HALF_WIDTH

                # 修复：使用正确的符号计算相对于车道中心的偏移
                # yRel_val 和 center_y 都是相对于相机的，所以相减得到相对于车道中心的偏移
                dist_from_center = yRel_val - center_y

                # 计算在车道内的概率（距离中心越近，概率越高）
                # 参考 radard.py:82 的计算方法
                in_lane_prob = max(0.0, 1.0 - (abs(dist_from_center) / lane_half_width))

                # 计算 dPath（相对于规划路径的横向偏移）
                # 修复：使用缓存的验证结果，避免重复的单调性检查（性能优化）
                # 单调性验证已在 _update_lane_cache() 中完成并缓存到 position_valid
                if self._lane_cache.get('position_valid', False):
                    path_y = np.interp(dRel_val, self._lane_cache['position_x'], self._lane_cache['position_y'])
                    # 修复：同样修复符号，dPath = yRel - path_y
                    dPath = yRel_val - path_y
                else:
                    dPath = dist_from_center

                return dPath, in_lane_prob

            # 计算当前时刻的值
            dPath, in_lane_prob = d_path_interp(dRel, yRel)

            # 计算未来时刻的值（用于 Cut-in 检测）
            # 参考 radard.py:30-72 的 Track.update() 方法
            # yRel_future = yRel + yvLead * radar_lat_factor
            # dRel_future = dRel + vLead * radar_lat_factor
            future_dRel = dRel + vLead * self.RADAR_LAT_FACTOR
            future_yRel = yRel + yvRel * self.RADAR_LAT_FACTOR
            _, in_lane_prob_future = d_path_interp(future_dRel, future_yRel)

            return float(dPath), float(in_lane_prob), float(in_lane_prob_future)

        except (IndexError, ValueError, TypeError) as e:
            # 修复：使用具体的异常类型
            # 调试信息（可选）
            # print(f"Error in _calculate_dpath: {e}")
            return 0.0, 0.0, 0.0

    def _estimate_lateral_velocity(self, current_yRel: float, current_dRel: float, history: List[Dict[str, float]]) -> float:
        """
        估计横向速度（yvRel）
        通过历史数据计算 yRel 的变化率

        参数:
        - current_yRel: 当前横向位置（未使用，保留用于接口兼容性）
        - current_dRel: 当前距离（未使用，保留用于接口兼容性）
        - history: 历史数据列表，包含 {'yRel': float, 'dRel': float, 'timestamp': float}

        返回: 横向速度（m/s）
        """
        if len(history) < 2:
            return 0.0

        try:
            # 修复：使用历史数据中最近两帧的差值计算速度
            # 取最近的两帧
            recent = history[-2:]
            if len(recent) < 2:
                return 0.0

            dt = recent[1]['timestamp'] - recent[0]['timestamp']
            if dt <= 0:
                return 0.0

            # 修复：使用历史数据中最近两帧的差值，而不是当前值与历史值的差值
            dyRel = recent[1]['yRel'] - recent[0]['yRel']
            yvRel = dyRel / dt

            return float(yvRel)
        except (KeyError, IndexError, ZeroDivisionError) as e:
            # 修复：使用具体的异常类型
            return 0.0

    def _calculate_lane_width(self, modelV2) -> float:
        """
        使用车道线坐标数据计算实际车道宽度
        参考 carrot.cc:2119-2130
        在约 20 米处计算车道宽度（使用插值方法）

        优化：优先使用缓存的数据（已验证单调性），避免重复验证和重复数据转换
        """
        try:
            # 优化：优先使用缓存的数据，因为 _update_lane_cache() 已经验证过单调性
            # 这样可以避免重复验证和重复的数据转换，提升性能
            if self._lane_cache.get('cache_valid', False):
                lane_xs = self._lane_cache['lane_xs']
                left_ys = self._lane_cache['left_ys']
                right_ys = self._lane_cache['right_ys']

                # 使用类常量替代魔法数字
                target_distance = self.TARGET_LANE_WIDTH_DISTANCE

                # 检查目标距离是否在范围内（缓存数据已保证单调性）
                if (len(lane_xs) > 0 and
                    target_distance <= max(lane_xs) and target_distance >= min(lane_xs)):

                    # 使用缓存的数据进行插值计算
                    left_y_at_dist = np.interp(target_distance, lane_xs, left_ys)
                    right_y_at_dist = np.interp(target_distance, lane_xs, right_ys)
                    lane_width = abs(right_y_at_dist - left_y_at_dist)
                    return lane_width

            # 如果缓存无效，回退到直接从 modelV2 读取（需要验证单调性）
            # 需要至少 3 条车道线（0=左路边线, 1=左车道线, 2=右车道线, 3=右路边线）
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                return 0.0

            left_lane = modelV2.laneLines[1]  # 左车道线
            right_lane = modelV2.laneLines[2]  # 右车道线

            target_distance = self.TARGET_LANE_WIDTH_DISTANCE

            if (len(left_lane.x) > 0 and len(left_lane.y) > 0 and
                len(right_lane.x) > 0 and len(right_lane.y) > 0):

                left_x = [float(x) for x in left_lane.x]
                left_y = [float(y) for y in left_lane.y]
                right_x = [float(x) for x in right_lane.x]
                right_y = [float(y) for y in right_lane.y]

                # 验证列表非空后再调用 max/min，并验证 x 坐标单调性
                # 注意：只有在缓存无效时才需要验证，因为缓存已经验证过了
                if (len(left_x) > 0 and len(right_x) > 0 and
                    # 验证 x 坐标单调递增（缓存无效时才需要）
                    len(left_x) >= 2 and all(left_x[i] < left_x[i+1] for i in range(len(left_x)-1)) and
                    len(right_x) >= 2 and all(right_x[i] < right_x[i+1] for i in range(len(right_x)-1)) and
                    # 检查目标距离是否在范围内
                    target_distance <= max(left_x) and target_distance <= max(right_x) and
                    target_distance >= min(left_x) and target_distance >= min(right_x)):

                    left_y_at_dist = np.interp(target_distance, left_x, left_y)
                    right_y_at_dist = np.interp(target_distance, right_x, right_y)
                    lane_width = abs(right_y_at_dist - left_y_at_dist)
                    return lane_width
        except (IndexError, ValueError, TypeError) as e:
            # 修复：使用具体的异常类型
            pass

        return 0.0

    def collect_model_data(self, modelV2, carState=None) -> Dict[str, Any]:
        """
        收集模型数据 - 优化版本
        通过 modelV2 数据间接推断侧方车辆情况，替代 radarState

        参数:
        - modelV2: 模型数据
        - carState: 车辆状态数据（可选，用于获取更准确的自车速度）
        """
        data = {}

        # 修复：优先使用 carState.vEgo（来自CAN总线，更准确），如果不可用则使用模型估计
        v_ego = 0.0
        if carState is not None and hasattr(carState, 'vEgo'):
            v_ego = float(carState.vEgo)
        elif hasattr(modelV2, 'velocity') and len(modelV2.velocity.x) > 0:
            v_ego = float(modelV2.velocity.x[0])

        data['modelVEgo'] = v_ego
        # 后续代码使用 v_ego 替代 model_v_ego

        # 更新车道线数据缓存（每帧更新一次，避免重复计算）
        self._update_lane_cache(modelV2)

        # 计算实际车道宽度（用于判断侧方车辆位置）
        lane_width = self._calculate_lane_width(modelV2)
        if lane_width > 0:
            data['laneWidth'] = lane_width
        else:
            # 如果无法从车道线计算，使用默认值 3.5 米
            lane_width = 3.5

        # 获取当前时间戳（用于计算横向速度）
        current_time = time.time()

        # 分类所有检测到的车辆（左/右/中车道）
        left_vehicles: List[Dict[str, Any]] = []
        right_vehicles: List[Dict[str, Any]] = []
        center_vehicles: List[Dict[str, Any]] = []

        # 遍历所有检测目标
        for i, lead in enumerate(modelV2.leadsV3):
            lead_prob = float(lead.prob)

            # 动态置信度阈值：根据距离和速度调整
            # 参考 radard.py:126-157 的匹配逻辑
            x = float(lead.x[0]) if len(lead.x) > 0 else 0.0  # 纵向距离
            v = float(lead.v[0]) if len(lead.v) > 0 else 0.0  # 速度

            # 优化：使用类常量配置动态置信度阈值
            # 动态调整置信度阈值：距离越远或速度差异越大，要求置信度越高
            min_prob = self.CONFIDENCE_BASE_THRESHOLD
            if x > self.CONFIDENCE_DISTANCE_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_DISTANCE_BOOST)
            if abs(v - v_ego) > self.CONFIDENCE_VELOCITY_DIFF_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_VELOCITY_BOOST)

            # 过滤低置信度目标
            if lead_prob < min_prob:
                continue

            # 提取车辆数据
            y = float(lead.y[0]) if len(lead.y) > 0 else 0.0  # 横向位置
            a = float(lead.a[0]) if len(lead.a) > 0 else 0.0  # 加速度

            # 计算相对速度（使用更准确的自车速度）
            v_rel = v - v_ego  # 修复：使用 v_ego

            # 计算 dRel（考虑雷达到相机的偏移，参考 radard.py:220-243）
            # 注意：虽然不使用雷达，但 RADAR_TO_CAMERA 是相机到车辆中心的偏移
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y  # 注意符号：modelV2.leadsV3[i].y 与 yRel 符号相反

            # 估计横向速度（yvRel）- 用于未来位置预测
            # 对于当前检测目标，使用简化的方法：假设横向速度与相对速度相关
            # 在实际应用中，可以通过历史数据计算，这里使用简化估计
            yvRel = 0.0  # 默认值，将在后续通过历史数据改进

            # 计算前车速度（vLead = vEgo + vRel）
            vLead = v_ego + v_rel  # 修复：使用 v_ego

            # 计算路径偏移和车道内概率（使用缓存和未来位置预测）
            dPath, in_lane_prob, in_lane_prob_future = self._calculate_dpath(dRel, yRel, yvRel, vLead)

            vehicle_data = {
                'x': x,
                'dRel': dRel,  # 相对于雷达的距离（已考虑 RADAR_TO_CAMERA 偏移）
                'y': y,
                'yRel': yRel,  # 相对于相机的横向位置
                'v': v,
                'vLead': vLead,  # 前车绝对速度
                'a': a,
                'vRel': v_rel,  # 相对速度
                'yvRel': yvRel,  # 横向速度（用于未来位置预测）
                'dPath': dPath,  # 路径偏移
                'inLaneProb': in_lane_prob,  # 车道内概率
                'inLaneProbFuture': in_lane_prob_future,  # 未来车道内概率（用于 Cut-in 检测）
                'prob': lead_prob,
                'timestamp': current_time,  # 时间戳，用于计算横向速度
            }

            # 优化：使用类常量配置车道分类阈值
            # 根据车道内概率和横向位置分类车辆
            # 参考 radard.py:520-546 的分类逻辑
            if in_lane_prob > self.LANE_PROB_THRESHOLD:
                # 当前车道车辆
                center_vehicles.append(vehicle_data)
            elif yRel < 0:  # 左侧车道
                left_vehicles.append(vehicle_data)
            else:  # 右侧车道
                right_vehicles.append(vehicle_data)

        # 前车检测 - 选择当前车道最近的前车（lead0）
        if center_vehicles:
            # 选择距离最近的前车
            lead0 = min(center_vehicles, key=lambda v: v['x'])
            data['lead0'] = {
                'x': lead0['x'],
                'dRel': lead0.get('dRel', lead0['x']),
                'v': lead0['v'],
                'a': lead0['a'],
                'y': lead0['y'],  # 添加横向位置
                'yRel': lead0.get('yRel', -lead0['y']),
                'vRel': lead0['vRel'],  # 相对速度
                'dPath': lead0['dPath'],  # 路径偏移
                'inLaneProb': lead0.get('inLaneProb', 1.0),
                'prob': lead0['prob'],
            }
        elif len(modelV2.leadsV3) > 0:
            # 如果没有明确的中心车道车辆，使用第一个检测目标
            lead0 = modelV2.leadsV3[0]
            x = float(lead0.x[0]) if len(lead0.x) > 0 else 0.0
            y = float(lead0.y[0]) if len(lead0.y) > 0 else 0.0
            v = float(lead0.v[0]) if len(lead0.v) > 0 else 0.0
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y
            v_rel = v - v_ego  # 修复：使用 v_ego
            vLead = v_ego + v_rel  # 修复：使用 v_ego
            dPath, in_lane_prob, _ = self._calculate_dpath(dRel, yRel, 0.0, vLead)
            data['lead0'] = {
                'x': x,
                'dRel': dRel,
                'v': v,
                'a': float(lead0.a[0]) if len(lead0.a) > 0 else 0.0,
                'y': y,  # 添加横向位置
                'yRel': yRel,
                'vRel': v - v_ego,  # 修复：使用 v_ego
                'dPath': dPath,
                'inLaneProb': in_lane_prob,
                'prob': float(lead0.prob),
            }
        else:
            data['lead0'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'a': 0.0, 'y': 0.0, 'yRel': 0.0,
                'vRel': 0.0, 'dPath': 0.0, 'inLaneProb': 0.0, 'prob': 0.0
            }

        # 第二前车 - 选择当前车道第二近的前车（lead1）
        if len(center_vehicles) > 1:
            # 按距离排序，选择第二近的
            sorted_center = sorted(center_vehicles, key=lambda v: v['x'])
            lead1 = sorted_center[1]
            data['lead1'] = {
                'x': lead1['x'],
                'dRel': lead1.get('dRel', lead1['x']),
                'v': lead1['v'],
                'a': lead1['a'],  # 添加加速度字段，与 lead0 保持一致
                'y': lead1['y'],  # 添加横向位置
                'yRel': lead1.get('yRel', -lead1['y']),
                'vRel': lead1['vRel'],
                'dPath': lead1['dPath'],
                'inLaneProb': lead1.get('inLaneProb', 1.0),
                'prob': lead1['prob'],
            }
        elif len(modelV2.leadsV3) > 1:
            # 如果没有明确的中心车道第二辆车，使用第二个检测目标
            lead1 = modelV2.leadsV3[1]
            x = float(lead1.x[0]) if len(lead1.x) > 0 else 0.0
            y = float(lead1.y[0]) if len(lead1.y) > 0 else 0.0
            v = float(lead1.v[0]) if len(lead1.v) > 0 else 0.0
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y
            v_rel = v - v_ego  # 修复：使用 v_ego
            vLead = v_ego + v_rel  # 修复：使用 v_ego
            dPath, in_lane_prob, _ = self._calculate_dpath(dRel, yRel, 0.0, vLead)
            data['lead1'] = {
                'x': x,
                'dRel': dRel,
                'v': v,
                'a': float(lead1.a[0]) if len(lead1.a) > 0 else 0.0,  # 添加加速度字段
                'y': y,  # 添加横向位置
                'yRel': yRel,
                'vRel': v - v_ego,  # 修复：使用 v_ego
                'dPath': dPath,
                'inLaneProb': in_lane_prob,
                'prob': float(lead1.prob),
            }
        else:
            data['lead1'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'a': 0.0, 'y': 0.0, 'yRel': 0.0,
                'vRel': 0.0, 'dPath': 0.0, 'inLaneProb': 0.0, 'prob': 0.0
            }

        # 优化：使用类常量配置侧方车辆筛选参数
        # 侧方车辆检测 - 选择最近的左侧和右侧车辆
        # 参考 radard.py:560-569 的筛选逻辑
        left_filtered = [
            v for v in left_vehicles
            if v['dRel'] > self.SIDE_VEHICLE_MIN_DISTANCE and abs(v['dPath']) < self.SIDE_VEHICLE_MAX_DPATH
        ]
        right_filtered = [
            v for v in right_vehicles
            if v['dRel'] > self.SIDE_VEHICLE_MIN_DISTANCE and abs(v['dPath']) < self.SIDE_VEHICLE_MAX_DPATH
        ]

        # 优化：使用类常量配置 Cut-in 检测阈值
        # Cut-in 检测：检测可能切入的车辆
        # 参考 radard.py:520-546，使用 in_lane_prob_future 检测
        cutin_vehicles = []
        for v in left_vehicles + right_vehicles:
            # 如果未来车道内概率超过阈值，可能是切入车辆
            if v.get('inLaneProbFuture', 0.0) > self.CUTIN_PROB_THRESHOLD:
                cutin_vehicles.append(v)

        # 选择左侧最近的车辆
        if left_filtered:
            lead_left = min(left_filtered, key=lambda vehicle: vehicle['dRel'])

            # 更新历史数据（用于计算横向速度）
            self.lead_left_history.append({
                'yRel': lead_left['yRel'],
                'dRel': lead_left['dRel'],
                'timestamp': lead_left.get('timestamp', current_time)
            })
            # 优化：使用类常量配置历史数据大小
            # 只保留最近 HISTORY_SIZE 帧数据
            if len(self.lead_left_history) > self.HISTORY_SIZE:
                self.lead_left_history.pop(0)

            # 计算横向速度（用于未来位置预测）
            yvRel = self._estimate_lateral_velocity(
                lead_left['yRel'],
                lead_left['dRel'],
                self.lead_left_history
            )

            # 应用时间滤波（指数移动平均）
            # 参考 radard.py:520-546，需要至少 FILTER_INIT_FRAMES 帧数据才使用滤波
            if self.lead_left_count < self.FILTER_INIT_FRAMES:
                # 初始化阶段：累积数据，使用平均值
                if self.lead_left_count == 0:
                    # 修复：只复制需要滤波的字段，避免复制不必要的字段（如timestamp, inLaneProb等）
                    self.lead_left_filtered = {
                        'x': lead_left['x'],
                        'v': lead_left['v'],
                        'y': lead_left['y'],
                        'vRel': lead_left['vRel'],
                        'dPath': lead_left['dPath'],
                        'yRel': lead_left['yRel']
                    }
                else:
                    # 使用简单平均初始化
                    count = self.lead_left_count + 1
                    self.lead_left_filtered['x'] = (self.lead_left_filtered['x'] * self.lead_left_count + lead_left['x']) / count
                    self.lead_left_filtered['v'] = (self.lead_left_filtered['v'] * self.lead_left_count + lead_left['v']) / count
                    self.lead_left_filtered['y'] = (self.lead_left_filtered['y'] * self.lead_left_count + lead_left['y']) / count
                    self.lead_left_filtered['vRel'] = (self.lead_left_filtered['vRel'] * self.lead_left_count + lead_left['vRel']) / count
                    self.lead_left_filtered['dPath'] = (self.lead_left_filtered['dPath'] * self.lead_left_count + lead_left['dPath']) / count
                    self.lead_left_filtered['yRel'] = (self.lead_left_filtered['yRel'] * self.lead_left_count + lead_left['yRel']) / count
            else:
                # 稳定阶段：使用指数移动平均滤波
                alpha = self.filter_alpha
                self.lead_left_filtered['x'] = alpha * lead_left['x'] + (1 - alpha) * self.lead_left_filtered['x']
                self.lead_left_filtered['v'] = alpha * lead_left['v'] + (1 - alpha) * self.lead_left_filtered['v']
                self.lead_left_filtered['y'] = alpha * lead_left['y'] + (1 - alpha) * self.lead_left_filtered['y']
                self.lead_left_filtered['vRel'] = alpha * lead_left['vRel'] + (1 - alpha) * self.lead_left_filtered['vRel']
                self.lead_left_filtered['dPath'] = alpha * lead_left['dPath'] + (1 - alpha) * self.lead_left_filtered['dPath']
                self.lead_left_filtered['yRel'] = alpha * lead_left['yRel'] + (1 - alpha) * self.lead_left_filtered['yRel']

            self.lead_left_count += 1

            data['leadLeft'] = {
                'x': self.lead_left_filtered['x'],
                'dRel': lead_left['dRel'],  # 使用原始值，不过滤
                'v': self.lead_left_filtered['v'],
                'y': self.lead_left_filtered['y'],
                'yRel': self.lead_left_filtered['yRel'],
                'vRel': self.lead_left_filtered['vRel'],
                'yvRel': yvRel,  # 横向速度
                'dPath': self.lead_left_filtered['dPath'],
                'inLaneProb': lead_left.get('inLaneProb', 0.0),
                'inLaneProbFuture': lead_left.get('inLaneProbFuture', 0.0),
                'prob': lead_left['prob'],
                'status': True,
            }
        else:
            # 没有检测到车辆，重置滤波状态
            self.lead_left_count = 0
            self.lead_left_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
            self.lead_left_history.clear()  # 清空历史数据
            data['leadLeft'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'y': 0.0, 'yRel': 0.0, 'vRel': 0.0, 'yvRel': 0.0,
                'dPath': 0.0, 'inLaneProb': 0.0, 'inLaneProbFuture': 0.0,
                'prob': 0.0, 'status': False
            }

        # 选择右侧最近的车辆
        if right_filtered:
            lead_right = min(right_filtered, key=lambda vehicle: vehicle['dRel'])

            # 更新历史数据（用于计算横向速度）
            self.lead_right_history.append({
                'yRel': lead_right['yRel'],
                'dRel': lead_right['dRel'],
                'timestamp': lead_right.get('timestamp', current_time)
            })
            # 优化：使用类常量配置历史数据大小
            # 只保留最近 HISTORY_SIZE 帧数据
            if len(self.lead_right_history) > self.HISTORY_SIZE:
                self.lead_right_history.pop(0)

            # 计算横向速度（用于未来位置预测）
            yvRel = self._estimate_lateral_velocity(
                lead_right['yRel'],
                lead_right['dRel'],
                self.lead_right_history
            )

            # 应用时间滤波（指数移动平均）
            # 参考 radard.py:520-546，需要至少 FILTER_INIT_FRAMES 帧数据才使用滤波
            if self.lead_right_count < self.FILTER_INIT_FRAMES:
                # 初始化阶段：累积数据，使用平均值
                if self.lead_right_count == 0:
                    # 修复：只复制需要滤波的字段，避免复制不必要的字段（如timestamp, inLaneProb等）
                    self.lead_right_filtered = {
                        'x': lead_right['x'],
                        'v': lead_right['v'],
                        'y': lead_right['y'],
                        'vRel': lead_right['vRel'],
                        'dPath': lead_right['dPath'],
                        'yRel': lead_right['yRel']
                    }
                else:
                    # 使用简单平均初始化
                    count = self.lead_right_count + 1
                    self.lead_right_filtered['x'] = (self.lead_right_filtered['x'] * self.lead_right_count + lead_right['x']) / count
                    self.lead_right_filtered['v'] = (self.lead_right_filtered['v'] * self.lead_right_count + lead_right['v']) / count
                    self.lead_right_filtered['y'] = (self.lead_right_filtered['y'] * self.lead_right_count + lead_right['y']) / count
                    self.lead_right_filtered['vRel'] = (self.lead_right_filtered['vRel'] * self.lead_right_count + lead_right['vRel']) / count
                    self.lead_right_filtered['dPath'] = (self.lead_right_filtered['dPath'] * self.lead_right_count + lead_right['dPath']) / count
                    self.lead_right_filtered['yRel'] = (self.lead_right_filtered['yRel'] * self.lead_right_count + lead_right['yRel']) / count
            else:
                # 稳定阶段：使用指数移动平均滤波
                alpha = self.filter_alpha
                self.lead_right_filtered['x'] = alpha * lead_right['x'] + (1 - alpha) * self.lead_right_filtered['x']
                self.lead_right_filtered['v'] = alpha * lead_right['v'] + (1 - alpha) * self.lead_right_filtered['v']
                self.lead_right_filtered['y'] = alpha * lead_right['y'] + (1 - alpha) * self.lead_right_filtered['y']
                self.lead_right_filtered['vRel'] = alpha * lead_right['vRel'] + (1 - alpha) * self.lead_right_filtered['vRel']
                self.lead_right_filtered['dPath'] = alpha * lead_right['dPath'] + (1 - alpha) * self.lead_right_filtered['dPath']
                self.lead_right_filtered['yRel'] = alpha * lead_right['yRel'] + (1 - alpha) * self.lead_right_filtered['yRel']

            self.lead_right_count += 1

            data['leadRight'] = {
                'x': self.lead_right_filtered['x'],
                'dRel': lead_right['dRel'],  # 使用原始值，不过滤
                'v': self.lead_right_filtered['v'],
                'y': self.lead_right_filtered['y'],
                'yRel': self.lead_right_filtered['yRel'],
                'vRel': self.lead_right_filtered['vRel'],
                'yvRel': yvRel,  # 横向速度
                'dPath': self.lead_right_filtered['dPath'],
                'inLaneProb': lead_right.get('inLaneProb', 0.0),
                'inLaneProbFuture': lead_right.get('inLaneProbFuture', 0.0),
                'prob': lead_right['prob'],
                'status': True,
            }
        else:
            # 没有检测到车辆，重置滤波状态
            self.lead_right_count = 0
            self.lead_right_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
            self.lead_right_history.clear()  # 清空历史数据
            data['leadRight'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'y': 0.0, 'yRel': 0.0, 'vRel': 0.0, 'yvRel': 0.0,
                'dPath': 0.0, 'inLaneProb': 0.0, 'inLaneProbFuture': 0.0,
                'prob': 0.0, 'status': False
            }

        # 添加 Cut-in 检测结果
        if cutin_vehicles:
            # 选择最近的潜在切入车辆
            cutin_vehicle = min(cutin_vehicles, key=lambda vehicle: vehicle['dRel'])
            data['cutin'] = {
                'x': cutin_vehicle['x'],
                'dRel': cutin_vehicle['dRel'],
                'v': cutin_vehicle['v'],
                'y': cutin_vehicle['y'],
                'vRel': cutin_vehicle['vRel'],
                'dPath': cutin_vehicle['dPath'],
                'inLaneProb': cutin_vehicle.get('inLaneProb', 0.0),
                'inLaneProbFuture': cutin_vehicle.get('inLaneProbFuture', 0.0),
                'prob': cutin_vehicle['prob'],
                'status': True,
            }
        else:
            data['cutin'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0,
                'dPath': 0.0, 'inLaneProb': 0.0, 'inLaneProbFuture': 0.0,
                'prob': 0.0, 'status': False
            }

        # 车道线置信度 - 超车决策需要
        data['laneLineProbs'] = [
            float(modelV2.laneLineProbs[1]) if len(modelV2.laneLineProbs) >= 3 else 0.0,  # 左车道线置信度
            float(modelV2.laneLineProbs[2]) if len(modelV2.laneLineProbs) >= 3 else 0.0,  # 右车道线置信度
        ]

        # 车道宽度和变道状态 - 保留（超车决策需要）
        meta = modelV2.meta
        # Cap'n Proto 枚举类型转换：_DynamicEnum 类型需要特殊处理
        def enum_to_int(enum_value, default=0):
            """将 Cap'n Proto 枚举转换为整数"""
            if enum_value is None:
                return default
            try:
                return int(enum_value)
            except (TypeError, ValueError):
                try:
                    return enum_value.raw
                except AttributeError:
                    try:
                        return enum_value.value
                    except AttributeError:
                        try:
                            return int(str(enum_value).split('.')[-1])
                        except (ValueError, AttributeError):
                            return default

        data['meta'] = {
            'laneWidthLeft': float(meta.laneWidthLeft),  # 左车道宽度
            'laneWidthRight': float(meta.laneWidthRight),  # 右车道宽度
            'laneChangeState': enum_to_int(meta.laneChangeState, 0),  # 变道状态
            'laneChangeDirection': enum_to_int(meta.laneChangeDirection, 0),  # 变道方向
        }

        # 曲率信息 - 用于判断弯道（超车决策关键数据）
        # 修复：改进空列表检查逻辑，使代码更清晰
        if hasattr(modelV2, 'orientationRate') and len(modelV2.orientationRate.z) > 0:
            orientation_rate_z = [float(x) for x in modelV2.orientationRate.z]
            data['curvature'] = {
                'maxOrientationRate': max(orientation_rate_z, key=abs),  # 最大方向变化率 (rad/s)
            }
        else:
            data['curvature'] = {'maxOrientationRate': 0.0}

        return data

    def collect_system_state(self, selfdriveState) -> Dict[str, Any]:
        """收集系统状态"""
        return {
            'enabled': bool(selfdriveState.enabled) if selfdriveState else False,
            'active': bool(selfdriveState.active) if selfdriveState else False,
        }

    # 移除 collect_carrot_data() - CarrotMan 数据已不再需要
    # 移除 collect_blindspot_data() - 盲区数据已直接从carState获取

    def create_packet(self, data: Dict[str, Any]) -> bytes:
        """创建数据包，包含序列号、时间戳和校验"""
        packet_data = {
            'version': 1,
            'sequence': self.sequence,
            'timestamp': time.time(),
            'data': data
        }

        # 转换为JSON
        json_str = json.dumps(packet_data)
        packet_bytes = json_str.encode('utf-8')

        # 添加CRC32校验
        checksum = zlib.crc32(packet_bytes) & 0xffffffff

        # 数据包格式: [校验和(4字节)][数据长度(4字节)][数据]
        packet = struct.pack('!II', checksum, len(packet_bytes)) + packet_bytes

        # 修复：改进数据包大小检查和处理
        if len(packet) > 1400:  # 留一些余量，避免超过MTU（以太网MTU通常为1500字节）
            print(f"Warning: Packet size {len(packet)} bytes may exceed MTU")
            # 注意：如果数据包过大，可以考虑：
            # 1. 压缩数据（但会增加CPU开销）
            # 2. 分包发送（但会增加协议复杂度）
            # 3. 减少数据字段（但可能影响功能）
            # 当前实现：仅记录警告，由上层决定如何处理

        return packet

    def broadcast_data(self):
        """主循环：收集数据并广播"""
        rk = Ratekeeper(20, print_delay_threshold=None)  # 20Hz

        print(f"XiaogeDataBroadcaster started, broadcasting to {self.broadcast_ip}:{self.broadcast_port}")

        while True:
            try:
                # 性能监控
                start_time = time.perf_counter()

                # 更新所有消息
                self.sm.update(0)

                # 收集数据
                data = {}

                # 本车状态 - 始终收集（数据验证已在 collect_car_state() 内部完成）
                if self.sm.alive['carState']:
                    data['carState'] = self.collect_car_state(self.sm['carState'])

                # 模型数据
                if self.sm.alive['modelV2']:
                    # 修复：传递 carState 以获取更准确的自车速度
                    carState = self.sm['carState'] if self.sm.alive['carState'] else None
                    data['modelV2'] = self.collect_model_data(self.sm['modelV2'], carState)

                # 系统状态
                if self.sm.alive['selfdriveState']:
                    data['systemState'] = self.collect_system_state(
                        self.sm['selfdriveState']
                    )

                # 盲区数据已包含在carState中，无需单独收集

                # 性能监控
                processing_time = time.perf_counter() - start_time
                if processing_time > 0.05:  # 超过50ms
                    print(f"Warning: Slow processing detected: {processing_time*1000:.1f}ms")

                # 如果有数据则广播
                # 注意：如果 openpilot 系统正常运行，至少会有 carState 数据
                # Android 端已有 15 秒超时机制，不需要额外的心跳包
                if data:
                    packet = self.create_packet(data)

                    try:
                        self.udp_socket.sendto(packet, (self.broadcast_ip, self.broadcast_port))
                        self.sequence += 1

                        # 每100帧打印一次日志
                        if self.sequence % 100 == 0:
                            print(f"Broadcasted {self.sequence} packets, last size: {len(packet)} bytes")
                    except Exception as e:
                        print(f"Failed to broadcast packet: {e}")
                # 如果没有数据，不发送任何包（系统可能未启动或消息源不可用）
                # Android 端会在 15 秒后检测到超时并显示"断开"

                rk.keep_time()

            except Exception as e:
                print(f"XiaogeDataBroadcaster error: {e}")
                traceback.print_exc()
                time.sleep(1)


def main():
    broadcaster = XiaogeDataBroadcaster()
    broadcaster.broadcast_data()


if __name__ == "__main__":
    main()