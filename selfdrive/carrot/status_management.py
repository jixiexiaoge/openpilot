#!/usr/bin/env python3
"""
状态管理模块 - 优化版
负责系统状态的管理和维护
"""

import time
import socket

# 导入配置模块
try:
    from selfdrive.carrot.auto_overtake.config import Config
except ImportError:
    from config import Config

class StatusManager:
    """状态管理器"""
    
    def __init__(self):
        self.vehicle_data = self._init_vehicle_data()
        self.control_state = self._init_control_state()

    def _init_vehicle_data(self):
        """初始化车辆数据字典"""
        return {
            # 速度相关
            'v_cruise_kph': 0,      # 巡航速度 (km/h)
            'v_ego_kph': 0,         # 本车速度 (km/h)
            'desire_speed': 0,      # 期望速度
            'lead_speed': 0,        # 前车速度
            'lead_distance': 0,     # 前车距离
            'lead_relative_speed': 0, # 前车相对速度

            # 车道信息
            'lane_count': 3,        # 车道总数
            'l_lane_width': 3.2,    # 左侧车道宽度
            'r_lane_width': 3.2,    # 右侧车道宽度
            'l_edge_dist': 1.5,     # 左侧边缘距离
            'r_edge_dist': 1.5,     # 右侧边缘距离

            # 控制状态
            'IsOnroad': False,      # 是否在道路上
            'active': False,        # 系统是否激活
            'engaged': False,       # 巡航是否激活
            'steering_angle': 0.0,  # 方向盘角度
            'lat_a': 0.0,           # 横向加速度
            'road_curvature': 0.0,  # 道路曲率
            'max_curve': 0.0,       # 最大曲率

            # 盲区检测
            'left_blindspot': False,    # 左侧盲区有车
            'right_blindspot': False,   # 右侧盲区有车
            'l_front_blind': False,     # 左侧前盲区
            'r_front_blind': False,     # 右侧前盲区

            # 侧方车辆信息
            'left_lead_speed': 0,           # 左侧前车速度
            'left_lead_distance': 0,        # 左侧前车距离
            'left_lead_relative_speed': 0,  # 左侧前车相对速度
            'right_lead_speed': 0,          # 右侧前车速度
            'right_lead_distance': 0,       # 右侧前车距离
            'right_lead_relative_speed': 0, # 右侧前车相对速度

            # 车辆信号
            'blinker': 'none',      # 转向灯状态
            'gas_press': False,     # 油门踏板
            'break_press': False,   # 刹车踏板

            # 系统控制
            'system_auto_control': 0,   # OP自动控制状态
            'last_op_control_time': 0,  # 最后OP控制时间
            'atc_type': 'none'          # 自动控制类型
        }

    def _init_control_state(self):
        """初始化控制状态字典"""
        control_state = {
            # 基本状态
            'current_status': '就绪',          # 当前状态描述
            'last_command': '',               # 最后执行的命令
            'blinker_state': 'none',          # 转向灯状态
            'cruise_active': False,           # 巡航激活状态

            # 超车状态
            'isOvertaking': False,            # 是否正在超车
            'overtakeState': '等待超车条件',   # 超车状态描述
            'overtakeReason': '分析道路情况中...', # 超车原因
            'overtakingCompleted': False,     # 超车是否完成
            'overtakeSuccessCount': 0,        # 超车成功次数
            'lastOvertakeDirection': '',      # 最后超车方向
            'lastOvertakeTime': 0,            # 最后超车时间

            # 变道控制
            'lane_change_in_progress': False, # 变道进行中
            'lastLaneChangeCommandTime': 0,   # 最后变道命令时间

            # 智能返回系统
            'net_lane_changes': 0,            # 净变道次数（左+1, 右-1）
            'max_return_attempts': 2,         # 最大返回尝试次数
            'return_attempts': 0,             # 当前返回尝试次数
            'return_conditions_met': False,   # 返回条件是否满足
            'return_timer_start': 0,          # 返回计时开始时间
            'last_return_direction': None,    # 最后返回方向
            'return_retry_count': 0,          # 返回重试次数
            'original_lane_clear': False,     # 原车道前车是否已超越

            # 跟车计时
            'follow_start_time': None,        # 跟车开始时间
            'is_following_slow_vehicle': False, # 是否跟随慢车
            'max_follow_time_reached': False, # 是否达到最大跟车时间

            # 冷却系统
            'last_overtake_result': 'none',   # 最后超车结果
            'dynamic_cooldown': 8000,         # 动态冷却时间(ms)
            'consecutive_failures': 0,        # 连续失败次数

            # 自动超车专用
            'last_auto_overtake_time': 0,     # 最后自动超车时间
            'return_timeout': 40000,          # 返回超时时间(ms)
            'is_auto_overtake': False,        # 是否为自动超车

            # OP控制冷却
            'op_control_cooldown': 0,         # OP控制冷却时间
            'last_op_control_end_time': 0,    # OP控制结束时间

            # 目标车辆跟踪
            'target_vehicle_tracker': None,  # 跟踪要超越的目标车辆
            'target_vehicle_speed': 0,       # 目标车辆速度
            'target_vehicle_distance': 0,    # 目标车辆距离
            'target_vehicle_side': None,     # 目标车辆所在侧 ('left'/'right')
            'overtake_complete_timer': 0,    # 超越完成计时器
            'overtake_complete_duration': 5000,  # 超越完成后等待时间(ms)
            'consecutive_overtake_count': 0,  # 连续超车次数
            'last_lane_number': 0,           # 上次车道编号
            'lane_change_detected': False,    # 是否检测到变道
            'last_status_update_time': 0,     # 最后状态更新时间
            'completion_timer': 0,           # 完成状态计时器,
            
            # 条件稳定性检查
            'condition_stability_timer': 0,
            'condition_stable_duration': 1500,
            'condition_met_count': 0,
            'condition_met_threshold': 3,
            'last_condition_check_time': 0,
            'stable_condition_flags': {},
            'quick_trigger_enabled': False,
            
            # 原车道记忆系统
            'original_lane_number': 0,
            'target_return_lane': 0,
            'lane_change_history': [],
            'max_lane_memory_time': 30000,
            'lane_memory_start_time': 0,
            'return_timeout_timer': 0,
        }
        
        return control_state

    def ensure_status_refresh(self, control_state):
        """确保状态及时刷新 - 优化版本"""
        current_time = time.time() * 1000
        
        # 🆕 状态超时检查：5秒无活动自动恢复等待状态
        if (current_time - control_state.get('last_status_update_time', 0) > 5000 and
            not control_state.get('isOvertaking', False) and 
            not control_state.get('lane_change_in_progress', False) and
            control_state.get('overtakeState') != "等待超车条件"):
            control_state.update({
                'overtakeState': "等待超车条件",
                'overtakeReason': "分析道路情况中...",
                'current_status': "就绪"
            })
            control_state['last_status_update_time'] = current_time
        
        # 🆕 添加状态机检查
        state_timeout = 10000  # 10秒状态超时
        
        # 情况1：超车完成且没有其他活动，恢复就绪状态
        if (control_state.get('overtakingCompleted') and 
            not control_state['isOvertaking'] and 
            not control_state['lane_change_in_progress']):
            
            control_state.update({
                'overtakeState': "等待超车条件",
                'overtakeReason': "分析道路情况中...",
                'current_status': "就绪",
                'overtakingCompleted': False
            })

        # 情况2：长时间处于同一状态，强制刷新
        elif (control_state.get('last_status_update_time') and 
              current_time - control_state['last_status_update_time'] > state_timeout and
              not control_state['isOvertaking'] and 
              not control_state['lane_change_in_progress']):
            
            # 检查是否需要重置
            current_state = control_state.get('overtakeState', '')
            if current_state not in ['等待超车条件', '就绪']:
                control_state.update({
                    'overtakeState': "等待超车条件",
                    'overtakeReason': "状态超时，自动恢复",
                    'current_status': "就绪"
                })
        
        # 🆕 情况3：检查完成定时器
        if control_state.get('completion_timer') and current_time - control_state['completion_timer'] > 2000:
            if not control_state['isOvertaking'] and not control_state['lane_change_in_progress']:
                control_state.update({
                    'overtakeState': "等待超车条件",
                    'overtakeReason': "分析道路情况中...",
                    'current_status': "就绪"
                })
                del control_state['completion_timer']
        
        # 更新状态时间戳
        control_state['last_status_update_time'] = current_time

    def get_local_ip(self):
        """获取本地IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def get_no_overtake_reasons(self, vehicle_data, config, control_state, overtake_decision):
        """获取未超车的具体原因"""
        reasons = []

        if vehicle_data['system_auto_control'] == 1:
            reasons.append("OP自动控制中")
            return reasons

        if not vehicle_data['IsOnroad']:
            reasons.append("车辆不在道路上")
            return reasons

        if not vehicle_data['engaged']:
            reasons.append("巡航未激活")
            return reasons

        if vehicle_data['lead_distance'] <= 0:
            reasons.append("前方无车辆")
            return reasons

        speed_ratio = vehicle_data['v_ego_kph'] / vehicle_data['v_cruise_kph'] if vehicle_data['v_cruise_kph'] > 0 else 1.0
        time_gap = overtake_decision.calculate_time_gap(vehicle_data)

        trigger_conditions_met = []

        if vehicle_data['lead_relative_speed'] < config['LEAD_RELATIVE_SPEED_THRESHOLD']:
            trigger_conditions_met.append("前车相对速度")

        if 0 < time_gap <= config['FOLLOW_TIME_GAP_THRESHOLD']:
            trigger_conditions_met.append("跟车时间距离")

        if speed_ratio < config['CRUISE_SPEED_RATIO_THRESHOLD']:
            trigger_conditions_met.append("速度比例")

        if not trigger_conditions_met:
            reasons.append("未满足任何超车触发条件")
            reasons.append(f"相对速度:{vehicle_data['lead_relative_speed']}km/h(阈值:{config['LEAD_RELATIVE_SPEED_THRESHOLD']}km/h)")
            reasons.append(f"时间距离:{time_gap:.1f}秒(阈值:{config['FOLLOW_TIME_GAP_THRESHOLD']}秒)")
            reasons.append(f"速度比例:{speed_ratio*100:.0f}%(阈值:{config['CRUISE_SPEED_RATIO_THRESHOLD']*100:.0f}%)")
            return reasons

        if config['road_type'] == 'highway' and vehicle_data['v_ego_kph'] < config['HIGHWAY_MIN_SPEED']:
            reasons.append(f"高速车速{vehicle_data['v_ego_kph']}km/h过低(阈值:{config['HIGHWAY_MIN_SPEED']}km/h)")

        if config['road_type'] == 'normal' and vehicle_data['v_ego_kph'] < config['NORMAL_ROAD_MIN_SPEED']:
            reasons.append(f"普通路车速{vehicle_data['v_ego_kph']}km/h过低(阈值:{config['NORMAL_ROAD_MIN_SPEED']}km/h)")

        now = time.time() * 1000
        if control_state['lastOvertakeTime'] > 0 and now - control_state['lastOvertakeTime'] < control_state['dynamic_cooldown']:
            remaining = (control_state['dynamic_cooldown'] - (now - control_state['lastOvertakeTime'])) / 1000
            reasons.append(f"冷却时间剩余{remaining:.1f}秒")

        if trigger_conditions_met and reasons:
            reasons.insert(0, f"触发条件: {', '.join(trigger_conditions_met)}")

        return reasons

    def reset_net_lane_changes(self, control_state, verification_system):
        """重置净变道次数 - 多源验证版本"""
        # 原有重置逻辑
        control_state['net_lane_changes'] = 0
        control_state['return_attempts'] = 0
        control_state['return_conditions_met'] = False
        control_state['return_timer_start'] = 0
        control_state['last_auto_overtake_time'] = 0
        control_state['is_auto_overtake'] = False
        control_state['original_lane_clear'] = False

        # 🆕 多源验证系统重置
        verification_system.reset_verification_system()

        # 🆕 清理原车道记忆
        control_state['original_lane_number'] = 0
        control_state['target_return_lane'] = 0
        control_state['lane_memory_start_time'] = 0
        control_state['lane_change_history'] = []
        control_state['return_timeout_timer'] = 0

        # 状态重置
        control_state['isOvertaking'] = False
        control_state['lane_change_in_progress'] = False
        control_state['overtakingCompleted'] = False
        control_state['overtakeState'] = "等待超车条件"
        control_state['overtakeReason'] = "分析道路情况中..."
        control_state['current_status'] = "就绪"

    def get_status_data(self, vehicle_data, control_state, config, overtake_decision):
        """获取状态数据 - 保持与Web界面完全兼容"""
        vd = vehicle_data
        cs = control_state
        cfg = config

        time_gap = overtake_decision.calculate_time_gap(vd)
        speed_ratio = vd['v_ego_kph'] / vd['v_cruise_kph'] if vd['v_cruise_kph'] > 0 else 1.0

        remaining_cooldown = 0
        now = time.time() * 1000
        if cs['lastOvertakeTime'] > 0:
            elapsed = now - cs['lastOvertakeTime']
            remaining_cooldown = max(0, cs['dynamic_cooldown'] - elapsed) / 1000

        remaining_return_timeout = 0
        if cs['net_lane_changes'] != 0 and cs['last_auto_overtake_time'] > 0:
            elapsed_auto = now - cs['last_auto_overtake_time']
            remaining_return_timeout = max(0, cs['return_timeout'] - elapsed_auto) / 1000

        remaining_op_cooldown = 0
        if cs['op_control_cooldown'] > 0:
            elapsed_op = now - cs['last_op_control_end_time']
            remaining_op_cooldown = max(0, cs['op_control_cooldown'] - elapsed_op) / 1000

        trigger_conditions = overtake_decision.get_trigger_conditions(vd, cs)
        no_overtake_reasons = self.get_no_overtake_reasons(vd, cfg, cs, overtake_decision)

        left_lane_narrow = vd.get('l_lane_width', 3.2) < cfg.get('MIN_LANE_WIDTH', 2.5)
        right_lane_narrow = vd.get('r_lane_width', 3.2) < cfg.get('MIN_LANE_WIDTH', 2.5)

        left_warnings = []
        right_warnings = []

        if left_lane_narrow:
            left_warnings.append("车道过窄⚠️禁止变道")
        if vd.get('left_blindspot', False) or vd.get('l_front_blind', False):
            left_warnings.append("盲区有车⚠️禁止变道")
        if vd.get('left_lead_distance', 0) > 0 and vd.get('left_lead_distance', 0) < cfg.get('SIDE_LEAD_DISTANCE_MIN', 15):
            left_warnings.append("侧车过近⚠️禁止变道")
        if abs(vd.get('left_lead_relative_speed', 0)) > cfg.get('SIDE_RELATIVE_SPEED_THRESHOLD', 20):
            left_warnings.append("侧车相对⚠️速度过高")

        if right_lane_narrow:
            right_warnings.append("车道过窄⚠️禁止变道")
        if vd.get('right_blindspot', False) or vd.get('r_front_blind', False):
            right_warnings.append("盲区有车⚠️禁止变道")
        if vd.get('right_lead_distance', 0) > 0 and vd.get('right_lead_distance', 0) < cfg.get('SIDE_LEAD_DISTANCE_MIN', 15):
            right_warnings.append("侧车过近⚠️禁止变道")
        if abs(vd.get('right_lead_relative_speed', 0)) > cfg.get('SIDE_RELATIVE_SPEED_THRESHOLD', 20):
            right_warnings.append("侧车相对⚠️速度过高")

        max_follow_time_ms = cfg.get('MAX_FOLLOW_TIME', 120000)
        max_follow_time_minutes = max_follow_time_ms / 60000

        # 🌐 系统状态
        status_data = {
            # 🌐 系统状态
            'w': True,
            'ip': self.get_local_ip(),

            # 🚗 速度信息
            's': vd.get('v_ego_kph', 0),
            'c': vd.get('v_cruise_kph', 0),
            'd': vd.get('desire_speed', 0),

            # 🚘 前车信息
            'ls': vd.get('lead_speed', 0),
            'ld': vd.get('lead_distance', 0),
            'lrs': vd.get('lead_relative_speed', 0),

            # 👁️ 盲区状态
            'lb': bool(vd.get('left_blindspot', False)),
            'rb': bool(vd.get('right_blindspot', False)),
            'l_front_blind': bool(vd.get('l_front_blind', False)),
            'r_front_blind': bool(vd.get('r_front_blind', False)),

            # 🛣️ 车道几何信息
            'llw': float(vd.get('l_lane_width', 3.2)),
            'rlw': float(vd.get('r_lane_width', 3.2)),
            'led': float(vd.get('l_edge_dist', 1.5)),
            'red': float(vd.get('r_edge_dist', 1.5)),

            # 🚘 侧方车辆信息 - 保持原有字段
            'lls': vd.get('left_lead_speed', 0),
            'lld': vd.get('left_lead_distance', 0),
            'llrs': vd.get('left_lead_relative_speed', 0),
            'rls': vd.get('right_lead_speed', 0),
            'rld': vd.get('right_lead_distance', 0),
            'rlrs': vd.get('right_lead_relative_speed', 0),

            # ⚙️ 配置信息
            'rt': cfg.get('road_type', 'highway'),
            'lc': cfg.get('lane_count', 3),
            'cl': cfg.get('current_lane_number', 2),
            'lane_count_mode': cfg.get('lane_count_mode', 'auto'),

            # 🚀 超车状态
            'os': cs.get('overtakeState', '等待超车条件'),
            'or': cs.get('overtakeReason', '分析道路情况中...'),
            'oc': cs.get('overtakeSuccessCount', 0),

            # 🎛️ 超车参数
            'hms': cfg.get('HIGHWAY_MIN_SPEED', 75),
            'nms': cfg.get('NORMAL_ROAD_MIN_SPEED', 40),
            'sr': cfg.get('CRUISE_SPEED_RATIO_THRESHOLD', 0.8),
            'ftg': cfg.get('FOLLOW_TIME_GAP_THRESHOLD', 3.0),
            'mft': max_follow_time_minutes,
            'mft_ms': cfg.get('MAX_FOLLOW_TIME', 120000),
            'mlw': cfg.get('MIN_LANE_WIDTH', 2.5),
            'slw': cfg.get('SAFE_LANE_WIDTH', 3.0),
            'sld': cfg.get('SIDE_LEAD_DISTANCE_MIN', 15),
            'srs': cfg.get('SIDE_RELATIVE_SPEED_THRESHOLD', 20),
            'lrs_threshold': cfg.get('LEAD_RELATIVE_SPEED_THRESHOLD', -5.0),

            # 🔧 功能开关
            'aoe': cfg.get('autoOvertakeEnabled', True),
            'aoel': cfg.get('autoOvertakeEnabledL', True),
            'srtl': cfg.get('shouldReturnToLane', True),

            # ⚠️ 警告状态
            'left_lane_narrow': left_lane_narrow,
            'right_lane_narrow': right_lane_narrow,

            # 🎮 系统控制状态
            'system_auto_control': vd.get('system_auto_control', 0),

            # 🔄 智能返回系统
            'net_lane_changes': cs.get('net_lane_changes', 0),
            'return_attempts': cs.get('return_attempts', 0),
            'original_lane_clear': cs.get('original_lane_clear', False),

            # ❄️ 冷却系统
            'remaining_cooldown': remaining_cooldown,
            'dynamic_cooldown': cs.get('dynamic_cooldown', 8000),
            'last_overtake_result': cs.get('last_overtake_result', 'none'),
            'consecutive_failures': cs.get('consecutive_failures', 0),

            # 📊 实时指标
            'time_gap': time_gap,
            'speed_ratio': speed_ratio,
            'sr_threshold': cfg.get('CRUISE_SPEED_RATIO_THRESHOLD', 0.8),

            # 📋 条件分析
            'trigger_conditions': trigger_conditions,
            'no_overtake_reasons': no_overtake_reasons,

            # ⏰ 超时信息
            'remaining_return_timeout': remaining_return_timeout,
            'remaining_op_cooldown': remaining_op_cooldown,

            # 🚨 警告信息
            'left_warnings': left_warnings,
            'right_warnings': right_warnings,

            # 🔥 新增状态
            'is_auto_overtake': cs.get('is_auto_overtake', False),

            # 🛣️ 返回策略状态
            'return_strategy_enabled': cfg['RETURN_STRATEGY'][cfg['road_type']]['enabled'],
            'road_type_display': '高速公路' if cfg['road_type'] == 'highway' else '普通道路',

            # 🆕 v3.7 新增参数
            'highway_lead_min_speed': cfg.get('HIGHWAY_LEAD_MIN_SPEED', 35),
            'normal_lead_min_speed': cfg.get('NORMAL_LEAD_MIN_SPEED', 20),
            'early_overtake_speed_ratio': cfg.get('EARLY_OVERTAKE_SPEED_RATIO', 0.6),
            'early_overtake_min_lead_speed': cfg.get('EARLY_OVERTAKE_MIN_LEAD_SPEED', 50),
            'early_overtake_min_distance': cfg.get('EARLY_OVERTAKE_MIN_DISTANCE', 30),
            'early_overtake_max_distance': cfg.get('EARLY_OVERTAKE_MAX_DISTANCE', 100),
            'early_overtake_min_speed_diff': cfg.get('EARLY_OVERTAKE_MIN_SPEED_DIFF', 20),
        }

        return status_data