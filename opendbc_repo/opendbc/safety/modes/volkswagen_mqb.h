#pragma once

#include "opendbc/safety/declarations.h"
#include "opendbc/safety/modes/volkswagen_common.h"

#define MSG_LWI_01          0x086U
#define MSG_MQB_APD_1       0x6A0U
#define MSG_MQB_DEBUG_LA    0x6A2U

static safety_config volkswagen_mqb_init(uint16_t param) {
  static const CanMsg VOLKSWAGEN_MQB_STOCK_TX_MSGS[] = {{MSG_HCA_01, 0, 8, .check_relay = true}, {MSG_GRA_ACC_01, 0, 8, .check_relay = false}, {MSG_GRA_ACC_01, 2, 8, .check_relay = false},
                                                        {MSG_LDW_02, 0, 8, .check_relay = true}, {MSG_LH_EPS_03, 2, 8, .check_relay = true}, {MSG_MQB_APD_1, 1, 8, .check_relay = false}};

  static const CanMsg VOLKSWAGEN_MQB_LONG_TX_MSGS[] = {{MSG_HCA_01, 0, 8, .check_relay = true}, {MSG_LDW_02, 0, 8, .check_relay = true}, {MSG_LH_EPS_03, 2, 8, .check_relay = true},
                                                       {MSG_ACC_02, 0, 8, .check_relay = true}, {MSG_ACC_06, 0, 8, .check_relay = true}, {MSG_ACC_07, 0, 8, .check_relay = true},
                                                       {MSG_MQB_APD_1, 1, 8, .check_relay = false}};

  static RxCheck volkswagen_mqb_rx_checks[] = {
    {.msg = {{MSG_ESP_19, 0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_LH_EPS_03, 0, 8, 100U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ESP_05, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_TSK_06, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_MOTOR_20, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_MOTOR_14, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_GRA_ACC_01, 0, 8, 33U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  volkswagen_common_init();

#ifdef ALLOW_DEBUG
  volkswagen_longitudinal = GET_FLAG(param, FLAG_VOLKSWAGEN_LONG_CONTROL);
  volkswagen_allow_long_accel_with_gas_pressed = GET_FLAG(param, FLAG_VOLKSWAGEN_ALLOW_LONG_ACCEL_WITH_GAS_PRESSED);
#else
  SAFETY_UNUSED(param);
#endif

  return volkswagen_longitudinal ? BUILD_SAFETY_CFG(volkswagen_mqb_rx_checks, VOLKSWAGEN_MQB_LONG_TX_MSGS) : \
                                   BUILD_SAFETY_CFG(volkswagen_mqb_rx_checks, VOLKSWAGEN_MQB_STOCK_TX_MSGS);
}

static void volkswagen_mqb_rx_hook(const CANPacket_t *msg) {
  if (msg->bus == 0U) {
    if (msg->addr == MSG_ESP_19) {
      uint32_t speed = 0U;
      for (uint8_t i = 0U; i < 8U; i += 2U) {
        speed += (uint32_t)msg->data[i] | ((uint32_t)msg->data[i + 1U] << 8);
      }
      vehicle_moving = speed > 0U;
      UPDATE_VEHICLE_SPEED(((float)speed / 4.0f) * 0.0075f / 3.6f);
    }

    if (msg->addr == MSG_LH_EPS_03) {
      update_sample(&torque_driver, volkswagen_mlb_mqb_driver_input_torque(msg));
    }

    if (msg->addr == MSG_TSK_06) {
      int acc_status = (msg->data[3] & 0x7U);
      bool cruise_engaged = (acc_status == 3) || (acc_status == 4) || (acc_status == 5);
      acc_main_on = cruise_engaged || (acc_status == 2);

      if (!volkswagen_longitudinal) {
        pcm_cruise_check(cruise_engaged);
      }

      if (!acc_main_on) {
        controls_allowed = false;
      }
    }

    if (msg->addr == MSG_GRA_ACC_01) {
      if (volkswagen_longitudinal) {
        bool set_button = GET_BIT(msg, 16U);
        bool resume_button = GET_BIT(msg, 19U);
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

    if (msg->addr == MSG_MOTOR_20) {
      gas_pressed = ((GET_BYTES(msg, 0, 4) >> 12) & 0xFFU) != 0U;
    }

    if (msg->addr == MSG_MOTOR_14) {
      volkswagen_brake_pedal_switch = GET_BIT(msg, 28U);
    }

    if (msg->addr == MSG_ESP_05) {
      volkswagen_brake_pressure_detected = GET_BIT(msg, 26U);
    }

    if (msg->addr == MSG_LWI_01) {
      uint16_t lwi_angle_raw = ((uint16_t)msg->data[2] | ((uint16_t)msg->data[3] << 8)) & 0x1FFFU;
      bool lwi_angle_sign = ((msg->data[3] >> 5) & 0x1U) != 0U;
      float lwi_angle_deg = (float)lwi_angle_raw * 0.1f;
      vw_iq_measured_angle_deg = lwi_angle_sign ? -lwi_angle_deg : lwi_angle_deg;

      uint16_t alc_angle_raw = (uint16_t)msg->data[5] | ((uint16_t)msg->data[6] << 8);
      vw_iq_alc_desired_angle_deg = (float)alc_angle_raw * 0.1f;
      vw_iq_alc_active = msg->data[7] != 0U;
    }

    brake_pressed = volkswagen_brake_pedal_switch || volkswagen_brake_pressure_detected;
  }
}

static bool volkswagen_mqb_tx_hook(const CANPacket_t *msg) {
  bool tx = true;

  if (msg->addr == MSG_MQB_APD_1) {
    volkswagen_iq_decode_apd(msg);
  }

  if (msg->addr == MSG_HCA_01) {
    volkswagen_iq_send_debug_la(MSG_MQB_DEBUG_LA, 1U);
  }

  if ((msg->addr == MSG_ACC_06) || (msg->addr == MSG_ACC_07)) {
    int desired_accel = 0;

    if (msg->addr == MSG_ACC_06) {
      desired_accel = ((((msg->data[4] & 0x7U) << 8) | msg->data[3]) * 5U) - 7220U;
    } else {
      desired_accel = (((msg->data[7] << 3) | ((msg->data[6] & 0xE0U) >> 5)) * 5U) - 7220U;
    }

    if (volkswagen_iq_long_accel_check(desired_accel)) {
      tx = false;
    }
  }

  if ((msg->addr == MSG_GRA_ACC_01) && !controls_allowed) {
    if ((msg->data[2] & 0x9U) != 0U) {
      tx = false;
    }
  }

  return tx;
}

const safety_hooks volkswagen_mqb_hooks = {
  .init = volkswagen_mqb_init,
  .rx = volkswagen_mqb_rx_hook,
  .tx = volkswagen_mqb_tx_hook,
  .get_counter = volkswagen_mqb_meb_get_counter,
  .get_checksum = volkswagen_mqb_meb_get_checksum,
  .compute_checksum = volkswagen_mqb_meb_compute_crc,
};
