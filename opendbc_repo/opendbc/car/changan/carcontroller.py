import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_std_steer_angle_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.car.changan.values import CarControllerParams
from openpilot.common.realtime import DT_CTRL
from openpilot.common.conversions import Conversions as CV

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
    self.max_steering_angle = 130.0 # From reference

    self.emergency_turn_active = False
    self.emergency_turn_counter = 0
    self.emergency_turn_timeout = 0
    self.last_steering_angle = 0

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators

    if self.first_start:
      if "GW_244" in CS.sigs:
        self.first_start = False

    # Advanced Emergency/Large Turn Logic (From reference)
    current_steering_angle = CS.out.steeringAngleDeg
    steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
    self.last_steering_angle = current_steering_angle

    is_emergency_turn = (abs(current_steering_angle) > 35.0 or steering_rate > 60.0 or abs(current_steering_angle) > 40.0)
    if is_emergency_turn:
      self.emergency_turn_counter += 1
      if self.emergency_turn_counter > 3:
        self.emergency_turn_active = True
        self.emergency_turn_timeout = 100
    else:
      self.emergency_turn_counter = max(0, self.emergency_turn_counter - 1)

    if self.emergency_turn_active:
      self.emergency_turn_timeout -= 1
      if self.emergency_turn_timeout <= 0:
        self.emergency_turn_active = False

    can_sends = []

    # Steering Control
    if CC.latActive and not CS.steeringPressed:
      apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg
      apply_angle = np.clip(apply_angle, -self.max_steering_angle, self.max_steering_angle)

      # Smoothing
      self.filtered_steering_angle = (self.steering_smoothing_factor * self.filtered_steering_angle +
                                     (1 - self.steering_smoothing_factor) * apply_angle)
      apply_angle = self.filtered_steering_angle

      # Apply standard limits
      apply_angle = apply_std_steer_angle_limits(apply_angle, self.last_angle, CS.out.vEgoRaw,
                                                 CS.out.steeringAngleDeg + CS.out.steeringAngleOffsetDeg,
                                                 CC.latActive, self.params.ANGLE_LIMITS)

      # Rate limits for emergency turning
      if self.emergency_turn_active:
        max_angle_rate = 80.0 if CS.out.vEgo * CV.MS_TO_KPH < 30 else 65.0
        angle_diff = apply_angle - self.last_angle
        if abs(angle_diff) > max_angle_rate * DT_CTRL:
           apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate * DT_CTRL

      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 1, CS.counter_1ba))
    else:
      apply_angle = CS.out.steeringAngleDeg
      self.filtered_steering_angle = apply_angle
      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 0, CS.counter_1ba))

    self.last_angle = apply_angle

    # EPS Control (100Hz) - From reference 17E use PT counter
    can_sends.append(changancan.create_eps_control(self.packer, CS.sigs["GW_17E"], CC.longActive or self.emergency_turn_active, CS.counter_17e))

    # Longitudinal Control
    if self.frame % 2 == 0:
      acctrq = -5000
      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

      # Acceleration mapping from reference
      speed_kph = CS.out.vEgoRaw * 3.6
      if speed_kph > 110: offset, gain = 1000, 120
      elif speed_kph > 90: offset, gain = 700, 100
      elif speed_kph > 70: offset, gain = 700, 80
      elif speed_kph > 50: offset, gain = 700, 60
      else: offset, gain = 500, 50

      if accel > 0:
        base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000
        acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)

      self.last_acctrq = acctrq
      can_sends.append(changancan.create_acc_control(self.packer, CS.sigs["GW_244"], accel, CS.counter_244, CC.longActive, acctrq))

    # HUD & Set Speed (10Hz)
    if self.frame % 10 == 0:
      # Use speed in KPH for HUD
      cruise_speed_kph = CS.out.cruiseState.speed * CV.MS_TO_KPH
      can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs["GW_307"], CS.counter_307, cruise_speed_kph))
      can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs["GW_31A"], CS.counter_31a, CC.longActive, CS.out.steeringPressed))

    self.frame += 1
    return actuators.as_builder(), can_sends
