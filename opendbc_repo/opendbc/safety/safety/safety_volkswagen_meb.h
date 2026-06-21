#pragma once

#include "safety_declarations.h"
#include "safety_volkswagen_common.h"

#define MSG_ESC_51           0xFCU
#define MSG_Motor_54         0x14CU
#define MSG_HCA_03           0x303U
#define MSG_QFK_01           0x13DU
#define MSG_MEB_ACC_01       0x300U
#define MSG_ACC_18           0x14DU
#define MSG_Motor_51         0x10BU
#define MSG_TA_01            0x26BU
#define MSG_EA_01            0x1A4U
#define MSG_EA_02            0x1F0U
#define MSG_KLR_01           0x25DU
#define MSG_AWV_03           0xDBU
#define MSG_MEB_DISTANCE_01  0x24FU
#define MSG_UDS_FUNCTIONAL   0x700U

static uint32_t volkswagen_meb_compute_crc(const CANPacket_t *msg) {
  const int len = GET_LEN(msg);

  uint8_t crc = 0xFFU;
  for (int i = 1; i < len; i++) {
    crc ^= (uint8_t)msg->data[i];
    crc = volkswagen_crc8_lut_8h2f[crc];
  }

  const uint8_t counter = volkswagen_mqb_meb_get_counter(msg);
  if (msg->addr == MSG_LH_EPS_03) {
    crc ^= (uint8_t[]){0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5,0xF5}[counter];
  } else if (msg->addr == MSG_GRA_ACC_01) {
    crc ^= (uint8_t[]){0x6A,0x38,0xB4,0x27,0x22,0xEF,0xE1,0xBB,0xF8,0x80,0x84,0x49,0xC7,0x9E,0x1E,0x2B}[counter];
  } else if (msg->addr == MSG_QFK_01) {
    crc ^= (uint8_t[]){0x20,0xCA,0x68,0xD5,0x1B,0x31,0xE2,0xDA,0x08,0x0A,0xD4,0xDE,0x9C,0xE4,0x35,0x5B}[counter];
  } else if (msg->addr == MSG_ESC_51) {
    crc ^= (uint8_t[]){0x77,0x5C,0xA0,0x89,0x4B,0x7C,0xBB,0xD6,0x1F,0x6C,0x4F,0xF6,0x20,0x2B,0x43,0xDD}[counter];
  } else if (msg->addr == MSG_Motor_54) {
    crc ^= (uint8_t[]){0x16,0x35,0x59,0x15,0x9A,0x2A,0x97,0xB8,0x0E,0x4E,0x30,0xCC,0xB3,0x07,0x01,0xAD}[counter];
  } else if (msg->addr == MSG_Motor_51) {
    crc ^= (uint8_t[]){0x77,0x5C,0xA0,0x89,0x4B,0x7C,0xBB,0xD6,0x1F,0x6C,0x4F,0xF6,0x20,0x2B,0x43,0xDD}[counter];
  } else if (msg->addr == MSG_MOTOR_14) {
    crc ^= (uint8_t[]){0x1F,0x28,0xC6,0x85,0xE6,0xF8,0xB0,0x19,0x5B,0x64,0x35,0x21,0xE4,0xF7,0x9C,0x24}[counter];
  } else if (msg->addr == MSG_KLR_01) {
    crc ^= (uint8_t[]){0xDA,0x6B,0x0E,0xB2,0x78,0xBD,0x5A,0x81,0x7B,0xD6,0x41,0x39,0x76,0xB6,0xD7,0x35}[counter];
  } else if (msg->addr == MSG_EA_02) {
    crc ^= (uint8_t[]){0x2F,0x3C,0x22,0x60,0x18,0xEB,0x63,0x76,0xC5,0x91,0x0F,0x27,0x34,0x04,0x7F,0x02}[counter];
  }
  crc = volkswagen_crc8_lut_8h2f[crc];

  return (uint8_t)(crc ^ 0xFFU);
}

static uint32_t volkswagen_meb_gen2_compute_crc(const CANPacket_t *msg) {
  if (!volkswagen_alt_crc_variant_1) {
    return volkswagen_meb_compute_crc(msg);
  }

  int len = GET_LEN(msg);
  if (msg->addr == MSG_QFK_01) {
    len = 28;
  } else if (msg->addr == MSG_ESC_51) {
    len = 60;
  } else if (msg->addr == MSG_Motor_51) {
    len = 44;
  } else {
    return volkswagen_meb_compute_crc(msg);
  }

  uint8_t crc = 0xFFU;
  for (int i = 1; i < len; i++) {
    crc ^= (uint8_t)msg->data[i];
    crc = volkswagen_crc8_lut_8h2f[crc];
  }

  const uint8_t counter = volkswagen_mqb_meb_get_counter(msg);
  if (msg->addr == MSG_QFK_01) {
    crc ^= (uint8_t[]){0x18,0x71,0x10,0x8D,0xD7,0xAA,0xB0,0x78,0xAC,0x12,0xAE,0x0C,0xDD,0xF1,0x85,0x68}[counter];
  } else if (msg->addr == MSG_ESC_51) {
    crc ^= (uint8_t[]){0x69,0xDC,0xF9,0x64,0x6A,0xCE,0x55,0x2C,0xC4,0x38,0x8F,0xD1,0xC6,0x43,0xB4,0xB1}[counter];
  } else if (msg->addr == MSG_Motor_51) {
    crc ^= (uint8_t[]){0x2C,0xB1,0x1A,0x75,0xBB,0x65,0x79,0x47,0x81,0x2B,0xCC,0x96,0x17,0xDB,0xC0,0x94}[counter];
  } else {
    return volkswagen_meb_compute_crc(msg);
  }

  crc = (uint8_t)(volkswagen_crc8_lut_8h2f[crc] ^ 0xFFU);
  if (crc != msg->data[0]) {
    return volkswagen_meb_compute_crc(msg);
  }
  return (uint8_t)crc;
}

static safety_config volkswagen_meb_init(uint16_t param) {
  static const CanMsg VOLKSWAGEN_MEB_STOCK_TX_MSGS[] = {
    {MSG_HCA_03, 0, 24, .check_relay = true},
    {MSG_GRA_ACC_01, 0, 8, .check_relay = false},
    {MSG_EA_01, 0, 8, .check_relay = false},
    {MSG_EA_02, 0, 8, .check_relay = true},
    {MSG_KLR_01, 0, 8, .check_relay = false},
    {MSG_KLR_01, 2, 8, .check_relay = true},
    {MSG_GRA_ACC_01, 2, 8, .check_relay = false},
    {MSG_LDW_02, 0, 8, .check_relay = true},
  };

  static const CanMsg VOLKSWAGEN_MEB_LONG_TX_MSGS[] = {
    {MSG_HCA_03, 0, 24, .check_relay = true},
    {MSG_MEB_ACC_01, 0, 48, .check_relay = true},
    {MSG_ACC_18, 0, 32, .check_relay = true},
    {MSG_EA_01, 0, 8, .check_relay = false},
    {MSG_EA_02, 0, 8, .check_relay = true},
    {MSG_KLR_01, 0, 8, .check_relay = false},
    {MSG_KLR_01, 2, 8, .check_relay = true},
    {MSG_LDW_02, 0, 8, .check_relay = true},
    {MSG_TA_01, 0, 8, .check_relay = true},
    {MSG_AWV_03, 0, 48, .check_relay = false},
    {MSG_MEB_DISTANCE_01, 0, 64, .check_relay = false},
    {MSG_UDS_FUNCTIONAL, 0, 8, .check_relay = false},
  };

  static RxCheck volkswagen_meb_rx_checks[] = {
    {.msg = {{MSG_LH_EPS_03, 0, 8, 100U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_MOTOR_14, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_GRA_ACC_01, 0, 8, 33U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_QFK_01, 0, 32, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_Motor_51, 0, 32, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ESC_51, 0, 48, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  static RxCheck volkswagen_meb_gen2_rx_checks[] = {
    {.msg = {{MSG_LH_EPS_03, 0, 8, 100U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_MOTOR_14, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_GRA_ACC_01, 0, 8, 33U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_QFK_01, 0, 32, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_Motor_51, 0, 48, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ESC_51, 0, 64, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  volkswagen_common_init();

  volkswagen_alt_crc_variant_1 = GET_FLAG(param, FLAG_VOLKSWAGEN_ALT_CRC_VARIANT_1);
  volkswagen_no_gas_offset = GET_FLAG(param, FLAG_VOLKSWAGEN_NO_GAS_OFFSET);

#ifdef ALLOW_DEBUG
  volkswagen_longitudinal = GET_FLAG(param, FLAG_VOLKSWAGEN_LONG_CONTROL);
  volkswagen_allow_long_accel_with_gas_pressed = GET_FLAG(param, FLAG_VOLKSWAGEN_ALLOW_LONG_ACCEL_WITH_GAS_PRESSED);
#else
  SAFETY_UNUSED(param);
#endif

  safety_config ret;
  if (volkswagen_longitudinal) {
    SET_TX_MSGS(VOLKSWAGEN_MEB_LONG_TX_MSGS, ret);
  } else {
    SET_TX_MSGS(VOLKSWAGEN_MEB_STOCK_TX_MSGS, ret);
  }

  if (volkswagen_alt_crc_variant_1) {
    SET_RX_CHECKS(volkswagen_meb_gen2_rx_checks, ret);
  } else {
    SET_RX_CHECKS(volkswagen_meb_rx_checks, ret);
  }

  return ret;
}

static void volkswagen_meb_rx_hook(const CANPacket_t *msg) {
  if (msg->bus != 0U) {
    return;
  }

  if (msg->addr == MSG_ESC_51) {
    const uint32_t fr = msg->data[10] | (msg->data[11] << 8);
    const uint32_t rl = msg->data[12] | (msg->data[13] << 8);
    const uint32_t rr = msg->data[14] | (msg->data[15] << 8);
    const uint32_t fl = msg->data[8] | (msg->data[9] << 8);

    vehicle_moving = (fr > 0U) || (rr > 0U) || (rl > 0U) || (fl > 0U);
    UPDATE_VEHICLE_SPEED(((fr + rr + rl + fl) / 4U) * 0.0075f / 3.6f);
  }

  if (msg->addr == MSG_QFK_01) {
    int current_curvature = ((msg->data[6] & 0x7FU) << 8) | msg->data[5];
    const bool current_curvature_sign = GET_BIT(msg, 55U);
    if (!current_curvature_sign) {
      current_curvature *= -1;
    }
    update_sample(&angle_meas, current_curvature);
  }

  if (msg->addr == MSG_LH_EPS_03) {
    update_sample(&torque_driver, volkswagen_mlb_mqb_driver_input_torque(msg));
  }

  if (msg->addr == MSG_Motor_51) {
    const int acc_status = ((msg->data[11] >> 0) & 0x07U);
    const bool cruise_engaged = (acc_status == 3) || (acc_status == 4) || (acc_status == 5);
    acc_main_on = cruise_engaged || (acc_status == 2);

    if (!volkswagen_longitudinal) {
      pcm_cruise_check(cruise_engaged);
    }

    if (!acc_main_on) {
      controls_allowed = false;
    }

    const int accel_pedal_value = ((msg->data[1] >> 4) & 0x0FU) | ((msg->data[2] & 0x1FU) << 4);
    gas_pressed = accel_pedal_value > 0;
  }

  if (msg->addr == MSG_GRA_ACC_01) {
    if (volkswagen_longitudinal) {
      const bool set_button = GET_BIT(msg, 16U);
      const bool resume_button = GET_BIT(msg, 19U);
      if ((volkswagen_set_button_prev && !set_button) || (volkswagen_resume_button_prev && !resume_button)) {
        controls_allowed = acc_main_on;
      }
      volkswagen_set_button_prev = set_button;
      volkswagen_resume_button_prev = resume_button;
    }

    if (GET_BIT(msg, 13U)) {
      controls_allowed = false;
    }
  }

  if (msg->addr == MSG_MOTOR_14) {
    brake_pressed = GET_BIT(msg, 28U);
  }
}

static const CurvatureSteeringLimits VOLKSWAGEN_MEB_STEERING_LIMITS = {
  .max_curvature = 29105,
  .curvature_to_can = 149253.7313f,
  .send_rate = 0.02f,
  .inactive_curvature_is_zero = true,
  .max_power = 125,
};

static bool volkswagen_meb_tx_hook(const CANPacket_t *msg) {
  const LongitudinalLimits VOLKSWAGEN_MEB_LONG_LIMITS = {
    .max_accel = 2000,
    .min_accel = -3500,
    .inactive_accel = 3010,
  };

  bool tx = true;

  if (msg->addr == MSG_HCA_03) {
    int desired_curvature_raw = GET_BYTES(msg, 3, 2) & 0x7FFFU;
    const bool desired_curvature_sign = GET_BIT(msg, 39U);
    if (!desired_curvature_sign) {
      desired_curvature_raw *= -1;
    }

    const bool steer_req = (((msg->data[1] >> 4) & 0x0FU) == 4U);
    const int steer_power = msg->data[2];

    if (steer_power_cmd_checks(steer_power, steer_req, VOLKSWAGEN_MEB_STEERING_LIMITS)) {
      tx = true;
    }
    if (steer_curvature_cmd_checks_average(desired_curvature_raw, steer_req, VOLKSWAGEN_MEB_STEERING_LIMITS)) {
      tx = true;
    }
  }

  if (msg->addr == MSG_ACC_18) {
    const int desired_accel = ((((msg->data[4] & 0x7U) << 8) | msg->data[3]) * 5U) - 7220U;
    if (volkswagen_longitudinal_accel_checks(desired_accel, VOLKSWAGEN_MEB_LONG_LIMITS)) {
      tx = true;
    }
  }

  if ((msg->addr == MSG_GRA_ACC_01) && !controls_allowed) {
    if ((msg->data[2] & 0x9U) != 0U) {
      tx = false;
    }
  }

  return tx;
}

const safety_hooks volkswagen_meb_hooks = {
  .init = volkswagen_meb_init,
  .rx = volkswagen_meb_rx_hook,
  .tx = volkswagen_meb_tx_hook,
  .get_counter = volkswagen_mqb_meb_get_counter,
  .get_checksum = volkswagen_mqb_meb_get_checksum,
  .compute_checksum = volkswagen_meb_gen2_compute_crc,
};
