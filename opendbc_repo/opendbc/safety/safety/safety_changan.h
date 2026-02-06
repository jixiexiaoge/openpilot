#pragma once

#include "safety_declarations.h"

// CAN message addresses from changan_can.dbc
#define CHANGAN_STEER_ANGLE      0x180  // GW_180 - Steering angle sensor
#define CHANGAN_STEER_COMMAND    0x1BA  // GW_1BA - Steering control command
#define CHANGAN_STEER_TORQUE     0x17E  // GW_17E - EPS torque and status
#define CHANGAN_EPS_STATUS       0x170  // GW_170 - EPS actual torque
#define CHANGAN_EPS_FAULT        0x24F  // GW_24F - EPS fault status
#define CHANGAN_WHEEL_SPEEDS     0x187  // GW_187 - Vehicle speed (Z6)
#define CHANGAN_IDD_WHEEL_SPEEDS 0x17A  // GW_17A - Vehicle speed (Z6 iDD)
#define CHANGAN_PEDAL_DATA       0x196  // GW_196 - Brake/gas pedal (Z6)
#define CHANGAN_IDD_PEDAL_DATA   0x1A6  // GW_1A6 - Brake pedal (Z6 iDD)
#define CHANGAN_IDD_GAS_DATA     0x1C6  // GW_1C6 - Gas pedal (Z6 iDD)
#define CHANGAN_PCU_PEDAL_DATA   0x17D  // GW_17D - Brake/gas pedal (A05)
#define CHANGAN_ACC_COMMAND      0x244  // GW_244 - ACC acceleration control
#define CHANGAN_CRUISE_BUTTONS   0x28C  // GW_28C - Cruise control buttons
#define CHANGAN_ADAS_INFO        0x31A  // GW_31A - ADAS HUD information
#define CHANGAN_CRUISE_SPEED     0x307  // GW_307 - Cruise speed setting
#define CHANGAN_GEAR_Z6          0x338  // GW_338 - Gear position (Z6/Z6 iDD)
#define CHANGAN_GEAR_A05         0x331  // GW_331 - Gear position (A05)
#define CHANGAN_DOOR_STATUS      0x28B  // GW_28B - Door and blinker status
#define CHANGAN_SEATBELT         0x50   // GW_50 - Seatbelt status
#define CHANGAN_BSM_INFO         0x2A4  // GW_2A4 - BSM status

// Angle steering limits
static const AngleSteeringLimits CHANGAN_STEER_LIMITS = {
  .max_angle = 4760,  // ±476 degrees (10x scale in CAN)
  .angle_deg_to_can = 10.,
  .angle_rate_up_lookup = { .x = {0, 5, 15}, .y = {5, 0.8, 0.15} },
  .angle_rate_down_lookup = { .x = {0, 5, 15}, .y = {5, 3.5, 0.4} },
  .max_angle_error = 100,  // 10 degrees
  .angle_error_min_speed = 5.0,  // m/s
  .angle_is_curvature = false,
  .enforce_angle_error = true,
  .inactive_angle_is_zero = false,
};

// Longitudinal limits
static const LongitudinalLimits CHANGAN_LONG_LIMITS = {
  .max_accel = 200,   // 2.0 m/s² (0.01 scale)
  .min_accel = -350,  // -3.5 m/s² (0.01 scale)
  .inactive_accel = 0,
  .max_gas = 0,
  .min_gas = 0,
  .inactive_gas = 0,
  .max_brake = 0,
  .max_transmission_rpm = 0,
  .min_transmission_rpm = 0,
  .inactive_transmission_rpm = 0,
  .inactive_speed = 0,
};

// Safety parameters
static uint16_t changan_eps_scale = 73;  // Default EPS scale (1-100%)
static bool changan_idd_variant = false;  // Hybrid (iDD) variant flag

static uint16_t changan_cruise_button_prev = 0U;
static bool changan_cruise_engaged = false;

// CRC8 lookup table for SAE J1850
static uint8_t changan_crc8_lut[256];

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  if (addr == 0x50) {
    return GET_BYTE(to_push, 3);
  }
  return GET_BYTE(to_push, 7);
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  // Control and HUD related messages use SAE J1850 CRC8
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x17D || addr == 0x244 ||
      addr == 0x28C || addr == 0x1BA || addr == 0x307 || addr == 0x31A ||
      addr == 0x170 || addr == 0x24F || addr == 0x338 || addr == 0x331 ||
      addr == 0x28B || addr == 0x2A4) {
    uint8_t crc = 0xFFU;
    for (int i = 0; i < 7; i++) {
      crc = changan_crc8_lut[crc ^ GET_BYTE(to_push, i)];
    }
    return (uint32_t)(crc ^ 0xFFU);
  }
  return 0;
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  // Counter position varies by message
  int addr = GET_ADDR(to_push);

  // Most messages have counter at bit 51-48 (byte 6, lower nibble)
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x17D || addr == 0x28C ||
      addr == 0x170 || addr == 0x24F || addr == 0x338 || addr == 0x331 ||
      addr == 0x28B || addr == 0x2A4) {
    return GET_BYTE(to_push, 6) & 0x0FU;
  }

  // 0x50 has counter at bits 23-20 (byte 2, lower nibble)
  if (addr == 0x50) {
    return GET_BYTE(to_push, 2) & 0x0FU;
  }

  // 0x1BA has counter at bit 51-48
  if (addr == 0x1BA) {
    return GET_BYTE(to_push, 6) & 0x0FU;
  }

  // 0x244 has counter at bit 51-48 (first segment)
  if (addr == 0x244) {
    return GET_BYTE(to_push, 6) & 0x0FU;
  }

  // 0x307 and 0x31A have multiple counters, use first one
  if (addr == 0x307 || addr == 0x31A) {
    return GET_BYTE(to_push, 6) & 0x0FU;
  }

  return 0;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  int bus = GET_BUS(to_push);

  // Only process bus 0 (PT-CAN) and bus 2 (CAM-CAN)
  if (bus != 0 && bus != 2) {
    return;
  }

  // Cruise button logic - rising edge detection for activation
  if (addr == CHANGAN_CRUISE_BUTTONS && bus == 0) {
    // Motorola: Byte 1 bit 4 is iACC enable, Byte 0 bit 1 is Cancel, bit 4 is RES+, bit 6 is SET-
    uint16_t b = (uint16_t)((GET_BYTE(to_push, 1) << 8) | GET_BYTE(to_push, 0));
    uint16_t current_button = b & 0x1052U; // iACC(0x1000), SET-(0x0040), RES+(0x0010), Cancel(0x0002)

    // Rising edge of iACC, RES+, or SET- enables cruise
    bool rising_edge = ((current_button & 0x1050U) != 0U) && ((changan_cruise_button_prev & 0x1050U) == 0U);
    if (rising_edge) {
      controls_allowed = true;
      changan_cruise_engaged = true;
    }

    // Cancel button disables cruise
    if ((current_button & 0x0002U) != 0U) { // Cancel button
      controls_allowed = false;
      changan_cruise_engaged = false;
    }

    changan_cruise_button_prev = current_button;
  }

  // Speed parsing - handle all variants
  if (addr == CHANGAN_WHEEL_SPEEDS && bus == 0) {
    // Z6: ESP_VehicleSpeed at bits 39-24 (bytes 3-4), 0.05 km/h scale
    int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 3);
    UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);  // Convert km/h to m/s
  }

  if (changan_idd_variant && addr == CHANGAN_IDD_WHEEL_SPEEDS && bus == 0) {
    // Z6 iDD: ESP_VehicleSpeed at bits 39-24 (bytes 3-4), 0.05 km/h scale
    int speed = (GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 3);
    UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);  // Convert km/h to m/s
  }

  // Pedal parsing - handle all variants
  if (addr == CHANGAN_PEDAL_DATA && bus == 0) {
    // Z6: EMS_BrakePedalStatus at bit 0, EMS_RealAccPedal at bit 20
    brake_pressed = (GET_BYTE(to_push, 0) & 0x01U) != 0U;
    gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0U;
  }

  if (changan_idd_variant && addr == CHANGAN_IDD_PEDAL_DATA && bus == 0) {
    // Z6 iDD: EMS_BrakePedalStatus at bit 4
    brake_pressed = (GET_BYTE(to_push, 0) & 0x10U) != 0U;
  }
  if (changan_idd_variant && addr == CHANGAN_IDD_GAS_DATA && bus == 0) {
    // Z6 iDD: EMS_RealAccPedal at bit 20 (Byte 2, bit 4)
    gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0U;
  }
  if (addr == CHANGAN_PCU_PEDAL_DATA && bus == 0) {
    // A05: PCU_BrkPedlSts at bit 0, PCU_RealAccPedl at bit 20
    brake_pressed = (GET_BYTE(to_push, 0) & 0x01U) != 0U;
    gas_pressed = (GET_BYTE(to_push, 2) & 0x10U) != 0U;
  }

  // Brake press disables cruise
  if (brake_pressed && !brake_pressed_prev) {
    controls_allowed = false;
    changan_cruise_engaged = false;
  }

  // Steering angle measurement for angle error check
  if (addr == CHANGAN_STEER_ANGLE && bus == 0) {
    // steeringAngleDeg at bits 7-15 (bytes 0-1), Motorola Signed, 0.1 deg scale
    // Byte 0 is MSB, Byte 1 is LSB
    int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
    angle_meas_new = to_signed(angle_meas_new, 16);
    update_sample(&angle_meas, angle_meas_new);
  }

  // Stock ECU detection - check for stock ACC messages on CAM bus
  bool stock_ecu_detected = (addr == CHANGAN_ACC_COMMAND && bus == 2);

  // Generic RX checks (gas, brake, steering disengage)
  generic_rx_checks(stock_ecu_detected);
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  int addr = GET_ADDR(to_send);
  int bus = GET_BUS(to_send);
  bool tx = true;

  // Only allow TX on bus 2 (CAM-CAN) for control messages
  if (bus != 2 && bus != 0) {
    return false;
  }

  // Steering control command (0x1BA)
  if (addr == CHANGAN_STEER_COMMAND) {
    // ACC_SteeringAngleSub_1BA at bits 31-17 (Bytes 3-2), Motorola signed, 0.1 deg scale
    // Byte 3 is MSB, Byte 2 bits 23-17 are LSB. Bit 16 is Req.
    int desired_angle = (GET_BYTE(to_send, 3) << 8) | (GET_BYTE(to_send, 2) & 0xFEU);
    desired_angle = to_signed(desired_angle >> 1, 15);

    // ACC_SteeringAngleReq_1BA at bit 16
    bool steer_req = (GET_BYTE(to_send, 2) & 0x01U) != 0U;

    // Check if controls are allowed
    if (steer_req && !controls_allowed) {
      tx = false;
    }

    // Check angle limits
    if (steer_angle_cmd_checks(desired_angle, steer_req, CHANGAN_STEER_LIMITS)) {
      tx = false;
    }
  }

  // ACC acceleration control command (0x244)
  if (addr == CHANGAN_ACC_COMMAND) {
    // ACC_Acceleration_24E at bits 7-15 (Bytes 0-1), Motorola signed, 0.05 m/s² scale
    // Byte 0 is MSB, Byte 1 is LSB.
    int desired_accel = (GET_BYTE(to_send, 0) << 8) | GET_BYTE(to_send, 1);
    desired_accel = to_signed(desired_accel, 16);
    desired_accel = desired_accel * 5;  // Convert from 0.05 to 0.01 m/s² scale for safety checks

    // ACC_ACCMode at bits 39-41 (byte 4, bits 7-5 and byte 5, bit 0)
    // Mode: 0=Off, 1=Standby, 2=Ready, 3=Active
    // We check mode >= 2 (Ready or Active) to determine if ACC is engaged
    uint8_t acc_mode = (GET_BYTE(to_send, 4) >> 7) | ((GET_BYTE(to_send, 5) & 0x03U) << 1);
    bool acc_engaged = (acc_mode >= 2U);

    // Check if controls are allowed
    if (acc_engaged && !controls_allowed) {
      tx = false;
    }

    // Check acceleration limits
    if (longitudinal_accel_checks(desired_accel, CHANGAN_LONG_LIMITS)) {
      tx = false;
    }
  }

  // Allow EPS status (0x17E), cruise speed (0x307), and ADAS HUD (0x31A) messages
  if (addr == CHANGAN_STEER_TORQUE || addr == CHANGAN_CRUISE_SPEED || addr == CHANGAN_ADAS_INFO) {
    return true;
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  // Forward PT-CAN (bus 0) to CAM-CAN (bus 2)
  if (bus == 0) {
    return 2;
  }

  // Forward CAM-CAN (bus 2) to PT-CAN (bus 0), except control messages
  if (bus == 2) {
    bool block = (addr == CHANGAN_STEER_COMMAND) || (addr == CHANGAN_ACC_COMMAND) ||
                 (addr == CHANGAN_CRUISE_SPEED) || (addr == CHANGAN_ADAS_INFO) ||
                 (addr == CHANGAN_STEER_TORQUE);
    if (!block) {
      return 0;
    }
  }

  return -1;
}

static safety_config changan_init(uint16_t param) {
  // Extract EPS scale from lower 8 bits (default 73)
  changan_eps_scale = param & 0xFFU;
  if (changan_eps_scale == 0U) {
    changan_eps_scale = 73U;  // Fallback to default
  }

  // Extract variant flags from upper bits
  // Bit 8: iDD variant (Z6 iDD)
  changan_idd_variant = (param & 0x100U) != 0U;

  // Generate CRC8 lookup table for SAE J1850
  gen_crc_lookup_table_8(0x1D, changan_crc8_lut);

  // Initialize state
  changan_cruise_button_prev = 0U;
  changan_cruise_engaged = false;
  controls_allowed = false;

  // TX messages allowed on CAM-CAN (bus 2)
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, 2, 32},
    {CHANGAN_ACC_COMMAND, 2, 32},
    {CHANGAN_STEER_TORQUE, 2, 8},
    {CHANGAN_CRUISE_SPEED, 2, 64},
    {CHANGAN_ADAS_INFO, 2, 64},
  };

  // RX checks for critical messages
  static RxCheck changan_rx_checks[] = {
    // Critical steering angle message (100Hz) - checksum and counter validated
    {.msg = {{CHANGAN_STEER_ANGLE, 0, 8, .frequency = 100U}, {0}, {0}}},
    // Cruise control buttons (25Hz) - checksum and counter validated
    {.msg = {{CHANGAN_CRUISE_BUTTONS, 0, 8, .frequency = 25U}, {0}, {0}}},
    // Wheel speed messages - support all variants (50-100Hz) - checksum and counter validated
    {.msg = {{CHANGAN_WHEEL_SPEEDS, 0, 8, .frequency = 100U},
             {CHANGAN_IDD_WHEEL_SPEEDS, 0, 8, .frequency = 100U}, {0}}},
    // Pedal data messages - support all variants (50-100Hz) - checksum and counter validated
    {.msg = {{CHANGAN_PEDAL_DATA, 0, 8, .frequency = 100U},
             {CHANGAN_IDD_PEDAL_DATA, 0, 8, .frequency = 100U}, {0}}},
    // EPS torque and status (100Hz) - checksum and counter validated
    {.msg = {{CHANGAN_STEER_TORQUE, 0, 8, .frequency = 100U}, {0}, {0}}},
    // Stock ACC command for relay malfunction detection (50Hz on CAM bus)
    {.msg = {{CHANGAN_ACC_COMMAND, 2, 32, .frequency = 50U}, {0}, {0}}},
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