#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // STEER_ANGLE_SENSOR
#define CHANGAN_STEER_LKA        0x1BA // STEERING_LKA
#define CHANGAN_STEER_TORQUE     0x17E // STEER_TORQUE_SENSOR
#define CHANGAN_VEHICLE_SPEED    0x17A // VEHICLE_SPEED
#define CHANGAN_WHEEL_SPEEDS     0x187 // WHEEL_SPEEDS
#define CHANGAN_BRAKE_MODULE     0x196 // BRAKE_MODULE
#define CHANGAN_BRAKE_ALT        0x1A6 // BRAKE_MODULE_ALT
#define CHANGAN_GAS_ALT          0x1C6 // GAS_PEDAL_ALT
#define CHANGAN_ACC_CONTROL      0x244 // ACC_CONTROL
#define CHANGAN_ACC_BUTTONS      0x28C // ACC_BUTTONS
#define CHANGAN_ACC_HUD          0x307 // DISTANCE_LEVEL (formerly ACC_HUD)
#define CHANGAN_ACC_STATE        0x31A // ACC_STATE
#define CHANGAN_EPS_STATUS       0x24F // EPS_STATUS
#define CHANGAN_GEAR             0x338 // GEAR_PACKET
#define CHANGAN_BODY_STATE       0x50  // BODY_CONTROL_STATE
#define CHANGAN_BODY_STATE_2     0x28B // BODY_CONTROL_STATE_2

// CAN bus numbers
#define CHANGAN_MAIN 0
#define CHANGAN_CAM  2

static uint8_t changan_crc8_lut[256];

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  // All standardized messages have CHECKSUM at bit 63 (Byte 7)
  return (uint32_t)GET_BYTE(to_push, 7);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  uint8_t crc = 0xFF;
  for (int i = 0; i < 7; i++) {
    crc = changan_crc8_lut[crc ^ GET_BYTE(to_push, i)];
  }
  return (uint32_t)(crc ^ 0xFF);
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  return GET_BYTE(to_push, 6) & 0xFU;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  if (GET_BUS(to_push) == CHANGAN_MAIN) {
    int addr = GET_ADDR(to_push);

    if (addr == CHANGAN_VEHICLE_SPEED || addr == CHANGAN_WHEEL_SPEEDS) {
      // Signal: VEHICLE_SPEED or WHEEL_SPEED_FL
      // Both are Big Endian, 39|16@0+, factor 0.05 (updated from 0.01)
      // Byte 4 is MSB, Byte 5 is LSB in openpilot's big-endian interpretation of bits
      int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5);
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    if (addr == CHANGAN_STEER_ANGLE) {
      // Signal: STEER_ANGLE, factor: 0.1, Big Endian 7|16@0-
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      angle_meas_new = to_signed(angle_meas_new, 16);
      update_sample(&angle_meas, angle_meas_new);
    }

    if (addr == CHANGAN_STEER_TORQUE) {
      // Signal: STEER_TORQUE_DRIVER, factor: 0.01, Big Endian 7|16@0-
      int torque_driver_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      torque_driver_new = to_signed(torque_driver_new, 16);
      update_sample(&torque_driver, torque_driver_new);
    }

    if (addr == CHANGAN_ACC_BUTTONS) {
      // Manual engagement toggle from Carrot
      // Signal: GW_MFS_IACCenable_switch_signal at bit 0 (0|1@0+)
      // Signal: GW_MFS_Cancle_switch_signal at bit 1 (1|1@0+)
      bool iacc_button = (GET_BYTE(to_push, 0) & 0x1U) != 0;
      bool cancel_button = (GET_BYTE(to_push, 0) & 0x2U) != 0;
      static bool iacc_button_prev = false;

      if (iacc_button && !iacc_button_prev) {
        pcm_cruise_check(!controls_allowed);
      }
      if (cancel_button) {
        pcm_cruise_check(false);
      }
      iacc_button_prev = iacc_button;
    }

    if (addr == CHANGAN_BRAKE_MODULE) {
      // Signal: BRAKE_PRESSED at 54|1, GAS_PEDAL_USER at 20|1
      brake_pressed = (GET_BYTE(to_push, 6) & 0x40U) != 0; // Bit 54 is Byte 6, Bit 6
      gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0;   // Bit 20 is Byte 2, Bit 4
      if (brake_pressed) {
        pcm_cruise_check(false);
      }
    }

    if (addr == CHANGAN_BRAKE_ALT) {
       // Signal: BRAKE_PRESSED
       brake_pressed = (GET_BYTE(to_push, 0) & 0x1U) != 0;
    }

    if (addr == CHANGAN_GAS_ALT) {
       // Signal: GAS_PEDAL_USER (7|8@0+) is Byte 0
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

    if (addr == CHANGAN_ACC_BUTTONS) {
      // Check for cancel button
      // Signal: GW_MFS_Cancle_switch_signal at bit 1 (1|1@0+)
      // bool cancel_cmd = (GET_BYTE(to_send, 0) & 0x2U) != 0;
      // Allow engagement bypass for debugging
      // if (!controls_allowed && !cancel_cmd) {
      //   tx = false;
      // }
      tx = true; // Temporary permissive TX for debugging
    }
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;

  if (bus == CHANGAN_MAIN) {
    bus_fwd = CHANGAN_CAM;
  } else if (bus == CHANGAN_CAM) {
    bool block = (addr == CHANGAN_STEER_LKA) || (addr == CHANGAN_ACC_BUTTONS) ||
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
    {CHANGAN_STEER_LKA, 0, 32},
    {CHANGAN_ACC_BUTTONS, 0, 8},
    {CHANGAN_STEER_TORQUE, 0, 8},
    {CHANGAN_ACC_CONTROL, 0, 32},
    {CHANGAN_ACC_HUD, 0, 64},
    {CHANGAN_ACC_STATE, 0, 64}
  };

  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE,   CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_STEER_TORQUE,  CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_ACC_BUTTONS,   CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 25U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_VEHICLE_SPEED, CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_BRAKE_MODULE,  CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_ACC_STATE,     CHANGAN_CAM, 64, .max_counter = 15U, .frequency = 10U}, { 0 }, { 0 }}},
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
