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

#define VW_IQ_MAX_LAT_ACCEL   3.0f
#define VW_IQ_MAX_LONG_ACCEL  2000
#define VW_IQ_MIN_LONG_ACCEL  -3500
#define VW_IQ_INACTIVE_LONG_ACCEL 3010
#define VW_IQ_DEG_TO_RAD      0.017453292f

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

extern float vw_iq_debug_lat_accel;
float vw_iq_debug_lat_accel = 0.0f;

void can_send(CANPacket_t *to_push, uint8_t bus_number, bool skip_tx_hook);
void can_set_checksum(CANPacket_t *packet);

#define MSG_LH_EPS_03        0x09FU   // RX from EPS, for driver steering torque
#define MSG_ESP_19           0x0B2U   // RX from ABS, for wheel speeds
#define MSG_ESP_05           0x106U   // RX from ABS, for brake switch state
#define MSG_TSK_06           0x120U   // RX from ECU, for ACC status from drivetrain coordinator
#define MSG_MOTOR_20         0x121U   // RX from ECU, for driver throttle input
#define MSG_ACC_06           0x122U   // TX by OP, ACC control instructions to the drivetrain coordinator
#define MSG_HCA_01           0x126U   // TX by OP, Heading Control Assist steering torque
#define MSG_GRA_ACC_01       0x12BU   // TX by OP, ACC control buttons for cancel/resume
#define MSG_ACC_07           0x12EU   // TX by OP, ACC control instructions to the drivetrain coordinator
#define MSG_ACC_02           0x30CU   // TX by OP, ACC HUD data to the instrument cluster
#define MSG_LDW_02           0x397U   // TX by OP, Lane line recognition and text alerts
#define MSG_MOTOR_14         0x3BEU   // RX from ECU, for brake switch status

// MLB only messages
#define MSG_ESP_03      0x103U   // RX from ABS, for wheel speeds
#define MSG_LS_01       0x10BU   // TX by OP, ACC control buttons for cancel/resume
#define MSG_MOTOR_03    0x105U   // RX from ECU, for driver throttle input and brake switch status
#define MSG_TSK_02      0x10CU   // RX from ECU, for ACC status from drivetrain coordinator
#define MSG_ACC_05      0x10DU   // RX from radar, for ACC status
#define MSG_ACC_01      0x109U   // RX from radar, for ACC status (Audi B8)

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

static void volkswagen_iq_decode_apd(const CANPacket_t *msg) {
  uint8_t version = (msg->data[1] >> 4) & 0x0FU;
  uint8_t flags = msg->data[2] & 0x0FU;
  if (version == 1U) {
    vw_iq_aol_active = (flags & 0x08U) != 0U;
    uint16_t angle_offset_raw = ((msg->data[5] >> 2) & 0x3FU) | (((uint16_t)msg->data[6] & 0x1FU) << 6);
    vw_iq_angle_offset_deg = (float)angle_offset_raw * 0.01f - 10.0f;
  }
  if ((version == 1U) && (flags & 0x01U)) {
    uint16_t sr_raw = ((msg->data[2] >> 4) & 0x0FU) | (((uint16_t)msg->data[3] & 0x7FU) << 4);
    uint16_t wb_raw = ((msg->data[3] >> 7) & 0x01U) | (((uint16_t)msg->data[4]) << 1) | (((uint16_t)msg->data[5] & 0x03U) << 9);
    vw_iq_apd_steer_ratio = (float)sr_raw * 0.01f + 8.0f;
    vw_iq_apd_wheelbase = ((float)wb_raw + 2000.0f) * 0.001f;
    vw_iq_apd_params_valid = (vw_iq_apd_steer_ratio > 1.0f) && (vw_iq_apd_wheelbase > 1.0f);
  }
}

static bool volkswagen_iq_lat_accel_torque_check(int desired_torque) {
  if (!controls_allowed && !vw_iq_aol_active) {
    vw_iq_debug_lat_accel = 0.0f;
    return desired_torque != 0;
  }

  if (!vw_iq_apd_params_valid) {
    vw_iq_debug_lat_accel = 0.0f;
    return false;
  }

  float speed_ms = (float)(vehicle_speed.min) / VEHICLE_SPEED_FACTOR;
  if (speed_ms < 1.0f) {
    vw_iq_debug_lat_accel = 0.0f;
    return false;
  }

  float abs_angle = vw_iq_measured_angle_deg >= 0.0f ? vw_iq_measured_angle_deg : -vw_iq_measured_angle_deg;
  float angle_rad = abs_angle * VW_IQ_DEG_TO_RAD;
  float curvature = angle_rad / (vw_iq_apd_steer_ratio * vw_iq_apd_wheelbase);
  float lat_accel = curvature * speed_ms * speed_ms;
  vw_iq_debug_lat_accel = lat_accel;

  if (lat_accel > VW_IQ_MAX_LAT_ACCEL) {
    bool torque_positive = desired_torque > 0;
    bool angle_positive = vw_iq_measured_angle_deg > 0.0f;
    if (torque_positive == angle_positive) {
      return true;
    }
  }

  return false;
}

static float volkswagen_iq_angle_to_lat_accel(float angle_deg) {
  float abs_angle = angle_deg >= 0.0f ? angle_deg : -angle_deg;
  float angle_rad = abs_angle * VW_IQ_DEG_TO_RAD;
  float curvature = angle_rad / (vw_iq_apd_steer_ratio * vw_iq_apd_wheelbase);
  float speed_ms = (float)(vehicle_speed.min) / VEHICLE_SPEED_FACTOR;
  return curvature * speed_ms * speed_ms;
}

static bool volkswagen_iq_alc_angle_accel_check(bool require_activation_gate) {
  if (require_activation_gate && !controls_allowed && !vw_iq_aol_active) {
    return true;
  }
  if (!vw_iq_apd_params_valid) {
    return false;
  }
  float speed_ms = (float)(vehicle_speed.min) / VEHICLE_SPEED_FACTOR;
  if (speed_ms < 1.0f) {
    return false;
  }

  const float desired_effective_angle = vw_iq_alc_desired_angle_deg - vw_iq_angle_offset_deg;
  const float actual_effective_angle = vw_iq_measured_angle_deg - vw_iq_angle_offset_deg;
  const float delta_angle = desired_effective_angle - actual_effective_angle;
  const float delta_lat_accel = volkswagen_iq_angle_to_lat_accel(delta_angle);

  vw_iq_debug_lat_accel = delta_lat_accel;

  if (delta_lat_accel <= VW_IQ_MAX_LAT_ACCEL) {
    return false;
  }

  return true;
}

static void volkswagen_iq_send_debug_la(uint32_t debug_addr, uint8_t bus) {
  CANPacket_t msg = {0};
  msg.addr = debug_addr;
  msg.bus = bus;
  msg.data_len_code = 8U;

  uint16_t la_raw = (uint16_t)(vw_iq_debug_lat_accel * 1000.0f);
  float speed_kmh = ((float)(vehicle_speed.min) / VEHICLE_SPEED_FACTOR) * 3.6f;
  uint16_t spd_raw = (uint16_t)(speed_kmh * 100.0f);
  int16_t ang_raw = (int16_t)(vw_iq_measured_angle_deg * 100.0f);
  uint8_t flags = (vw_iq_apd_params_valid ? 0x01U : 0x00U);

  msg.data[0] = (uint8_t)(la_raw & 0xFFU);
  msg.data[1] = (uint8_t)((la_raw >> 8) & 0xFFU);
  msg.data[2] = (uint8_t)(spd_raw & 0xFFU);
  msg.data[3] = (uint8_t)((spd_raw >> 8) & 0xFFU);
  msg.data[4] = (uint8_t)((uint16_t)ang_raw & 0xFFU);
  msg.data[5] = (uint8_t)(((uint16_t)ang_raw >> 8) & 0xFFU);
  msg.data[6] = flags;
  msg.data[7] = 0U;

  can_set_checksum(&msg);
  can_send(&msg, bus, true);
}

static bool volkswagen_iq_long_accel_check(int desired_accel) {
  if (desired_accel == VW_IQ_INACTIVE_LONG_ACCEL) {
    return false;
  }
  if (!controls_allowed) {
    return true;
  }
  if (gas_pressed_prev && !volkswagen_allow_long_accel_with_gas_pressed) {
    return true;
  }
  return (desired_accel > VW_IQ_MAX_LONG_ACCEL) || (desired_accel < VW_IQ_MIN_LONG_ACCEL);
}

static uint32_t volkswagen_mqb_meb_get_checksum(const CANPacket_t *msg) {
  return (uint8_t)msg->data[0];
}

static uint8_t volkswagen_mqb_meb_get_counter(const CANPacket_t *msg) {
  // MQB/MEB message counters are consistently found at LSB 8.
  return (uint8_t)msg->data[1] & 0xFU;
}

static uint32_t volkswagen_mqb_meb_compute_crc(const CANPacket_t *msg) {
  int len = GET_LEN(msg);

  // This is CRC-8H2F/AUTOSAR with a twist. See the opendbc/car/volkswagen/ implementation
  // of this algorithm for a version with explanatory comments.

  uint8_t crc = 0xFFU;
  for (int i = 1; i < len; i++) {
    crc ^= (uint8_t)msg->data[i];
    crc = volkswagen_crc8_lut_8h2f[crc];
  }

  uint8_t counter = volkswagen_mqb_meb_get_counter(msg);
  if (msg->addr == MSG_LH_EPS_03) {
    crc ^= (uint8_t[]){0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5, 0xF5}[counter];
  } else if (msg->addr == MSG_ESP_05) {
    crc ^= (uint8_t[]){0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07}[counter];
  } else if (msg->addr == MSG_TSK_06) {
    crc ^= (uint8_t[]){0xC4, 0xE2, 0x4F, 0xE4, 0xF8, 0x2F, 0x56, 0x81, 0x9F, 0xE5, 0x83, 0x44, 0x05, 0x3F, 0x97, 0xDF}[counter];
  } else if (msg->addr == MSG_MOTOR_20) {
    crc ^= (uint8_t[]){0xE9, 0x65, 0xAE, 0x6B, 0x7B, 0x35, 0xE5, 0x5F, 0x4E, 0xC7, 0x86, 0xA2, 0xBB, 0xDD, 0xEB, 0xB4}[counter];
  } else if (msg->addr == MSG_GRA_ACC_01) {
    crc ^= (uint8_t[]){0x6A, 0x38, 0xB4, 0x27, 0x22, 0xEF, 0xE1, 0xBB, 0xF8, 0x80, 0x84, 0x49, 0xC7, 0x9E, 0x1E, 0x2B}[counter];
  } else {
    // Undefined CAN message, CRC check expected to fail
  }
  crc = volkswagen_crc8_lut_8h2f[crc];

  return (uint8_t)(crc ^ 0xFFU);
}

static int volkswagen_mlb_mqb_driver_input_torque(const CANPacket_t *msg) {
  // Signal: LH_EPS_03.EPS_Lenkmoment (absolute torque)
  // Signal: LH_EPS_03.EPS_VZ_Lenkmoment (direction)
  int torque_driver_new = msg->data[5] | ((msg->data[6] & 0x1FU) << 8);
  bool sign = GET_BIT(msg, 55U);
  if (sign) {
    torque_driver_new *= -1;
  }
  return torque_driver_new;
}

static int volkswagen_mlb_mqb_steering_control_torque(const CANPacket_t *msg) {
  // Signal: HCA_01.HCA_01_LM_Offset (absolute torque)
  // Signal: HCA_01.HCA_01_LM_OffSign (direction)
  int desired_torque = msg->data[2] | ((msg->data[3] & 0x1U) << 8);
  bool sign = GET_BIT(msg, 31U);
  if (sign) {
    desired_torque *= -1;
  }
  return desired_torque;
}
