#!/usr/bin/env python3
"""
Tests for ALKA (Always-on Lane Keeping Assist) Python layer.

Tests the controlsd logic for computing latActive when ALKA is enabled.
Matches the logic in selfdrive/controls/controlsd.py.
"""
import unittest

from cereal import log
from opendbc.safety import ALTERNATIVE_EXPERIENCE


class TestALKAAlternativeExperience(unittest.TestCase):
  """Test ALTERNATIVE_EXPERIENCE.ALKA constant."""

  def test_alka_constant_value(self):
    """ALKA constant should be 1024 (2^10)."""
    self.assertEqual(ALTERNATIVE_EXPERIENCE.ALKA, 1024)

  def test_alka_flag_bitwise(self):
    """ALKA flag should work with bitwise operations."""
    # Test setting ALKA flag
    exp = ALTERNATIVE_EXPERIENCE.DEFAULT | ALTERNATIVE_EXPERIENCE.ALKA
    self.assertTrue(exp & ALTERNATIVE_EXPERIENCE.ALKA)

    # Test combining with other flags
    exp = ALTERNATIVE_EXPERIENCE.DISABLE_STOCK_AEB | ALTERNATIVE_EXPERIENCE.ALKA
    self.assertTrue(exp & ALTERNATIVE_EXPERIENCE.ALKA)
    self.assertTrue(exp & ALTERNATIVE_EXPERIENCE.DISABLE_STOCK_AEB)

    # Test without ALKA
    exp = ALTERNATIVE_EXPERIENCE.DISABLE_STOCK_AEB
    self.assertFalse(exp & ALTERNATIVE_EXPERIENCE.ALKA)


class TestALKALatActive(unittest.TestCase):
  """Test latActive computation with ALKA.

  This mirrors the logic in controlsd.py:
    alka_enabled = (self.CP.alternativeExperience & ALTERNATIVE_EXPERIENCE.ALKA) != 0
    lkas_on = self.sm['carStateExt'].lkasOn
    calibrated = self.sm['liveCalibration'].calStatus == log.LiveCalibrationData.Status.calibrated
    gear_ok = CS.gearShifter not in (park, neutral, reverse)
    alka_active = lkas_on and gear_ok and calibrated and not CS.seatbeltUnlatched and not CS.doorOpen
    CC.latActive = (self.sm['selfdriveState'].active or alka_active) and not CS.steerFaultTemporary and not CS.steerFaultPermanent and \
                   (not standstill or self.CP.steerAtStandstill)
  """

  def _compute_alka_active(self, alka_enabled, lkas_on, gear_ok, calibrated, seatbelt_unlatched, door_open):
    """Compute alka_active matching controlsd.py logic."""
    return alka_enabled and lkas_on and gear_ok and calibrated and \
           not seatbelt_unlatched and not door_open

  def _compute_lat_active(self, selfdrive_active, alka_active, steer_fault_temp, steer_fault_perm, standstill, steer_at_standstill=False):
    """Compute latActive matching controlsd.py logic."""
    return (selfdrive_active or alka_active) and not steer_fault_temp and not steer_fault_perm and \
           (not standstill or steer_at_standstill)

  def test_lat_active_normal_mode(self):
    """Without ALKA, latActive should follow selfdriveState.active."""
    alka_active = self._compute_alka_active(
      alka_enabled=False, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=True, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertTrue(lat_active)

    # When selfdrive not active, lat should be inactive
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_alka_mode(self):
    """With ALKA, latActive can be true even when selfdriveState.active is false."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertTrue(lat_active)

  def test_lat_active_alka_requires_lkas_on(self):
    """ALKA requires lkasOn (ACC Main ON)."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=False, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_alka_requires_gear_ok(self):
    """ALKA requires gear not in P/N/R."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=False,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_alka_requires_calibration(self):
    """ALKA requires calibration to be complete."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=False, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_alka_requires_seatbelt(self):
    """ALKA requires seatbelt to be latched."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=True, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_alka_requires_doors_closed(self):
    """ALKA requires all doors to be closed."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=True)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_blocked_by_steer_fault_temporary(self):
    """Temporary steer fault should block lateral control regardless of ALKA."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=True, steer_fault_perm=False, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_blocked_by_steer_fault_permanent(self):
    """Permanent steer fault should block lateral control regardless of ALKA."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=True, standstill=False)
    self.assertFalse(lat_active)

  def test_lat_active_blocked_by_standstill(self):
    """ALKA should be blocked at standstill (latActive checks standstill)."""
    alka_active = self._compute_alka_active(
      alka_enabled=True, lkas_on=True, gear_ok=True,
      calibrated=True, seatbelt_unlatched=False, door_open=False)
    lat_active = self._compute_lat_active(
      selfdrive_active=False, alka_active=alka_active,
      steer_fault_temp=False, steer_fault_perm=False, standstill=True)
    self.assertFalse(lat_active)


class TestALKASettings(unittest.TestCase):
  """Test ALKA settings configuration."""

  def test_alka_setting_in_lateral_section(self):
    """ALKA setting should be in the Lateral section."""
    from dragonpilot.settings import SETTINGS

    lateral_section = None
    for section in SETTINGS:
      if section["title"] == "Lateral":
        lateral_section = section
        break

    self.assertIsNotNone(lateral_section, "Lateral section not found in SETTINGS")

    # Find ALKA setting
    alka_setting = None
    for setting in lateral_section["settings"]:
      if setting.get("key") == "dp_lat_alka":
        alka_setting = setting
        break

    self.assertIsNotNone(alka_setting, "dp_lat_alka setting not found")

  def test_alka_setting_has_brands(self):
    """ALKA setting brands should match safety modes with alka_allowed=true."""
    from dragonpilot.settings import SETTINGS
    from opendbc.car.structs import CarParams
    from opendbc.safety.tests.libsafety import libsafety_py

    # Map of brand names to their safety modes
    brand_to_safety_mode = {
      "toyota": CarParams.SafetyModel.toyota,
      "hyundai": CarParams.SafetyModel.hyundai,
      "honda": CarParams.SafetyModel.hondaNidec,
      "volkswagen": CarParams.SafetyModel.volkswagen,
      "subaru": CarParams.SafetyModel.subaru,
      "mazda": CarParams.SafetyModel.mazda,
      "nissan": CarParams.SafetyModel.nissan,
      "ford": CarParams.SafetyModel.ford,
      "chrysler": CarParams.SafetyModel.chrysler,
    }

    # Find ALKA setting
    alka_setting = None
    for section in SETTINGS:
      for setting in section.get("settings", []):
        if setting.get("key") == "dp_lat_alka":
          alka_setting = setting
          break

    self.assertIsNotNone(alka_setting)
    self.assertIn("brands", alka_setting)
    self.assertIsInstance(alka_setting["brands"], list)

    # Verify each brand in settings has alka_allowed=true in safety mode
    safety = libsafety_py.libsafety
    for brand in alka_setting["brands"]:
      self.assertIn(brand, brand_to_safety_mode, f"Unknown brand: {brand}")
      safety_mode = brand_to_safety_mode[brand]
      safety.set_safety_hooks(safety_mode, 0)
      safety.init_tests()
      self.assertTrue(safety.get_alka_allowed(), f"Brand {brand} should have alka_allowed=true")


class TestALKAAllConditions(unittest.TestCase):
  """Comprehensive truth table tests for all ALKA conditions."""

  def test_alka_all_conditions_truth_table(self):
    """Test all combinations of ALKA conditions."""
    # Test cases: (alka_enabled, lkas_on, gear_ok, calibrated, seatbelt_unlatched, door_open) -> expected_alka_active
    test_cases = [
      # All conditions met
      (True, True, True, True, False, False, True),
      # Missing one condition each
      (False, True, True, True, False, False, False),  # ALKA disabled
      (True, False, True, True, False, False, False),  # lkas_on false
      (True, True, False, True, False, False, False),  # gear not ok (P/N/R)
      (True, True, True, False, False, False, False),  # Not calibrated
      (True, True, True, True, True, False, False),    # Seatbelt unlatched
      (True, True, True, True, False, True, False),    # Door open
      # Multiple conditions missing
      (True, False, False, True, False, False, False),   # No lkas_on + bad gear
      (True, True, True, False, True, True, False),      # Not calibrated + seatbelt + door
    ]

    for alka_enabled, lkas_on, gear_ok, calibrated, seatbelt_unlatched, door_open, expected in test_cases:
      alka_active = alka_enabled and lkas_on and gear_ok and calibrated and \
                    not seatbelt_unlatched and not door_open

      self.assertEqual(alka_active, expected,
                       f"Failed for alka_enabled={alka_enabled}, lkas_on={lkas_on}, gear_ok={gear_ok}, "
                       f"calibrated={calibrated}, seatbelt_unlatched={seatbelt_unlatched}, "
                       f"door_open={door_open}")

  def test_lat_active_truth_table(self):
    """Test latActive computation with various inputs."""
    # Test cases: (selfdrive_active, alka_active, steer_fault, standstill) -> expected_lat_active
    test_cases = [
      (False, False, False, False, False),  # Nothing active
      (True, False, False, False, True),    # Selfdrive only
      (False, True, False, False, True),    # ALKA only
      (True, True, False, False, True),     # Both active
      (True, False, True, False, False),    # Selfdrive but fault
      (False, True, True, False, False),    # ALKA but fault
      (True, False, False, True, False),    # Selfdrive but standstill (no steerAtStandstill)
      (False, True, False, True, False),    # ALKA but standstill
    ]

    for selfdrive_active, alka_active, steer_fault, standstill, expected in test_cases:
      lat_active = (selfdrive_active or alka_active) and not steer_fault and not standstill

      self.assertEqual(lat_active, expected,
                       f"Failed for selfdrive_active={selfdrive_active}, alka_active={alka_active}, "
                       f"steer_fault={steer_fault}, standstill={standstill}")


if __name__ == "__main__":
  unittest.main()
