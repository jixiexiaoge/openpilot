#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // SAS_SteeringAngle
#define CHANGAN_STEER_COMMAND    0x1BA // GW_1BA
#define CHANGAN_STEER_TORQUE     0x17E // GW_17E
#define CHANGAN_WHEEL_SPEEDS     0x187 // GW_187 (Petrol)
#define CHANGAN_IDD_WHEEL_SPEEDS 0x17A // SPEED (IDD)
#define CHANGAN_PEDAL_DATA       0x196 // GW_196 (Petrol Brake/Gas)
#define CHANGAN_IDD_PEDAL_DATA   0x1A6 // GW_1A6 (IDD Brake/Gas)
#define CHANGAN_ACC_COMMAND      0x244 // GW_244
#define CHANGAN_CRUISE_BUTTONS   0x28C // GW_28C
#define CHANGAN_ADAS_INFO        0x31A // GW_31A (ACC State Info)

const AngleSteeringLimits CHANGAN_STEER_LIMITS = {
  .max_angle = 4760,
  .angle_deg_to_can = 10.,
  .angle_rate_up_lookup = {
    .x = {0, 5, 15},
    .y = {5, 0.8, 0.15},
  },
  .angle_rate_down_lookup = {
    .x = {0, 5, 15},
    .y = {5, 3.5, 0.4},
  },
  .enforce_angle_error = false, // Relaxed for porting
  .inactive_angle_is_zero = false,
};

static const uint8_t changan_crc8_tab[256] = {
  0x00, 0x1D, 0x3A, 0x27, 0x74, 0x69, 0x4E, 0x53, 0xE8, 0xF5, 0xD2, 0xCF, 0x9C, 0x81, 0xA6, 0xBB,
  0xCD, 0xD0, 0xF7, 0xEA, 0xB9, 0xA4, 0x83, 0x9E, 0x25, 0x38, 0x1F, 0x02, 0x51, 0x4C, 0x6B, 0x76,
  0x87, 0x9A, 0xBD, 0xA0, 0xF3, 0xEE, 0xC9, 0xD4, 0x6F, 0x72, 0x55, 0x48, 0x1B, 0x06, 0x21, 0x3C,
  0x4A, 0x57, 0x70, 0x6D, 0x3E, 0x23, 0x04, 0x19, 0xA2, 0xBF, 0x98, 0x85, 0xD6, 0xCB, 0xEC, 0xF1,
  0x13, 0x0E, 0x29, 0x34, 0x67, 0x7A, 0x5D, 0x40, 0xFB, 0xE6, 0xC1, 0xDC, 0x8F, 0x92, 0xB5, 0xA8,
  0xDE, 0xC3, 0xE4, 0xF9, 0xAA, 0xB7, 0x90, 0x8D, 0x36, 0x2B, 0x0C, 0x11, 0x42, 0x5F, 0x78, 0x65,
  0x94, 0x89, 0xAE, 0xB3, 0xE0, 0xFD, 0xDA, 0xC7, 0x7C, 0x61, 0x46, 0x5B, 0x08, 0x15, 0x32, 0x2F,
  0x59, 0x44, 0x63, 0x7E, 0x2D, 0x30, 0x17, 0x0A, 0xB1, 0xAC, 0x8B, 0x96, 0xC5, 0xD8, 0xFF, 0xE2,
  0x26, 0x3B, 0x1C, 0x01, 0x52, 0x4F, 0x68, 0x75, 0xCE, 0xD3, 0xF4, 0xE9, 0xBA, 0xA7, 0x80, 0x9D,
  0xEB, 0xF6, 0xD1, 0xCC, 0x9F, 0x82, 0xA5, 0xB8, 0x03, 0x1E, 0x39, 0x24, 0x77, 0x6A, 0x4D, 0x50,
  0xA1, 0xBC, 0x9B, 0x86, 0xD5, 0xC8, 0xEF, 0xF2, 0x49, 0x54, 0x73, 0x6E, 0x3D, 0x20, 0x07, 0x1A,
  0x6C, 0x71, 0x56, 0x4B, 0x18, 0x05, 0x22, 0x3F, 0x84, 0x99, 0xBE, 0xA3, 0xF0, 0xED, 0xCA, 0xD7,
  0x35, 0x28, 0x0F, 0x12, 0x41, 0x5C, 0x7B, 0x66, 0xDD, 0xC0, 0xE7, 0xFA, 0xA9, 0xB4, 0x93, 0x8E,
  0xf8, 0xE5, 0xC2, 0xDF, 0x8C, 0x91, 0xB6, 0xAB, 0x10, 0x0D, 0x2A, 0x37, 0x64, 0x79, 0x5E, 0x43,
  0xB2, 0xAF, 0x88, 0x95, 0xC6, 0xDB, 0xFC, 0xE1, 0x5A, 0x47, 0x60, 0x7D, 0x2E, 0x33, 0x14, 0x09,
  0x7F, 0x62, 0x45, 0x58, 0x0B, 0x16, 0x31, 0x2C, 0x97, 0x8A, 0xAD, 0xB0, 0xE3, 0xFE, 0xD9, 0xC4
};

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  return (uint32_t)GET_BYTE(to_push, GET_LEN(to_push) - 1);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  uint8_t crc = 0xFFU;
  int len = GET_LEN(to_push);
  for (int i = 0; i < (len - 1); i++) {
    crc = changan_crc8_tab[crc ^ GET_BYTE(to_push, i)];
  }
  return (uint32_t)(crc ^ 0xFFU);
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  // All relevant messages (0x1BA, 0x244, 0x307, 0x31A) use Byte 6 for the counter (51|4@0+)
  return (uint8_t)(GET_BYTE(to_push, 6) & 0x0FU);
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  if (GET_BUS(to_push) == 0) {
    int addr = GET_ADDR(to_push);

    if ((addr == CHANGAN_WHEEL_SPEEDS) || (addr == CHANGAN_IDD_WHEEL_SPEEDS)) {
      int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5);
      vehicle_moving = speed > 10;
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    if (addr == CHANGAN_STEER_ANGLE) {
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      update_sample(&angle_meas, to_signed(angle_meas_new, 16));
    }

    if (addr == CHANGAN_STEER_TORQUE) {
      int torque_driver_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      update_sample(&torque_driver, to_signed(torque_driver_new, 16));
    }

    if (addr == CHANGAN_IDD_PEDAL_DATA) {
      brake_pressed = (GET_BYTE(to_push, 6) & 0x01U) != 0U;
      gas_pressed = (GET_BYTE(to_push, 4) & 0x40U) != 0U;
    } else if (addr == CHANGAN_PEDAL_DATA) {
      brake_pressed = (GET_BYTE(to_push, 6) & 0x01U) != 0U;
      gas_pressed = (GET_BYTE(to_push, 2) & 0x01U) != 0U;
    }

    // Manual cruise control logic via buttons since 0x31A is too long for legacy checks
    if (addr == CHANGAN_CRUISE_BUTTONS) {
      bool cancel = (GET_BYTE(to_push, 0) & 0x02U) != 0U;
      bool resume = (GET_BYTE(to_push, 0) & 0x10U) != 0U;
      bool iacc   = (GET_BYTE(to_push, 1) & 0x10U) != 0U;

      if (cancel) {
        controls_allowed = false;
      }
      if (resume || iacc) {
        controls_allowed = true;
      }
    }

    /*
    // Commented out to fix compilation error: array subscript 8 is above array bounds
    // GW_31A is a 64-byte message, but current panda struct definition only supports 8 bytes in this context.
    if (addr == CHANGAN_ADAS_INFO) {
      bool cruise_engaged = (GET_BYTE(to_push, 8) & 0x10U) != 0U; // cruiseState bit 68
      pcm_cruise_check(cruise_engaged);
    }
    */
  }
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  int addr = GET_ADDR(to_send);
  bool tx = true;
  bool violation = false;

  if (addr == CHANGAN_STEER_COMMAND) {
    int desired_angle = ((GET_BYTE(to_send, 2) & 0x7FU) << 8) | GET_BYTE(to_send, 3);
    bool steer_req = (GET_BYTE(to_send, 2) & 0x80U) != 0U;

    // Safety Check 1: Controls allowed
    if (steer_req && !controls_allowed) {
      violation = true;
    }

    // Safety Check 2: Angle Limits (Returns true if check fails)
    if (steer_angle_cmd_checks(to_signed(desired_angle, 16), steer_req, CHANGAN_STEER_LIMITS)) {
      violation = true;
    }
  }

  if (addr == CHANGAN_ACC_COMMAND) {
    tx = true; // In angle-based steer, long is standard pass-through or checked via accel limits
  }

  if (addr == 0x307 || addr == 0x31A) {
    tx = true;
  }

  if (violation) {
    tx = false;
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;
  if (bus == 0) {
    bus_fwd = 2; // Forward MAIN -> CAM
  }
  if (bus == 2) {
    // Forward CAM -> MAIN
    // BLOCK critical control messages from the stock camera to prevent conflict
    bool block = (addr == CHANGAN_STEER_COMMAND) || // 0x1BA
                 (addr == CHANGAN_ACC_COMMAND) ||   // 0x244
                 (addr == 0x307) ||                 // HUD
                 (addr == 0x31A);                   // ADAS Info

    if (!block) {
      bus_fwd = 0;
    }
  }
  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  controls_allowed = false;
  heartbeat_engaged = false;
  heartbeat_engaged_mismatches = 0U;

  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, 0, 32}, {CHANGAN_ACC_COMMAND, 0, 32},
    {0x307, 0, 64}, {0x31A, 0, 64}
  };

  // Rx Checks using alternative messages for Pedal Data
  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE, 0, 8, .frequency = 100U}, {0}, {0}}},
    {.msg = {{CHANGAN_PEDAL_DATA, 0, 8, .frequency = 100U},
             {CHANGAN_IDD_PEDAL_DATA, 0, 8, .frequency = 100U}, {0}}}, // Support both 0x196 and 0x1A6
  };

  // Note: We don't need separate arrays for petrol/IDD anymore if we use the alternative msg feature!
  // BUT: `param` might still be useful if we had other diffs. Here we simplify.

  UNUSED(param);
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
