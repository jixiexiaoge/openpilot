#!/usr/bin/env python3
"""
Tests for the dp Honda Nidec stock-longitudinal feature.

When `dp_honda_nidec_stock_long` is set:
- python: honda/interface.py flips `openpilotLongitudinalControl` to False and
          sets the `HondaSafetyFlags.NIDEC_STOCK_LONG` (= 32) safety param.
- panda:  honda.h reads `HONDA_PARAM_NIDEC_STOCK_LONG` and switches the TX
          whitelist from HONDA_N_TX_MSGS to HONDA_N_STOCK_LONG_TX_MSGS, which
          drops brake (0x1FA) and ACC HUD (0x30C).

These tests exercise the panda side: with the flag set, brake/ACC-hud TX must
be rejected unconditionally; steering + LKAS hud remain allowed. All other
Nidec PCM safety behaviour (RX checks, button enable, etc.) is inherited
verbatim from TestHondaNidecPcmSafety.
"""
import unittest
import numpy as np

from opendbc.car.honda.values import HondaSafetyFlags
from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py
import opendbc.safety.tests.common as common
from opendbc.safety.tests.common import CANPackerSafety
from opendbc.safety.tests.test_honda import TestHondaNidecPcmSafety


class TestHondaNidecPcmStockLongSafety(TestHondaNidecPcmSafety):
  """Honda Nidec lateral-only mode: stock ACC owns gas/brake."""

  TX_MSGS = [[0xE4, 0], [0x194, 0], [0x33D, 0]]
  FWD_BLACKLISTED_ADDRS = {2: [0xE4, 0x194, 0x33D]}
  RELAY_MALFUNCTION_ADDRS = {0: (0xE4, 0x194, 0x33D)}

  def setUp(self):
    self.packer = CANPackerSafety("honda_civic_touring_2016_can_generated")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.hondaNidec, HondaSafetyFlags.NIDEC_STOCK_LONG)
    self.safety.init_tests()

  def test_brake_safety_check(self):
    # Stock ACC owns longitudinal — every brake TX must be rejected.
    for brake in np.arange(0, self.MAX_BRAKE + 10, 1):
      for controls_allowed in (True, False):
        self.safety.set_controls_allowed(controls_allowed)
        self.assertFalse(
          self._tx(self._send_brake_msg(brake)),
          f"brake={brake} controls_allowed={controls_allowed} should be rejected",
        )

  def test_acc_hud_safety_check(self):
    # Stock ACC owns longitudinal — every ACC HUD TX must be rejected.
    for controls_allowed in (True, False):
      self.safety.set_controls_allowed(controls_allowed)
      for pcm_gas in (0, 100, self.MAX_GAS):
        for pcm_speed in (0, 50, 100):
          self.assertFalse(
            self._tx(self._send_acc_hud_msg(pcm_gas, pcm_speed)),
            f"acc_hud gas={pcm_gas} speed={pcm_speed} controls_allowed={controls_allowed} should be rejected",
          )

  def test_honda_fwd_brake_latching(self):
    # AEB-forwarding logic doesn't apply: openpilot never TX's its own brake to compare against.
    pass

  def test_fwd_hook(self):
    # Base Nidec test mutates FWD_BLACKLISTED_ADDRS to include 0x1FA/0x30C, which are
    # not in our TX list. Run the simpler common.CarSafetyTest version directly.
    common.CarSafetyTest.test_fwd_hook(self)


if __name__ == "__main__":
  unittest.main()
