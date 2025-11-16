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
        self._lane_cache = {
            'lane_xs': None,
            'left_ys': None,
            'right_ys': None,
            'position_x': None,
            'position_y': None,
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
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                self._lane_cache['cache_valid'] = False
                return
            
            # 更新车道线数据
            self._lane_cache['lane_xs'] = [float(x) for x in modelV2.laneLines[1].x]
            self._lane_cache['left_ys'] = [float(y) for y in modelV2.laneLines[1].y]
            self._lane_cache['right_ys'] = [float(y) for y in modelV2.laneLines[2].y]
            
            # 更新规划路径数据
            if hasattr(modelV2, 'position') and len(modelV2.position.x) > 0:
                self._lane_cache['position_x'] = [float(x) for x in modelV2.position.x]
                self._lane_cache['position_y'] = [float(y) for y in modelV2.position.y]
            else:
                self._lane_cache['position_x'] = None
                self._lane_cache['position_y'] = None
            
            self._lane_cache['cache_valid'] = (
                len(self._lane_cache['lane_xs']) > 0 and
                len(self._lane_cache['left_ys']) > 0 and
                len(self._lane_cache['right_ys']) > 0
            )
        except Exception:
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
                lane_half_width = abs(right_lane_y - left_lane_y) / 2.0
                if lane_half_width < 0.1:  # 避免除零
                    lane_half_width = 1.75  # 默认车道半宽 3.5m / 2
                
                # 计算车辆相对于车道中心的偏移
                dist_from_center = yRel_val + center_y
                
                # 计算在车道内的概率（距离中心越近，概率越高）
                # 参考 radard.py:82 的计算方法
                in_lane_prob = max(0.0, 1.0 - (abs(dist_from_center) / lane_half_width))
                
                # 计算 dPath（相对于规划路径的横向偏移）
                if self._lane_cache['position_x'] is not None:
                    path_y = np.interp(dRel_val, self._lane_cache['position_x'], self._lane_cache['position_y'])
                    dPath = yRel_val + path_y
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
            
        except Exception as e:
            # 调试信息（可选）
            # print(f"Error in _calculate_dpath: {e}")
            return 0.0, 0.0, 0.0
    
    def _estimate_lateral_velocity(self, current_yRel: float, current_dRel: float, history: List[Dict[str, float]]) -> float:
        """
        估计横向速度（yvRel）
        通过历史数据计算 yRel 的变化率
        
        参数:
        - current_yRel: 当前横向位置
        - current_dRel: 当前距离
        - history: 历史数据列表，包含 {'yRel': float, 'dRel': float, 'timestamp': float}
        
        返回: 横向速度（m/s）
        """
        if len(history) < 2:
            return 0.0
        
        try:
            # 使用最近两帧数据计算速度
            # 取最近的两帧
            recent = history[-2:]
            if len(recent) < 2:
                return 0.0
            
            dt = recent[1]['timestamp'] - recent[0]['timestamp']
            if dt <= 0:
                return 0.0
            
            # 计算 yRel 的变化率（横向速度）
            dyRel = current_yRel - recent[0]['yRel']
            yvRel = dyRel / dt
            
            return float(yvRel)
        except Exception:
            return 0.0

    def _calculate_lane_width(self, modelV2) -> float:
        """
        使用车道线坐标数据计算实际车道宽度
        参考 carrot.cc:2119-2130
        在约 20 米处计算车道宽度
        """
        try:
            # 需要至少 3 条车道线（0=左路边线, 1=左车道线, 2=右车道线, 3=右路边线）
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                return 0.0
            
            left_lane = modelV2.laneLines[1]  # 左车道线
            right_lane = modelV2.laneLines[2]  # 右车道线
            
            # 在约 20 米处（索引 10 对应约 20 米）计算车道宽度
            idx = 10
            if len(left_lane.y) > idx and len(right_lane.y) > idx:
                lane_width = abs(float(left_lane.y[idx]) - float(right_lane.y[idx]))
                return lane_width
        except Exception:
            pass
        
        return 0.0

    def collect_model_data(self, modelV2) -> Dict[str, Any]:
        """
        收集模型数据 - 优化版本
        通过 modelV2 数据间接推断侧方车辆情况，替代 radarState
        """
        data = {}

        # 获取模型估计的自车速度（用于计算相对速度）
        model_v_ego = 0.0
        if hasattr(modelV2, 'velocity') and len(modelV2.velocity.x) > 0:
            model_v_ego = float(modelV2.velocity.x[0])
        data['modelVEgo'] = model_v_ego

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
            
            # 动态调整置信度阈值：距离越远或速度差异越大，要求置信度越高
            # 基础阈值 0.5，根据距离和速度调整
            min_prob = 0.5
            if x > 50:  # 距离超过 50 米
                min_prob = max(min_prob, 0.7)
            if abs(v - model_v_ego) > 10:  # 速度差异超过 10 m/s
                min_prob = max(min_prob, 0.6)
            
            # 过滤低置信度目标
            if lead_prob < min_prob:
                continue

            # 提取车辆数据
            y = float(lead.y[0]) if len(lead.y) > 0 else 0.0  # 横向位置
            a = float(lead.a[0]) if len(lead.a) > 0 else 0.0  # 加速度

            # 计算相对速度（使用模型估计的自车速度）
            v_rel = v - model_v_ego

            # 计算 dRel（考虑雷达到相机的偏移，参考 radard.py:220-243）
            # 注意：虽然不使用雷达，但 RADAR_TO_CAMERA 是相机到车辆中心的偏移
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y  # 注意符号：modelV2.leadsV3[i].y 与 yRel 符号相反
            
            # 估计横向速度（yvRel）- 用于未来位置预测
            # 对于当前检测目标，使用简化的方法：假设横向速度与相对速度相关
            # 在实际应用中，可以通过历史数据计算，这里使用简化估计
            yvRel = 0.0  # 默认值，将在后续通过历史数据改进
            
            # 计算前车速度（vLead = vEgo + vRel）
            vLead = model_v_ego + v_rel

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

            # 根据车道内概率和横向位置分类车辆
            # 参考 radard.py:520-546 的分类逻辑
            # in_lane_prob > 0.1: 当前车道车辆
            # in_lane_prob <= 0.1 且 yRel < 0: 左侧车道车辆
            # in_lane_prob <= 0.1 且 yRel >= 0: 右侧车道车辆
            if in_lane_prob > 0.1:
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
            v_rel = v - model_v_ego
            vLead = model_v_ego + v_rel
            dPath, in_lane_prob, _ = self._calculate_dpath(dRel, yRel, 0.0, vLead)
            data['lead0'] = {
                'x': x,
                'dRel': dRel,
                'v': v,
                'a': float(lead0.a[0]) if len(lead0.a) > 0 else 0.0,
                'y': y,  # 添加横向位置
                'yRel': yRel,
                'vRel': v - model_v_ego,  # 修复：始终计算相对速度
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
            v_rel = v - model_v_ego
            vLead = model_v_ego + v_rel
            dPath, in_lane_prob, _ = self._calculate_dpath(dRel, yRel, 0.0, vLead)
            data['lead1'] = {
                'x': x,
                'dRel': dRel,
                'v': v,
                'a': float(lead1.a[0]) if len(lead1.a) > 0 else 0.0,  # 添加加速度字段
                'y': y,  # 添加横向位置
                'yRel': yRel,
                'vRel': v - model_v_ego,  # 修复：始终计算相对速度
                'dPath': dPath,
                'inLaneProb': in_lane_prob,
                'prob': float(lead1.prob),
            }
        else:
            data['lead1'] = {
                'x': 0.0, 'dRel': 0.0, 'v': 0.0, 'a': 0.0, 'y': 0.0, 'yRel': 0.0,
                'vRel': 0.0, 'dPath': 0.0, 'inLaneProb': 0.0, 'prob': 0.0
            }

        # 侧方车辆检测 - 选择最近的左侧和右侧车辆
        # 参考 radard.py:560-569 的筛选逻辑：dRel > 5 且 |dPath| < 3.5
        left_filtered = [
            v for v in left_vehicles 
            if v['dRel'] > 5.0 and abs(v['dPath']) < 3.5
        ]
        right_filtered = [
            v for v in right_vehicles 
            if v['dRel'] > 5.0 and abs(v['dPath']) < 3.5
        ]
        
        # Cut-in 检测：检测可能切入的车辆
        # 参考 radard.py:520-546，使用 in_lane_prob_future 检测
        cutin_vehicles = []
        for v in left_vehicles + right_vehicles:
            # 如果未来车道内概率 > 0.1，可能是切入车辆
            if v.get('inLaneProbFuture', 0.0) > 0.1:
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
            # 只保留最近 10 帧数据
            if len(self.lead_left_history) > 10:
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
                    self.lead_left_filtered = lead_left.copy()
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
            # 只保留最近 10 帧数据
            if len(self.lead_right_history) > 10:
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
                    self.lead_right_filtered = lead_right.copy()
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
        if hasattr(modelV2, 'orientationRate') and modelV2.orientationRate.z:
            orientation_rate_z = [float(x) for x in modelV2.orientationRate.z]
            data['curvature'] = {
                'maxOrientationRate': max(orientation_rate_z, key=abs) if orientation_rate_z else 0.0,  # 最大方向变化率 (rad/s)
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

        # 检查数据包大小
        if len(packet) > 1400:  # 留一些余量，避免超过MTU
            print(f"Warning: Packet size {len(packet)} bytes may exceed MTU")

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
                    data['modelV2'] = self.collect_model_data(self.sm['modelV2'])

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
