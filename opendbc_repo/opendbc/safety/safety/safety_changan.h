#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // STEER_ANGLE_SENSOR
#define CHANGAN_STEER_LKA        0x1BA // STEERING_LKA
#define CHANGAN_STEER_TORQUE     0x17E // STEER_TORQUE_SENSOR
#define CHANGAN_MFS_BUTTONS      0x28C // MFS_BUTTONS
#define CHANGAN_VEHICLE_SPEED    0x17A // VEHICLE_SPEED (ALT is 0x187 WHEEL_SPEEDS)
#define CHANGAN_WHEEL_SPEEDS     0x187 // WHEEL_SPEEDS
#define CHANGAN_BRAKE_MODULE     0x196 // BRAKE_MODULE
#define CHANGAN_BRAKE_ALT        0x1A6 // BRAKE_MODULE_ALT
#define CHANGAN_GAS_ALT          0x1C6 // GAS_PEDAL_ALT
#define CHANGAN_ACC_CONTROL      0x244 // ACC_CONTROL
#define CHANGAN_ACC_HUD          0x307 // ACC_HUD
#define CHANGAN_ACC_STATE        0x31A // ACC_STATE

// CAN bus numbers
#define CHANGAN_MAIN 0
#define CHANGAN_CAM  2

static uint8_t changan_crc8_lut[256];

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  int len = GET_LEN(to_push);
  return (uint32_t)GET_BYTE(to_push, len - 1);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  int len = GET_LEN(to_push);
  uint8_t crc = 0xFF;
  for (int i = 0; i < (len - 1); i++) {
    crc = changan_crc8_lut[crc ^ GET_BYTE(to_push, i)];
  }
  return (uint32_t)(crc ^ 0xFF);
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  uint8_t counter = 0;
  if (addr == CHANGAN_STEER_TORQUE) {
    counter = GET_BYTE(to_push, 6) & 0xFU; // 51|4@0+
  } else if (addr == CHANGAN_STEER_LKA) {
    counter = (GET_BYTE(to_push, 3) >> 7) | ((GET_BYTE(to_push, 4) & 0x7) << 1); // 31|4@0+
    // Note: 31|4 Big Endian is bits 31, 30, 29, 28.
    // In Byte 3 (bits 31-24), it's bit 31 (mask 0x80).
    // In Byte 4 (bits 23-16), it's bits 23, 22, 21? Wait.
    // 31|4@0+ Motorola:
    // start_bit 31 is Byte 3, Bit 7.
    // bits are 31, 30, 29, 28. These are all in Byte 3.
    // Wait, 31|4@0+ is Byte 3, bits 7, 6, 5, 4.
    counter = (GET_BYTE(to_push, 3) >> 4) & 0xFU;
  } else if (addr == CHANGAN_ACC_CONTROL) {
    counter = (GET_BYTE(to_push, 3) >> 4) & 0xFU; // 31|4@0+
  } else if (addr == CHANGAN_ACC_HUD) {
    counter = (GET_BYTE(to_push, 1) >> 4) & 0xFU; // 15|4@0+
  } else if (addr == CHANGAN_ACC_STATE) {
    counter = (GET_BYTE(to_push, 1) >> 4) & 0xFU; // 15|4@0+
  }
  return counter;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  if (GET_BUS(to_push) == CHANGAN_MAIN) {
    int addr = GET_ADDR(to_push);

    if (addr == CHANGAN_VEHICLE_SPEED || addr == CHANGAN_WHEEL_SPEEDS) {
      // Signal: VEHICLE_SPEED or WHEEL_SPEED_FL
      // Both are Big Endian, 7|16@0+, factor 0.01
      int speed = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      UPDATE_VEHICLE_SPEED(speed * 0.01 / 3.6);
    }

    if (addr == CHANGAN_STEER_ANGLE) {
      // Signal: STEER_ANGLE, factor: 0.1, Big Endian 7|16@0-
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      // Handle signed
      if (angle_meas_new > 0x7FFF) {
        angle_meas_new -= 0x10000;
      }
      update_sample(&angle_meas, angle_meas_new);
    }

    if (addr == CHANGAN_STEER_TORQUE) {
      // Signal: STEER_TORQUE_DRIVER, factor: 1.0, Big Endian 7|16@0-
      int torque_driver_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      if (torque_driver_new > 0x7FFF) {
        torque_driver_new -= 0x10000;
      }
      update_sample(&torque_driver, torque_driver_new);
    }

    if (addr == CHANGAN_MFS_BUTTONS) {
      // Signal: CRUISE_ENABLE_BUTTON
      bool cruise_engaged = (GET_BYTE(to_push, 0) & 0x1U) != 0;
      pcm_cruise_check(cruise_engaged);
    }

    if (addr == CHANGAN_BRAKE_MODULE) {
      // Signal: BRAKE_PRESSED
      brake_pressed = (GET_BYTE(to_push, 0) & 0x1U) != 0;
      gas_pressed = GET_BYTE(to_push, 1) > 0U; // GAS_PEDAL_USER at byte 1 (15|8@0+)
    }

    if (addr == CHANGAN_BRAKE_ALT) {
       // Signal: BRAKE_PRESSED
       brake_pressed = (GET_BYTE(to_push, 0) & 0x1U) != 0;
    }

    if (addr == CHANGAN_GAS_ALT) {
       // Signal: GAS_PEDAL_USER
       gas_pressed = GET_BYTE(to_push, 0) > 0U;
    }

    generic_rx_checks(false);
  }
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  static const AngleSteeringLimits CHANGAN_STEERING_LIMITS = {
    .max_angle = 4800,       // 480.0 deg
    .angle_deg_to_can = 10,  // 0.1 factor
    .angle_rate_up_lookup = {
      {5., 25., 25.},
      {0.3, 0.15, 0.15}      // 3.0 deg/s at 100Hz
    },
    .angle_rate_down_lookup = {
      {5., 25., 25.},
      {0.5, 0.25, 0.25}      // 5.0 deg/s at 100Hz
    },
    .frequency = 100U,
  };

  bool tx = true;
  int addr = GET_ADDR(to_send);
  int bus = GET_BUS(to_send);

  if (bus == CHANGAN_MAIN) {
    if (addr == CHANGAN_STEER_LKA) {
      int desired_angle = (GET_BYTE(to_send, 0) << 8) | GET_BYTE(to_send, 1);
      if (desired_angle > 0x7FFF) {
        desired_angle -= 0x10000;
      }

      if (steer_angle_cmd_checks(desired_angle, controls_allowed, CHANGAN_STEERING_LIMITS)) {
        tx = false;
      }
    }

    if (addr == CHANGAN_MFS_BUTTONS) {
      // Check for cancel button
      bool cancel_cmd = (GET_BYTE(to_send, 0) & 0x2U) != 0; // CANCEL_BUTTON at bit 1
      if (!controls_allowed && !cancel_cmd) {
        tx = false;
      }
    }
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;

  if (bus == CHANGAN_MAIN) {
    bus_fwd = CHANGAN_CAM;
  } else if (bus == CHANGAN_CAM) {
    bool block = (addr == CHANGAN_STEER_LKA) || (addr == CHANGAN_MFS_BUTTONS) ||
                 (addr == CHANGAN_ACC_CONTROL) || (addr == CHANGAN_ACC_HUD) || (addr == CHANGAN_ACC_STATE) ||
                 (addr == CHANGAN_STEER_TORQUE);
    if (!block) {
      bus_fwd = CHANGAN_MAIN;
    }
  }

  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_LKA, 0, 8},
    {CHANGAN_MFS_BUTTONS, 0, 8},
    {CHANGAN_STEER_TORQUE, 0, 8},
    {CHANGAN_ACC_CONTROL, 0, 8},
    {CHANGAN_ACC_HUD, 0, 8},
    {CHANGAN_ACC_STATE, 0, 8}
  };

  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE,   0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_STEER_TORQUE,  0, 8, .max_counter = 15U, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_MFS_BUTTONS,   0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 10U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_VEHICLE_SPEED, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, {CHANGAN_WHEEL_SPEEDS, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }}},
    {.msg = {{CHANGAN_BRAKE_MODULE,  0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, {CHANGAN_BRAKE_ALT, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, {CHANGAN_GAS_ALT, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}}},
  };

  UNUSED(param);
  gen_crc_lookup_table_8(0x1D, changan_crc8_lut);
  return BUILD_SAFETY_CFG(changan_rx_checks, CHANGAN_TX_MSGS);
}

const safety_hooks changan_hooks = {
  .init = changan_init,
  .rx = changan_rx_hook,
  .tx = changan_tx_hook,
  .fwd = changan_fwd_hook,
  .get_checksum = changan_get_checksum,
  .compute_checksum = changan_compute_checksum,
  .get_counter = changan_get_counter,
};
