#!/usr/bin/env python3
"""
Tests for tx_ext hook functionality.

tx_ext allows additional TX messages beyond the base whitelist, with per-message
check_relay control. This is used for dragonpilot-specific features:
- lock_ctrl: allows any UDS message on 0x750 (not just tester present)
"""
import unittest

from opendbc.car.toyota.values import ToyotaSafetyFlags
from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.common import CANPackerSafety


class TestTxExtBase(unittest.TestCase):
  """Base test class for tx_ext functionality."""

  TX_MSGS = []  # Required by test_tx_hook_on_wrong_safety_mode

  safety: libsafety_py.LibSafety
  packer: CANPackerSafety

  @classmethod
  def setUpClass(cls):
    if cls.__name__ == "TestTxExtBase":
      raise unittest.SkipTest("Base class")

  def _tx(self, msg):
    return self.safety.safety_tx_hook(msg)

  def _rx(self, msg):
    return self.safety.safety_rx_hook(msg)


class TestTxExtToyotaLockCtrl(TestTxExtBase):
  """Test lock_ctrl feature for Toyota.

  lock_ctrl allows any UDS message on 0x750, not just tester present.
  This is used for door lock control via diagnostic messages.
  """

  EPS_SCALE = 73

  def setUp(self):
    self.packer = CANPackerSafety("toyota_nodsu_pt_generated")
    self.safety = libsafety_py.libsafety

  def _uds_msg(self, data: bytes):
    """Create a UDS message on 0x750."""
    return libsafety_py.make_CANPacket(0x750, 0, data)

  def _tester_present_msg(self):
    """Valid tester present message (always allowed without lock_ctrl)."""
    return self._uds_msg(b"\x0F\x02\x3E\x00\x00\x00\x00\x00")

  def _lock_ctrl_msg(self):
    """Example lock control message (only allowed with lock_ctrl)."""
    return self._uds_msg(b"\x0F\x03\x30\x01\x00\x00\x00\x00")

  def _random_uds_msg(self):
    """Random UDS message (only allowed with lock_ctrl)."""
    return self._uds_msg(b"\x0F\x05\xAA\xBB\xCC\xDD\x00\x00")

  def test_lock_ctrl_disabled_only_tester_present(self):
    """Without lock_ctrl, only tester present is allowed on 0x750."""
    # OP long mode (0x750 in whitelist), no lock_ctrl
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, self.EPS_SCALE)
    self.safety.init_tests()

    # Tester present should be allowed
    self.assertTrue(self._tx(self._tester_present_msg()))

    # Other UDS messages should be blocked
    self.assertFalse(self._tx(self._lock_ctrl_msg()))
    self.assertFalse(self._tx(self._random_uds_msg()))

  def test_lock_ctrl_enabled_allows_any_uds(self):
    """With lock_ctrl, any UDS message is allowed on 0x750."""
    # OP long mode with lock_ctrl
    param = self.EPS_SCALE | ToyotaSafetyFlags.LOCK_CTRL
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, param)
    self.safety.init_tests()

    # All UDS messages should be allowed
    self.assertTrue(self._tx(self._tester_present_msg()))
    self.assertTrue(self._tx(self._lock_ctrl_msg()))
    self.assertTrue(self._tx(self._random_uds_msg()))

  def test_lock_ctrl_stock_long_allows_uds(self):
    """With lock_ctrl + stock_long, 0x750 is allowed via tx_ext."""
    # Stock long mode (0x750 NOT in base whitelist) with lock_ctrl
    param = self.EPS_SCALE | ToyotaSafetyFlags.STOCK_LONGITUDINAL | ToyotaSafetyFlags.LOCK_CTRL
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, param)
    self.safety.init_tests()

    # All UDS messages should be allowed via tx_ext
    self.assertTrue(self._tx(self._tester_present_msg()))
    self.assertTrue(self._tx(self._lock_ctrl_msg()))
    self.assertTrue(self._tx(self._random_uds_msg()))

  def test_lock_ctrl_stock_long_without_flag_blocks_uds(self):
    """Without lock_ctrl, stock_long blocks all 0x750 messages."""
    # Stock long mode without lock_ctrl
    param = self.EPS_SCALE | ToyotaSafetyFlags.STOCK_LONGITUDINAL
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, param)
    self.safety.init_tests()

    # 0x750 is not in stock long whitelist, should be blocked
    self.assertFalse(self._tx(self._tester_present_msg()))
    self.assertFalse(self._tx(self._lock_ctrl_msg()))


class TestTxExtRelayCheck(TestTxExtBase):
  """Test check_relay behavior for tx_ext messages.

  Messages allowed via tx_ext can have check_relay=true or false.
  - lock_ctrl 0x750: check_relay=false (no relay check)
  """

  EPS_SCALE = 73

  def setUp(self):
    self.packer = CANPackerSafety("toyota_nodsu_pt_generated")
    self.safety = libsafety_py.libsafety

  def _uds_msg_raw(self):
    """Create raw UDS message for relay testing."""
    return libsafety_py.make_CANPacket(0x750, 0, b"\x00" * 8)

  def _wait_for_relay_timeout(self):
    """Wait for relay transition timeout (1 second = 100 ticks at 100Hz)."""
    for _ in range(200):
      self.safety.safety_tick_current_safety_config()

  def test_lock_ctrl_no_relay_malfunction(self):
    """lock_ctrl 0x750 should not trigger relay malfunction when received."""
    param = self.EPS_SCALE | ToyotaSafetyFlags.STOCK_LONGITUDINAL | ToyotaSafetyFlags.LOCK_CTRL
    self.safety.set_safety_hooks(CarParams.SafetyModel.toyota, param)
    self.safety.init_tests()

    self._wait_for_relay_timeout()

    # Receiving 0x750 should NOT trigger relay malfunction
    # (check_relay=false for lock_ctrl)
    self.assertFalse(self.safety.get_relay_malfunction())
    self._rx(self._uds_msg_raw())
    self.assertFalse(self.safety.get_relay_malfunction())


class TestTxExtDisabledBrands(unittest.TestCase):
  """Test that tx_ext returns not allowed for brands without tx_ext hook."""

  TX_MSGS = []  # Required by test_tx_hook_on_wrong_safety_mode

  def test_hyundai_no_tx_ext(self):
    """Hyundai should not have any tx_ext allowances."""
    safety = libsafety_py.libsafety
    safety.set_safety_hooks(CarParams.SafetyModel.hyundai, 0)
    safety.init_tests()

    # Random message should not be allowed via tx_ext
    msg = libsafety_py.make_CANPacket(0x750, 0, b"\x00" * 8)
    self.assertFalse(safety.safety_tx_hook(msg))

  def test_honda_no_tx_ext(self):
    """Honda should not have any tx_ext allowances."""
    safety = libsafety_py.libsafety
    safety.set_safety_hooks(CarParams.SafetyModel.hondaNidec, 0)
    safety.init_tests()

    # Random message should not be allowed via tx_ext
    msg = libsafety_py.make_CANPacket(0x750, 0, b"\x00" * 8)
    self.assertFalse(safety.safety_tx_hook(msg))


if __name__ == "__main__":
  unittest.main()
