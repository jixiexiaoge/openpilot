#pragma once

extern const uint16_t FLAG_VOLKSWAGEN_LONG_CONTROL;
const uint16_t FLAG_VOLKSWAGEN_LONG_CONTROL = 1;
extern const uint16_t FLAG_VOLKSWAGEN_ALT_CRC_VARIANT_1;
const uint16_t FLAG_VOLKSWAGEN_ALT_CRC_VARIANT_1 = 2;
extern const uint16_t FLAG_VOLKSWAGEN_NO_GAS_OFFSET;
const uint16_t FLAG_VOLKSWAGEN_NO_GAS_OFFSET = 4;
extern const uint16_t FLAG_VOLKSWAGEN_ALLOW_LONG_ACCEL_WITH_GAS_PRESSED;
const uint16_t FLAG_VOLKSWAGEN_ALLOW_LONG_ACCEL_WITH_GAS_PRESSED = 8;
extern const uint16_t FLAG_VOLKSWAGEN_PQ_ALC_MODULE;
const uint16_t FLAG_VOLKSWAGEN_PQ_ALC_MODULE = 32;

static uint8_t volkswagen_crc8_lut_8h2f[256]; // Static lookup table for CRC8 poly 0x2F, aka 8H2F/AUTOSAR

extern bool volkswagen_longitudinal;
bool volkswagen_longitudinal = false;

extern bool volkswagen_alt_crc_variant_1;
bool volkswagen_alt_crc_variant_1 = false;

extern bool volkswagen_no_gas_offset;
bool volkswagen_no_gas_offset = false;

extern bool volkswagen_allow_long_accel_with_gas_pressed;
bool volkswagen_allow_long_accel_with_gas_pressed = false;

extern bool volkswagen_set_button_prev;
bool volkswagen_set_button_prev = false;

extern bool volkswagen_resume_button_prev;
bool volkswagen_resume_button_prev = false;

extern bool volkswagen_brake_pedal_switch;
extern bool volkswagen_brake_pressure_detected;
bool volkswagen_brake_pedal_switch = false;
bool volkswagen_brake_pressure_detected = false;

// IQ ALC integration variables (stub, not used without IQ private modules)
extern float vw_iq_apd_steer_ratio;
extern float vw_iq_apd_wheelbase;
extern bool vw_iq_apd_params_valid;
float vw_iq_apd_steer_ratio = 0.0f;
float vw_iq_apd_wheelbase = 0.0f;
bool vw_iq_apd_params_valid = false;

extern float vw_iq_measured_angle_deg;
float vw_iq_measured_angle_deg = 0.0f;

extern bool vw_iq_aol_active;
bool vw_iq_aol_active = false;

extern float vw_iq_angle_offset_deg;
float vw_iq_angle_offset_deg = 0.0f;

extern float vw_iq_alc_desired_angle_deg;
float vw_iq_alc_desired_angle_deg = 0.0f;

extern bool vw_iq_alc_active;
bool vw_iq_alc_active = false;

#define MSG_LH_EPS_03        0x09F   // RX from EPS, for driver steering torque
#define MSG_ESP_19           0x0B2   // RX from ABS, for wheel speeds
#define MSG_ESP_05           0x106   // RX from ABS, for brake switch state
#define MSG_TSK_06           0x120   // RX from ECU, for ACC status from drivetrain coordinator
#define MSG_MOTOR_20         0x121   // RX from ECU, for driver throttle input
#define MSG_ACC_06           0x122   // TX by OP, ACC control instructions to the drivetrain coordinator
#define MSG_HCA_01           0x126   // TX by OP, Heading Control Assist steering torque
#define MSG_GRA_ACC_01       0x12B   // TX by OP, ACC control buttons for cancel/resume
#define MSG_ACC_07           0x12E   // TX by OP, ACC control instructions to the drivetrain coordinator
#define MSG_ACC_02           0x30C   // TX by OP, ACC HUD data to the instrument cluster
#define MSG_LDW_02           0x397   // TX by OP, Lane line recognition and text alerts
#define MSG_MOTOR_14         0x3BE   // RX from ECU, for brake switch status

// MLB only messages
#define MSG_ESP_03      0x103U
#define MSG_LS_01       0x10BU
#define MSG_MOTOR_03    0x105U
#define MSG_TSK_02      0x10CU
#define MSG_ACC_05      0x10DU
#define MSG_ACC_01      0x109U


static void volkswagen_common_init(void) {
  volkswagen_set_button_prev = false;
  volkswagen_resume_button_prev = false;
  volkswagen_brake_pedal_switch = false;
  volkswagen_brake_pressure_detected = false;
  volkswagen_alt_crc_variant_1 = false;
  volkswagen_no_gas_offset = false;
  volkswagen_allow_long_accel_with_gas_pressed = false;
  vw_iq_apd_steer_ratio = 0.0f;
  vw_iq_apd_wheelbase = 0.0f;
  vw_iq_apd_params_valid = false;
  vw_iq_aol_active = false;
  vw_iq_angle_offset_deg = 0.0f;
  vw_iq_alc_desired_angle_deg = 0.0f;
  vw_iq_alc_active = false;
  vw_iq_measured_angle_deg = 0.0f;
  gen_crc_lookup_table_8(0x2F, volkswagen_crc8_lut_8h2f);
  return;
}

bool volkswagen_longitudinal_accel_checks(int desired_accel, const LongitudinalLimits limits) {
  bool accel_valid = controls_allowed &&
                     (volkswagen_allow_long_accel_with_gas_pressed || !gas_pressed_prev) &&
                     !safety_max_limit_check(desired_accel, limits.max_accel, limits.min_accel);
  bool accel_inactive = desired_accel == limits.inactive_accel;
  return !(accel_valid || accel_inactive);
}

static uint32_t volkswagen_mqb_meb_get_checksum(const CANPacket_t *to_push) {
  return (uint8_t)GET_BYTE(to_push, 0);
}

static uint8_t volkswagen_mqb_meb_get_counter(const CANPacket_t *to_push) {
  return (uint8_t)GET_BYTE(to_push, 1) & 0xFU;
}

static uint32_t volkswagen_mqb_meb_compute_crc(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  int len = GET_LEN(to_push);

  uint8_t crc = 0xFFU;
  for (int i = 1; i < len; i++) {
    crc ^= (uint8_t)GET_BYTE(to_push, i);
    crc = volkswagen_crc8_lut_8h2f[crc];
  }

  uint8_t counter = volkswagen_mqb_meb_get_counter(to_push);
  if (addr == MSG_LH_EPS_03) {
    crc ^= (uint8_t[]){0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5}[counter];
  } else if (addr == MSG_ESP_05) {
    crc ^= (uint8_t[]){0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07,0x07}[counter];
  } else if (addr == MSG_TSK_06) {
    crc ^= (uint8_t[]){0xC4,0xE2,0x4F,0xE4,0xF8,0x2F,0x56,0x81,0x9F,0xE5,0x83,0x44,0x05,0x3F,0x97,0xDF}[counter];
  } else if (addr == MSG_MOTOR_20) {
    crc ^= (uint8_t[]){0xE9,0x65,0xAE,0x6B,0x7B,0x35,0xE5,0x5F,0x4E,0xC7,0x86,0xA2,0xBB,0xDD,0xEB,0xB4}[counter];
  } else if (addr == MSG_GRA_ACC_01) {
    crc ^= (uint8_t[]){0x6A,0x38,0xB4,0x27,0x22,0xEF,0xE1,0xBB,0xF8,0x80,0x84,0x49,0xC7,0x9E,0x1E,0x2B}[counter];
  } else {
    // Undefined CAN message, CRC check expected to fail
  }
  crc = volkswagen_crc8_lut_8h2f[crc];

  return (uint8_t)(crc ^ 0xFFU);
}

static int volkswagen_mlb_mqb_driver_input_torque(const CANPacket_t *msg) {
  int torque_driver_new = GET_BYTE(msg, 5) | ((GET_BYTE(msg, 6) & 0x1FU) << 8);
  bool sign = GET_BIT(msg, 55U);
  if (sign) {
    torque_driver_new *= -1;
  }
  return torque_driver_new;
}

static int volkswagen_mlb_mqb_steering_control_torque(const CANPacket_t *msg) {
  int desired_torque = GET_BYTE(msg, 2) | ((GET_BYTE(msg, 3) & 0x1U) << 8);
  bool sign = GET_BIT(msg, 31U);
  if (sign) {
    desired_torque *= -1;
  }
  return desired_torque;
}
