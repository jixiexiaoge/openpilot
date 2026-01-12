import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_std_steer_angle_limits
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams

class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.params = CarControllerParams(self.CP)
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.frame = 0
    self.last_angle = 0
    self.last_acctrq = -5000
    self.first_start = True

    self.steering_smoothing_factor = 0.3
    self.filtered_steering_angle = 0.0
    self.max_steering_angle = 480.0

    self.is_emergency_turning = False
    self.emergency_turn_timer = 0
    self.emergency_turn_counter = 0

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators

    if self.first_start:
      if "GW_244" in CS.sigs:
        self.first_start = False

    # Emergency turn detection logic
    if abs(CS.out.steeringAngleDeg) > 100:
      self.emergency_turn_counter += 1
    else:
      self.emergency_turn_counter = 0

    if self.emergency_turn_counter > 3 or self.is_emergency_turning:
      self.is_emergency_turning = True
      self.emergency_turn_timer += 1
      if self.emergency_turn_timer > 100 and abs(CS.out.steeringAngleDeg) < 30:
        self.is_emergency_turning = False
        self.emergency_turn_timer = 0

    can_sends = []

    # Steering Control
    if CC.latActive:
      apply_angle = actuators.steeringAngleDeg
      apply_angle = np.clip(apply_angle, -self.max_steering_angle, self.max_steering_angle)

      # Smoothing
      smoothing = 0.5 if self.is_emergency_turning else self.steering_smoothing_factor
      self.filtered_steering_angle = (smoothing * self.filtered_steering_angle +
                                     (1 - smoothing) * apply_angle)
      apply_angle = self.filtered_steering_angle

      # Apply standards limits
      apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                 CS.out.steeringAngleDeg,
                                                 CC.latActive, self.params.ANGLE_LIMITS)

      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 1, (self.frame // 1) % 16))
    else:
      apply_angle = CS.out.steeringAngleDeg
      self.filtered_steering_angle = apply_angle
      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 0, (self.frame // 1) % 16))

    self.last_angle = apply_angle

    # Longitudinal Control
    if CC.longActive:
      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

      if self.is_emergency_turning:
        accel = min(accel, 0.5)

      # Curve slow down
      if abs(CS.out.steeringAngleDeg) > 150:
        max_speed_limit = 40 / 3.6
        if CS.out.vEgo > max_speed_limit:
          accel = min(accel, -0.5)

      # Low speed smoothing
      if CS.out.vEgo < 40 / 3.6:
        accel *= 0.7

      # ACCTRQ calculation (Critical for Changan)
      speed_kph = CS.out.vEgoRaw * 3.6
      offset, gain = (500, 50) if speed_kph > 10 else (400, 50)
      base_acctrq = (offset + int(abs(accel) / 0.02) * gain) - 5000
      acctrq = np.clip(base_acctrq, self.last_acctrq - 200, self.last_acctrq + 50)
      self.last_acctrq = acctrq

      can_sends.append(changancan.create_acc_control(self.packer, CS.sigs["GW_244"], accel, (self.frame // 1) % 16, True, acctrq))

    # HUD & State (10Hz)
    if self.frame % 10 == 0:
      can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs["GW_307"], (self.frame // 10) % 16, CS.out.cruiseState.speedCluster))
      can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs["GW_31A"], (self.frame // 10) % 16, CC.longActive, CS.out.steeringPressed))

    # EPS Control (100Hz)
    can_sends.append(changancan.create_eps_control(self.packer, CS.sigs["GW_17E"], CC.latActive, self.frame % 16))

    self.frame += 1
    return CC.actuators.as_builder(), can_sends
