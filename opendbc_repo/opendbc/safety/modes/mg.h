#pragma once

#include "opendbc/safety/declarations.h"

static bool mg_zs_ev_brake = false;
static bool mg_non_ev = false;

static void mg_rx_hook(const CANPacket_t *msg) {
  if (msg->bus == 0U)  {
    // Vehicle speed
    if (msg->addr == 0x23cU) {
      float speed = (((msg->data[2] & 0x7FU) << 8) | msg->data[3]) * 0.015625;
      vehicle_moving = speed > 0.0;
      UPDATE_VEHICLE_SPEED(speed * KPH_TO_MS);
    }

    // Gas pressed
    if (mg_non_ev) {
      if (msg->addr == 0xc9U) {
        gas_pressed = msg->data[4] != 0U;
      }
    } else {
      if (msg->addr == 0xafU) {
        gas_pressed = msg->data[0] != 0U;
      }
    }

    // Driver torque
    if (msg->addr == 0x1ecU) {
      int torque_driver_new = (((msg->data[4] & 0x7U) << 8) | msg->data[5]) - 1024U;
      update_sample(&torque_driver, torque_driver_new);
    }

    // Brake pressed
    if (mg_non_ev) {
      if (msg->addr == 0x214U) {
        brake_pressed = msg->data[1] != 0U;
      }
    } else if (mg_zs_ev_brake) {
      if (msg->addr == 0xafU) {
        brake_pressed = GET_BIT(msg, 31U);
      }
    } else {
      if (msg->addr == 0x1b6U) {
        brake_pressed = GET_BIT(msg, 10U);
      }
    }

    // Cruise state
    if (msg->addr == 0x242U) {
      int cruise_state = (msg->data[5] & 0x38U) >> 3;
      bool cruise_engaged = (cruise_state == 2) ||  // Active
                            (cruise_state == 3);    // Override
      pcm_cruise_check(cruise_engaged);

      // dp - ALKA: ACC main on (any non-Off state) enables lane keep without engagement
      if (alka_allowed && ((alternative_experience & ALT_EXP_ALKA) != 0)) {
        lkas_on = cruise_state != 0;
      }
    }
  }
}

static bool mg_tx_hook(const CANPacket_t *msg) {
  const TorqueSteeringLimits MG_STEERING_LIMITS = {
    .max_torque = 300,
    .max_rate_up = 10,
    .max_rate_down = 15,
    .max_rt_delta = 125,
    .driver_torque_multiplier = 2,
    .driver_torque_allowance = 100,
    .type = TorqueDriverLimited,
  };

  bool tx = true;
  bool violation = false;

  // Steering control
  if (msg->addr == 0x1fdU) {
    int desired_torque = (((msg->data[0] & 0x7U) << 8) | msg->data[1]) - 1024U;
    bool steer_req = GET_BIT(msg, 35U);

    violation |= steer_torque_cmd_checks(desired_torque, steer_req, MG_STEERING_LIMITS);
  }

  if (violation) {
    tx = false;
  }

  return tx;
}

#define MG_COMMON_RX_CHECKS                                                                                                                                      \
  {.msg = {{0x23c, 0, 8, .frequency = 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  /* SCS_HSC2_FrP19 */  \
  {.msg = {{0x1ec, 0, 8, .frequency = 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  /* EPS_HSC2_FrP03 */  \
  {.msg = {{0x242, 0, 8, .frequency = 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  /* RADAR_HSC2_FrP00 */

static safety_config mg_init(uint16_t param) {
  alka_allowed = true;  // dp - ALKA enabled for MG

  static const CanMsg MG_TX_MSGS[] = {{0x1fd, 0, 8, .check_relay = true}};

  static RxCheck mg_rx_checks[] = {
    MG_COMMON_RX_CHECKS
    {.msg = {{0xaf, 0, 8, .frequency = 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // GW_HSC2_HCU_FrP00 (gas pedal)
    {.msg = {{0x1b6, 0, 8, .frequency = 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // EHBS_HSC2_FrP00 (brake pedal)
  };

  static RxCheck mg_rx_checks_non_ev[] = {
    MG_COMMON_RX_CHECKS
    {.msg = {{0xc9, 0, 8, .frequency = 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // Tester_HSC2_ECM_FrP00 (gas pedal)
    {.msg = {{0x214, 0, 6, .frequency = 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // SCS_HSC2_FrP09 (brake pressure)
  };

  const uint16_t MG_PARAM_ALT_BRAKE = 2;
  const uint16_t MG_PARAM_NON_EV = 4;
  mg_zs_ev_brake = GET_FLAG(param, MG_PARAM_ALT_BRAKE);
  mg_non_ev = GET_FLAG(param, MG_PARAM_NON_EV);

  safety_config ret;
  SET_TX_MSGS(MG_TX_MSGS, ret);
  if (mg_non_ev) {
    SET_RX_CHECKS(mg_rx_checks_non_ev, ret);
  } else {
    SET_RX_CHECKS(mg_rx_checks, ret);
  }
  return ret;
}

const safety_hooks mg_hooks = {
  .init = mg_init,
  .rx = mg_rx_hook,
  .tx = mg_tx_hook,
};
