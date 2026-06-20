"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.volkswagen import pqcan


class PQRadarHandler:
  GRA_STEP = 3                            # GRA_Neu cadence (~33 Hz), matches stock stalk module
  SPOOF_STEP = 2                         # Motor_2 / Motor_5 spoof cadence (50 Hz)

  ENGAGE_FLOOR = 1.0 * CV.KPH_TO_MS      # never SET at/below 1 kph
  REENGAGE_FLOOR = 2.0 * CV.KPH_TO_MS    # hysteresis: only (re)engage above 2 kph

  SETSPEED_TOL_KPH = 1.0                 # don't chase set-speed within this band
  SHORT_STEP_KPH = 1.0 * CV.MPH_TO_KPH   # GRA_*_kurz ~= 1 mph
  LONG_STEP_KPH = 5.0 * CV.MPH_TO_KPH    # GRA_*_lang ~= 5 mph
  TAP_RELEASE_CYCLES = 2                 # GRA cycles to release between set-speed taps

  def __init__(self, CAN):
    self.bus = CAN.ext                   # radar lives on bus 2 (ext/cam)
    self.counter = 0
    self.failed = False                  # ACS_Fehler / irrev_Fehler -> radar dead for the drive
    self.want_engaged = False            # our belief the radar cruise should be on
    self._press_phase = 0                # alternate press/release for SET/cancel discrete edges
    self._tap_cooldown = 0               # set-speed tap rate limiter

  def reset(self):
    self.want_engaged = False
    self._press_phase = 0
    self._tap_cooldown = 0

  @staticmethod
  def _map_gap_bars(gap_bars):
    if not gap_bars:
      return None
    return int(min(3, max(1, gap_bars)))

  def update(self, packer, frame, CS, *, blend_active, engage_req, cancel_req,
             set_speed_kph, gap_bars, v_ego):
    can_sends = []

    if not blend_active:
      self.reset()
      return can_sends

    if CS.acc_radar_fehler or CS.acc_radar_sta_adr == 3:
      self.failed = True

    radar_active = (CS.acc_radar_sta_adr == 1) and not self.failed

    if self.failed:
      self.want_engaged = False
    elif cancel_req:
      self.want_engaged = False
    elif engage_req and v_ego > self.REENGAGE_FLOOR:
      self.want_engaged = True

    if (frame % self.SPOOF_STEP) == 0:
      can_sends.append(pqcan.filter_motor2(packer, self.bus, CS.motor2_stock, gra_active=self.want_engaged))
      can_sends.append(pqcan.filter_motor5(packer, self.bus, CS.motor5_stock, gra_active=self.want_engaged))

    if (frame % self.GRA_STEP) == 0:
      set_btn = cancel = up_s = down_s = up_l = down_l = False
      self._press_phase ^= 1
      pressing = self._press_phase == 0

      if self.failed:
        pass
      elif cancel_req:
        cancel = pressing
      elif self.want_engaged and not radar_active and v_ego > self.ENGAGE_FLOOR:
        set_btn = pressing
      elif self.want_engaged and radar_active:
        if self._tap_cooldown > 0:
          self._tap_cooldown -= 1
        elif set_speed_kph > 0:
          delta = set_speed_kph - CS.acc_radar_v_wunsch
          if abs(delta) >= self.SETSPEED_TOL_KPH:
            big = abs(delta) >= self.LONG_STEP_KPH
            if delta > 0:
              up_l, up_s = big, not big
            else:
              down_l, down_s = big, not big
            self._tap_cooldown = self.TAP_RELEASE_CYCLES

      self.counter = (self.counter + 1) % 16
      can_sends.append(pqcan.create_radar_gra(
        packer, self.bus, CS.gra_stock_values, self.counter,
        set_btn=set_btn, cancel=cancel, up_short=up_s, down_short=down_s,
        up_long=up_l, down_long=down_l, zeitluecke=self._map_gap_bars(gap_bars),
      ))

    return can_sends
