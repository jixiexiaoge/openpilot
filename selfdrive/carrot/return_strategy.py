#!/usr/bin/env python3
"""
返回策略模块
负责智能返回原车道的决策和执行
"""

import time

# 导入配置模块
try:
    from selfdrive.carrot.auto_overtake.config import Config
except ImportError:
    from config import Config

class ReturnStrategy:
    """智能返回策略"""
    
    def __init__(self, config):
        self.config = config

    def start_lane_memory(self, control_state, current_lane):
        """开始记录原车道"""
        if control_state['original_lane_number'] == 0:
            control_state['original_lane_number'] = current_lane
            control_state['target_return_lane'] = current_lane
            control_state['lane_memory_start_time'] = time.time() * 1000
            control_state['return_timeout_timer'] = time.time() * 1000

    def check_lane_memory_timeout(self, control_state):
        """检查原车道记忆超时（30秒）"""
        current_time = time.time() * 1000
        
        if (control_state['original_lane_number'] > 0 and 
            current_time - control_state['return_timeout_timer'] > control_state['max_lane_memory_time']):
            return True
        return False

    def update_target_vehicle_tracking(self, vehicle_data, control_state):
        """更新目标车辆跟踪 - 基于前雷达数据"""
        # 如果没有正在跟踪的目标车辆，尝试识别
        if control_state['target_vehicle_tracker'] is None and control_state['net_lane_changes'] != 0:
            # 根据净变道方向确定要跟踪的目标车辆在哪一侧
            if control_state['net_lane_changes'] > 0:  # 当前在左侧，需要返回右侧
                target_side = 'right'
                target_distance = vehicle_data['right_lead_distance']
                target_speed = vehicle_data['right_lead_speed']
                target_relative_speed = vehicle_data['right_lead_relative_speed']
            else:  # 当前在右侧，需要返回左侧
                target_side = 'left'
                target_distance = vehicle_data['left_lead_distance']
                target_speed = vehicle_data['left_lead_speed']
                target_relative_speed = vehicle_data['left_lead_relative_speed']
            
            # 只有在目标侧有车辆时才建立跟踪
            if target_distance > 0 and target_distance < 100:  # 只跟踪100米内的车辆
                control_state['target_vehicle_tracker'] = {
                    'side': target_side,
                    'initial_distance': target_distance,
                    'initial_speed': target_speed,
                    'last_seen_distance': target_distance,
                    'last_seen_time': time.time() * 1000,
                    'tracking_start_time': time.time() * 1000,
                    'distance_increase_count': 0,  # 🆕 距离增加计数
                    'last_distance': target_distance
                }
    
        # 更新已跟踪的目标车辆
        elif control_state['target_vehicle_tracker'] is not None:
            tracker = control_state['target_vehicle_tracker']
            target_side = tracker['side']
            
            if target_side == 'right':
                current_distance = vehicle_data['right_lead_distance']
                current_speed = vehicle_data['right_lead_speed']
            else:
                current_distance = vehicle_data['left_lead_distance']
                current_speed = vehicle_data['left_lead_speed']
            
            # 🆕 更新距离变化趋势
            if current_distance > tracker['last_distance'] + 2:  # 距离增加2米以上
                tracker['distance_increase_count'] = min(5, tracker.get('distance_increase_count', 0) + 1)
            elif current_distance < tracker['last_distance'] - 2:  # 距离减少
                tracker['distance_increase_count'] = max(0, tracker.get('distance_increase_count', 0) - 1)
            
            tracker['last_distance'] = current_distance
            
            # 检查目标车辆是否还存在
            if current_distance > 0 and current_distance < 120:  # 120米内
                tracker['last_seen_distance'] = current_distance
                tracker['last_seen_time'] = time.time() * 1000
            else:
                # 目标车辆消失，可能是已超越或超出范围
                control_state['target_vehicle_tracker'] = None

    def has_completely_overtaken_target(self, vehicle_data, control_state):
        """检查是否完全超越了目标车辆 - 基于前雷达的间接判断"""
        current_speed = vehicle_data['v_ego_kph']
        
        # 🎯 关键限制：只有前雷达，无法直接检测已超车辆
        
        # 确定需要检查的目标侧
        if control_state['net_lane_changes'] > 0:  # 需要返回右侧
            target_side = 'right'
            target_distance = vehicle_data['right_lead_distance']
            target_speed = vehicle_data['right_lead_speed']
            target_relative_speed = vehicle_data['right_lead_relative_speed']
        else:  # 需要返回左侧
            target_side = 'left' 
            target_distance = vehicle_data['left_lead_distance']
            target_speed = vehicle_data['left_lead_speed']
            target_relative_speed = vehicle_data['left_lead_relative_speed']
        
        # 🆕 基于前雷达的间接超越判断
        
        # 情况1：目标侧无车（最理想情况）
        if target_distance <= 0:
            return True
        
        # 情况2：目标车辆距离足够远且相对速度有利
        if target_distance > 80:  # 距离很远，可以认为已超越
            return True
        
        # 情况3：有明显速度优势且距离适中
        speed_advantage = current_speed - target_speed
        if speed_advantage > 20 and target_distance > 40:  # 优势明显
            return True
        
        # 情况4：目标车辆明显减速（相对速度为负且较大）
        if target_relative_speed < -15 and target_distance > 30:
            return True
        
        # 🆕 情况5：基于时间的持续优势判断
        if control_state['target_vehicle_tracker']:
            tracker = control_state['target_vehicle_tracker']
            tracking_time = time.time() * 1000 - tracker['tracking_start_time']
            
            # 长时间保持速度优势（10秒以上）
            if tracking_time > 10000 and speed_advantage > 10:
                return True
            
            # 距离持续增加的趋势
            if tracker.get('distance_increase_count', 0) >= 3:  # 连续3次检测距离增加
                return True
        
        # 🆕 情况6：原车道前车状态判断
        original_lead_distance = vehicle_data['lead_distance']
        if original_lead_distance <= 0 or original_lead_distance > 60:
            # 原车道无车或车很远，可以安全返回
            return True
        
        return False

    def is_return_efficient(self, vehicle_data, return_direction):
        """检查返回是否有效率优势"""
        current_speed = vehicle_data['v_ego_kph']
        
        # 获取目标车道（返回方向）的速度预期
        if return_direction == "RIGHT":
            target_lead_speed = vehicle_data['right_lead_speed']
            target_lead_distance = vehicle_data['right_lead_distance']
            target_relative_speed = vehicle_data['right_lead_relative_speed']
        else:
            target_lead_speed = vehicle_data['left_lead_speed']
            target_lead_distance = vehicle_data['left_lead_distance']
            target_relative_speed = vehicle_data['left_lead_relative_speed']
        
        # 计算目标车道的预期速度
        if target_lead_distance <= 0:
            # 优化：目标车道无车，预期速度为巡航速度或当前速度+10
            expected_target_speed = vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else current_speed + 10
        else:
            # 目标车道有车，预期速度受前车限制
            if target_relative_speed > 5:  # 目标车道前车比我们快
                expected_target_speed = min(target_lead_speed, vehicle_data['v_cruise_kph'])
            else:  # 目标车道前车比我们慢或相当
                expected_target_speed = target_lead_speed
        
        # 计算当前车道的预期速度
        if vehicle_data['lead_distance'] <= 0:
            expected_current_speed = vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else current_speed
        else:
            if vehicle_data['lead_relative_speed'] > 5:  # 当前前车比我们快
                expected_current_speed = min(vehicle_data['lead_speed'], vehicle_data['v_cruise_kph'])
            else:  # 当前前车比我们慢
                expected_current_speed = vehicle_data['lead_speed']
        
        # 效率判断：只要不是明显更慢就可以返回
        speed_advantage = expected_target_speed - expected_current_speed
        min_advantage = -10  # 目标车道比当前慢10km/h以上，不返回
        
        is_efficient = speed_advantage >= min_advantage
        
        return is_efficient, speed_advantage

    def is_return_safe(self, vehicle_data, check_side):
        """检查返回原车道是否安全 - 只关注目标车道情况"""
        current_speed = vehicle_data['v_ego_kph']
        
        if check_side == "right":
            target_distance = vehicle_data['right_lead_distance']
            target_relative_speed = vehicle_data['right_lead_relative_speed']
            blindspot = vehicle_data['right_blindspot'] or vehicle_data['r_front_blind']
        else:
            target_distance = vehicle_data['left_lead_distance']
            target_relative_speed = vehicle_data['left_lead_relative_speed']
            blindspot = vehicle_data['left_blindspot'] or vehicle_data['l_front_blind']
        
        # 🎯 安全条件1：盲区检查
        if blindspot:
            return False, "盲区有车"
        
        # 🎯 安全条件2：目标车道车辆情况
        if target_distance <= 0:
            # 目标车道无车，安全返回
            return True, "车道畅通"
        
        # 🎯 安全条件3：目标车道有车，判断是否安全
        # 情况1：目标车道车辆比我们快+5km/h以上，安全返回
        if target_relative_speed > 5:
            safe_distance = max(30, current_speed * 0.4)
            if target_distance > safe_distance:
                return True, "前车较快且距离安全"
            else:
                return False, "前车较快但距离过近"
        
        # 情况2：目标车道车辆距离超过50米，安全返回
        elif target_distance > 50:
            return True, "前车距离安全"
        
        # 情况3：目标车道车辆比我们慢，不应该返回（继续超车）
        else:
            return False, "前车较慢，继续超车"

    def is_return_direction_available(self, current_lane, total_lanes, return_direction):
        """检查返回方向是否可用"""
        if return_direction == "RIGHT":
            return current_lane < total_lanes
        else:
            return current_lane > 1

    def check_return_stability(self, vehicle_data):
        """检查返回前的稳定性"""
        # 检查速度稳定性
        if vehicle_data['v_ego_kph'] < 60:
            return True

        # 检查方向盘角度
        if abs(vehicle_data['steering_angle']) > 10:
            return False

        # 检查横向加速度
        if abs(vehicle_data['lat_a']) > 0.5:
            return False

        return True

    def check_smart_return_conditions(self, vehicle_data, control_state, config):
        """检查智能返回条件 - 适应前雷达限制"""
        # 基础条件检查
        if not config['shouldReturnToLane'] or control_state['net_lane_changes'] == 0:
            return False
        
        if control_state['isOvertaking'] or control_state['lane_change_in_progress']:
            return False
        
        # 🎯 简化判断：适应前雷达技术限制
        
        # 条件1：基于间接指标的超越判断
        if not self.has_completely_overtaken_target(vehicle_data, control_state):
            control_state['overtakeState'] = "正在超越前车"
            control_state['overtakeReason'] = "基于前雷达数据判断尚未完全超越"
            return False
        
        # 条件2：返回方向的安全性（盲区检查）
        if control_state['net_lane_changes'] > 0:
            return_direction = "RIGHT"
            check_side = "right"
            blindspot = vehicle_data['right_blindspot'] or vehicle_data['r_front_blind']
        else:
            return_direction = "LEFT"
            check_side = "left" 
            blindspot = vehicle_data['left_blindspot'] or vehicle_data['l_front_blind']
        
        if blindspot:
            control_state['overtakeState'] = f"返回{return_direction}不安全"
            control_state['overtakeReason'] = "盲区有车"
            return False
        
        # 条件3：基本的安全距离检查
        if check_side == "right":
            target_distance = vehicle_data['right_lead_distance']
        else:
            target_distance = vehicle_data['left_lead_distance']
        
        # 🆕 简化的安全距离：只要不是非常近就认为安全
        if 0 < target_distance < 25:  # 25米内认为不安全
            control_state['overtakeState'] = "返回距离不安全"
            control_state['overtakeReason'] = f"目标车道车辆过近: {target_distance}m"
            return False
        
        # 🆕 条件4：原车道状态检查
        original_lead_distance = vehicle_data['lead_distance']
        if original_lead_distance > 0 and original_lead_distance < 30:
            # 原车道有近距离前车，谨慎返回
            control_state['overtakeState'] = "原车道有近距离前车"
            control_state['overtakeReason'] = "等待原车道畅通"
            return False
        
        # 所有条件满足，可以返回
        control_state['return_conditions_met'] = True
        return True