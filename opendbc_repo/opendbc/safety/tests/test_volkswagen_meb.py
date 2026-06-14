#!/usr/bin/env python3
import unittest
import numpy as np

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py
import opendbc.safety.tests.common as common
from opendbc.safety.tests.common import CANPackerSafety
from opendbc.car.volkswagen.values import VolkswagenSafetyFlags
from opendbc.car.lateral import ISO_LATERAL_JERK

MAX_ACCEL = 2.0
MIN_ACCEL = -3.5

MSG_ESC_51 = 0xFC
MSG_QFK_01 = 0x13D
MSG_Motor_54 = 0x14C
MSG_Motor_51 = 0x10B
MSG_ACC_18 = 0x14D
MSG_MEB_ACC_01 = 0x300
MSG_HCA_03 = 0x303
MSG_GRA_ACC_01 = 0x12B
MSG_LDW_02 = 0x397
MSG_MOTOR_14 = 0x3BE
MSG_TA_01 = 0x26B
MSG_KLR_01 = 0x25D
MSG_EA_01 = 0x1A4
MSG_EA_02 = 0x1F0
MSG_AWV_03 = 0xDB
MSG_MEB_DISTANCE_01 = 0x24F
MSG_UDS_FUNCTIONAL = 0x700


class TestVolkswagenMebSafetyBase(common.CarSafetyTest):
  RELAY_MALFUNCTION_ADDRS = {0: (MSG_HCA_03, MSG_LDW_02, MSG_EA_02),
                             2: (MSG_KLR_01,)}

  CURVATURE_TO_CAN = 149253.7313
  MAX_CURVATURE = 0.195
  SEND_RATE = 0.02
  MAX_POWER = 225
  POWER_FACTOR = 0.4

  def _speed_msg(self, speed_mps: float):
    spd_kph = speed_mps * 3.6
    values = {"HL_Radgeschw": spd_kph, "HR_Radgeschw": spd_kph, "VL_Radgeschw": spd_kph, "VR_Radgeschw": spd_kph}
    return self.packer.make_can_msg_safety("ESC_51", 0, values)

  def _speed_msg_2(self, speed: float):
    return None

  def _motor_14_msg(self, brake):
    values = {"MO_Fahrer_bremst": brake}
    return self.packer.make_can_msg_safety("Motor_14", 0, values)

  def _user_brake_msg(self, brake):
    return self._motor_14_msg(brake)

  def _user_gas_msg(self, gas):
    values = {"Accel_Pedal_Pressure": gas, "TSK_Status": 3}
    return self.packer.make_can_msg_safety("Motor_51", 0, values)

  def _tsk_status_msg(self, enable, main_switch=True):
    tsk_status = 3 if enable else (2 if main_switch else 0)
    values = {"TSK_Status": tsk_status}
    return self.packer.make_can_msg_safety("Motor_51", 0, values)

  def _pcm_status_msg(self, enable):
    return self._tsk_status_msg(enable)

  def _curvature_meas_msg(self, curvature):
    values = {"Curvature": abs(curvature), "Curvature_VZ": curvature > 0}
    return self.packer.make_can_msg_safety("QFK_01", 0, values)

  def _curvature_cmd_msg(self, curvature, steer_req=True, power=50):
    values = {
      "Curvature": abs(curvature),
      "Curvature_VZ": curvature > 0,
      "RequestStatus": 4 if steer_req else 0,
      "Power": power,
    }
    return self.packer.make_can_msg_safety("HCA_03", 0, values)

  def _button_msg(self, cancel=0, resume=0, _set=0, bus=2):
    values = {"GRA_Abbrechen": cancel, "GRA_Tip_Setzen": _set, "GRA_Tip_Wiederaufnahme": resume}
    return self.packer.make_can_msg_safety("GRA_ACC_01", bus, values)

  def test_curvature_measurements(self):
    self._rx(self._curvature_meas_msg(0.15))
    self._rx(self._curvature_meas_msg(-0.1))
    for _ in range(4):
      self._rx(self._curvature_meas_msg(0))

    self.assertEqual(int(-0.1 * self.CURVATURE_TO_CAN), self.safety.get_angle_meas_min())
    self.assertEqual(int(0.15 * self.CURVATURE_TO_CAN), self.safety.get_angle_meas_max())

    self._reset_safety_hooks()
    self.assertEqual(0, self.safety.get_angle_meas_min())
    self.assertEqual(0, self.safety.get_angle_meas_max())

  def test_curvature_cmd_limits(self):
    self._rx(self._speed_msg(0.0))
    self._rx(self._curvature_meas_msg(0.0))
    self.safety.set_controls_allowed(True)

    self.safety.set_desired_angle_last(int(self.MAX_CURVATURE * self.CURVATURE_TO_CAN))
    self.assertTrue(self._tx(self._curvature_cmd_msg(self.MAX_CURVATURE, True, power=50)))
    self.safety.set_desired_angle_last(int(self.MAX_CURVATURE * self.CURVATURE_TO_CAN))
    self.assertTrue(self._tx(self._curvature_cmd_msg(self.MAX_CURVATURE + 0.05, True, power=50)))

    self.assertTrue(self._tx(self._curvature_cmd_msg(0.0, False, power=0)))
    self.assertTrue(self._tx(self._curvature_cmd_msg(0.01, False, power=0)))

    power_over = (self.MAX_POWER + 1) * self.POWER_FACTOR
    self.assertTrue(self._tx(self._curvature_cmd_msg(0.0, True, power=power_over)))

  def test_curvature_cmd_jerk_limit(self):
    speed = 10.0
    for _ in range(common.MAX_SAMPLE_VALS):
      self._rx(self._speed_msg(speed))
    self._rx(self._curvature_meas_msg(0.0))
    self.safety.set_controls_allowed(True)

    max_rate = ISO_LATERAL_JERK / (speed * speed)
    max_delta = max_rate * self.SEND_RATE
    prev = 0.0
    self.safety.set_desired_angle_last(int(prev * self.CURVATURE_TO_CAN))

    self.assertTrue(self._tx(self._curvature_cmd_msg(prev + max_delta * 0.9, True, power=50)))
    self.safety.set_desired_angle_last(int(prev * self.CURVATURE_TO_CAN))
    self.assertTrue(self._tx(self._curvature_cmd_msg(prev + max_delta * 3.0, True, power=50)))


class TestVolkswagenMebStockSafety(TestVolkswagenMebSafetyBase):
  TX_MSGS = [[MSG_HCA_03, 0], [MSG_LDW_02, 0], [MSG_GRA_ACC_01, 0], [MSG_GRA_ACC_01, 2],
             [MSG_EA_01, 0], [MSG_EA_02, 0], [MSG_KLR_01, 0], [MSG_KLR_01, 2]]
  FWD_BLACKLISTED_ADDRS = {0: [MSG_KLR_01],
                           2: [MSG_HCA_03, MSG_LDW_02, MSG_EA_02]}

  def setUp(self):
    self.packer = CANPackerSafety("vw_meb")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.volkswagenMeb, 0)
    self.safety.init_tests()

  def test_spam_cancel_safety_check(self):
    self.safety.set_controls_allowed(0)
    self.assertTrue(self._tx(self._button_msg(cancel=1)))
    self.assertFalse(self._tx(self._button_msg(resume=1)))
    self.assertFalse(self._tx(self._button_msg(_set=1)))
    self.safety.set_controls_allowed(1)
    self.assertTrue(self._tx(self._button_msg(resume=1)))


class TestVolkswagenMqbEvoStockSafety(TestVolkswagenMebStockSafety):
  def setUp(self):
    self.packer = CANPackerSafety("vw_mqbevo")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.volkswagenMqbEvo, VolkswagenSafetyFlags.NO_GAS_OFFSET)
    self.safety.init_tests()


class TestVolkswagenMebLongSafety(TestVolkswagenMebSafetyBase):
  TX_MSGS = [[MSG_HCA_03, 0], [MSG_LDW_02, 0],
             [MSG_MEB_ACC_01, 0], [MSG_ACC_18, 0], [MSG_TA_01, 0],
             [MSG_EA_01, 0], [MSG_EA_02, 0], [MSG_KLR_01, 0], [MSG_KLR_01, 2],
             [MSG_AWV_03, 0], [MSG_MEB_DISTANCE_01, 0], [MSG_UDS_FUNCTIONAL, 0]]
  FWD_BLACKLISTED_ADDRS = {0: [MSG_KLR_01],
                           2: [MSG_HCA_03, MSG_LDW_02, MSG_EA_02, MSG_MEB_ACC_01, MSG_ACC_18, MSG_TA_01]}
  RELAY_MALFUNCTION_ADDRS = {0: (MSG_HCA_03, MSG_LDW_02, MSG_EA_02, MSG_TA_01, MSG_MEB_ACC_01, MSG_ACC_18),
                             2: (MSG_KLR_01,)}
  INACTIVE_ACCEL = 3.01

  def setUp(self):
    self.packer = CANPackerSafety("vw_meb")
    self.safety = libsafety_py.libsafety
    safety_param = VolkswagenSafetyFlags.LONG_CONTROL | VolkswagenSafetyFlags.ALLOW_LONG_ACCEL_WITH_GAS_PRESSED
    self.safety.set_safety_hooks(CarParams.SafetyModel.volkswagenMeb, safety_param)
    self.safety.init_tests()

  def _accel_msg(self, accel):
    values = {"ACC_Sollbeschleunigung_02": accel}
    return self.packer.make_can_msg_safety("ACC_18", 0, values)

  def test_disable_control_allowed_from_cruise(self):
    pass

  def test_enable_control_allowed_from_cruise(self):
    pass

  def test_cruise_engaged_prev(self):
    pass

  def test_set_and_resume_buttons(self):
    for button in ["set", "resume"]:
      self.safety.set_controls_allowed(0)
      self._rx(self._tsk_status_msg(False, main_switch=False))
      self._rx(self._button_msg(_set=(button == "set"), resume=(button == "resume"), bus=0))
      self.assertFalse(self.safety.get_controls_allowed())
      self._rx(self._tsk_status_msg(False, main_switch=True))
      self._rx(self._button_msg(_set=(button == "set"), resume=(button == "resume"), bus=0))
      self.assertFalse(self.safety.get_controls_allowed())
      self._rx(self._button_msg(bus=0))
      self.assertTrue(self.safety.get_controls_allowed())

  def test_cancel_button(self):
    self._rx(self._tsk_status_msg(False, main_switch=True))
    self.safety.set_controls_allowed(1)
    self._rx(self._button_msg(cancel=True, bus=0))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_main_switch(self):
    self._rx(self._tsk_status_msg(False, main_switch=True))
    self.safety.set_controls_allowed(1)
    self._rx(self._tsk_status_msg(False, main_switch=False))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_accel_safety_check(self):
    for controls_allowed in [True, False]:
      for accel in np.concatenate((np.arange(MIN_ACCEL - 2, MAX_ACCEL + 2, 0.03), [0, self.INACTIVE_ACCEL])):
        accel = round(accel, 2)
        self.safety.set_controls_allowed(controls_allowed)
        self.assertTrue(self._tx(self._accel_msg(accel)), (controls_allowed, accel))

  def test_accel_allowed_with_gas_pressed(self):
    self._rx(self._user_gas_msg(1))
    self.safety.set_controls_allowed(True)
    self.assertTrue(self._tx(self._accel_msg(0.5)))


class TestVolkswagenMqbEvoLongSafety(TestVolkswagenMebLongSafety):
  def setUp(self):
    self.packer = CANPackerSafety("vw_mqbevo")
    self.safety = libsafety_py.libsafety
    safety_param = VolkswagenSafetyFlags.LONG_CONTROL | VolkswagenSafetyFlags.NO_GAS_OFFSET | VolkswagenSafetyFlags.ALLOW_LONG_ACCEL_WITH_GAS_PRESSED
    self.safety.set_safety_hooks(CarParams.SafetyModel.volkswagenMqbEvo, safety_param)
    self.safety.init_tests()


if __name__ == "__main__":
  unittest.main()
