#!/usr/bin/env python3
"""
车辆跟踪模块
负责侧方车辆检测和跟踪
"""

import time
from collections import deque
from common.filter_simple import FirstOrderFilter

class SideVehicleTracker:
    """侧方车辆跟踪器"""
    
    def __init__(self, side):
        self.side = side  # 'left' 或 'right'
        self.vehicles = {}  # 跟踪的车辆字典，key为车辆ID
        self.closest_vehicle = None  # 最近的车辆
        self.last_update_time = 0
        self.data_history = deque(maxlen=10)  # 数据历史记录
        
        # 滤波器
        self.distance_filter = FirstOrderFilter(0, 10, 0.1)  # 距离滤波器
        self.speed_filter = FirstOrderFilter(0, 10, 0.1)     # 速度滤波器
        self.relative_speed_filter = FirstOrderFilter(0, 10, 0.1)  # 相对速度滤波器
        
    def update(self, radar_data):
        """更新侧方车辆数据"""
        current_time = time.time()
        
        if not radar_data or not hasattr(radar_data, 'leads') or len(radar_data.leads) == 0:
            # 没有雷达数据，清理过时的车辆
            self._clean_old_vehicles(current_time)
            return
            
        # 处理所有检测到的车辆
        valid_vehicles = {}
        
        for i, lead in enumerate(radar_data.leads):
            if not lead.status:
                continue
                
            # 计算车辆ID（基于位置和速度的哈希）
            vehicle_id = self._calculate_vehicle_id(lead, i)
            
            # 更新车辆数据
            valid_vehicles[vehicle_id] = {
                'id': vehicle_id,
                'distance': lead.dRel,
                'speed': lead.vLead * 3.6 if lead.vLead else 0,  # 转换为km/h
                'relative_speed': lead.vRel * 3.6 if lead.vRel else 0,  # 转换为km/h
                'last_seen': current_time,
                'track_count': self.vehicles.get(vehicle_id, {}).get('track_count', 0) + 1
            }
            
        # 更新跟踪的车辆
        self.vehicles = valid_vehicles
        
        # 找到最近的车辆
        self._update_closest_vehicle()
        
        # 更新滤波器
        if self.closest_vehicle:
            closest = self.closest_vehicle
            self.distance_filter.update(closest['distance'])
            self.speed_filter.update(closest['speed'])
            self.relative_speed_filter.update(closest['relative_speed'])
            
            # 记录数据历史
            self.data_history.append({
                'time': current_time,
                'distance': closest['distance'],
                'speed': closest['speed'],
                'relative_speed': closest['relative_speed'],
                'vehicle_count': len(self.vehicles)
            })
            
        self.last_update_time = current_time
        
    def _calculate_vehicle_id(self, lead, index):
        """计算车辆ID，用于跟踪同一辆车"""
        # 使用距离、速度和角度的组合来生成相对稳定的ID
        distance = lead.dRel
        speed = lead.vLead * 3.6 if lead.vLead else 0
        relative_speed = lead.vRel * 3.6 if lead.vRel else 0
        
        # 简化的ID生成：基于距离和速度的量化
        distance_quantized = round(distance / 5) * 5  # 5米量化
        speed_quantized = round(speed / 10) * 10     # 10km/h量化
        
        return f"{self.side}_{distance_quantized}_{speed_quantized}_{index}"
        
    def _clean_old_vehicles(self, current_time):
        """清理超过1秒未更新的车辆"""
        expired_vehicles = []
        for vehicle_id, vehicle in self.vehicles.items():
            if current_time - vehicle['last_seen'] > 1.0:  # 1秒超时
                expired_vehicles.append(vehicle_id)
                
        for vehicle_id in expired_vehicles:
            del self.vehicles[vehicle_id]
            
    def _update_closest_vehicle(self):
        """更新最近的车辆"""
        if not self.vehicles:
            self.closest_vehicle = None
            return
            
        # 找到距离最近的车辆
        closest = None
        for vehicle in self.vehicles.values():
            if closest is None or vehicle['distance'] < closest['distance']:
                closest = vehicle
                
        self.closest_vehicle = closest
        
    def is_reliable_no_vehicle(self, min_clear_duration=2000):
        """检查是否可靠的无车状态（需要连续一段时间无车）"""
        current_time = time.time() * 1000
        
        # 如果当前有车，直接返回False
        if self.closest_vehicle and self.closest_vehicle['distance'] > 0:
            return False
        
        # 检查历史数据，确保连续min_clear_duration毫秒内都无车
        if len(self.data_history) < 3:  # 至少需要3个数据点
            return False
            
        clear_duration = 0
        for data_point in reversed(self.data_history):
            if data_point['distance'] > 0:  # 历史上有车
                return False
            clear_duration = current_time - data_point['time'] * 1000
            if clear_duration >= min_clear_duration:
                break
        
        return clear_duration >= min_clear_duration
        
    def get_filtered_data(self):
        """获取滤波后的数据"""
        if not self.closest_vehicle:
            return {
                'distance': 0,
                'speed': 0,
                'relative_speed': 0,
                'vehicle_count': 0,
                'track_quality': 0
            }
            
        # 计算跟踪质量（基于跟踪次数和数据稳定性）
        track_quality = min(100, self.closest_vehicle['track_count'] * 10)
        
        return {
            'distance': max(0, self.distance_filter.x),
            'speed': self.speed_filter.x,
            'relative_speed': self.relative_speed_filter.x,
            'vehicle_count': len(self.vehicles),
            'track_quality': track_quality
        }