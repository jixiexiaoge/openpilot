
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
        self.first_start = True

        # 转向平滑控制参数
        self.steering_smoothing_factor = 0.3
        self.filtered_steering_angle = 0.0
        self.max_steering_angle = 480.0

    def update(self, CC, CS, now_nanos):
        actuators = CC.actuators

        if self.first_start:
            self.counter_244 = CS.counter_244
            self.counter_1ba = CS.counter_1ba
            self.counter_307 = CS.counter_307
            self.counter_31a = CS.counter_31a
            self.first_start = False

        can_sends = []

        # 转向控制
        if CC.latActive:
            apply_angle = actuators.steeringAngleDeg

            # 应用转向角度限制
            apply_angle = np.clip(apply_angle, -self.max_steering_angle, self.max_steering_angle)

            # 应用转向平滑滤波
            self.filtered_steering_angle = (self.steering_smoothing_factor * self.filtered_steering_angle +
                                           (1 - self.steering_smoothing_factor) * apply_angle)
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
            can_sends.append(changancan.create_244_command(self.packer, CS.sigs244, accel, self.counter_244, True, 0, CS.out.vEgoRaw))

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



















