#!/usr/bin/env python3
"""
变道验证模块
多源验证系统，确保变道检测的准确性
"""

import time
from collections import deque, Counter

class LaneChangeVerificationSystem:
    """多源变道验证系统"""

    def __init__(self):
        self.lane_change_verification = {
            'last_confirmed_lane': 0,
            'verification_events': deque(maxlen=10),
            'confidence_score': 100,
            'min_confidence': 60,
            'last_blinker_state': 'none',
            'last_steering_angle': 0,
            'blinker_change_time': 0
        }

        # 转向灯变道验证
        self.blinker_lane_change_tracker = {
            'pending_change': False,
            'blinker_start_time': 0,
            'expected_direction': None,
            'lane_before_blinker': 0
        }

        # 车道序号稳定性优化
        self.lane_number_history = []
        self.lane_count_history = []
        self.max_history_size = 10

    def verify_lane_change_multisource(self, from_lane, to_lane, lane_change, vehicle_data):
        """
        多源验证变道是否真实发生
        返回: (是否通过, 验证分数, 原因列表)
        """
        verification_score = 0
        max_score = 100
        reasons = []

        current_time = time.time() * 1000

        # 🎯 验证1：转向灯状态 (权重: 30%)
        expected_blinker = "left" if lane_change == -1 else "right"
        current_blinker = vehicle_data.get('blinker', 'none')

        if current_blinker == expected_blinker:
            verification_score += 30
            reasons.append("转向灯匹配")
        elif current_blinker != 'none':
            # 转向灯方向错误，严重扣分
            verification_score -= 20
            reasons.append(f"转向灯方向错误: {current_blinker} vs {expected_blinker}")
        else:
            # 没有转向灯，中等扣分
            verification_score += 10
            reasons.append("无转向灯信号")

        # 🎯 验证2：转向灯时间逻辑 (权重: 20%)
        blinker_start_time = self.blinker_lane_change_tracker.get('blinker_start_time', 0)
        if (self.blinker_lane_change_tracker['pending_change'] and 
            current_time - blinker_start_time < 5000):  # 5秒内
            expected_direction = self.blinker_lane_change_tracker['expected_direction']
            if expected_direction == expected_blinker:
                verification_score += 20
                reasons.append("转向灯预测匹配")

        # 🎯 验证3：方向盘角度 (权重: 15%)
        steering_angle = abs(vehicle_data.get('steering_angle', 0))
        if 5 <= steering_angle <= 30:  # 合理的变道方向盘角度
            verification_score += 15
            reasons.append("方向盘角度合理")
        elif steering_angle > 45:
            verification_score -= 10
            reasons.append("方向盘角度过大")

        # 🎯 验证4：横向加速度 (权重: 15%)
        lat_accel = abs(vehicle_data.get('lat_a', 0))
        if 0.1 <= lat_accel <= 0.8:  # 合理的变道横向加速度
            verification_score += 15
            reasons.append("横向加速度合理")
        elif lat_accel > 1.0:
            verification_score -= 10
            reasons.append("横向加速度过大")

        # 🎯 验证5：系统置信度历史 (权重: 10%)
        confidence_bonus = min(10, self.lane_change_verification['confidence_score'] / 10)
        verification_score += confidence_bonus
        reasons.append(f"系统置信度+{confidence_bonus}")

        # 🎯 验证6：变道频率检查 (权重: 10%)
        recent_events = list(self.lane_change_verification['verification_events'])
        if recent_events:
            last_event_time = recent_events[-1]['time']
            time_since_last = current_time - last_event_time
            if time_since_last > 3000:  # 至少3秒间隔
                verification_score += 10
                reasons.append("变道间隔合理")
            else:
                verification_score -= 15
                reasons.append("变道间隔过短")
        else:
            verification_score += 10
            reasons.append("首次变道")

        # 最终判断
        verification_ratio = verification_score / max_score
        is_verified = verification_ratio >= 0.6  # 需要60%的验证分数

        reasons.append(f"总评分: {verification_score}/{max_score} ({verification_ratio*100:.1f}%)")

        return is_verified, verification_score, reasons

    def verify_blinker_based_lane_change(self, vehicle_data, config):
        """基于转向灯的变道预测验证"""
        current_blinker = vehicle_data.get('blinker', 'none')
        last_blinker = self.lane_change_verification['last_blinker_state']
        current_time = time.time() * 1000

        # 转向灯状态变化检测
        if current_blinker != last_blinker and current_blinker != 'none':
            # 新的转向灯开启
            self.blinker_lane_change_tracker = {
                'pending_change': True,
                'blinker_start_time': current_time,
                'expected_direction': current_blinker,
                'lane_before_blinker': config['current_lane_number']
            }

        elif (current_blinker == 'none' and last_blinker != 'none' and
              self.blinker_lane_change_tracker['pending_change']):
            # 转向灯关闭，结束预测
            self.blinker_lane_change_tracker['pending_change'] = False

        # 更新最后转向灯状态
        self.lane_change_verification['last_blinker_state'] = current_blinker

    def update_lane_based_net_changes(self, current_lane, last_lane, vehicle_data, config, control_state):
        """基于多源验证的净变道数计算"""
        current_lane = config['current_lane_number']
        last_lane = self.lane_change_verification['last_confirmed_lane']

        # 初始化确认的车道
        if last_lane == 0:
            self.lane_change_verification['last_confirmed_lane'] = current_lane
            control_state['last_lane_number'] = current_lane
            return

        # 🎯 多源验证1：车道序号变化验证
        lane_change = current_lane - last_lane

        # 只有±1的变化才认为是可能的变道
        if abs(lane_change) == 1:
            verification_passed, verification_score, reasons = self.verify_lane_change_multisource(
                last_lane, current_lane, lane_change, vehicle_data
            )

            if verification_passed:
                # 🎯 真实变道发生，更新净变道数
                direction = "LEFT" if lane_change == -1 else "RIGHT"

                # 基于原车道记忆计算
                if control_state['original_lane_number'] > 0:
                    target_lane = control_state['original_lane_number']
                    current_net = target_lane - current_lane
                    control_state['net_lane_changes'] = current_net

                else:
                    # 传统方法
                    if direction == "LEFT":
                        control_state['net_lane_changes'] += 1
                    else:
                        control_state['net_lane_changes'] -= 1

                # 更新确认的车道
                self.lane_change_verification['last_confirmed_lane'] = current_lane
                self.lane_change_verification['confidence_score'] = min(100, 
                    self.lane_change_verification['confidence_score'] + 5)

                # 记录验证事件
                verification_event = {
                    'time': time.time() * 1000,
                    'from_lane': last_lane,
                    'to_lane': current_lane,
                    'direction': direction,
                    'score': verification_score,
                    'reasons': reasons
                }
                self.lane_change_verification['verification_events'].append(verification_event)

                # 重置目标车辆跟踪
                if control_state['target_vehicle_tracker'] is not None:

                    control_state['target_vehicle_tracker'] = None

            else:
                # 验证失败，可能是误报
                self.lane_change_verification['confidence_score'] = max(0,
                    self.lane_change_verification['confidence_score'] - 10)

                # 不更新确认车道，保持原车道
                config['current_lane_number'] = last_lane  # 回滚车道变化

        elif abs(lane_change) > 1:
            # 异常变化，一定是误报

            config['current_lane_number'] = last_lane
            self.lane_change_verification['confidence_score'] = max(0,
                self.lane_change_verification['confidence_score'] - 20)

        # 更新上次车道编号（用于下次比较）
        control_state['last_lane_number'] = current_lane

        # 🎯 多源验证2：转向灯变道预测
        self.verify_blinker_based_lane_change(vehicle_data, config)

    def reset_verification_system(self):
        """重置验证系统"""
        self.lane_change_verification['last_confirmed_lane'] = 0
        self.lane_change_verification['verification_events'].clear()
        self.lane_change_verification['confidence_score'] = 100
        self.blinker_lane_change_tracker = {
            'pending_change': False,
            'blinker_start_time': 0,
            'expected_direction': None,
            'lane_before_blinker': 0
        }
        self.lane_number_history.clear()