"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import math
from types import SimpleNamespace

from opendbc.car.volkswagen.carcontroller import MQBStandstillManager


def _pitch(grade_pct):
  return math.atan(grade_pct / 100.0)


def _mgr():
  return MQBStandstillManager(vehicle_mass=1540.0, accel_min=-3.5)


def _cs(*, esp_hold_confirmation=False, esp_stopping=False, rolling_backward=False,
        rolling_forward=False, brake_pressed=False, gas_pressed=False, standstill=True, v_ego=0.0,
        sum_wegimpulse=0):
  out = SimpleNamespace(brakePressed=brake_pressed, gasPressed=gas_pressed, standstill=standstill, vEgo=v_ego)
  return SimpleNamespace(out=out, esp_hold_confirmation=esp_hold_confirmation,
                         esp_stopping=esp_stopping, rolling_backward=rolling_backward,
                         rolling_forward=rolling_forward, sum_wegimpulse=sum_wegimpulse)


def _run(mgr, cs, *, long_active=True, accel=0.0, stopping=False, starting=False,
         max_planned_speed=0.0, grade_pct=0.0, tsk_brake_torque=0.0):
  return mgr.update(cs, long_active, accel, stopping, starting, max_planned_speed,
                    _pitch(grade_pct), tsk_brake_torque)


def _safe_speed(mgr, grade_pct, brake_torque=0.0):
  return mgr.get_safe_speed_for_brake_torque(_pitch(grade_pct), brake_torque)


# ── brake press ──────────────────────────────────────────────────────────────

def test_brake_pressed_disables_long_active():
  mgr = _mgr()
  long_active, *_ = _run(mgr, _cs(brake_pressed=True), long_active=True)
  assert not long_active


# ── rollback detection ───────────────────────────────────────────────────────

def test_rollback_detected_on_rolling_backward():
  mgr = _mgr()
  _run(mgr, _cs(rolling_backward=True))
  assert mgr.rollback_detected


def test_rollback_clears_on_rolling_forward():
  mgr = _mgr()
  _run(mgr, _cs(rolling_backward=True))
  assert mgr.rollback_detected
  _run(mgr, _cs(rolling_forward=True))
  assert not mgr.rollback_detected


def test_rollback_forces_brake():
  mgr = _mgr()
  _run(mgr, _cs(rolling_backward=True))
  _, accel, *_ = _run(mgr, _cs(), accel=-0.5)
  assert accel == mgr.accel_min


def test_rollback_cleared_when_rolling_forward_passes_through_accel():
  mgr = _mgr()
  _run(mgr, _cs(rolling_backward=True))
  _, accel, *_ = _run(mgr, _cs(rolling_forward=True, standstill=False), accel=-0.5)
  assert accel == -0.5


def test_rollback_forces_brake_with_positive_accel():
  mgr = _mgr()
  _run(mgr, _cs(rolling_backward=True))
  _, accel, stopping, starting, *_ = _run(mgr, _cs(), accel=0.5)
  assert accel == mgr.accel_min
  assert stopping
  assert not starting


# ── safe speed braking ───────────────────────────────────────────────────────

def test_flat_ground_passes_raw_accel():
  mgr = _mgr()
  _, accel, stopping, starting, *_ = _run(mgr, _cs(v_ego=0.0), accel=-0.55,
                                          stopping=True, starting=False, grade_pct=0.0)
  assert accel == -0.55
  assert stopping
  assert not starting


def test_current_brake_torque_reduces_safe_speed():
  mgr = _mgr()
  zero_brake_safe_speed = _safe_speed(mgr, 20.0)
  current_brake_safe_speed = _safe_speed(mgr, 20.0, 500.0)
  assert 0.0 < current_brake_safe_speed < zero_brake_safe_speed


def test_current_brake_torque_can_eliminate_safe_speed():
  mgr = _mgr()
  assert _safe_speed(mgr, 20.0, 10000.0) == 0.0


def test_safe_speed_is_capped_at_10_kph():
  mgr = _mgr()
  assert _safe_speed(mgr, 100.0) == MQBStandstillManager.MAX_SAFE_STOPPING_SPEED


def test_esp_stopping_passes_raw_accel_on_flat():
  mgr = _mgr()
  _, accel, stopping, starting, esp_starting_override, esp_stopping_override = _run(
    mgr, _cs(esp_stopping=True, v_ego=0.2), accel=-0.55, stopping=True, starting=False,
  )
  assert accel == -0.55
  assert stopping
  assert not starting
  assert esp_starting_override is True
  assert esp_stopping_override is False


def test_below_safe_speed_blends_brake():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  required_torque = mgr.get_hill_hold_decel_deficit(_pitch(grade), 0.0) * mgr.vehicle_mass * mgr.ASSUMED_WHEEL_RADIUS
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=-0.55, grade_pct=grade,
    tsk_brake_torque=required_torque * 0.5,
  )
  assert mgr.accel_min < accel < -0.55
  assert stopping
  assert not starting


def test_sufficient_brake_torque_passes_raw_accel():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=-0.2, stopping=True, starting=False,
    grade_pct=grade, tsk_brake_torque=10000.0,
  )
  assert accel == -0.2
  assert stopping
  assert not starting


def test_below_safe_speed_with_low_planned_speed_uses_blended_braking():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=-0.55,
    max_planned_speed=safe_speed * 0.5, grade_pct=grade,
  )
  assert mgr.accel_min <= accel < -0.55
  assert stopping
  assert not starting


def test_below_safe_speed_with_high_planned_speed_and_negative_accel_uses_blended_braking():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=-0.55,
    max_planned_speed=safe_speed * 2.0, grade_pct=grade,
  )
  assert mgr.accel_min <= accel < -0.55
  assert stopping
  assert not starting


def test_below_safe_speed_with_high_planned_speed_and_positive_accel_uses_hill_takeoff():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=0.1,
    max_planned_speed=safe_speed * 2.0, grade_pct=grade,
  )
  assert accel == max(0.1, 0.1 * grade, 0.2)
  assert starting
  assert not stopping


# ── start commit ─────────────────────────────────────────────────────────────

def test_start_commit_on_pre_enable():
  mgr = _mgr()
  _run(mgr, _cs(esp_hold_confirmation=True))
  assert mgr.start_commit_active


def test_start_commit_forces_accel():
  mgr = _mgr()
  grade = 10.0
  expected_min = max(0.1 * grade, 0.2)
  _run(mgr, _cs(esp_hold_confirmation=True), grade_pct=grade)
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(esp_hold_confirmation=True), accel=0.0, grade_pct=grade,
  )
  assert accel >= expected_min
  assert starting
  assert not stopping


def test_start_commit_clears_above_safe_speed_while_moving():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _run(mgr, _cs(esp_hold_confirmation=True), grade_pct=grade)
  assert mgr.start_commit_active
  _run(mgr, _cs(v_ego=safe_speed * 2.0, standstill=True), grade_pct=grade)
  assert not mgr.start_commit_active


def test_start_commit_persists_below_safe_speed():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)
  _run(mgr, _cs(esp_hold_confirmation=True), grade_pct=grade)
  assert mgr.start_commit_active
  _, accel, stopping, starting, *_ = _run(
    mgr, _cs(v_ego=safe_speed * 0.5), accel=-0.55, grade_pct=grade,
  )
  assert mgr.start_commit_active
  assert accel == max(-0.55, 0.1 * grade, 0.2)
  assert starting
  assert not stopping


# ── can_stop_forever / ESP override ──────────────────────────────────────────

def test_can_stop_forever_latches_on_esp_stopping():
  mgr = _mgr()
  *_, esp_start, esp_stop = _run(mgr, _cs(esp_stopping=True), accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  assert esp_start is True
  assert esp_stop is False


def test_can_stop_forever_persists():
  mgr = _mgr()
  _run(mgr, _cs(esp_stopping=True), accel=-1.0, stopping=True)
  *_, esp_start, esp_stop = _run(mgr, _cs(), accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  assert esp_start is True
  assert esp_stop is False


def test_can_stop_forever_cleared_by_hold_confirmation():
  mgr = _mgr()
  _run(mgr, _cs(esp_stopping=True), accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  _run(mgr, _cs(esp_hold_confirmation=True), accel=-1.0, stopping=True)
  assert not mgr.can_stop_forever


def test_hold_confirmation_recovers_stop_forever_after_launch_commit():
  mgr = _mgr()
  grade = 20.0
  safe_speed = _safe_speed(mgr, grade)

  *_, esp_start, esp_stop = _run(mgr, _cs(esp_hold_confirmation=True, sum_wegimpulse=0),
                                 accel=0.0, grade_pct=grade)
  assert mgr.start_commit_active
  assert mgr.hold_recovery_active
  assert esp_start is True
  assert esp_stop is False

  *_, esp_start, esp_stop = _run(mgr, _cs(v_ego=safe_speed * 2.0, standstill=False, sum_wegimpulse=1),
                                 accel=0.0, grade_pct=grade)
  assert not mgr.start_commit_active
  assert mgr.hold_recovery_active
  assert esp_start is False
  assert esp_stop is True

  *_, esp_start, esp_stop = _run(mgr, _cs(esp_stopping=True, v_ego=safe_speed * 2.0, standstill=False,
                                          sum_wegimpulse=2), accel=0.0, grade_pct=grade)
  assert mgr.can_stop_forever
  assert not mgr.hold_recovery_active
  assert esp_start is True
  assert esp_stop is False


def test_can_stop_forever_cleared_when_moving():
  mgr = _mgr()
  _run(mgr, _cs(esp_stopping=True), accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  _run(mgr, _cs(v_ego=MQBStandstillManager.ESP_OVERRIDE_SPEED + 0.01), accel=0.5)
  assert not mgr.can_stop_forever


def test_can_stop_forever_cleared_when_long_inactive():
  mgr = _mgr()
  _run(mgr, _cs(esp_stopping=True), accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  _run(mgr, _cs(), long_active=False)
  assert not mgr.can_stop_forever


def test_esp_override_stop_at_standstill():
  mgr = _mgr()
  esp_start = esp_stop = None
  for _ in range(MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES + 1):
    *_, esp_start, esp_stop = _run(mgr, _cs(sum_wegimpulse=0), accel=-1.0, stopping=True)
  assert esp_start is False
  assert esp_stop is True


def test_esp_override_stop_persists_at_standstill():
  mgr = _mgr()
  for _ in range(MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES + 1):
    _run(mgr, _cs(sum_wegimpulse=0), accel=-1.0, stopping=True)
  *_, esp_start, esp_stop = _run(mgr, _cs(sum_wegimpulse=0), accel=-1.0, stopping=True)
  assert esp_start is False
  assert esp_stop is True


def test_esp_override_stop_not_sent_while_esp_stopping():
  mgr = _mgr()
  *_, esp_start, esp_stop = _run(mgr, _cs(esp_stopping=True, sum_wegimpulse=0),
                                 accel=-1.0, stopping=True)
  assert mgr.can_stop_forever
  assert esp_start is True
  assert esp_stop is False


def test_esp_override_stop_not_requested_while_moving():
  mgr = _mgr()
  esp_start = esp_stop = None
  for sum_wegimpulse in range(MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES + 1):
    *_, esp_start, esp_stop = _run(mgr, _cs(sum_wegimpulse=sum_wegimpulse), accel=-1.0, stopping=True)
  assert esp_start is True
  assert esp_stop is False


def test_esp_override_default_below_grant_speed_when_inactive():
  mgr = _mgr()
  *_, esp_start, esp_stop = _run(mgr, _cs(), long_active=False)
  assert esp_start is True
  assert esp_stop is False


def test_wegimpulse_at_standstill_after_stillness_frames():
  mgr = _mgr()
  for _ in range(MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES + 1):
    _run(mgr, _cs(sum_wegimpulse=0))
  assert mgr.frames_since_last_wheel_pulse >= MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES


def test_wegimpulse_resets_on_change():
  mgr = _mgr()
  for _ in range(MQBStandstillManager.WEGIMPULSE_STILLNESS_FRAMES):
    _run(mgr, _cs(sum_wegimpulse=0))
  _run(mgr, _cs(sum_wegimpulse=1))
  assert mgr.frames_since_last_wheel_pulse == 0


