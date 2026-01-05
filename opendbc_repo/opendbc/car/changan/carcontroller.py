
from opendbc.car import structs, apply_std_steer_angle_limits
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, DT_CTRL
import numpy as np

class CarController(CarControllerBase):
    def __init__(self, dbc_names, CP):
        super().__init__(dbc_names, CP)
        self.params = CarControllerParams(self.CP)
        self.packer = CANPacker(dbc_names[Bus.pt])
        self.counter_1ba = 0
        self.counter_244 = 0
        self.counter_307 = 0
        self.counter_31a = 0
        self.frame = 0
        self.last_angle = 0
        self.last_acctrq = -5000
        self.first_start = True

        # 转向平滑控制参数
        self.steering_smoothing_factor = 0.3
        self.filtered_steering_angle = 0.0
        self.max_steering_angle = 480.0

        # 紧急转向和弯道控制逻辑
        self.emergency_turn_counter = 0
        self.is_emergency_turning = False
        self.emergency_turn_timer = 0

    def update(self, CC, CS, now_nanos):
        actuators = CC.actuators

        if self.first_start:
            if hasattr(CS, 'counter_244'):
                self.counter_244 = CS.counter_244
                self.counter_1ba = CS.counter_1ba
                self.counter_307 = CS.counter_307
                self.counter_31a = CS.counter_31a
                self.first_start = False

        # 紧急转向检测逻辑
        if abs(CS.out.steeringAngleDeg) > 100:
            self.emergency_turn_counter += 1
        else:
            self.emergency_turn_counter = 0

        if self.emergency_turn_counter > 3 or self.is_emergency_turning:
            self.is_emergency_turning = True
            # 100帧后自动退出紧急转向状态
            self.emergency_turn_timer += 1
            if self.emergency_turn_timer > 100 and abs(CS.out.steeringAngleDeg) < 30:
                self.is_emergency_turning = False
                self.emergency_turn_timer = 0

        can_sends = []

        # 转向控制
        if CC.latActive:
            apply_angle = actuators.steeringAngleDeg

            # 应用转向角度限制
            apply_angle = np.clip(apply_angle, -self.max_steering_angle, self.max_steering_angle)

            # 应用转向平滑滤波
            smoothing = 0.5 if self.is_emergency_turning else self.steering_smoothing_factor
            self.filtered_steering_angle = (smoothing * self.filtered_steering_angle +
                                           (1 - smoothing) * apply_angle)
            apply_angle = self.filtered_steering_angle

            # 应用标准转向角度限制
            apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                       CS.out.steeringAngleDeg,
                                                       CC.latActive, self.params.ANGLE_LIMITS)

            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
        else:
            apply_angle = CS.out.steeringAngleDeg
            self.filtered_steering_angle = apply_angle
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 0, self.counter_1ba))

        self.last_angle = apply_angle

        # 纵向控制
        if CC.longActive:
            accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

            # 紧急转向时限制加速度
            if self.is_emergency_turning:
                accel = min(accel, 0.5)

            # 弯道限速逻辑
            if abs(CS.out.steeringAngleDeg) > 150:
                max_speed_limit = 40 / 3.6
                if CS.out.vEgo > max_speed_limit:
                    accel = min(accel, -0.5)

            # 低速起步平滑处理
            if CS.out.vEgo < 40 / 3.6:
                accel *= 0.7

            # 加速度请求扭矩计算 (acctrq) - 关键防退出逻辑
            speed_kph = CS.out.vEgoRaw * 3.6
            if speed_kph > 10:
                offset, gain = 500, 50
            else:
                offset, gain = 400, 50

            base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000
            acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)
            self.last_acctrq = acctrq

            can_sends.append(changancan.create_244_command(self.packer, CS.sigs244, accel, self.counter_244, True, acctrq))

        # 状态消息发送 (10Hz)
        if self.frame % 10 == 0:
            can_sends.append(changancan.create_307_command(self.packer, CS.sigs307, self.counter_307, CS.out.cruiseState.speedCluster))
            can_sends.append(changancan.create_31A_command(self.packer, CS.sigs31a, self.counter_31a, CC.longActive, CS.out.steeringPressed))
            self.counter_307 = (self.counter_307 + 1) % 16
            self.counter_31a = (self.counter_31a + 1) % 16

        # 17E 消息发送 (100Hz)
        can_sends.append(changancan.create_17E_command(self.packer, CS.sigs17e, CC.latActive, self.frame % 16))

        self.counter_1ba = (self.counter_1ba + 1) % 16
        self.counter_244 = (self.counter_244 + 1) % 16
        self.frame += 1
        return CC.actuators.as_builder(), can_sends



















