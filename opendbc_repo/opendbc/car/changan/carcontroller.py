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

    self.counter_307 = 0
    self.counter_31a = 0
    self.counter_187 = 0
    self.counter_196 = 0

    self.last_apply_accel = 0.0
    self.stop_lead_distance = 0.0
    self.last_speed = 0.0

    self.expected_accel = 0.0
    self.actual_accel_filtered = 0.0
    self.slope_compensation = 0.0

    self.expected_daccel = 0.0
    self.actual_daccel_filtered = 0.0
    self.slope_daccel = 0.0

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators

    if self.first_start:
      if "GW_244" in CS.sigs:
        self.counter_244 = int(CS.counter_244) & 0xF
        self.counter_1ba = int(CS.counter_1ba) & 0xF
        self.counter_17e = int(CS.counter_17e) & 0xF
        self.counter_307 = int(CS.counter_307) & 0xF
        self.counter_31a = int(CS.counter_31a) & 0xF
        if "GW_187" in CS.sigs:
          self.counter_187 = int(CS.counter_187) & 0xF
        if "GW_196" in CS.sigs:
          self.counter_196 = int(CS.counter_196) & 0xF

        self.last_angle = CS.out.steeringAngleDeg
        self.filtered_steering_angle = CS.out.steeringAngleDeg
        self.first_start = False

    current_steering_angle = CS.out.steeringAngleDeg
    steering_rate = abs(current_steering_angle - self.last_steering_angle) / DT_CTRL
    self.last_steering_angle = current_steering_angle

    is_emergency_turn = (abs(current_steering_angle) > 35.0 or steering_rate > 60.0) and self.frame >= 100
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

    self.counter_1ba = (int(self.counter_1ba) + 1) & 0xF
    self.counter_17e = (int(self.counter_17e) + 1) & 0xF

    lat_active = CC.latActive and not CS.steeringPressed and self.frame >= 100 and not self.first_start

    if lat_active:
      apply_angle = actuators.steeringAngleDeg + CS.out.steeringAngleOffsetDeg
      apply_angle = apply_std_steer_angle_limits(
        apply_angle, self.last_angle, CS.out.vEgoRaw, CS.out.steeringAngleDeg + CS.out.steeringAngleOffsetDeg, CC.latActive, self.params.ANGLE_LIMITS
      )
      apply_angle = np.clip(apply_angle, CS.out.steeringAngleDeg - 30, CS.out.steeringAngleDeg + 30)

      max_change = 5 if abs(CS.out.steeringAngleDeg) > 450 else 15
      angle_diff = apply_angle - self.last_angle
      if abs(angle_diff) > max_change:
        apply_angle = self.last_angle + max_change * (1 if angle_diff > 0 else -1)
      apply_angle = np.clip(apply_angle, -480, 480)

      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 1, self.counter_1ba))
    else:
      apply_angle = self.last_angle if not self.first_start else 0.0
      can_sends.append(changancan.create_steering_control(self.packer, CS.sigs["GW_1BA"], apply_angle, 0, self.counter_1ba))

    self.last_angle = apply_angle

    can_sends.append(changancan.create_eps_control(self.packer, CS.sigs["GW_17E"], lat_active, self.counter_17e))

    if self.frame % 2 == 0:
      self.counter_244 = (int(self.counter_244) + 1) & 0xF
      acctrq = -5000
      accel = np.clip(actuators.accel, self.params.ACCEL_MIN, self.params.ACCEL_MAX)

      self.last_speed = CS.out.vEgoRaw * CV.MS_TO_KPH

      if accel < 0:
        self.expected_daccel = accel
        self.actual_daccel_filtered = 0.9 * self.actual_daccel_filtered + 0.1 * CS.out.aEgo
        if self.actual_daccel_filtered > self.expected_daccel * 0.8:
          self.slope_daccel = 0.15
        else:
          self.slope_daccel = 0.0
        accel -= self.slope_daccel

        accel = np.clip(accel, self.last_apply_accel - 0.2, self.last_apply_accel + 0.10)
        if self.last_apply_accel >= 0 and CC.hudControl.leadVisible and CC.hudControl.leadDistance < 30:
          accel = -0.4
        accel = max(accel, -3.5)

        if self.last_speed == 0 and CC.hudControl.leadVisible and CC.hudControl.leadDistance > 0:
          if self.stop_lead_distance == 0:
            self.stop_lead_distance = CC.hudControl.leadDistance
        if self.stop_lead_distance != 0 and self.last_speed == 0 and CC.hudControl.leadVisible and CC.hudControl.leadDistance - self.stop_lead_distance > 1:
          accel = 0.5

      if self.last_speed > 0:
        self.stop_lead_distance = 0

      if accel > 0:
        speed_kph = self.last_speed
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

      accel = int(accel / 0.05) * 0.05
      self.last_apply_accel = accel
      self.last_acctrq = acctrq

      can_sends.append(changancan.create_acc_control(self.packer, CS.sigs["GW_244"], accel, self.counter_244, CC.longActive, acctrq))

    if self.frame % 10 == 0:
      self.counter_307 = (int(self.counter_307) + 1) & 0xF
      self.counter_31a = (int(self.counter_31a) + 1) & 0xF
      cruise_speed_kph = CS.out.cruiseState.speed * CV.MS_TO_KPH
      can_sends.append(changancan.create_acc_set_speed(self.packer, CS.sigs["GW_307"], self.counter_307, cruise_speed_kph))
      can_sends.append(changancan.create_acc_hud(self.packer, CS.sigs["GW_31A"], self.counter_31a, CC.longActive, CS.out.steeringPressed))

    self.frame += 1
    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.last_angle)
    new_actuators.accel = float(self.last_apply_accel)
    return new_actuators, can_sends
