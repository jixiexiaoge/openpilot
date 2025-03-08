#!/usr/bin/env python3
import math

from opendbc.can.parser import CANParser
from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.mazda.values import DBC, CanBus, MazdaFlags
from opendbc.car.interfaces import RadarInterfaceBase

# 根据 mazda_radar.dbc 文件定义的雷达跟踪消息 ID
RADAR_TRACK_MSGS = list(range(865, 871))  # 从 RADAR_TRACK_361 到 RADAR_TRACK_366
LAST_RADAR_MSG = 870  # RADAR_TRACK_366

def create_radar_can_parser(car_fingerprint):
    if 'radar' not in DBC[car_fingerprint]:
        return None

    signals = []

    # 添加每个雷达跟踪消息的信号
    for track_msg in RADAR_TRACK_MSGS:
        signals.append(("DIST_OBJ", track_msg))
        signals.append(("ANG_OBJ", track_msg))
        signals.append(("RELV_OBJ", track_msg))

    messages = list({(s[1], 8) for s in signals})  # 8 表示消息长度为 8 字节

    return CANParser(DBC[car_fingerprint][Bus.pt], messages, CanBus.main)

class RadarInterface(RadarInterfaceBase):
    def __init__(self, CP):
        super().__init__(CP)
        self.updated_messages = set()
        self.track_id = 0
        self.v_ego = 0.0  # 自车速度，用于计算目标绝对速度

        # 检查雷达是否可用
        self.radar_off_can = CP.radarUnavailable
        self.rcp = create_radar_can_parser(CP.carFingerprint) if not self.radar_off_can else None

        self.trigger_msg = LAST_RADAR_MSG
        self.pts = {}  # 存储雷达点的字典

    def update(self, can_strings):
        if self.radar_off_can or (self.rcp is None):
            return super().update(None)

        vls = self.rcp.update_strings(can_strings)
        self.updated_messages.update(vls)

        if self.trigger_msg not in self.updated_messages:
            return None

        ret = structs.RadarData()
        errors = []

        if not self.rcp.can_valid:
            errors.append("canError")
        ret.errors = errors

        current_targets = set()

        # 处理更新的雷达跟踪消息
        for track_msg in self.updated_messages:
            if track_msg not in RADAR_TRACK_MSGS:
                continue

            if track_msg not in self.rcp.vl:
                continue

            msg = self.rcp.vl[track_msg]

            # 检查数据是否有效
            # 这里的无效值参考自 mazda_radar.dbc 文件，根据实际情况可能需要调整
            valid = (msg['DIST_OBJ'] != 4095) and (msg['ANG_OBJ'] != 2046) and (msg['RELV_OBJ'] != -16)

            if valid:
                # 使用消息 ID 作为跟踪目标 ID
                addr = track_msg
                current_targets.add(addr)

                if addr not in self.pts:
                    self.pts[addr] = structs.RadarData.RadarPoint()
                    self.pts[addr].trackId = self.track_id
                    self.track_id += 1

                # 单位转换：按照 DBC 文件中的定义进行转换
                azimuth = math.radians(msg['ANG_OBJ'] / 64)  # 角度转换为弧度
                distance = msg['DIST_OBJ'] / 16  # 距离单位转换

                self.pts[addr].dRel = distance  # 纵向距离（从车头开始）
                self.pts[addr].yRel = -math.sin(azimuth) * distance  # 计算横向距离，注意负号表示方向
                self.pts[addr].vRel = msg['RELV_OBJ'] / 16  # 速度单位转换
                self.pts[addr].aRel = float('nan')  # 加速度数据不可用
                self.pts[addr].yvRel = float('nan')  # 横向速度数据不可用
                self.pts[addr].measured = True  # 标记为实际测量值

                # 计算目标的绝对速度
                self.pts[addr].vLead = self.pts[addr].vRel + self.v_ego
                # 暂不设置加速度和加加速度
                self.pts[addr].aLead = float('nan')
                self.pts[addr].jLead = float('nan')

        # 删除消失的目标
        for old_target in list(self.pts.keys()):
            if old_target not in current_targets:
                del self.pts[old_target]

        ret.points = list(self.pts.values())
        self.updated_messages.clear()
        return ret

    def set_speed(self, v_ego):
        """更新自车速度以便计算目标绝对速度"""
        self.v_ego = v_ego
