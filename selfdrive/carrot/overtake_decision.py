#!/usr/bin/env python3
"""
超车决策模块 - 优化版
负责超车条件判断和决策执行
"""

import time
from collections import deque

# 导入配置模块
try:
    from selfdrive.carrot.auto_overtake.config import Config
except ImportError:
    from config import Config

class OvertakeDecisionEngine:
    """超车决策引擎"""
    
    def __init__(self, config):
        self.config = config

    def check_op_control_cooldown(self, control_state):
        """检查OP控制后的冷却时间"""
        current_time = time.time() * 1000

        if control_state['op_control_cooldown'] > 0:
            elapsed = current_time - control_state['last_op_control_end_time']
            if elapsed < control_state['op_control_cooldown']:
                remaining = (control_state['op_control_cooldown'] - elapsed) / 1000
                control_state['overtakeReason'] = f"OP控制后冷却中，请等待{remaining:.1f}秒"
                return True
            else:
                control_state['op_control_cooldown'] = 0

        return False

    def update_following_status(self, vehicle_data, control_state):
        """更新跟车状态"""
        now = time.time() * 1000

        time_gap = self.calculate_time_gap(vehicle_data)
        speed_ratio = vehicle_data['v_ego_kph'] / vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else 1.0

        is_following = (
            vehicle_data['lead_distance'] > 0 and (
                vehicle_data['lead_relative_speed'] < self.config['LEAD_RELATIVE_SPEED_THRESHOLD'] or
                (0 < time_gap <= self.config['FOLLOW_TIME_GAP_THRESHOLD']) or
                speed_ratio < self.config['CRUISE_SPEED_RATIO_THRESHOLD']
            )
        )

        if is_following:
            if control_state['follow_start_time'] is None:
                control_state['follow_start_time'] = now
                control_state['is_following_slow_vehicle'] = True
            follow_duration = now - control_state['follow_start_time']
            if follow_duration >= self.config['MAX_FOLLOW_TIME'] and not control_state['max_follow_time_reached']:
                control_state['max_follow_time_reached'] = True
                minutes = self.config['MAX_FOLLOW_TIME'] // 60000
                control_state['overtakeReason'] = f"跟车时间超过{minutes}分钟，强制超车"
        else:
            if control_state['follow_start_time'] is not None:
                pass
            control_state['follow_start_time'] = None
            control_state['is_following_slow_vehicle'] = False
            control_state['max_follow_time_reached'] = False

    def check_condition_stability(self, current_conditions, control_state):
        """
        检查条件稳定性 - 避免数据波动导致的误触发
        """
        current_time = time.time() * 1000
        
        # 如果没有条件满足，重置稳定性检查
        if not current_conditions:
            control_state['condition_stability_timer'] = 0
            control_state['condition_met_count'] = 0
            control_state['stable_condition_flags'] = {}
            control_state['quick_trigger_enabled'] = False
            return False
        
        # 检查条件变化
        condition_changed = False
        current_flags = {cond: True for cond in current_conditions}
        
        if control_state['stable_condition_flags'] != current_flags:
            condition_changed = True
            control_state['stable_condition_flags'] = current_flags
        
        # 如果条件变化，重置计时器但增加计数
        if condition_changed:
            control_state['condition_stability_timer'] = current_time
            control_state['condition_met_count'] += 1
        else:
            # 条件稳定，检查持续时间
            if control_state['condition_stability_timer'] == 0:
                control_state['condition_stability_timer'] = current_time
            
            stable_duration = current_time - control_state['condition_stability_timer']
            
            # 检查是否达到稳定要求
            if (stable_duration >= control_state['condition_stable_duration'] or 
                control_state['condition_met_count'] >= control_state['condition_met_threshold']):
                
                # 启用快速触发（在稳定后的短时间内可以快速响应）
                control_state['quick_trigger_enabled'] = True
                control_state['quick_trigger_start'] = current_time
                return True
        
        control_state['last_condition_check_time'] = current_time
        return False

    def check_lead_vehicle_min_speed(self, vehicle_data, control_state):
        """
        检查前车最低速度限制
        高速：前车速度 ≥ 35km/h
        普通道路：前车速度 ≥ 20km/h
        """
        # 如果没有前车，不限制
        if vehicle_data['lead_distance'] <= 0:
            return True
        
        lead_speed = vehicle_data['lead_speed']
        
        if self.config['road_type'] == 'highway':
            min_speed = self.config['HIGHWAY_LEAD_MIN_SPEED']
            if lead_speed < min_speed:
                control_state['overtakeReason'] = f"高速公路前车速度{lead_speed}km/h低于{min_speed}km/h，可能为堵车"
                control_state['last_overtake_result'] = 'condition'
                return False
        else:
            min_speed = self.config['NORMAL_LEAD_MIN_SPEED']
            if lead_speed < min_speed:
                control_state['overtakeReason'] = f"普通道路前车速度{lead_speed}km/h低于{min_speed}km/h，可能为堵车"
                control_state['last_overtake_result'] = 'condition'
                return False
        
        return True

    def check_early_overtake_conditions(self, vehicle_data, control_state):
        """
        检查远距离超车触发条件
        条件1：前车速度比自己慢40%或以上
        条件2：前车速度在50公里以上（避免堵车情况）
        """
        # 只在高速公路上启用远距离超车
        if self.config['road_type'] != 'highway':
            return False
        
        # 检查必要条件
        if (vehicle_data['lead_distance'] <= 0 or vehicle_data['v_ego_kph'] <= 0 or 
            vehicle_data['lead_speed'] <= 0 or vehicle_data['v_cruise_kph'] <= 0):
            return False
        
        # 🆕 远距离超车也需要遵守前车最低速度限制
        if not self.check_lead_vehicle_min_speed(vehicle_data, control_state):
            return False
        
        current_speed = vehicle_data['v_ego_kph']
        lead_speed = vehicle_data['lead_speed']
        speed_difference = current_speed - lead_speed
        
        # 🎯 条件1：前车速度比自己慢40%或以上
        speed_ratio = lead_speed / current_speed if current_speed > 0 else 1
        is_slow_vehicle = speed_ratio <= self.config['EARLY_OVERTAKE_SPEED_RATIO']  # 前车速度 ≤ 60% 本车速度
        
        # 🎯 条件2：前车速度在50公里以上（避免堵车）
        is_not_traffic_jam = lead_speed >= self.config['EARLY_OVERTAKE_MIN_LEAD_SPEED']
        
        # 🎯 条件3：相对速度足够大
        is_significant_slowdown = speed_difference >= self.config['EARLY_OVERTAKE_MIN_SPEED_DIFF']  # 至少慢20km/h
        
        # 🎯 条件4：距离适中（不太近也不太远）
        lead_distance = vehicle_data['lead_distance']
        is_proper_distance = (self.config['EARLY_OVERTAKE_MIN_DISTANCE'] <= lead_distance <= 
                             self.config['EARLY_OVERTAKE_MAX_DISTANCE'])  # 30-100米范围内
        
        # 所有条件满足
        if (is_slow_vehicle and is_not_traffic_jam and 
            is_significant_slowdown and is_proper_distance):
            
            return True
        
        return False

    def get_trigger_conditions(self, vehicle_data, control_state):
        """获取当前触发超车的条件状态"""
        conditions = []

        # 🆕 远距离超车条件（最高优先级）
        if self.check_early_overtake_conditions(vehicle_data, control_state):
            conditions.append("🚀 远距离超车触发（前车过慢）")
            return conditions

        if control_state['max_follow_time_reached']:
            conditions.append("⏰ 最大跟车时间触发")
            return conditions

        speed_ratio = vehicle_data['v_ego_kph'] / vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else 1.0

        if vehicle_data['lead_relative_speed'] < self.config['LEAD_RELATIVE_SPEED_THRESHOLD']:
            conditions.append(f"🚗 前车较慢: {vehicle_data['lead_relative_speed']}km/h")
            return conditions

        time_gap = self.calculate_time_gap(vehicle_data)
        if 0 < time_gap <= self.config['FOLLOW_TIME_GAP_THRESHOLD']:
            conditions.append(f"⏱️ 跟车时间: {time_gap:.1f}秒")
            return conditions

        if speed_ratio < self.config['CRUISE_SPEED_RATIO_THRESHOLD']:
            conditions.append(f"🚀 速度比例: {speed_ratio*100:.0f}%")
            return conditions

        return conditions

    def calculate_time_gap(self, vehicle_data):
        """
        计算跟车时间距离（秒）
        """
        if vehicle_data['lead_distance'] <= 0 or vehicle_data['v_ego_kph'] <= 0:
            return 0

        v_ego_ms = vehicle_data['v_ego_kph'] / 3.6
        time_gap = vehicle_data['lead_distance'] / v_ego_ms if v_ego_ms > 0 else 0
        return time_gap

    def check_overtake_conditions(self, vehicle_data, control_state):
        """检查超车条件 - 增加远距离超车触发和前车最低速度限制"""
        now = time.time() * 1000

        if vehicle_data['system_auto_control'] == 1:
            control_state['overtakeReason'] = "OP自动控制中，暂停超车"
            control_state['last_overtake_result'] = 'condition'
            return False

        if self.check_op_control_cooldown(control_state):
            control_state['last_overtake_result'] = 'condition'
            return False

        if not vehicle_data['IsOnroad']:
            control_state['overtakeReason'] = "车辆不在道路上"
            control_state['last_overtake_result'] = 'condition'
            return False

        if not vehicle_data['engaged']:
            control_state['overtakeReason'] = "巡航未激活"
            control_state['last_overtake_result'] = 'condition'
            return False

        # 🆕 远距离超车触发条件检查（优先于其他条件）
        if self.check_early_overtake_conditions(vehicle_data, control_state):
            control_state['overtakeReason'] = "前车速度过慢，触发远距离超车"
            # 重置稳定性检查，因为这是强制触发
            control_state['condition_stability_timer'] = 0
            control_state['condition_met_count'] = 0
            control_state['quick_trigger_enabled'] = False
            return True

        # 🆕 前车最低速度限制检查
        if not self.check_lead_vehicle_min_speed(vehicle_data, control_state):
            return False

        if vehicle_data['lead_distance'] <= 0:
            control_state['overtakeReason'] = "前方无车辆"
            control_state['last_overtake_result'] = 'condition'
            control_state['condition_stability_timer'] = 0
            control_state['condition_met_count'] = 0
            return False

        # 🎯 关键修改：新增速度限制条件 - 达到巡航速度95%不触发超车
        speed_ratio = vehicle_data['v_ego_kph'] / vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else 1.0
        if speed_ratio >= 0.95:
            control_state['overtakeReason'] = f"当前速度{vehicle_data['v_ego_kph']}km/h已达到巡航速度{vehicle_data['v_cruise_kph']}km/h的{speed_ratio*100:.0f}%，无需超车"
            control_state['last_overtake_result'] = 'condition'
            # 重置稳定性检查，因为速度已经足够
            control_state['condition_stability_timer'] = 0
            control_state['condition_met_count'] = 0
            return False

        # 检查车速条件
        if self.config['road_type'] == 'highway' and vehicle_data['v_ego_kph'] < self.config['HIGHWAY_MIN_SPEED']:
            control_state['overtakeReason'] = f"高速公路车速{vehicle_data['v_ego_kph']}km/h低于最低超车速度"
            control_state['last_overtake_result'] = 'condition'
            return False

        if self.config['road_type'] == 'normal' and vehicle_data['v_ego_kph'] < self.config['NORMAL_ROAD_MIN_SPEED']:
            control_state['overtakeReason'] = f"普通公路车速{vehicle_data['v_ego_kph']}km/h低于最低超车速度"
            control_state['last_overtake_result'] = 'condition'
            return False

        # 🎯 关键修改：检查冷却时间（考虑快速触发）
        current_cooldown = self.calculate_dynamic_cooldown(control_state)
        if now - control_state['lastOvertakeTime'] < current_cooldown and not control_state['quick_trigger_enabled']:
            remaining = (current_cooldown - (now - control_state['lastOvertakeTime'])) / 1000
            reason_suffix = ""
            if control_state['last_overtake_result'] == 'success':
                reason_suffix = "（成功超车后冷却）"
            elif control_state['last_overtake_result'] == 'failed':
                reason_suffix = "（超车失败后快速重试）"
            elif control_state['last_overtake_result'] == 'condition':
                reason_suffix = "（条件不满足冷却）"

            control_state['overtakeReason'] = f"超车冷却中，请等待{remaining:.1f}秒{reason_suffix}"
            return False

        # 🆕 获取当前触发条件
        current_conditions = self.get_trigger_conditions(vehicle_data, control_state)
        
        # 🎯 关键修改：稳定性检查
        conditions_stable = self.check_condition_stability(current_conditions, control_state)
        
        # 如果条件稳定或者启用快速触发，则允许超车
        if conditions_stable or control_state['quick_trigger_enabled']:
            # 检查快速触发超时（快速触发只持续短时间）
            if control_state['quick_trigger_enabled']:
                quick_trigger_timeout = 3000  # 快速触发超时3秒
                if now - control_state.get('quick_trigger_start', now) > quick_trigger_timeout:
                    control_state['quick_trigger_enabled'] = False
                else:
                    pass
            
            if current_conditions:
                trigger_reason = ", ".join(current_conditions)
                control_state['overtakeReason'] = f"触发超车: {trigger_reason} | 条件稳定"
                return True
        else:
            # 条件不稳定，显示等待信息
            if current_conditions:
                stable_duration = now - control_state['condition_stability_timer'] if control_state['condition_stability_timer'] > 0 else 0
                remaining_time = max(0, control_state['condition_stable_duration'] - stable_duration) / 1000
                condition_count = control_state['condition_met_count']
                
                if remaining_time > 0:
                    control_state['overtakeReason'] = f"条件满足，等待稳定({remaining_time:.1f}s) | 计数: {condition_count}/{control_state['condition_met_threshold']}"
                else:
                    control_state['overtakeReason'] = f"条件满足，等待稳定 | 计数: {condition_count}/{control_state['condition_met_threshold']}"
            else:
                control_state['overtakeReason'] = "未满足任何超车触发条件"
            
            control_state['last_overtake_result'] = 'condition'
            return False

        control_state['overtakeReason'] = "未满足任何超车触发条件"
        control_state['last_overtake_result'] = 'condition'
        return False

    def calculate_dynamic_cooldown(self, control_state):
        """计算动态冷却时间"""
        base_cooldown = self.config['OVERTAKE_COOLDOWN_BASE']

        if control_state['last_overtake_result'] == 'success':
            cooldown = self.config['OVERTAKE_COOLDOWN_SUCCESS']
            control_state['consecutive_failures'] = 0
        elif control_state['last_overtake_result'] == 'failed':
            cooldown = self.config['OVERTAKE_COOLDOWN_FAILED']
            control_state['consecutive_failures'] += 1
        elif control_state['last_overtake_result'] == 'condition':
            cooldown = self.config['OVERTAKE_COOLDOWN_CONDITION']
            control_state['consecutive_failures'] += 1
        else:
            cooldown = base_cooldown

        if control_state['consecutive_failures'] > 3:
            penalty = min(10000, control_state['consecutive_failures'] * 2000)
            cooldown += penalty

        if self.config['road_type'] == 'highway':
            cooldown = max(5000, cooldown * 0.8)
        else:
            cooldown = cooldown * 1.2

        control_state['dynamic_cooldown'] = cooldown
        return cooldown

    def evaluate_overtake_effectiveness(self, vehicle_data, direction):
        """评估超车有效性 - 增强数据可靠性检查"""
        if direction == "LEFT":
            side_lead_speed = vehicle_data['left_lead_speed']
            side_lead_distance = vehicle_data['left_lead_distance']
            side_relative_speed = vehicle_data['left_lead_relative_speed']
            # 新增：数据可靠性检查
            left_reliable_no_vehicle = vehicle_data.get('left_reliable_no_vehicle', False)
            side_track_quality = vehicle_data.get('left_track_quality', 0)
        else:
            side_lead_speed = vehicle_data['right_lead_speed']
            side_lead_distance = vehicle_data['right_lead_distance']
            side_relative_speed = vehicle_data['right_lead_relative_speed']
            right_reliable_no_vehicle = vehicle_data.get('right_reliable_no_vehicle', False)
            side_track_quality = vehicle_data.get('right_track_quality', 0)

        current_speed = vehicle_data['v_ego_kph']
        current_lead_speed = vehicle_data['lead_speed']
        current_lead_distance = vehicle_data['lead_distance']

        effectiveness = 100
        reasons = []

        # 🎯 关键修复：区分"真正无车"和"可能数据丢失"
        if side_lead_distance <= 0:
            if (direction == "LEFT" and left_reliable_no_vehicle) or \
               (direction == "RIGHT" and right_reliable_no_vehicle):
                # 可靠的无车状态
                effectiveness = 90  # 稍降低分数，保持谨慎
                reasons.append("✅ 目标车道确认畅通无车")
            else:
                # 可能的数据丢失，保守处理
                effectiveness = 70  # 中等分数
                reasons.append("⚠️ 目标车道可能无车，数据可靠性待确认")
                
            expected_target_speed = vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else current_speed + 15
        else:
            # 原有有车逻辑保持不变，但增加数据质量检查
            if side_track_quality < 50:  # 跟踪质量低
                effectiveness -= 20
                reasons.append("⚠️ 侧车道数据跟踪质量较低")
            
            # 情况1：目标车道有前车，且速度比当前前车更慢 - 严重惩罚
            if side_lead_speed > 0 and side_lead_speed < current_lead_speed - 2:
                effectiveness -= 50
                reasons.append(f"❌ 目标车道前车{side_lead_speed}km/h比当前前车{current_lead_speed}km/h更慢")
            
            # 情况2：目标车道前车比本车慢很多 - 禁止变道
            if side_lead_speed > 0 and side_lead_speed < current_speed - 8:
                effectiveness -= 60
                reasons.append(f"❌ 目标车道前车{side_lead_speed}km/h比本车{current_speed}km/h慢太多")
            
            # 情况3：目标车道前车距离很近且相对速度为负（比我们慢）
            if (side_lead_distance > 0 and side_lead_distance < 25 and 
                side_relative_speed < -10):
                effectiveness -= 40
                reasons.append(f"⚠️ 目标车道前车较近{side_lead_distance}m且更慢{side_relative_speed}km/h")
            
            # 情况4：目标车道前车距离适中但明显比我们慢
            if (side_lead_distance > 0 and side_lead_distance < 40 and
                side_relative_speed < -15):
                effectiveness -= 35
                reasons.append(f"⚠️ 目标车道前车{side_lead_distance}m明显更慢{side_relative_speed}km/h")

            # 计算目标车道的预期速度
            expected_target_speed = side_lead_speed if side_lead_speed > 0 else current_speed + 10
            if side_relative_speed < 0:  # 目标车道前车比我们慢
                expected_target_speed = min(expected_target_speed, current_speed + side_relative_speed)

        # 当前车道的预期速度（考虑前车限制）
        expected_current_speed = current_lead_speed if current_lead_speed > 0 else current_speed
        
        # 优化：根据是否有前车调整最小优势要求
        if side_lead_distance <= 0 and ((direction == "LEFT" and left_reliable_no_vehicle) or (direction == "RIGHT" and right_reliable_no_vehicle)):
            min_advantage = 0  # 无车时不需要速度优势
        else:
            min_advantage = 5  # 有车时需要5km/h的速度优势
        
        if expected_target_speed - expected_current_speed < min_advantage:
            effectiveness -= max(0, (min_advantage - (expected_target_speed - expected_current_speed)) * 8)
            reasons.append(f"⚠️ 速度优势不足: 目标{expected_target_speed} vs 当前{expected_current_speed}")
        else:
            reasons.append(f"✅ 速度优势充足: +{expected_target_speed - expected_current_speed:.1f}km/h")

        # 道路类型特殊考虑
        if direction == "RIGHT" and self.config['road_type'] == 'highway':
            # 高速右侧车道通常较慢，需要更强的速度优势
            effectiveness -= 8
            reasons.append("🛣️ 右侧车道通常较慢")

        effectiveness = max(0, effectiveness)  # 确保不低于0
        
        return effectiveness, reasons

    def is_overtake_effective(self, vehicle_data, direction):
        """判断超车是否有效"""
        effectiveness, reasons = self.evaluate_overtake_effectiveness(vehicle_data, direction)
        
        #  动态调整最小有效性阈值
        min_effectiveness = 65  # 普通公路为65分
        
        # 根据道路类型调整阈值
        if self.config['road_type'] == 'highway':
            min_effectiveness = 70  # 高速公路要求更高
        
        # 如果目标车道有明显慢车，大幅提高阈值
        if direction == "LEFT" and vehicle_data['left_lead_relative_speed'] < -10:
            min_effectiveness = 75
        elif direction == "RIGHT" and vehicle_data['right_lead_relative_speed'] < -10:
            min_effectiveness = 75
        
        is_effective = effectiveness >= min_effectiveness
        
        # 添加有效性分数信息
        reasons.append(f"有效性评分: {effectiveness:.1f}/100 (阈值: {min_effectiveness})")
        
        return is_effective, effectiveness, reasons

    def check_lane_safety(self, vehicle_data, side):
        """检查车道安全性 - 修复版本"""
        if side == "left":
            # 检查盲区
            if vehicle_data.get('left_blindspot', False) or vehicle_data.get('l_front_blind', False):
                return False, "盲区有车⚠️禁止变道"
            # 检查车道宽度
            if vehicle_data.get('l_lane_width', 3.2) < self.config['MIN_LANE_WIDTH']:
                return False, "车道过窄⚠️禁止变道"
            # 检查距离
            left_distance = vehicle_data.get('left_lead_distance', 0)
            if left_distance > 0 and left_distance < 20.0:
                return False, f"侧车过近⚠️{left_distance:.0f}m"
            # 检查速度差异（只检查负值 - 慢车）
            left_relative_speed = vehicle_data.get('left_lead_relative_speed', 0)
            if left_relative_speed < -20.0:
                return False, f"侧车过慢⚠️{left_relative_speed:.0f}km/h"
            return True, "安全"

        elif side == "right":
            # 检查盲区
            if vehicle_data.get('right_blindspot', False) or vehicle_data.get('r_front_blind', False):
                return False, "盲区有车⚠️禁止变道"
            # 检查车道宽度
            if vehicle_data.get('r_lane_width', 3.2) < self.config['MIN_LANE_WIDTH']:
                return False, "车道过窄⚠️禁止变道"
            # 检查距离
            right_distance = vehicle_data.get('right_lead_distance', 0)
            if right_distance > 0 and right_distance < 20.0:
                return False, f"侧车过近⚠️{right_distance:.0f}m"
            # 检查速度差异（只检查负值 - 慢车）
            right_relative_speed = vehicle_data.get('right_lead_relative_speed', 0)
            if right_relative_speed < -20.0:
                return False, f"侧车过慢⚠️{right_relative_speed:.0f}km/h"
            return True, "安全"

        return False, "未知方向"
    def evaluate_lane_suitability(self, vehicle_data, side):
        """评估车道适合度 - 优化版：改进无车情况评分"""
        current_lane = self.config['current_lane_number']
        total_lanes = self.config['lane_count']

        if side == "left":
            target_lane = current_lane - 1
        else:
            target_lane = current_lane + 1

        if self.is_emergency_lane(target_lane, vehicle_data):
            return 0, ["🚫 应急车道，禁止行驶"]

        penalty_score = 0
        analysis = []
        weights = self.config['PENALTY_WEIGHTS']

        if side == "left":
            if vehicle_data['left_blindspot'] or vehicle_data['l_front_blind']:
                penalty_score += 100
                analysis.append("❌ 盲区有车")
                return penalty_score, analysis

            lane_width = vehicle_data['l_lane_width']
            if lane_width < self.config['MIN_LANE_WIDTH']:
                penalty_score += 80
                analysis.append(f"❌ 车道过窄: {lane_width}m")
            elif lane_width < self.config['SAFE_LANE_WIDTH']:
                penalty_score += (self.config['SAFE_LANE_WIDTH'] - lane_width) * weights['lane_width'] * 10
                analysis.append(f"⚠️ 车道略窄: {lane_width}m")
            else:
                analysis.append(f"✅ 车道宽度正常: {lane_width}m")

            if self.config['road_type'] == 'highway' and target_lane == 1:
                analysis.append("🚀 快车道 - 超车优先")
                penalty_score -= 15

            side_distance = vehicle_data['left_lead_distance']
            # 优化：区分可靠无车和可能数据丢失
            if side_distance <= 0:
                if vehicle_data.get('left_reliable_no_vehicle', False):
                    # 可靠的无车状态
                    penalty_score -= 20
                    analysis.append("✅ 侧方确认无车辆")
                else:
                    # 可能的数据丢失
                    penalty_score -= 5
                    analysis.append("⚠️ 侧方可能无车，数据待确认")
            else:
                if side_distance < self.config['SIDE_LEAD_DISTANCE_MIN']:
                    penalty_score += (self.config['SIDE_LEAD_DISTANCE_MIN'] - side_distance) * weights['side_lead_distance']
                    analysis.append(f"⚠️ 侧前车过近: {side_distance}m")
                else:
                    distance_advantage = side_distance - self.config['SIDE_LEAD_DISTANCE_MIN']
                    penalty_score -= min(distance_advantage * 0.5, 20)
                    analysis.append(f"✅ 侧前车安全距离: {side_distance}m")

            side_relative_speed = vehicle_data['left_lead_relative_speed']
            # 优化：无车时不需要考虑相对速度
            if side_distance > 0 and side_relative_speed != 0:
                if side_relative_speed < -weights['min_speed_advantage']:
                    penalty_score += abs(side_relative_speed) * weights['side_relative_speed']
                    analysis.append(f"❌ 侧前车较慢: {side_relative_speed}km/h")
                elif side_relative_speed > weights['min_speed_advantage']:
                    speed_advantage = min(side_relative_speed * 0.8, 25)
                    penalty_score -= speed_advantage
                    analysis.append(f"✅ 侧前车较快: +{side_relative_speed}km/h")
                else:
                    analysis.append(f"➖ 侧前车速度相当: {side_relative_speed}km/h")

        elif side == "right":
            if vehicle_data['right_blindspot'] or vehicle_data['r_front_blind']:
                penalty_score += 100
                analysis.append("❌ 盲区有车")
                return penalty_score, analysis

            lane_width = vehicle_data['r_lane_width']
            if lane_width < self.config['MIN_LANE_WIDTH']:
                penalty_score += 80
                analysis.append(f"❌ 车道过窄: {lane_width}m")
            elif lane_width < self.config['SAFE_LANE_WIDTH']:
                penalty_score += (self.config['SAFE_LANE_WIDTH'] - lane_width) * weights['lane_width'] * 10
                analysis.append(f"⚠️ 车道略窄: {lane_width}m")
            else:
                analysis.append(f"✅ 车道宽度正常: {lane_width}m")

            if self.is_emergency_lane(target_lane, vehicle_data):
                return 0, ["🚫 应急车道，禁止行驶"]

            if self.config['road_type'] == 'highway' and target_lane == total_lanes:
                analysis.append("⚠️ 右侧车道通常较慢")
                penalty_score += 10

            side_distance = vehicle_data['right_lead_distance']
            # 优化：区分可靠无车和可能数据丢失
            if side_distance <= 0:
                if vehicle_data.get('right_reliable_no_vehicle', False):
                    # 可靠的无车状态
                    penalty_score -= 20
                    analysis.append("✅ 侧方确认无车辆")
                else:
                    # 可能的数据丢失
                    penalty_score -= 5
                    analysis.append("⚠️ 侧方可能无车，数据待确认")
            else:
                if side_distance < self.config['SIDE_LEAD_DISTANCE_MIN']:
                    penalty_score += (self.config['SIDE_LEAD_DISTANCE_MIN'] - side_distance) * weights['side_lead_distance']
                    analysis.append(f"⚠️ 侧前车过近: {side_distance}m")
                else:
                    distance_advantage = side_distance - self.config['SIDE_LEAD_DISTANCE_MIN']
                    penalty_score -= min(distance_advantage * 0.5, 20)
                    analysis.append(f"✅ 侧前车安全距离: {side_distance}m")

            side_relative_speed = vehicle_data['right_lead_relative_speed']
            #优化：无车时不需要考虑相对速度
            if side_distance > 0 and side_relative_speed != 0:
                if side_relative_speed < -weights['min_speed_advantage']:
                    penalty_score += abs(side_relative_speed) * weights['side_relative_speed']
                    analysis.append(f"❌ 侧前车较慢: {side_relative_speed}km/h")
                elif side_relative_speed > weights['min_speed_advantage']:
                    speed_advantage = min(side_relative_speed * 0.8, 25)
                    penalty_score -= speed_advantage
                    analysis.append(f"✅ 侧前车较快: +{side_relative_speed}km/h")
                else:
                    analysis.append(f"➖ 侧前车速度相当: {side_relative_speed}km/h")

        penalty_score = max(0, penalty_score)
        suitability_score = max(0, 100 - penalty_score)
        analysis.insert(0, f"适合度评分: {suitability_score:.1f}/100")
        return suitability_score, analysis

    def get_current_lane_penalty(self, vehicle_data):
        """计算当前车道的惩罚分数"""
        penalty = 0
        analysis = []

        if vehicle_data['lead_relative_speed'] < -self.config['MIN_SPEED_ADVANTAGE']:
            speed_penalty = abs(vehicle_data['lead_relative_speed']) * self.config['PENALTY_WEIGHTS']['lead_relative_speed']
            penalty += speed_penalty
            analysis.append(f"当前前车较慢: {vehicle_data['lead_relative_speed']}km/h → +{speed_penalty:.1f}惩罚")

        time_gap = self.calculate_time_gap(vehicle_data)
        if time_gap > 0 and time_gap < self.config['FOLLOW_TIME_GAP_THRESHOLD']:
            distance_penalty = (self.config['FOLLOW_TIME_GAP_THRESHOLD'] - time_gap) * 10
            penalty += distance_penalty
            analysis.append(f"跟车时间较近: {time_gap:.1f}秒 → +{distance_penalty:.1f}惩罚")

        return penalty, analysis

    def get_available_overtake_directions(self, vehicle_data):
        """获取可用的超车方向 - 修复版：整合安全检测"""
        current_lane = self.config['current_lane_number']
        total_lanes = self.config['lane_count']

        available_directions = []

        if self.config['road_type'] == 'highway':

            if current_lane == 1:
                # 最左侧车道：只能向右
                if current_lane < total_lanes - 1:
                    available_directions.append("RIGHT")
                else:
                    pass

            elif current_lane == total_lanes:
                # 最右侧车道：只能向左
                pass

            else:
                # 中间车道：可以向左或向右
                if current_lane > 1:
                    available_directions.append("LEFT")

                if current_lane < total_lanes - 1:
                    available_directions.append("RIGHT")
                elif current_lane == total_lanes - 1:
                    pass

        else:
            # 普通道路
            if current_lane > 1:
                available_directions.append("LEFT")
            if current_lane < total_lanes and not self.is_emergency_lane(current_lane + 1, vehicle_data):
                available_directions.append("RIGHT")

        # 关键修复：安全检测过滤
        safe_directions = []
        for direction in available_directions:
            side = "left" if direction == "LEFT" else "right"
            is_safe, reason = self.check_lane_safety(vehicle_data, side)
            if is_safe:
                safe_directions.append(direction)

        return safe_directions
    def is_emergency_lane(self, lane_number, vehicle_data):
        """判断是否为应急车道"""
        if self.config['road_type'] == 'highway' and lane_number == self.config['lane_count']:
            return True

        if lane_number == self.config['lane_count']:
            right_lane_width = vehicle_data.get('r_lane_width', 3.2)
            if right_lane_width < 2.8:
                return True

        return False