#pragma once

#include "safety_declarations.h"

// CAN msgs matching changan_can.dbc
#define CHANGAN_STEER_ANGLE      0x180
#define CHANGAN_STEER_COMMAND    0x1BA
#define CHANGAN_STEER_TORQUE     0x17E
#define CHANGAN_WHEEL_SPEEDS     0x187
#define CHANGAN_IDD_WHEEL_SPEEDS 0x17A
#define CHANGAN_PEDAL_DATA       0x196
#define CHANGAN_IDD_PEDAL_DATA   0x1A6
#define CHANGAN_ACC_COMMAND      0x244
#define CHANGAN_CRUISE_BUTTONS   0x28C
#define CHANGAN_ADAS_INFO        0x31A

const AngleSteeringLimits CHANGAN_STEER_LIMITS = {
  .max_angle = 4760,
  .angle_deg_to_can = 10.,
  .angle_rate_up_lookup = { .x = {0, 5, 15}, .y = {5, 0.8, 0.15} },
  .angle_rate_down_lookup = { .x = {0, 5, 15}, .y = {5, 3.5, 0.4} },
};

static uint16_t changan_cruise_button_prev = 0U;

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  return GET_BYTE(to_push, 7);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  // Control and HUD related messages use SAE J1850 CRC8
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x244 || addr == 0x28C ||
      addr == 0x1BA || addr == 0x307 || addr == 0x31A) {
    uint8_t crc = 0xFFU;
    for (int i = 0; i < 7; i++) {
      crc ^= GET_BYTE(to_push, i);
      for (int b = 0; b < 8; b++) {
        if ((crc & 0x80U) != 0U) {
          crc = (uint8_t)((crc << 1) ^ 0x1DU);
        } else {
          crc <<= 1;
        }
      }
    }
    return (uint32_t)(crc ^ 0xFFU);
  }
  return 0;
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  // Typical counter position (bit 51-48, Motorola)
  return GET_BYTE(to_push, 6) & 0x0FU;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  int bus = GET_BUS(to_push);

  if (addr == CHANGAN_CRUISE_BUTTONS) {
    // Motorola: 0x28C Byte 1 bit 4 is Button_iACC (0x1000 in word), 0x28C Byte 0 bit 4 is RES+, bit 6 is SET-
    uint16_t b = (uint16_t)((GET_BYTE(to_push, 1) << 8) | GET_BYTE(to_push, 0));
    uint16_t current_button = (b & 0x1052U); // iACC, SET-, RES+, Cancel

    bool rising_edge = ((current_button & 0x1050U) != 0U) && ((changan_cruise_button_prev & 0x1050U) == 0U);
    if (rising_edge) {
      controls_allowed = true;
    }
    if ((current_button & 0x0002U) != 0U) { // Cancel
      controls_allowed = false;
    }
    changan_cruise_button_prev = current_button;
  }

  // Speed parsing based on Motorola 39|16
  if (bus == 0) {
    if (addr == CHANGAN_WHEEL_SPEEDS || addr == CHANGAN_IDD_WHEEL_SPEEDS) {
      int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 3);
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }
    if (addr == CHANGAN_PEDAL_DATA) {
        brake_pressed = (GET_BYTE(to_push, 0) & 0x01U) != 0U;
        gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0U;
    }
    if (addr == CHANGAN_IDD_PEDAL_DATA) {
        brake_pressed = (GET_BYTE(to_push, 0) & 0x10U) != 0U; // Check DBC for correct bit
        // gas_pressed = ...
    }
  }
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  int addr = GET_ADDR(to_send);
  bool tx = true;

  if (addr == CHANGAN_STEER_COMMAND) {
    int desired_angle = (GET_BYTE(to_send, 3) << 8) | GET_BYTE(to_send, 2);
    bool steer_req = (GET_BYTE(to_send, 2) & 0x01U) != 0U;
    if (steer_req && !controls_allowed) { tx = false; }
    if (steer_angle_cmd_checks(to_signed(desired_angle, 16), steer_req, CHANGAN_STEER_LIMITS)) { tx = false; }
  }

  if (addr == CHANGAN_ACC_COMMAND) {
    bool acc_req = (GET_BYTE(to_send, 6) & 0x80U) != 0U;
    if (acc_req && !controls_allowed) { tx = false; }
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  if (bus == 0) { return 2; }
  if (bus == 2) {
    bool block = (addr == CHANGAN_STEER_COMMAND) || (addr == CHANGAN_ACC_COMMAND) ||
                 (addr == 0x307) || (addr == 0x31A) || (addr == 0x17E);
    if (!block) { return 0; }
  }
  return -1;
}

static safety_config changan_init(uint16_t param) {
  UNUSED(param);
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, 0, 32}, {CHANGAN_ACC_COMMAND, 0, 32},
    {0x17E, 0, 8}, {0x307, 0, 64}, {0x31A, 0, 64},
  };
  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, {0}, {0}}},
    {.msg = {{CHANGAN_CRUISE_BUTTONS, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 10U}, {0}, {0}}},
  };
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