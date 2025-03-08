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
    """创建雷达CAN解析器

    Args:
        car_fingerprint: 车辆特征码

    Returns:
        CANParser: 配置好的雷达CAN解析器，如果不支持雷达则返回None
    """
    # 检查是否有雷达DBC定义
    if car_fingerprint not in DBC or 'radar' not in DBC[car_fingerprint]:
        return None

    signals = []

    # 添加每个雷达跟踪消息的信号
    for track_msg in RADAR_TRACK_MSGS:
        signals.append(("DIST_OBJ", track_msg))  # 目标距离
        signals.append(("ANG_OBJ", track_msg))   # 目标角度
        signals.append(("RELV_OBJ", track_msg))  # 相对速度

    # 生成消息列表，消息长度为8字节
    messages = list({(s[1], 8) for s in signals})

    # 创建并返回配置好的CAN解析器
    try:
        return CANParser(DBC[car_fingerprint][Bus.pt], messages, CanBus.main)
    except Exception as e:
        print(f"创建雷达CAN解析器失败：{e}")
        return None


class RadarInterface(RadarInterfaceBase):
    def __init__(self, CP):
        """初始化雷达接口

        Args:
            CP: 车辆参数
        """
        super().__init__(CP)
        # 跟踪已更新的消息
        self.updated_messages = set()
        self.track_id = 0
        self.v_ego = 0.0  # 自车速度，用于计算目标绝对速度

        # 检查雷达是否可用
        self.radar_off_can = CP.radarUnavailable
        self.rcp = create_radar_can_parser(CP.carFingerprint) if not self.radar_off_can else None

        # 触发消息ID，收到该消息后更新雷达数据
        self.trigger_msg = LAST_RADAR_MSG
        self.pts = {}  # 存储雷达点的字典

        # 无效值阈值，用于过滤无效数据
        self.INVALID_DISTANCE = 4095  # 距离无效值
        self.INVALID_ANGLE = 2046     # 角度无效值
        self.INVALID_REL_VEL = -16    # 相对速度无效值

    def update(self, can_strings):
        """更新雷达数据

        Args:
            can_strings: CAN消息数据

        Returns:
            structs.RadarData: 处理后的雷达数据
        """
        # 如果雷达不可用或解析器未初始化，返回空数据
        if self.radar_off_can or (self.rcp is None):
            return super().update(None)

        try:
            # 解析CAN消息
            vls = self.rcp.update_strings(can_strings)
            self.updated_messages.update(vls)

            # 如果没有收到触发消息，返回None表示数据尚未就绪
            if self.trigger_msg not in self.updated_messages:
                return None

            # 创建返回数据结构
            ret = structs.RadarData()
            errors = []

            # 检查CAN总线状态
            if not self.rcp.can_valid:
                errors.append("canError")
            ret.errors = errors

            # 跟踪当前帧中的有效目标
            current_targets = set()

            # 遍历所有雷达跟踪消息进行处理
            for track_msg in self.updated_messages:
                # 只处理雷达跟踪消息
                if track_msg not in RADAR_TRACK_MSGS:
                    continue

                # 确保消息在解析器中存在
                if track_msg not in self.rcp.vl:
                    continue

                # 获取消息数据
                msg = self.rcp.vl[track_msg]

                try:
                    # 数据有效性检查
                    distance = msg.get('DIST_OBJ', self.INVALID_DISTANCE)
                    angle = msg.get('ANG_OBJ', self.INVALID_ANGLE)
                    rel_vel = msg.get('RELV_OBJ', self.INVALID_REL_VEL)

                    valid = (distance != self.INVALID_DISTANCE and
                             angle != self.INVALID_ANGLE and
                             rel_vel != self.INVALID_REL_VEL)

                    # 额外合理性检查：距离和速度在合理范围内
                    if valid:
                        # 距离应在0.1-200米范围内
                        distance_m = distance / 16
                        if not (0.1 <= distance_m <= 200):
                            valid = False

                        # 相对速度应在-100至100 m/s范围内
                        rel_vel_ms = rel_vel / 16
                        if not (-100 <= rel_vel_ms <= 100):
                            valid = False

                    if valid:
                        # 使用消息ID作为目标跟踪ID
                        addr = track_msg
                        current_targets.add(addr)

                        # 如果是新目标，初始化数据结构
                        if addr not in self.pts:
                            self.pts[addr] = structs.RadarData.RadarPoint()
                            self.pts[addr].trackId = self.track_id
                            self.track_id += 1

                        # 单位转换
                        azimuth = math.radians(angle / 64)  # 角度转换为弧度
                        distance = distance / 16  # 距离单位转换(cm -> m)

                        # 更新目标数据
                        self.pts[addr].dRel = distance  # 纵向距离（从车头开始）
                        self.pts[addr].yRel = -math.sin(azimuth) * distance  # 计算横向距离，负号表示方向
                        self.pts[addr].vRel = rel_vel / 16  # 速度单位转换
                        self.pts[addr].aRel = float('nan')  # 加速度数据不可用
                        self.pts[addr].yvRel = float('nan')  # 横向速度数据不可用
                        self.pts[addr].measured = True  # 标记为实际测量值

                        # 计算目标的绝对速度
                        self.pts[addr].vLead = self.pts[addr].vRel + self.v_ego
                        # 加速度暂不可用
                        self.pts[addr].aLead = float('nan')
                        self.pts[addr].jLead = float('nan')

                except (KeyError, ValueError, TypeError) as e:
                    # 处理消息解析错误，继续处理下一个消息
                    continue

            # 删除消失的目标
            for old_target in list(self.pts.keys()):
                if old_target not in current_targets:
                    del self.pts[old_target]

            # 构建返回数据
            ret.points = list(self.pts.values())
            self.updated_messages.clear()
            return ret

        except Exception as e:
            # 捕获所有异常，确保不会导致系统崩溃
            import traceback
            print(f"雷达数据处理错误: {e}")
            print(traceback.format_exc())

            # 返回空的雷达数据
            ret = structs.RadarData()
            ret.errors = ["processingError"]
            return ret

    def set_speed(self, v_ego):
        """更新自车速度以便计算目标绝对速度

        Args:
            v_ego: 自车速度(m/s)
        """
        self.v_ego = v_ego
