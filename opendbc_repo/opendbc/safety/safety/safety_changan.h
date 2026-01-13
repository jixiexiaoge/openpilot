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

static uint8_t changan_crc8_lut[256];

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
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
  // Option 1 & 2: Diagnostic Override
  controls_allowed = true;

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
  }

  generic_rx_checks(false);
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  UNUSED(to_send);
  return true; // Force allow all transmissions for diagnostics
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
  // Option 1 & 2: Bypass Heartbeat and Multi-Layer Controls Allowed Check
  controls_allowed = true;
  heartbeat_engaged = true;
  heartbeat_engaged_mismatches = 0U;

  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, CHANGAN_MAIN, 32},
    {CHANGAN_ACC_COMMAND,   CHANGAN_MAIN, 32},
    {CHANGAN_ACC_HUD,       CHANGAN_CAM,  64},
    {CHANGAN_ADAS_INFO,     CHANGAN_CAM,  64},
    {CHANGAN_STEER_TORQUE,  CHANGAN_CAM,  8},
  };

  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE,    CHANGAN_MAIN, 8, .frequency = 100U, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_STEER_TORQUE,   CHANGAN_MAIN, 8, .frequency = 100U, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_CRUISE_BUTTONS, CHANGAN_MAIN, 8, .frequency = 50U,  .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_WHEEL_SPEEDS,   CHANGAN_MAIN, 8, .frequency = 100U, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_PEDAL_DATA,     CHANGAN_MAIN, 8, .frequency = 50U,  .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_ADAS_INFO,      CHANGAN_CAM,  64, .frequency = 10U,  .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
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
