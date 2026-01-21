#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // SAS_SteeringAngle
#define CHANGAN_STEER_COMMAND    0x1BA // GW_1BA
#define CHANGAN_STEER_TORQUE     0x17E // GW_17E
#define CHANGAN_WHEEL_SPEEDS     0x187 // GW_187
#define CHANGAN_PEDAL_DATA       0x196 // GW_196 (Brake Module / Pedal)
#define CHANGAN_ACC_COMMAND      0x244 // GW_244
#define CHANGAN_CRUISE_BUTTONS   0x28C // GW_28C (Decimal 652)
#define CHANGAN_ACC_HUD          0x307 // GW_307
#define CHANGAN_ADAS_INFO        0x31A // GW_31A (ACC State Info)
#define CHANGAN_EPS_INFO         0x24F // EPS_591 (Decimal 591)
#define CHANGAN_GEAR             0x338 // GW_338
#define CHANGAN_BODY_INFO        0x28B // GW_28B

// CAN bus numbers
#define CHANGAN_MAIN 0
#define CHANGAN_CAM  2



static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  return (uint32_t)GET_BYTE(to_push, GET_LEN(to_push) - 1);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  uint8_t checksum = 0U;
  int len = GET_LEN(to_push);
  for (int i = 0; i < (len - 1); i++) {
    checksum ^= GET_BYTE(to_push, i);
  }
  return (uint32_t)checksum;
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  return GET_BYTE(to_push, 6) & 0xFU;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  if (GET_BUS(to_push) == CHANGAN_MAIN) {
    int addr = GET_ADDR(to_push);

    if (addr == CHANGAN_WHEEL_SPEEDS) {
      int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5);
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    if (addr == CHANGAN_STEER_ANGLE) {
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      angle_meas_new = to_signed(angle_meas_new, 16);
      update_sample(&angle_meas, angle_meas_new);
    }

    if (addr == CHANGAN_STEER_TORQUE) {
      int torque_driver_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      torque_driver_new = to_signed(torque_driver_new, 16);
      update_sample(&torque_driver, torque_driver_new);
    }

    if (addr == CHANGAN_PEDAL_DATA) {
      brake_pressed = (GET_BYTE(to_push, 6) & 0x40) != 0; // Bit 54 (Byte 6, bit 6)
      gas_pressed = (GET_BYTE(to_push, 2) & 0x10) != 0; // Bit 20 (Byte 2, bit 4)
    }

    if (addr == CHANGAN_CRUISE_BUTTONS) {
      bool cancel = (GET_BYTE(to_push, 0) & 0x02) != 0; // Bit 1
      bool resume = (GET_BYTE(to_push, 0) & 0x10) != 0; // Bit 4
      bool iacc = (GET_BYTE(to_push, 1) & 0x10) != 0; // Bit 12 (Byte 1, bit 4)

      if ((resume || iacc) && !controls_allowed) {
        controls_allowed = true;
      }
      if (cancel && controls_allowed) {
        controls_allowed = false;
      }
    }
  }

  generic_rx_checks(false);
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  int addr = GET_ADDR(to_send);
  int bus = GET_BUS(to_send);

  // Simple validation: just check if the address and bus combination is allowed
  // All messages go to bus 0, then fwd_hook forwards them to bus 2
  if (addr == CHANGAN_STEER_COMMAND && bus == CHANGAN_MAIN) return true;   // 0x1BA / 442
  if (addr == CHANGAN_ACC_COMMAND && bus == CHANGAN_MAIN) return true;     // 0x244 / 580
  if (addr == CHANGAN_ACC_HUD && bus == CHANGAN_MAIN) return true;         // 0x307 / 775
  if (addr == CHANGAN_ADAS_INFO && bus == CHANGAN_MAIN) return true;       // 0x31A / 794
  if (addr == CHANGAN_STEER_TORQUE && bus == CHANGAN_CAM) return true;     // 0x17E / 382 on bus 2

  return false; // Reject all other messages
}

static int changan_fwd_hook(int bus, int addr) {
  UNUSED(addr);
  int bus_fwd = -1;
  if (bus == CHANGAN_MAIN) {
    bus_fwd = CHANGAN_CAM;
  } else if (bus == CHANGAN_CAM) {
    bus_fwd = CHANGAN_MAIN;
  }
  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  controls_allowed = false;
  heartbeat_engaged = false;
  heartbeat_engaged_mismatches = 0U;

  // Corrected bus assignments and message lengths based on DBC file:
  // - GW_1BA: 32 bytes (0x1BA / 442)
  // - GW_244: 32 bytes (0x244 / 580)
  // - GW_307: 64 bytes (0x307 / 775)
  // - GW_31A: 64 bytes (0x31A / 794)
  // - GW_17E: 8 bytes (0x17E / 382)
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, CHANGAN_MAIN, 32},  // 0x1BA on bus 0, 32 bytes
    {CHANGAN_ACC_COMMAND,   CHANGAN_MAIN, 32},  // 0x244 on bus 0, 32 bytes
    {CHANGAN_ACC_HUD,       CHANGAN_MAIN, 64},  // 0x307 on bus 0, 64 bytes
    {CHANGAN_ADAS_INFO,     CHANGAN_MAIN, 64},  // 0x31A on bus 0, 64 bytes
    {CHANGAN_STEER_TORQUE,  CHANGAN_CAM,  8},   // 0x17E on bus 2, 8 bytes
  };
  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_WHEEL_SPEEDS, CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 100U}, {0}, {0}}},
    {.msg = {{CHANGAN_PEDAL_DATA, CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 100U}, {0}, {0}}},
    {.msg = {{CHANGAN_CRUISE_BUTTONS, CHANGAN_MAIN, 8, .max_counter = 15U, .frequency = 25U}, {0}, {0}}},
  };

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
