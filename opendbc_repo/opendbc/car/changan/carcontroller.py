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

    self.steering_smoothing_factor = self.params.STEERING_SMOOTHING_FACTOR
    self.filtered_steering_angle = 0.0
    self.max_steering_angle = self.params.MAX_STEERING_ANGLE

    self.emergency_turn_active = False
    self.emergency_turn_counter = 0
    self.emergency_turn_timeout = 0
    self.last_steering_angle = 0

    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators

    if self.first_start:
      if "GW_244" in CS.sigs:
        self.counter_244 = CS.counter_244
        self.counter_1ba = CS.counter_1ba
        self.counter_17e = CS.counter_17e
        self.counter_307 = CS.counter_307
        self.counter_31a = CS.counter_31a
        self.first_start = False

    # Advanced Emergency/Large Turn Logic
    current_steering_angle = CS.out.steeringAngleDeg
    steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
    self.last_steering_angle = current_steering_angle

    is_emergency_turn = (abs(current_steering_angle) > 35.0 or steering_rate > 60.0)
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

    # Increment counters manually as per reference for reliable control
    self.counter_1ba = (self.counter_1ba + 1) & 0xF
    self.counter_17e = (self.counter_17e + 1) & 0xF

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

      # From reference 1interface.py: apply steering angle protection logic near 480 deg limit
      max_change = 5 if abs(CS.out.steeringAngleDeg) > 450 else 15
      angle_diff = apply_angle - self.last_angle
      if abs(angle_diff) > max_change:
        apply_angle = self.last_angle + max_change * (1 if angle_diff > 0 else -1)
      apply_angle = np.clip(apply_angle, -480, 480)

      # Rate limits for emergency turning
      if self.emergency_turn_active:
        max_angle_rate = 80.0 if CS.out.vEgo * CV.MS_TO_KPH < 30 else 65.0
        angle_diff = apply_angle - self.last_angle
        if abs(angle_diff) > max_angle_rate * DT_CTRL:
           apply_angle = self.last_angle + np.sign(angle_diff) * max_angle_rate * DT_CTRL

      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 1, self.counter_1ba))
    else:
      apply_angle = CS.out.steeringAngleDeg
      self.filtered_steering_angle = apply_angle
      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 0, self.counter_1ba))

    self.last_angle = apply_angle

    # EPS Control (100Hz)
    can_sends.append(changancan.create_eps_control(self.packer, CS.sigs["GW_17E"], CC.longActive or self.emergency_turn_active, self.counter_17e))

    # Longitudinal Control
    if self.frame % 2 == 0:
      self.counter_244 = (self.counter_244 + 1) & 0xF
      acctrq = -5000
      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

      # Acceleration mapping - aligning with reference
      speed_kph = CS.out.vEgoRaw * 3.6
      if speed_kph > 110: offset, gain = 1000, 120
      elif speed_kph > 90: offset, gain = 700, 100
      elif speed_kph > 70: offset, gain = 700, 80
      elif speed_kph > 50: offset, gain = 700, 60
      elif speed_kph > 10: offset, gain = 500, 50
      else: offset, gain = 400, 50

      if accel > 0:
        base_acctrq = (offset + int(abs(accel) / 0.05) * gain) - 5000
        acctrq = np.clip(base_acctrq, self.last_acctrq - 300, self.last_acctrq + 100)

      self.last_acctrq = acctrq
      can_sends.append(changancan.create_acc_control(self.packer, CS.sigs["GW_244"], accel, self.counter_244, CC.longActive, acctrq))

    # HUD & Set Speed (10Hz)
    if self.frame % 10 == 0:
      self.counter_307 = (self.counter_307 + 1) & 0xF
      self.counter_31a = (self.counter_31a + 1) & 0xF
      cruise_speed_kph = CS.out.cruiseState.speed * CV.MS_TO_KPH
      can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs["GW_307"], self.counter_307, cruise_speed_kph))
      can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs["GW_31A"], self.counter_31a, CC.longActive, CS.out.steeringPressed))

    self.frame += 1
    return actuators.as_builder(), can_sends
