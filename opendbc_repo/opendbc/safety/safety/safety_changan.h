#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER        0x180
#define CHANGAN_STEER_CMD    0x1BA // 442, Length 32
#define CHANGAN_EPS          0x17E
#define CHANGAN_CRZ_BTNS     0x28C
#define CHANGAN_SPEED        0x17A
#define CHANGAN_SPEED_ALT    0x187
#define CHANGAN_GAS          0x17D
#define CHANGAN_BRAKE        0x1A6
#define CHANGAN_BRAKE_ALT    0x196
#define CHANGAN_ACC_CTRL     0x244
#define CHANGAN_ACC_HUD      0x307
#define CHANGAN_ACC_STATE    0x31A

// CAN bus numbers
#define CHANGAN_MAIN 0
#define CHANGAN_CAM  2

static void changan_rx_hook(const CANPacket_t *to_push) {
  if (GET_BUS(to_push) == CHANGAN_MAIN) {
    int addr = GET_ADDR(to_push);

    if ((addr == CHANGAN_SPEED) || (addr == CHANGAN_SPEED_ALT)) {
      // Signal: ESP_VehicleSpeed, factor: 0.05625, offset: 0
      // Uniform 21|14@0+ layout in cleaned DBC
      int speed = ((GET_BYTE(to_push, 2) & 0x3FU) << 8) | GET_BYTE(to_push, 3);
      UPDATE_VEHICLE_SPEED(speed * 0.05625 / 3.6);
    }

    if (addr == CHANGAN_STEER) {
      // Signal: SAS_SteeringAngle, factor: 0.1, offset: -780
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      angle_meas_new -= 7800; // scale by 10 to match factor 0.1
      update_sample(&angle_meas, angle_meas_new);
    }

    if (addr == CHANGAN_EPS) {
      // Signal: EPS_MeasuredTorsionBarTorque, factor: 0.01, offset: -32
      int torque_driver_new = ((GET_BYTE(to_push, 1) & 0x3FU) << 8) | GET_BYTE(to_push, 2);
      torque_driver_new -= 3200; // scale by 100 to match factor 0.01
      update_sample(&torque_driver, torque_driver_new);
    }

    if (addr == CHANGAN_CRZ_BTNS) {
      // Signal: CRZ_IACC_Stat, 2: Active, 3: Override?
      int acc_status = (GET_BYTE(to_push, 0) >> 4) & 0x7U;
      bool cruise_engaged = (acc_status == 2) || (acc_status == 3);
      pcm_cruise_check(cruise_engaged);
    }

    if (addr == CHANGAN_GAS) {
      // Signal: EMS_GasPedalPosition, factor: 0.392157
      gas_pressed = GET_BYTE(to_push, 6) > 0U;
    }

    if (addr == CHANGAN_BRAKE) {
      // Signal: ESP_BrakePedalAnyPressed
      brake_pressed = (GET_BYTE(to_push, 0) >> 4) & 0x1U;
    }

    if (addr == CHANGAN_BRAKE_ALT) {
       // Signal: EMS_BrakePedalStatus
       if ((GET_BYTE(to_push, 0) & 0x1U) != 0) {
         brake_pressed = true;
       }
    }

    generic_rx_checks((addr == CHANGAN_STEER));
  }
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  static const AngleSteeringLimits CHANGAN_STEERING_LIMITS = {
    .max_angle = 4800,       // 480.0 deg
    .angle_deg_to_can = 10,  // 0.1 factor
    .angle_rate_up_lookup = {
      {5., 25., 25.},
      {0.3, 0.15, 0.15}      // 3.0 deg/s at 100Hz
    },
    .angle_rate_down_lookup = {
      {5., 25., 25.},
      {0.5, 0.25, 0.25}      // 5.0 deg/s at 100Hz
    },
  };

  bool tx = true;
  int addr = GET_ADDR(to_send);
  int bus = GET_BUS(to_send);

  if (bus == CHANGAN_MAIN) {
    if (addr == CHANGAN_STEER) {
      int desired_angle = (GET_BYTE(to_send, 0) << 8) | GET_BYTE(to_send, 1);
      desired_angle -= 7800;

      if (steer_angle_cmd_checks(desired_angle, controls_allowed, CHANGAN_STEERING_LIMITS)) {
        tx = false;
      }
    }

    if (addr == CHANGAN_STEER_CMD) {
      // TODO: Verify signal layout for 0x1BA (32 bytes).
      // Assuming controls_allowed check is sufficient for now, but angle limits should be enforced if possible.
      if (!controls_allowed) {
        tx = false;
      }
    }

    if (addr == CHANGAN_CRZ_BTNS) {
      // Signal: CRZ_IACC_Btn
      // 1: Res+, 2: Set-, 4: Cancel, 8: IACC
      int btn = GET_BYTE(to_send, 1) & 0x1FU;
      bool cancel_cmd = (btn == 4);
      if (!controls_allowed && !cancel_cmd) {
        tx = false;
      }
    }

    // Allow EPS status spoofing if needed
    if (addr == CHANGAN_EPS) {
      if (!controls_allowed) {
        // tx = false; // Maybe allow EPS spoofing even when controls not allowed if it's just status?
      }
    }
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;

  if (bus == CHANGAN_MAIN) {
    bus_fwd = CHANGAN_CAM;
  } else if (bus == CHANGAN_CAM) {
    bool block = (addr == CHANGAN_STEER) || (addr == CHANGAN_CRZ_BTNS) || (addr == CHANGAN_STEER_CMD) ||
                 (addr == CHANGAN_ACC_CTRL) || (addr == CHANGAN_ACC_HUD) || (addr == CHANGAN_ACC_STATE);
    if (!block) {
      bus_fwd = CHANGAN_MAIN;
    }
  }

  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER, 0, 8},
    {CHANGAN_CRZ_BTNS, 0, 8},
    {CHANGAN_STEER_CMD, 0, 32},
    {CHANGAN_EPS, 0, 8},
    {CHANGAN_ACC_CTRL, 0, 8},
    {CHANGAN_ACC_HUD, 0, 8},
    {CHANGAN_ACC_STATE, 0, 8}
  };

  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER,    0, 8, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_EPS,      0, 8, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_CRZ_BTNS, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_SPEED,    0, 8, .frequency = 50U}, {CHANGAN_SPEED_ALT, 0, 8, .frequency = 50U}, { 0 }}},
    {.msg = {{CHANGAN_GAS,      0, 8, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{CHANGAN_BRAKE,    0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  };

  UNUSED(param);
  return BUILD_SAFETY_CFG(changan_rx_checks, CHANGAN_TX_MSGS);
}

const safety_hooks changan_hooks = {
  .init = changan_init,
  .rx = changan_rx_hook,
  .tx = changan_tx_hook,
  .fwd = changan_fwd_hook,
};
