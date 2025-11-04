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
from typing import Dict, Any
import numpy as np

import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.system.hardware import PC


class XiaogeDataBroadcaster:
    def __init__(self):
        self.broadcast_port = 7701
        self.broadcast_ip = None
        self.sequence = 0

        # 初始化UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # 订阅消息
        self.sm = messaging.SubMaster([
            'carState',
            'modelV2',
            'radarState',
            'selfdriveState',
            'controlsState',
            'longitudinalPlan',
            'carrotMan',
            # 移除 'can' - 盲区数据直接从carState获取
        ])

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

    def _capnp_list_to_list(self, capnp_list, max_items=None):
        """将capnp列表转换为Python列表"""
        if capnp_list is None:
            return []
        try:
            result = [float(x) for x in capnp_list]
            if max_items is not None:
                return result[:max_items]
            return result
        except (TypeError, AttributeError):
            return []

    def _capnp_enum_to_int(self, enum_value):
        """将capnp枚举转换为整数"""
        try:
            return int(enum_value)
        except (TypeError, ValueError):
            return 0

    def collect_car_state(self, carState) -> Dict[str, Any]:
        """收集本车状态数据 - 优化版（移除冗余字段）"""
        return {
            'vEgo': float(carState.vEgo),  # 实际速度
            'aEgo': float(carState.aEgo),  # 加速度
            'steeringAngleDeg': float(carState.steeringAngleDeg),  # 方向盘角度
            'leftBlinker': bool(carState.leftBlinker),  # 转向灯
            'rightBlinker': bool(carState.rightBlinker),
            'brakePressed': bool(carState.brakePressed),  # 刹车
            'leftLatDist': float(carState.leftLatDist),  # 车道距离
            'rightLatDist': float(carState.rightLatDist),
            'leftLaneLine': int(carState.leftLaneLine),  # 车道线类型
            'rightLaneLine': int(carState.rightLaneLine),
            'standstill': bool(carState.standstill),  # 静止状态
            'leftBlindspot': bool(carState.leftBlindspot) if hasattr(carState, 'leftBlindspot') else False,  # 左盲区
            'rightBlindspot': bool(carState.rightBlindspot) if hasattr(carState, 'rightBlindspot') else False,  # 右盲区
            # 移除 vEgoCluster - 超车决策不需要仪表盘速度
            # 移除 vCruise - 使用 longitudinalPlan.cruiseTarget 代替
        }

    def collect_model_data(self, modelV2) -> Dict[str, Any]:
        """收集模型数据 - 优化版（移除冗余数据，只保留超车决策所需）"""
        data = {}

        # 前车检测 - 保留关键信息（距离、速度、加速度、置信度）
        if len(modelV2.leadsV3) > 0:
            lead0 = modelV2.leadsV3[0]
            data['lead0'] = {
                'x': float(lead0.x[0]) if len(lead0.x) > 0 else 0.0,  # 距离
                'v': float(lead0.v[0]) if len(lead0.v) > 0 else 0.0,  # 速度
                'a': float(lead0.a[0]) if len(lead0.a) > 0 else 0.0,  # 加速度（用于判断前车是否在减速）
                'prob': float(lead0.prob),  # 置信度
                # 移除 'y' (横向位置) - 超车决策不需要
            }
        else:
            data['lead0'] = {'x': 0.0, 'v': 0.0, 'a': 0.0, 'prob': 0.0}

        # 第二前车 - 添加速度信息（用于判断超车空间）
        if len(modelV2.leadsV3) > 1:
            lead1 = modelV2.leadsV3[1]
            data['lead1'] = {
                'x': float(lead1.x[0]) if len(lead1.x) > 0 else 0.0,  # 距离
                'v': float(lead1.v[0]) if len(lead1.v) > 0 else 0.0,  # 速度（判断超车空间）
                'prob': float(lead1.prob),  # 置信度
            }
        else:
            data['lead1'] = {'x': 0.0, 'v': 0.0, 'prob': 0.0}

        # 车道线置信度 - 这是最重要的，超车决策只需要置信度
        if len(modelV2.laneLineProbs) >= 3:
            data['laneLineProbs'] = [
                float(modelV2.laneLineProbs[1]),  # 左车道线置信度
                float(modelV2.laneLineProbs[2]),  # 右车道线置信度
            ]
        else:
            data['laneLineProbs'] = [0.0, 0.0]

        # 移除车道线坐标数组 - 超车决策不需要完整轨迹，只需要置信度

        # 车道宽度、到路边缘距离和变道状态 - 保留（超车决策需要）
        meta = modelV2.meta
        data['meta'] = {
            'laneWidthLeft': float(meta.laneWidthLeft),  # 左车道宽度
            'laneWidthRight': float(meta.laneWidthRight),  # 右车道宽度
            'distanceToRoadEdgeLeft': float(meta.distanceToRoadEdgeLeft) if hasattr(meta, 'distanceToRoadEdgeLeft') else 0.0,  # 到左路边缘距离
            'distanceToRoadEdgeRight': float(meta.distanceToRoadEdgeRight) if hasattr(meta, 'distanceToRoadEdgeRight') else 0.0,  # 到右路边缘距离
            'laneChangeState': self._capnp_enum_to_int(meta.laneChangeState),
            'laneChangeDirection': self._capnp_enum_to_int(meta.laneChangeDirection),
        }

        # 曲率信息 - 用于判断弯道（超车决策关键数据）
        if hasattr(modelV2, 'orientationRate') and len(modelV2.orientationRate.z) > 0:
            orientation_rate_z = self._capnp_list_to_list(modelV2.orientationRate.z)
            if orientation_rate_z:
                # 找到最大方向变化率（表示最大曲率点）
                max_index = max(range(len(orientation_rate_z)), key=lambda i: abs(orientation_rate_z[i]))
                max_orientation_rate = orientation_rate_z[max_index]
                data['curvature'] = {
                    'maxOrientationRate': float(max_orientation_rate),  # 最大方向变化率 (rad/s)
                    'direction': 1 if max_orientation_rate > 0 else -1,  # 方向：1=左转，-1=右转
                }
            else:
                data['curvature'] = {'maxOrientationRate': 0.0, 'direction': 0}
        else:
            data['curvature'] = {'maxOrientationRate': 0.0, 'direction': 0}

        # 移除路径规划数据 (position) - 超车决策不需要完整路径轨迹
        # 移除路边线数据 (roadEdges) - 超车决策依赖车道线，不是路边线
        # 移除模型速度估计 (velocity) - 已有 carState.vEgo 和 radarState.vLead

        return data

    def collect_radar_data(self, radarState) -> Dict[str, Any]:
        """收集雷达数据（纯视觉方案也会生成这些数据）"""
        data = {}

        # leadOne信息
        leadOne = radarState.leadOne
        data['leadOne'] = {
            'dRel': float(leadOne.dRel),
            'vRel': float(leadOne.vRel),
            'vLead': float(leadOne.vLead),
            'vLeadK': float(leadOne.vLeadK),
            'status': bool(leadOne.status),
        }

        # leadTwo信息
        if hasattr(radarState, 'leadTwo'):
            leadTwo = radarState.leadTwo
            data['leadTwo'] = {
                'dRel': float(leadTwo.dRel),
                'status': bool(leadTwo.status),
            }
        else:
            data['leadTwo'] = {'dRel': 0.0, 'status': False}

        # 侧方车辆信息
        if hasattr(radarState, 'leadLeft'):
            leadLeft = radarState.leadLeft
            data['leadLeft'] = {
                'dRel': float(leadLeft.dRel) if leadLeft.status else 0.0,
                'vRel': float(leadLeft.vRel) if leadLeft.status else 0.0,
                'status': bool(leadLeft.status),
            }
        else:
            data['leadLeft'] = {'dRel': 0.0, 'vRel': 0.0, 'status': False}

        if hasattr(radarState, 'leadRight'):
            leadRight = radarState.leadRight
            data['leadRight'] = {
                'dRel': float(leadRight.dRel) if leadRight.status else 0.0,
                'vRel': float(leadRight.vRel) if leadRight.status else 0.0,
                'status': bool(leadRight.status),
            }
        else:
            data['leadRight'] = {'dRel': 0.0, 'vRel': 0.0, 'status': False}

        return data

    def collect_system_state(self, selfdriveState, controlsState) -> Dict[str, Any]:
        """收集系统状态"""
        return {
            'enabled': bool(selfdriveState.enabled) if selfdriveState else False,
            'active': bool(selfdriveState.active) if selfdriveState else False,
            'longControlState': self._capnp_enum_to_int(controlsState.longControlState) if controlsState else 0,
        }

    def collect_carrot_data(self, carrotMan) -> Dict[str, Any]:
        """收集 carrot 导航和限速数据"""
        return {
            'nRoadLimitSpeed': int(carrotMan.nRoadLimitSpeed) if hasattr(carrotMan, 'nRoadLimitSpeed') else 0,
            'desiredSpeed': int(carrotMan.desiredSpeed) if hasattr(carrotMan, 'desiredSpeed') else 0,
            'xSpdLimit': int(carrotMan.xSpdLimit) if hasattr(carrotMan, 'xSpdLimit') else 0,
            'xSpdDist': int(carrotMan.xSpdDist) if hasattr(carrotMan, 'xSpdDist') else 0,
            'xSpdType': int(carrotMan.xSpdType) if hasattr(carrotMan, 'xSpdType') else 0,
            'roadcate': int(carrotMan.roadcate) if hasattr(carrotMan, 'roadcate') else 0,  # 道路类型（高速/快速路/城市道路）
        }

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

                # 本车状态 - 始终收集
                if self.sm.alive['carState']:
                    car_state = self.collect_car_state(self.sm['carState'])
                    # 数据验证
                    if car_state.get('vEgo', 0) < 0:
                        print("Warning: Invalid vEgo value detected")
                    data['carState'] = car_state

                # 模型数据
                if self.sm.alive['modelV2']:
                    data['modelV2'] = self.collect_model_data(self.sm['modelV2'])

                # 雷达数据（纯视觉方案也会有）
                if self.sm.alive['radarState']:
                    data['radarState'] = self.collect_radar_data(self.sm['radarState'])

                # 系统状态
                if self.sm.alive['selfdriveState'] and self.sm.alive['controlsState']:
                    data['systemState'] = self.collect_system_state(
                        self.sm['selfdriveState'],
                        self.sm['controlsState']
                    )

                # 纵向规划数据
                if self.sm.alive['longitudinalPlan']:
                    lp = self.sm['longitudinalPlan']
                    data['longitudinalPlan'] = {
                        'xState': self._capnp_enum_to_int(lp.xState),
                        'trafficState': self._capnp_enum_to_int(lp.trafficState),
                        'cruiseTarget': float(lp.cruiseTarget),
                        'hasLead': bool(lp.hasLead),
                    }

                # carrot 导航和限速数据
                if self.sm.alive['carrotMan']:
                    data['carrotMan'] = self.collect_carrot_data(self.sm['carrotMan'])

                # 盲区数据已包含在carState中，无需单独收集

                # 性能监控
                processing_time = time.perf_counter() - start_time
                if processing_time > 0.05:  # 超过50ms
                    print(f"Warning: Slow processing detected: {processing_time*1000:.1f}ms")

                # 如果有数据则广播
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