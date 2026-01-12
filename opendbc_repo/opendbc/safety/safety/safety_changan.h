#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // GW_180
#define CHANGAN_STEER_COMMAND    0x1BA // GW_1BA
#define CHANGAN_STEER_TORQUE     0x17E // GW_17E
#define CHANGAN_WHEEL_SPEEDS     0x187 // GW_187
#define CHANGAN_PEDAL_DATA       0x196 // GW_196
#define CHANGAN_ACC_COMMAND      0x244 // GW_244
#define CHANGAN_CRUISE_BUTTONS   0x652 // GW_MFS_IACC
#define CHANGAN_ACC_HUD          0x307 // GW_307
#define CHANGAN_ADAS_INFO        0x31A // GW_31A
#define CHANGAN_EPS_INFO         0x591 // EPS_591
#define CHANGAN_GEAR             0x338 // GW_338
#define CHANGAN_GW_50            0x50  // GW_50 (Seatbelt)
#define CHANGAN_BODY_INFO        0x28B // GW_28B

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

    if (addr == CHANGAN_WHEEL_SPEEDS) {
      // Signal: WHEEL_SPEED_FL (39|16@0+, factor 0.05)
      int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5);
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    if (addr == CHANGAN_STEER_ANGLE) {
      // Signal: STEER_ANGLE (7|16@0-, factor 0.1)
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      angle_meas_new = to_signed(angle_meas_new, 16);
      update_sample(&angle_meas, angle_meas_new);
    }

    if (addr == CHANGAN_STEER_TORQUE) {
      // Signal: STEER_TORQUE_DRIVER (7|16@0-, factor 0.001)
      int torque_driver_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      torque_driver_new = to_signed(torque_driver_new, 16);
      update_sample(&torque_driver, torque_driver_new);
    }

    if (addr == CHANGAN_CRUISE_BUTTONS) {
      // Signal: GW_MFS_ACC at bit 0 (0|1@0+)
      // Signal: GW_MFS_Cancel at bit 1 (1|1@0+)
      bool main_button = (GET_BYTE(to_push, 0) & 0x1U) != 0;
      bool cancel_button = (GET_BYTE(to_push, 0) & 0x2U) != 0;
      static bool main_button_prev = false;

      if (main_button && !main_button_prev) {
        controls_allowed = true;
      }
      if (cancel_button) {
        controls_allowed = false;
      }
      main_button_prev = main_button;
    }

    if (addr == CHANGAN_PEDAL_DATA) {
      // Signal: BRAKE_PRESSED at 54 (Byte 6, bit 6), GAS_PEDAL_USER at 20 (Byte 2, bit 4)
      brake_pressed = (GET_BYTE(to_push, 6) & 0x40U) != 0;
      gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0;
      if (brake_pressed) {
        pcm_cruise_check(false);
      }
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
    if (addr == CHANGAN_STEER_COMMAND) {
      // Signal: STEER_ANGLE_CMD (7|16@0-)
      int desired_angle = (GET_BYTE(to_send, 0) << 8) | GET_BYTE(to_send, 1);
      desired_angle = to_signed(desired_angle, 16);

      if (steer_angle_cmd_checks(desired_angle, controls_allowed, CHANGAN_STEERING_LIMITS)) {
        tx = false;
      }
    }

    if (addr == CHANGAN_CRUISE_BUTTONS) {
      tx = true;
    }
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;

  if (bus == CHANGAN_MAIN) {
    bus_fwd = CHANGAN_CAM;
  } else if (bus == CHANGAN_CAM) {
    // Block control signals if we are re-sending them from openpilot
    bool block = (addr == CHANGAN_STEER_COMMAND) || (addr == CHANGAN_CRUISE_BUTTONS) ||
                 (addr == CHANGAN_ACC_COMMAND) || (addr == CHANGAN_ACC_HUD) || (addr == CHANGAN_ADAS_INFO) ||
                 (addr == CHANGAN_STEER_TORQUE);
    if (!block) {
      bus_fwd = CHANGAN_MAIN;
    }
  }

  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  controls_allowed = true;

  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, CHANGAN_MAIN, 32},
    {CHANGAN_ACC_COMMAND,   CHANGAN_MAIN, 32},
    {CHANGAN_ACC_HUD,       CHANGAN_CAM,  64},
    {CHANGAN_ADAS_INFO,     CHANGAN_CAM,  64},
    {CHANGAN_STEER_TORQUE,  CHANGAN_MAIN, 8},
  };

  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE,    CHANGAN_MAIN, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_STEER_TORQUE,   CHANGAN_MAIN, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_CRUISE_BUTTONS, CHANGAN_MAIN, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_WHEEL_SPEEDS,   CHANGAN_MAIN, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_PEDAL_DATA,     CHANGAN_MAIN, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_ADAS_INFO,      CHANGAN_CAM, 64, .ignore_checksum = true, .ignore_counter = true, .frequency = 10U}, { 0 }, { 0 }}},
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
