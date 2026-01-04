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

        # 改进的急弯检测相关参数
        self.emergency_turn_threshold_angle = 45.0  # 急弯角度阈值（度）
        self.emergency_turn_threshold_rate = 60.0   # 急弯转向速率阈值（度/秒）
        self.emergency_turn_active = False          # 急弯激活标志
        self.last_steering_angle = 0.0              # 上一次转向角度
        self.steering_rate = 0.0                    # 转向速率
        self.emergency_turn_counter = 0              # 急弯计数器，防止频繁切换
        self.emergency_turn_timeout = 0             # 急弯超时计数器
        
        # 大角度转向控制参数
        self.large_angle_active = False
        self.large_angle_threshold = 100.0  # 大角度阈值（度）
        self.large_angle_counter = 0
        
        # 转弯时纵向控制限制参数
        self.turn_speed_limit = 0.0  # 转弯时的速度限制
        self.turn_accel_limit = 0.0  # 转弯时的加速度限制
        self.last_turn_state = False  # 上一次的转弯状态
        
        # 新增：直角弯速度控制参数
        self.sharp_turn_speed_limit = 25.0  # 直角弯速度限制（km/h）
        self.sharp_turn_angle_threshold = 70.0  # 直角弯角度阈值（度）

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
        
        # 检测大角度转向条件
        is_large_angle = abs(current_steering_angle) > self.large_angle_threshold
        
        # 检测直角弯条件（角度大于阈值）
        is_sharp_turn = abs(current_steering_angle) > self.sharp_turn_angle_threshold
        
        # 检测急弯条件：角度大于阈值或速率大于阈值
        is_emergency_turn = (abs(current_steering_angle) > self.emergency_turn_threshold_angle or 
                            self.steering_rate > self.emergency_turn_threshold_rate or
                            is_large_angle or is_sharp_turn)
        
        # 使用计数器防止状态频繁切换
        if is_emergency_turn:
            self.emergency_turn_counter += 1
            if self.emergency_turn_counter > 3:  # 连续3帧检测到急弯才切换状态
                if not self.emergency_turn_active:
                    self.emergency_turn_active = True
                    self.emergency_turn_timeout = 100  # 设置100帧的超时
                    print(f"Emergency turn activated: angle={current_steering_angle:.1f}°, rate={self.steering_rate:.1f}°/s")
        else:
            self.emergency_turn_counter = max(0, self.emergency_turn_counter - 1)
        
        # 检测大角度转向
        if is_large_angle:
            self.large_angle_counter += 1
            if self.large_angle_counter > 5 and not self.large_angle_active:  # 连续5帧检测到大角度
                self.large_angle_active = True
                print(f"Large angle steering detected: {current_steering_angle:.1f}°")
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
        
        # 优化大角度弯转向控制
        if CC.latActive and not CS.steeringPressed:
            apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg
            
            # 应用标准转向角度限制
            apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                       CS.out.steeringAngleDeg + CS.out.steeringAngleOffsetDeg,
                                                       CC.latActive, self.params.ANGLE_LIMITS)
            
            # 根据急弯状态调整转向限制
            if self.emergency_turn_active or self.large_angle_active or is_sharp_turn:
                # 急弯、大角度或直角弯时放宽角度变化限制
                speed_kph = CS.out.vEgo * CV.MS_TO_KPH
                
                if speed_kph < 30:  # 低速大角度转弯
                    # 低速大角度时进一步放宽限制
                    apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 25, CS.out.steeringAngleDeg + 25)
                    # 提高转向速率限制
                    max_angle_rate = 150.0
                else:
                    # 高速急弯时适度放宽限制
                    apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 20, CS.out.steeringAngleDeg + 20)
                    max_angle_rate = 120.0
                
                angle_diff = apply_angle - self.last_angle
                if abs(angle_diff) > max_angle_rate:
                    apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate
                    
                # 大角度时强制保持横向控制激活
                if (self.large_angle_active or is_sharp_turn) and not CC.latActive:
                    # 即使上层控制器认为不应激活横向控制，在大角度或直角弯时也强制保持
                    can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
                else:
                    can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
            else:
                # 非急弯时根据车速调整转向灵敏度
                speed_kph = CS.out.vEgo * CV.MS_TO_KPH
                if speed_kph < 30:
                    # 低速时降低转向速度，防止过快转向
                    max_angle_rate = 60.0  # 降低最大转向速率
                    angle_diff = apply_angle - self.last_angle
                    if abs(angle_diff) > max_angle_rate:
                        apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate
                else:
                    # 高速时保持正常转向限制
                    apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 7, CS.out.steeringAngleDeg + 7)
                
                can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
        else:
            apply_angle = CS.out.steeringAngleDeg
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 0, self.counter_1ba))
        
        self.last_angle = apply_angle
        
        # 在大角度转向时，确保17E消息正确发送
        can_sends.append(changancan.create_17E_command(self.packer, CS.sigs17e, CC.longActive or self.large_angle_active or is_sharp_turn, self.counter_17e))

        # 改进的纵向控制：转弯时限制加速，并降低0-40km/h的加速
        if self.frame % 2 == 0:
            acctrq = -5000
            accel = np.clip(
                actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)
            
            # 获取当前速度
            speed_kph = CS.out.vEgo * CV.MS_TO_KPH
            
            # 降低0-40km/h的加速
            if 0 <= speed_kph <= 40:
                # 在0-40km/h区间降低加速度
                accel_reduction_factor = 0.7  # 降低30%
                if accel > 0:  # 只对加速阶段进行限制
                    accel = accel * accel_reduction_factor
                    print(f"低速加速限制: 速度{speed_kph:.1f}km/h, 加速度从{actuators.accel:.2f}降低到{accel:.2f}")
            
            # 检查当前是否处于转弯状态
            current_turn_state = self.emergency_turn_active or self.large_angle_active or abs(current_steering_angle) > 30.0
            
            # 直角弯速度控制
            if is_sharp_turn:
                # 直角弯时限制车速不超过25km/h
                if speed_kph > self.sharp_turn_speed_limit:
                    # 如果车速超过25km/h，强制减速
                    accel = -0.4  # 较强的减速度
                    print(f"直角弯车速控制: 当前速度{speed_kph:.1f}km/h超过限制{self.sharp_turn_speed_limit}km/h，强制减速")
                else:
                    # 如果车速低于25km/h，限制加速度防止过快加速
                    max_sharp_turn_accel = 0.2  # 直角弯时最大加速度
                    if accel > max_sharp_turn_accel:
                        accel = max_sharp_turn_accel
                        print(f"直角弯加速度限制: 限制加速度为{max_sharp_turn_accel:.2f}m/s²")
            
            # 转弯时限制加速
            if current_turn_state:
                # 根据转向角度计算加速度限制
                turn_intensity = min(abs(current_steering_angle) / 150.0, 1.0)  # 0-1之间的转向强度
                
                # 转弯时最大加速度限制
                max_turn_accel = 0.4 - (turn_intensity * 0.3)  # 转向越强，加速度限制越严格
                
                # 如果当前是加速状态，且超过转弯限制，则限制加速度
                if accel > 0 and accel > max_turn_accel:
                    accel = max_turn_accel
                    print(f"Turn acceleration limited: {accel:.2f} m/s² (turn intensity: {turn_intensity:.2f})")
                
                # 如果是从非转弯状态进入转弯状态，且正在加速，则施加轻微制动
                if not self.last_turn_state and current_turn_state and accel > 0:
                    # 进入转弯时，如果正在加速，则转为轻微减速
                    accel = -0.1
                    print("Entering turn - applying mild deceleration")
                
                # 转弯时如果车速过高，施加更强制动
                if speed_kph > 40 and turn_intensity > 0.5:
                    # 高速急弯时施加更强制动
                    accel = max(accel, -0.3)
                    print(f"High speed turn - applying stronger deceleration: {accel:.2f} m/s²")
            
            self.last_turn_state = current_turn_state
            
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

                if speed_kph > 110:
                    offset, gain = 1100, 150
                elif speed_kph > 90:
                    offset, gain = 800, 120
                elif speed_kph > 70:
                    offset, gain = 800, 100
                elif speed_kph > 50:
                    offset, gain = 800, 80
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