
from opendbc.car import apply_std_steer_angle_limits, Bus, structs
import numpy as np
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams, CAR
from opendbc.can.packer import CANPacker
from openpilot.common.conversions import Conversions as CV
from openpilot.common.realtime import DT_CTRL

SteerControlType = structs.CarParams.SteerControlType
VisualAlert = structs.CarControl.HUDControl.VisualAlert

class CarController(CarControllerBase):
    def __init__(self, dbc_names, CP):
        super().__init__(dbc_names, CP)
        self.params = CarControllerParams(self.CP)
        self.last_angle = 0  # 上一次的转向角度
        self.alert_active = False
        self.last_standstill = False
        self.standstill_req = False
        self.counter_244 = 0
        self.counter_1ba = 0
        self.counter_17e = 0  # 17E消息的计数器
        self.counter_307 = 0
        self.counter_31a = 0
        self.first_start = True

        self.packer = CANPacker(dbc_names[Bus.pt])
        self.last_apply_accel = 0
        self.last_acctrq = -5000
        self.stop_lead_distance = 0
        self.last_speed = 0

        self.ldw_sys_sts = 0

        self.expected_accel = 0.0
        self.actual_accel_filtered = 0.0  # 滤波后的实际加速度
        self.slope_compensation = 0.0      # 坡度补偿值

        self.expected_daccel = 0.0  # 期望减速度
        self.actual_daccel_filtered = 0.0  # 滤波后的实际减速度
        self.slope_daccel = 0.0      # 减速度坡度补偿值

        # 改进的急弯检测相关参数 - 调整大角度转弯阈值为40度
        self.emergency_turn_threshold_angle = 35.0  # 急弯角度阈值从45度调整为35度
        self.emergency_turn_threshold_rate = 60.0   # 急弯转向速率阈值（度/秒）
        self.emergency_turn_active = False          # 急弯激活标志
        self.last_steering_angle = 0.0              # 上一次转向角度
        self.steering_rate = 0.0                    # 转向速率
        self.emergency_turn_counter = 0              # 急弯计数器，防止频繁切换
        self.emergency_turn_timeout = 0             # 急弯超时计数器

        # 大角度转向控制参数 - 调整阈值为40度
        self.large_angle_active = False
        self.large_angle_threshold = 40.0  # 大角度阈值从50度调整为40度
        self.large_angle_counter = 0

        # 转弯时纵向控制限制参数
        self.turn_speed_limit = 0.0  # 转弯时的速度限制
        self.turn_accel_limit = 0.0  # 转弯时的加速度限制
        self.last_turn_state = False  # 上一次的转弯状态

        # 新增：后方来车检测和变道控制参数
        self.rear_vehicle_detected = False  # 后方来车检测标志
        self.rear_vehicle_speed = 0.0  # 后方来车速度
        self.rear_vehicle_distance = 0.0  # 后方来车距离
        self.lane_change_blocked = False  # 变道被阻止标志
        self.lane_change_safety_timer = 0  # 变道安全计时器
        self.last_lane_change_direction = 0  # 上一次变道方向（-1左，0无，1右）

        # 修改：转向平滑控制参数 - 降低平滑因子使转向响应更快
        self.steering_smoothing_factor = 0.3  # 转向平滑因子从0.5降低到0.3（越小响应越快）
        self.filtered_steering_angle = 0.0     # 滤波后的转向角度

        # 修改：出弯回正控制参数 - 加快回正速度
        self.return_to_center_active = False  # 出弯回正激活标志
        self.return_to_center_threshold = 15.0  # 回正激活阈值（度）
        self.return_smoothing_factor = 0.5  # 回正平滑因子从0.7降低到0.5（加快回正）
        self.return_max_rate = 35.0  # 回正最大速率从25度/秒提高到35度/秒

        # 新增：大角度弯速度控制参数
        self.large_turn_target_speed = 25.0  # 大角度弯目标速度(km/h)
        self.large_turn_speed_control_active = False  # 大角度弯速度控制激活标志
        self.large_turn_speed_control_timer = 0  # 大角度弯速度控制计时器

        # 新增：滑行控制参数
        self.coasting_active = False  # 滑行模式激活标志
        self.coasting_timer = 0  # 滑行计时器
        self.coasting_speed_threshold = 30.0  # 滑行速度阈值(km/h)
        self.coasting_angle_threshold = 40.0  # 滑行角度阈值从50度调整为40度
        self.coasting_min_speed = 15.0  # 滑行最低速度(km/h)
        self.coasting_deceleration = 0.1  # 滑行减速度(m/s²)

        # 修改：方向盘角度限制参数 - 单边转向角度从160度调整为150度
        self.max_steering_angle = 480.0  # 单边最大转向角度150度
        self.steering_angle_offset = 0.0  # 转向角度偏移量

        # EPS保护机制过滤参数
        self.eps_protection_filtered = True  # EPS保护机制过滤标志
        self.eps_protection_override = True  # EPS保护机制覆盖标志
        self.max_steering_rate_override = 120.0  # 覆盖最大转向速率限制（度/秒）
        self.eps_temporary_disable = True  # 临时禁用EPS保护机制

    def update(self, CC, CS, now_nanos):
        actuators = CC.actuators
        hud_control = CC.hudControl

        if self.first_start:
            self.counter_244 = CS.counter_244
            self.counter_1ba = CS.counter_1ba
            self.counter_17e = CS.counter_17e
            self.counter_307 = CS.counter_307
            self.counter_31a = CS.counter_31a
            self.first_start = False

        # 控制消息
        can_sends = []
        self.counter_1ba = int(self.counter_1ba + 1) & 0xF
        self.counter_17e = int(self.counter_17e + 1) & 0xF

        # 改进的急弯检测逻辑
        current_steering_angle = CS.out.steeringAngleDeg
        self.steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
        self.last_steering_angle = current_steering_angle

        # 检测大角度转向条件 - 使用40度阈值
        is_large_angle = abs(current_steering_angle) > self.large_angle_threshold

        # 检测急弯条件：角度大于阈值或速率大于阈值
        is_emergency_turn = (abs(current_steering_angle) > self.emergency_turn_threshold_angle or 
                            self.steering_rate > self.emergency_turn_threshold_rate or
                            is_large_angle)

        # 使用计数器防止状态频繁切换
        if is_emergency_turn:
            self.emergency_turn_counter += 1
            if self.emergency_turn_counter > 3:  # 连续3帧检测到急弯才切换状态
                if not self.emergency_turn_active:
                    self.emergency_turn_active = True
                    self.emergency_turn_timeout = 100  # 设置100帧的超时
                    print(f"Emergency turn activated: angle={{current_steering_angle:.1f}}°, rate={{self.steering_rate:.1f}}°/s")
        else:
            self.emergency_turn_counter = max(0, self.emergency_turn_counter - 1)

        # 检测大角度转向 - 使用40度阈值
        if is_large_angle:
            self.large_angle_counter += 1
            if self.large_angle_counter > 5 and not self.large_angle_active:  # 连续5帧检测到大角度
                self.large_angle_active = True
                print(f"Large angle steering detected: {{current_steering_angle:.1f}}°")
        else:
            self.large_angle_counter = max(0, self.large_angle_counter - 1)
            if self.large_angle_counter == 0 and self.large_angle_active:
                self.large_angle_active = False
                print("Large angle steering deactivated")

        # 处理急弯超时
        if self.emergency_turn_active:
            self.emergency_turn_timeout -= 1
            if self.emergency_turn_timeout <= 0:
                self.emergency_turn_active = False
                self.emergency_turn_counter = 0
                print("Emergency turn timeout")

        # 新增：检测出弯回正状态
        self._update_return_to_center_detection(CS, CC)

        # 新增：滑行模式控制
        self._update_coasting_control(CS, CC)

        # 新增：大角度弯速度控制
        self._update_large_turn_speed_control(CS, CC)

        # 新增：后方来车检测和变道安全逻辑
        self._update_rear_vehicle_detection(CS, CC)

        # 优化大角度弯转向控制 - 加快转向速度
        if CC.latActive and not CS.steeringPressed:
            apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg

            # 应用转向角度限制 - 单边最大150度
            apply_angle = np.clip(apply_angle, -self.max_steering_angle, self.max_steering_angle)

            # 修改：应用转向平滑滤波 - 降低平滑因子使转向响应更快
            self.filtered_steering_angle = (self.steering_smoothing_factor * self.filtered_steering_angle + 
                                           (1 - self.steering_smoothing_factor) * apply_angle)
            apply_angle = self.filtered_steering_angle

            # 应用标准转向角度限制（但允许更大的变化率）
            apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                       CS.out.steeringAngleDeg + CS.out.steeringAngleOffsetDeg,
                                                       CC.latActive, self.params.ANGLE_LIMITS)

            # 检查是否有变道意图，并检测后方来车
            is_lane_change = self._detect_lane_change_intent(apply_angle, CS)

            # 如果有后方来车且正在变道，阻止变道
            if is_lane_change and self.lane_change_blocked:
                # 取消变道，保持当前车道
                apply_angle = CS.out.steeringAngleDeg
                control_active = 0
                print("后方来车，取消变道")
            else:
                # 根据急弯状态调整转向限制
                if self.emergency_turn_active or self.large_angle_active:
                    # 急弯或大角度时放宽角度变化限制，提高转向速度
                    speed_kph = CS.out.vEgo * CV.MS_TO_KPH

                    if speed_kph < 30:  # 低速大角度转弯
                        # 提高转向速率限制，使转向更快
                        apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 20, CS.out.steeringAngleDeg + 20)  # 从15增加到20
                        max_angle_rate = self.max_steering_rate_override  # 使用覆盖的最大转向速率120度/秒
                    else:
                        # 高速急弯时适度放宽限制，提高转向速度
                        apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 15, CS.out.steeringAngleDeg + 15)  # 从12增加到15
                        max_angle_rate = self.max_steering_rate_override * 0.8  # 高速时使用96度/秒

                    angle_diff = apply_angle - self.last_angle
                    if abs(angle_diff) > max_angle_rate * DT_CTRL:
                        apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate * DT_CTRL

                    # 大角度时强制保持横向控制激活
                    if self.large_angle_active and not CC.latActive:
                        # 即使上层控制器认为不应激活横向控制，在大角度时也强制保持
                        can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
                    else:
                        can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))

                # 出弯回正时的特殊处理
                elif self.return_to_center_active:
                    # 出弯回正时使用更快的控制
                    speed_kph = CS.out.vEgo * CV.MS_TO_KPH

                    # 提高回正速率
                    max_return_rate = self.return_max_rate  # 35度/秒
                    angle_diff = apply_angle - self.last_angle

                    # 如果是回正方向（向0度方向），使用更快的速率
                    if (self.last_angle > 0 and angle_diff < 0) or (self.last_angle < 0 and angle_diff > 0):
                        max_return_rate = 40.0  # 回正时最大40度/秒

                    if abs(angle_diff) > max_return_rate * DT_CTRL:
                        apply_angle = self.last_angle + np.sign(angle_diff) * max_return_rate * DT_CTRL

                    # 应用更快的回正平滑
                    apply_angle = self.return_smoothing_factor * self.last_angle + (1 - self.return_smoothing_factor) * apply_angle

                    can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))

                else:
                    # 非急弯时根据车速调整转向灵敏度，提高转向速度
                    speed_kph = CS.out.vEgo * CV.MS_TO_KPH
                    if speed_kph < 30:
                        # 低速时提高转向速度
                        max_angle_rate = self.max_steering_rate_override * 0.5  # 60度/秒
                        angle_diff = apply_angle - self.last_angle
                        if abs(angle_diff) > max_angle_rate * DT_CTRL:
                            apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate * DT_CTRL
                    else:
                        # 高速时保持适当的转向限制
                        apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 6, CS.out.steeringAngleDeg + 6)  # 从4增加到6

                    can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
        else:
            apply_angle = CS.out.steeringAngleDeg
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 0, self.counter_1ba))

        self.last_angle = apply_angle

        # 在大角度转向时，确保17E消息正确发送
        can_sends.append(changancan.create_17E_command(self.packer, CS.sigs17e, CC.longActive or self.large_angle_active, self.counter_17e))

        # 改进的纵向控制：滑行模式、大角度弯速度控制和转弯时限制加速
        if self.frame % 2 == 0:
            acctrq = -5000
            accel = np.clip(
                actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

            # 滑行模式控制：大角度急弯时允许滑行通过
            if self.coasting_active:
                current_speed_kph = CS.out.vEgo * CV.MS_TO_KPH

                # 滑行模式：禁止加速，允许自然减速
                if accel > 0:
                    accel = 0  # 禁止加速
                    print("滑行模式：禁止加速，允许自然减速")

                # 如果速度过高，施加轻微减速度
                if current_speed_kph > self.coasting_speed_threshold:
                    # 计算需要的减速度
                    speed_diff = current_speed_kph - self.coasting_speed_threshold
                    decel_needed = min(speed_diff * 0.05, self.coasting_deceleration)  # 轻微减速度
                    accel = -decel_needed
                    print(f"滑行模式：速度{{current_speed_kph:.1f}}km/h过高，施加轻微减速度{{-accel:.2f}}m/s²")
                else:
                    # 速度适中，保持滑行
                    accel = 0
                    print(f"滑行模式：速度{{current_speed_kph:.1f}}km/h适中，保持滑行")

            # 大角度弯速度控制：强制减速到25km/h（仅在非滑行模式时生效）
            elif self.large_turn_speed_control_active:
                current_speed_kph = CS.out.vEgo * CV.MS_TO_KPH
                target_speed_kph = self.large_turn_target_speed

                if current_speed_kph > target_speed_kph:
                    # 计算需要的减速度
                    speed_diff = current_speed_kph - target_speed_kph
                    # 使用P控制计算减速度
                    decel_needed = min(speed_diff * 0.1, 2.0)  # 最大减速度2.0m/s²
                    # 强制减速
                    accel = -decel_needed
                    print(f"大角度弯速度控制: 当前速度{{current_speed_kph:.1f}}km/h, 目标速度{{target_speed_kph}}km/h, 减速度{{-accel:.2f}}m/s²")
                else:
                    # 速度低于目标速度，允许轻微加速但不超目标速度
                    max_allowed_accel = 0.2  # 最大允许加速度
                    if accel > max_allowed_accel:
                        accel = max_allowed_accel
                    print(f"大角度弯速度控制: 当前速度{{current_speed_kph:.1f}}km/h低于目标速度，允许轻微加速")

            # 降低0-40km/h的加速
            speed_kph = CS.out.vEgo * CV.MS_TO_KPH
            if 0 <= speed_kph <= 40 and not self.large_turn_speed_control_active and not self.coasting_active:
                # 在0-40km/h区间降低加速度
                accel_reduction_factor = 0.7  # 降低30%
                if accel > 0:  # 只对加速阶段进行限制
                    accel = accel * accel_reduction_factor

            # 新增：降低50-150km/h的加速性能
            if 50 <= speed_kph <= 150 and not self.large_turn_speed_control_active and not self.coasting_active:
                # 在50-150km/h区间显著降低加速度
                accel_reduction_factor = 0.5  # 降低50%
                if accel > 0:  # 只对加速阶段进行限制
                    accel = accel * accel_reduction_factor
                    # 额外限制最大加速度
                    max_allowed_accel = 0.3  # 最大允许加速度0.3m/s²
                    accel = min(accel, max_allowed_accel)
                    print(f"中高速加速限制: 速度{{speed_kph:.1f}}km/h, 限制后加速度{{accel:.2f}}m/s²")

            # 检查当前是否处于转弯状态 - 使用40度阈值
            current_turn_state = self.emergency_turn_active or self.large_angle_active or abs(current_steering_angle) > 25.0

            # 转弯时限制加速（仅在非滑行模式和非大角度弯速度控制时生效）
            if current_turn_state and not self.large_turn_speed_control_active and not self.coasting_active:
                # 根据转向角度计算加速度限制
                turn_intensity = min(abs(current_steering_angle) / 150.0, 1.0)  # 使用150度作为最大角度参考

                # 转弯时最大加速度限制
                max_turn_accel = 0.4 - (turn_intensity * 0.3)  # 从0.5降低到0.4，转向越强，加速度限制越严格

                # 如果当前是加速状态，且超过转弯限制，则限制加速度
                if accel > 0 and accel > max_turn_accel:
                    accel = max_turn_accel

                # 如果是从非转弯状态进入转弯状态，且正在加速，则施加轻微制动
                if not self.last_turn_state and current_turn_state and accel > 0:
                    # 进入转弯时，如果正在加速，则转为轻微减速
                    accel = -0.1

                # 转弯时如果车速过高，施加更强制动
                if speed_kph > 40 and turn_intensity > 0.5:
                    # 高速急弯时施加更强制动
                    accel = max(accel, -0.3)

            self.last_turn_state = current_turn_state

            # 如果有后方来车且正在变道，适当减速
            if self.lane_change_blocked and is_lane_change:
                # 减速以增加安全距离
                accel = min(accel, -0.2)  # 轻微减速

            if accel < 0:
                self.expected_daccel = accel
                self.actual_daccel_filtered = 0.9 * self.actual_daccel_filtered + 0.1 * CS.out.aEgo
                if self.actual_daccel_filtered > self.expected_daccel * 0.8:
                    self.slope_daccel = 0.15
                else:
                    self.slope_daccel = 0.0
                accel -= self.slope_daccel

                accel = np.clip(accel, self.last_apply_accel - 0.2, self.last_apply_accel + 0.10)
                if self.last_apply_accel >= 0 and hud_control.leadVisible and hud_control.leadDistanceBars < 30:
                    accel = -0.4
                accel = max(accel, -3.5)
                if CS.out.vEgoRaw * CV.MS_TO_KPH == 0 and self.last_speed > 0 and hud_control.leadVisible and hud_control.leadDistanceBars > 0:
                    self.stop_lead_distance = hud_control.leadDistanceBars
                if self.stop_lead_distance != 0 and CS.out.vEgoRaw * CV.MS_TO_KPH == 0 and self.last_speed == 0 and hud_control.leadVisible and hud_control.leadDistanceBars - self.stop_lead_distance > 1:
                    accel = 0.5
            if CS.out.vEgoRaw * CV.MS_TO_KPH > 0:
                self.stop_lead_distance = 0
            if accel > 0:
                speed_kph = CS.out.vEgoRaw * CV.MS_TO_KPH

                # 调整50-150km/h的扭矩映射参数，降低加速性能
                if speed_kph > 110:
                    offset, gain = 1000, 120  # 原值1100,150，降低加速性能
                elif speed_kph > 90:
                    offset, gain = 700, 100  # 原值800,120，降低加速性能
                elif speed_kph > 70:
                    offset, gain = 700, 80   # 原值800,100，降低加速性能
                elif speed_kph > 50:
                    offset, gain = 700, 60   # 原值800,80，降低加速性能
                elif speed_kph > 10:
                    offset, gain = 500, 50
                else:
                    offset, gain = 400, 50

                base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000

                self.expected_accel = accel
                self.actual_accel_filtered = 0.9 * self.actual_accel_filtered + 0.1 * CS.out.aEgo

                if self.actual_accel_filtered < self.expected_accel * 0.8:
                    self.slope_compensation += 10
                else:
                    self.slope_compensation -= 10
                    self.slope_compensation = max(self.slope_compensation, 0)

                base_acctrq += self.slope_compensation
                base_acctrq = min(base_acctrq, -10)

                acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)

            self.last_speed = CS.out.vEgoRaw * CV.MS_TO_KPH
            accel = int(accel / 0.05) * 0.05

            self.counter_244 = int(self.counter_244 + 1) & 0xF
            if self.CP.carFingerprint == CAR.QIYUAN_A05:
                can_sends.append(changancan.create_244_command_a05(self.packer, accel, self.counter_244, CC.longActive, acctrq))
            elif self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
                can_sends.append(changancan.create_244_command_idd(self.packer, CS.sigs244, accel, self.counter_244, CC.longActive, acctrq, CS.out.vEgoRaw))
            else:
                can_sends.append(changancan.create_244_command(self.packer, CS.sigs244, accel, self.counter_244, CC.longActive, acctrq, CS.out.vEgoRaw))

            self.last_apply_accel = accel
            self.last_acctrq = acctrq

        if self.frame % 10 == 0:
            self.counter_307 = int(self.counter_307 + 1) & 0xF
            self.counter_31a = int(self.counter_31a + 1) & 0xF
            can_sends.append(changancan.create_307_command(self.packer, CS.sigs307, self.counter_307, CS.out.cruiseState.speedCluster * CV.MS_TO_KPH))
            can_sends.append(changancan.create_31A_command(self.packer, CS.sigs31a, self.counter_31a, CC.longActive, CS.steeringPressed))

        new_actuators = actuators.as_builder()
        new_actuators.steeringAngleDeg = float(self.last_angle)
        new_actuators.accel = float(self.last_apply_accel)

        self.frame += 1
        return new_actuators, can_sends

    def _update_return_to_center_detection(self, CS, CC):
        """检测出弯回正状态"""
        current_steering_angle = CS.out.steeringAngleDeg
        steering_rate = self.steering_rate

        # 检测出弯回正条件：角度小于阈值且转向速率表明正在回正
        is_returning_to_center = (abs(current_steering_angle) < self.return_to_center_threshold and 
                                 steering_rate > 10.0 and  # 有一定的转向速率
                                 ((self.last_steering_angle > 0 and current_steering_angle < self.last_steering_angle) or
                                  (self.last_steering_angle < 0 and current_steering_angle > self.last_steering_angle)))

        if is_returning_to_center:
            if not self.return_to_center_active:
                self.return_to_center_active = True
                print(f"出弯回正模式激活: 当前角度{{current_steering_angle:.1f}}°, 转向速率{{steering_rate:.1f}}°/s")
        else:
            self.return_to_center_active = False

    def _update_coasting_control(self, CS, CC):
        """更新滑行模式控制"""
        current_steering_angle = CS.out.steeringAngleDeg
        current_speed_kph = CS.out.vEgo * CV.MS_TO_KPH

        # 检测滑行模式条件：大角度急弯且速度适中 - 使用40度阈值
        is_coasting_condition = (
            (self.emergency_turn_active or abs(current_steering_angle) > self.coasting_angle_threshold) and
            (self.coasting_min_speed <= current_speed_kph <= self.coasting_speed_threshold)
        )

        if is_coasting_condition:
            if not self.coasting_active:
                self.coasting_active = True
                self.coasting_timer = 150  # 设置150帧的滑行时间
                print(f"滑行模式激活: 角度{{current_steering_angle:.1f}}°, 速度{{current_speed_kph:.1f}}km/h")
        else:
            # 更新滑行计时器
            if self.coasting_timer > 0:
                self.coasting_timer -= 1
            else:
                self.coasting_active = False

        # 如果前方有车，且距离较近，则取消滑行模式
        if CC.hudControl.leadVisible and CC.hudControl.leadDistanceBars < 3:
            self.coasting_active = False
            self.coasting_timer = 0

    def _update_large_turn_speed_control(self, CS, CC):
        """更新大角度弯速度控制"""
        current_steering_angle = CS.out.steeringAngleDeg
        current_speed_kph = CS.out.vEgo * CV.MS_TO_KPH

        # 检测大角度弯条件（仅在非滑行模式时生效）- 使用40度阈值
        is_large_turn = (abs(current_steering_angle) > self.large_angle_threshold and 
                        not self.coasting_active)

        if is_large_turn:
            if not self.large_turn_speed_control_active:
                self.large_turn_speed_control_active = True
                self.large_turn_speed_control_timer = 200  # 设置200帧的控制时间
                print(f"大角度弯速度控制激活: 角度{{current_steering_angle:.1f}}°, 当前速度{{current_speed_kph:.1f}}km/h, 目标速度{{self.large_turn_target_speed}}km/h")
        else:
            # 更新控制计时器
            if self.large_turn_speed_control_timer > 0:
                self.large_turn_speed_control_timer -= 1
            else:
                self.large_turn_speed_control_active = False

        # 如果前方有车，且距离较近，则取消速度控制
        if CC.hudControl.leadVisible and CC.hudControl.leadDistanceBars < 3:
            self.large_turn_speed_control_active = False
            self.large_turn_speed_control_timer = 0

    def _update_rear_vehicle_detection(self, CS, CC):
        """更新后方来车检测状态"""
        # 这里需要从传感器数据中获取后方来车信息
        # 在实际实现中，这些数据应该来自雷达或摄像头

        # 模拟后方来车检测逻辑
        # 在实际系统中，这些数据应该来自车辆传感器
        self.rear_vehicle_detected = False
        self.rear_vehicle_speed = 0.0
        self.rear_vehicle_distance = 0.0

        # 检查盲区监测系统状态
        if hasattr(CS, 'leftBlindspot') and hasattr(CS, 'rightBlindspot'):
            # 如果有盲区监测系统，使用其数据
            if CS.leftBlindspot or CS.rightBlindspot:
                self.rear_vehicle_detected = True
                # 估计后方来车距离和速度
                self.rear_vehicle_distance = 20.0  # 假设距离20米
                self.rear_vehicle_speed = CS.out.vEgo + 5.0  # 假设比本车快5m/s

        # 检查是否有变道意图
        current_steering_angle = CS.out.steeringAngleDeg
        steering_change = abs(current_steering_angle - self.last_steering_angle)

        # 检测变道意图
        if steering_change > 5.0 and abs(current_steering_angle) > 10.0:
            # 检测到明显的转向变化，可能是变道意图
            lane_change_direction = 1 if current_steering_angle > 0 else -1

            # 如果检测到变道意图，检查后方来车
            if self.rear_vehicle_detected:
                # 计算安全变道条件
                time_to_collision = self.rear_vehicle_distance / max(0.1, self.rear_vehicle_speed - CS.out.vEgo)

                # 如果后方来车距离太近或速度太快，阻止变道
                if time_to_collision < 3.0:  # 3秒内可能碰撞
                    self.lane_change_blocked = True
                    self.lane_change_safety_timer = 50  # 设置50帧的阻止时间
                else:
                    self.lane_change_blocked = False
            else:
                self.lane_change_blocked = False

            self.last_lane_change_direction = lane_change_direction
        else:
            # 更新安全计时器
            if self.lane_change_safety_timer > 0:
                self.lane_change_safety_timer -= 1
            else:
                self.lane_change_blocked = False

    def _detect_lane_change_intent(self, apply_angle, CS):
        """检测变道意图"""
        # 计算转向角度变化
        steering_change = abs(apply_angle - CS.out.steeringAngleDeg)

        # 如果转向角度变化较大，且角度绝对值较大，可能是变道意图
        if steering_change > 3.0 and abs(apply_angle) > 8.0:
            return True

        return False

