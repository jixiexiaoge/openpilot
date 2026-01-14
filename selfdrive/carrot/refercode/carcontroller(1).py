from opendbc.car import apply_std_steer_angle_limits, Bus, structs
import numpy as np
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams, CAR
from opendbc.can.packer import CANPacker
from openpilot.common.conversions import Conversions as CV

SteerControlType = structs.CarParams.SteerControlType
VisualAlert = structs.CarControl.HUDControl.VisualAlert

class CarController(CarControllerBase):
    def __init__(self, dbc_names, CP):
        super().__init__(dbc_names, CP)
        self.params = CarControllerParams(self.CP)
        self.last_angle = 0
        self.alert_active = False
        self.last_standstill = False
        self.standstill_req = False
        self.counter_244 = 0
        self.counter_1ba = 0
        self.counter_17e = 0
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
        self.slope_compensation = 0.0      # 动态补偿值

        self.expected_daccel = 0.0
        self.actual_daccel_filtered = 0.0  # 滤波后的实际减速度
        self.slope_daccel = 0.0      # 动态补偿值

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

        # *** control msgs ***
        can_sends = []
        self.counter_1ba = int(self.counter_1ba + 1) & 0xF
        self.counter_17e = int(self.counter_17e + 1) & 0xF
        if CC.latActive and not CS.steeringPressed:
            # EPS uses the torque sensor angle to control with, offset to compensate
            apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg
            # Angular rate limit based on speed
            apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                       CS.out.steeringAngleDeg + CS.out.steeringAngleOffsetDeg,
                                                       CC.latActive, self.params.ANGLE_LIMITS)
            # 修改点1：放宽转向角度变化限制，从±7度改为±30度
            apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 30, CS.out.steeringAngleDeg + 30)
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
        else:
            apply_angle = CS.out.steeringAngleDeg
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 0, self.counter_1ba))
        self.last_angle = apply_angle
        can_sends.append(changancan.create_17E_command(self.packer, CS.sigs17e, CC.longActive, self.counter_17e))

        # we can spam can to cancel the system even if we are using lat only control
        if self.frame % 2 == 0:
            acctrq = -5000
            # *** gas and brake ***
            accel = np.clip(
                actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)
            if accel < 0:
                self.expected_daccel = accel
                self.actual_daccel_filtered = 0.9 * self.actual_daccel_filtered + 0.1 * CS.out.aEgo
                if self.actual_daccel_filtered > self.expected_daccel * 0.8:  # 阈值可调
                    self.slope_daccel = 0.15
                else:
                    self.slope_daccel = 0.0
                accel -= self.slope_daccel

                accel = np.clip(accel, self.last_apply_accel - 0.2, self.last_apply_accel + 0.10) # 限制单次减速度变化
                if self.last_apply_accel >= 0 and hud_control.leadVisible and hud_control.leadDistanceBars < 30:
                    accel = -0.4
                accel = max(accel, -3.5)
                # if CS.out.vEgoRaw * CV.MS_TO_KPH == 0:
                #     accel = -0.05
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
                else:  # 0 <= speed_kph <= 10
                    offset, gain = 400, 50

                # 计算基础加速请求力矩（经验公式）
                base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000

                # 2. 动态坡度补偿（无坡度传感器时）
                self.expected_accel = accel  # 假设期望加速度=油门开度（需校准）
                self.actual_accel_filtered = 0.9 * self.actual_accel_filtered + 0.1 * CS.out.aEgo  # 低通滤波

                # 如果实际加速度持续低于预期，增加补偿
                if self.actual_accel_filtered < self.expected_accel * 0.8:  # 阈值可调
                    self.slope_compensation += 10  # 逐步增加补偿
                else:
                    self.slope_compensation -= 10  # 衰减补偿
                    self.slope_compensation = max(self.slope_compensation, 0)

                base_acctrq += self.slope_compensation
                base_acctrq = min(base_acctrq, -10)

                # 3. 限制扭矩变化
                acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)

            self.last_speed = CS.out.vEgoRaw * CV.MS_TO_KPH
            accel = int(accel / 0.05) * 0.05
            # 修改点2：添加调试信息，监控转向角度
            print(f"转向角度 - 期望: {actuators.steeringAngleDeg:.1f}°, 实际命令: {apply_angle:.1f}°, 当前: {CS.out.steeringAngleDeg:.1f}°")
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