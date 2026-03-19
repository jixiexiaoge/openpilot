#pragma once

#include "safety_declarations.h"
#include "safety_hyundai_common.h"

const TorqueSteeringLimits HYUNDAI_CANFD_STEERING_LIMITS = {
  .max_steer = 512, //270,
  .max_rt_delta = 112,
  .max_rt_interval = 250000,
  .max_rate_up = 2,
  .max_rate_down = 3,
  .driver_torque_allowance = 250,
  .driver_torque_multiplier = 2,
  .type = TorqueDriverLimited,

  // the EPS faults when the steering angle is above a certain threshold for too long. to prevent this,
  // we allow setting torque actuation bit to 0 while maintaining the requested torque value for two consecutive frames
  .min_valid_request_frames = 89,
  .max_invalid_request_frames = 2,
  .min_valid_request_rt_interval = 810000,  // 810ms; a ~10% buffer on cutting every 90 frames
  .has_steer_req_tolerance = true,
};

const CanMsg HYUNDAI_CANFD_HDA2_TX_MSGS[] = {
  {0x50, 0, 16},  // LKAS
  {0x1CF, 1, 8},  // CRUISE_BUTTON
  {0x2A4, 0, 24}, // CAM_0x2A4
};

const CanMsg HYUNDAI_CANFD_HDA2_ALT_STEERING_TX_MSGS[] = {
  {0x110, 0, 32}, // LKAS_ALT
  {0x1CF, 1, 8},  // CRUISE_BUTTON
  {0x362, 0, 32}, // CAM_0x362
  {0x1AA, 1, 16}, // CRUISE_ALT_BUTTONS , carrot
};

const CanMsg HYUNDAI_CANFD_HDA2_LONG_TX_MSGS[] = {
  {0x50, 0, 16},  // LKAS
  {0x1CF, 0, 8},  // CRUISE_BUTTON
  {0x1CF, 1, 8},  // CRUISE_BUTTON
  {0x1CF, 2, 8},  // CRUISE_BUTTON
  {0x1AA, 0, 16}, // CRUISE_ALT_BUTTONS , carrot
  {0x1AA, 1, 16}, // CRUISE_ALT_BUTTONS , carrot
  {0x1AA, 2, 16}, // CRUISE_ALT_BUTTONS , carrot
  {0x2A4, 0, 24}, // CAM_0x2A4
  {0x51, 0, 32},  // ADRV_0x51
  {0x730, 1, 8},  // tester present for ADAS ECU disable
  {0x12A, 1, 16}, // LFA
  {0x160, 1, 16}, // ADRV_0x160
  {0x1E0, 1, 16}, // LFAHDA_CLUSTER
  {0x1A0, 1, 32}, // CRUISE_INFO
  {0x1EA, 1, 32}, // ADRV_0x1ea
  {0x200, 1, 8},  // ADRV_0x200
  {0x345, 1, 8},  // ADRV_0x345
  {0x1DA, 1, 32}, // ADRV_0x1da

  {0x12A, 0, 16}, // LFA
  {0x1E0, 0, 16}, // LFAHDA_CLUSTER
  {0x160, 0, 16}, // ADRV_0x160
  {0x1EA, 0, 32}, // ADRV_0x1ea
  {0x200, 0, 8},  // ADRV_0x200
  {0x1A0, 0, 32}, // CRUISE_INFO
  {0x345, 0, 8},  // ADRV_0x345
  {0x1DA, 0, 32}, // ADRV_0x1da

  {0x362, 0, 32}, // CAM_0x362
  {0x362, 1, 32}, // CAM_0x362
  {0x2a4, 1, 24}, // CAM_0x2a4

  {0x110, 0, 32}, // LKAS_ALT (272)
  {0x110, 1, 32}, // LKAS_ALT (272)

  {0x50, 1, 16}, // 
  {0x51, 1, 32}, // 

  {353, 0, 32}, // ADRV_353
  {354, 0, 32}, // CORNER_RADAR_HIGHWAY
  {512, 0, 8}, // ADRV_0x200
  {1187, 2, 8}, // 4A3
  {1204, 2, 8}, // 4B4

  {203, 0, 24}, // CB
  {373, 2, 24}, // TCS(0x175)
  {506, 2, 32}, // CLUSTER_SPEED_LIMIT
  {234, 2, 24}, // MDPS
  {687, 2, 8}, // STEER_TOUCH_2AF

  {0x4BE, 2, 8}, // NEW_MSG_4BE (may be corner radar enabler x)
  {0x4B9, 2, 8}, // NEW_MSG_4B9 (may be corner radar enabler)
};

const CanMsg HYUNDAI_CANFD_HDA1_TX_MSGS[] = {
  {0x12A, 0, 16}, // LFA
  {0x1A0, 0, 32}, // CRUISE_INFO
  {0x1CF, 0, 8},  // CRUISE_BUTTON
  {0x1CF, 2, 8},  // CRUISE_BUTTON
  {0x1E0, 0, 16}, // LFAHDA_CLUSTER
  {0x160, 0, 16}, // ADRV_0x160
  {0x7D0, 0, 8},  // tester present for radar ECU disable
  {0x1AA, 2, 16}, // CRUISE_ALT_BUTTONS , carrot
  {203, 0, 24}, // CB
  {373, 2, 24}, // TCS(0x175)

  {353, 0, 32}, // ADRV_353
  {354, 0, 32}, // CORNER_RADAR_HIGHWAY
  {512, 0, 8}, // ADRV_0x200
  {1187, 2, 8}, // 4A3
  {1204, 2, 8}, // 4B4
  {373, 2, 24}, // TCS(0x175)
  {234, 2, 24}, // MDPS
  {687, 2, 8}, // STEER_TOUCH_2AF

};


// *** Addresses checked in rx hook ***
// EV, ICE, HYBRID: ACCELERATOR (0x35), ACCELERATOR_BRAKE_ALT (0x100), ACCELERATOR_ALT (0x105)
#define HYUNDAI_CANFD_COMMON_RX_CHECKS(pt_bus)                                                                              \
  {.msg = {{0x35, (pt_bus), 32, .max_counter = 0xffU, .frequency = 100U},                   \
           {0x100, (pt_bus), 32, .max_counter = 0xffU, .frequency = 100U},                  \
           {0x105, (pt_bus), 32, .max_counter = 0xffU, .frequency = 100U}}},                \
  {.msg = {{0x175, (pt_bus), 24, .max_counter = 0xffU, .frequency = 50U}, { 0 }, { 0 }}},  \
  {.msg = {{0xa0, (pt_bus), 24, .max_counter = 0xffU, .frequency = 100U}, { 0 }, { 0 }}},   \
  {.msg = {{0xea, (pt_bus), 24, .max_counter = 0xffU, .frequency = 100U}, { 0 }, { 0 }}},   \

#define HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(pt_bus)                                                                            \
  {.msg = {{0x1cf, (pt_bus), 8, .ignore_checksum = true, .max_counter = 0xfU, .frequency = 50U}, { 0 }, { 0 }}}, \

#define HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(pt_bus)                                                                            \
  {.msg = {{0x1aa, (pt_bus), 16, .ignore_checksum = true, .max_counter = 0xffU, .frequency = 50U}, { 0 }, { 0 }}},   \

// SCC_CONTROL (from ADAS unit or camera)
#define HYUNDAI_CANFD_SCC_ADDR_CHECK(scc_bus)                                                                                 \
  {.msg = {{0x1a0, (scc_bus), 32, .max_counter = 0xffU, .frequency = 50U}, { 0 }, { 0 }}}, \

//static bool hyundai_canfd_alt_buttons = false;
//static bool hyundai_canfd_hda2_alt_steering = false;

// *** Non-HDA2 checks ***
// Camera sends SCC messages on HDA1.
// Both button messages exist on some platforms, so we ensure we track the correct one using flag
RxCheck hyundai_canfd_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
};
RxCheck hyundai_canfd_alt_buttons_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
};

// Longitudinal checks for HDA1
RxCheck hyundai_canfd_long_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)
};
RxCheck hyundai_canfd_long_alt_buttons_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
};

// Radar sends SCC messages on these cars instead of camera
RxCheck hyundai_canfd_radar_scc_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(0)
};
RxCheck hyundai_canfd_radar_scc_alt_buttons_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(0)
};


// *** HDA2 checks ***
// E-CAN is on bus 1, ADAS unit sends SCC messages on HDA2.
// Does not use the alt buttons message
RxCheck hyundai_canfd_hda2_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(1)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(1)  // TODO: carrot: canival no 0x1cf
  HYUNDAI_CANFD_SCC_ADDR_CHECK(1)
};
RxCheck hyundai_canfd_hda2_rx_checks_scc2[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)  // TODO: carrot: canival no 0x1cf
  HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
};
RxCheck hyundai_canfd_hda2_alt_buttons_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(1)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(1)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(1)
};
RxCheck hyundai_canfd_hda2_alt_buttons_rx_checks_scc2[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
  HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
};
RxCheck hyundai_canfd_hda2_long_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(1)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(1)  // TODO: carrot: canival no 0x1cf
};
RxCheck hyundai_canfd_hda2_long_rx_checks_scc2[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)  
};
RxCheck hyundai_canfd_hda2_long_alt_buttons_rx_checks[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(1)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(1)
};
RxCheck hyundai_canfd_hda2_long_alt_buttons_rx_checks_scc2[] = {
  HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
  HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
};


const int HYUNDAI_PARAM_CANFD_ALT_BUTTONS = 32;
const int HYUNDAI_PARAM_CANFD_HDA2_ALT_STEERING = 128;
bool hyundai_canfd_alt_buttons = false;
bool hyundai_canfd_hda2_alt_steering = false;

int hyundai_canfd_hda2_get_lkas_addr(void) {
  return hyundai_canfd_hda2_alt_steering ? 0x110 : 0x50;
}

static uint8_t hyundai_canfd_get_counter(const CANPacket_t* to_push) {
  uint8_t ret = 0;
  if (GET_LEN(to_push) == 8U) {
    ret = GET_BYTE(to_push, 1) >> 4;
  }
  else {
    ret = GET_BYTE(to_push, 2);
  }
  return ret;
}

static uint32_t hyundai_canfd_get_checksum(const CANPacket_t* to_push) {
  uint32_t chksum = GET_BYTE(to_push, 0) | (GET_BYTE(to_push, 1) << 8);
  return chksum;
}


typedef struct {
  int addr;
  int bus;              // forwarding block 대상 tx bus: 0 or 2
  int hz;
  uint32_t timeout_us;
  uint32_t last_tx_us;
} CanfdTxState;

typedef struct {
  int addr;
  bool check_counter;
  uint8_t last_counter_rx;
  uint8_t last_counter_tx;
  uint8_t counter_step;
  bool counter_valid;
  bool tx_counter_valid;
} CanfdCounterState;

typedef struct {
  int addrs[128];
  int count;
} CanfdAddrList;

// forwarding block용: bus 0,2만 사용
CanfdTxState canfd_tx_states[] = {
  {0x50,  0, 100, 0U, 0U}, // 80:  LKAS
  {0x51,  0, 100, 0U, 0U}, // 81:  ADRV_0x51
  {0x110, 0, 100, 0U, 0U}, // 272: LKAS_ALT
  {0x12A, 0, 100, 0U, 0U}, // 298: LFA
  {0x160, 0, 50,  0U, 0U}, // 352: ADRV_0x160
  {0x161, 0, 20,  0U, 0U}, // 353: ADRV_0x161
  {0x162, 0, 20,  0U, 0U}, // 354: CCNC_0x162
  {0x1A0, 0, 50,  0U, 0U}, // 416: SCC_CONTROL
  {0x1DA, 0, 1,   0U, 0U}, // 474: ADRV_0x1da
  {0x1E0, 0, 20,  0U, 0U}, // 480: LFAHDA_CLUSTER
  {0x1EA, 0, 20,  0U, 0U}, // 490: ADRV_0x1ea
  {0x200, 0, 20,  0U, 0U}, // 512: ADRV_0x200
  {0x2A4, 0, 20,  0U, 0U}, // 676: CAM_0x2a4
  {0x345, 0, 5,   0U, 0U}, // 837: ADRV_0x345
  {0x362, 0, 10,  0U, 0U}, // 866: CAM_0x362
  {0x0CB, 0, 100, 0U, 0U}, // 203: LFA_ALT

  {0x175, 2, 50,  0U, 0U}, // 373: TCS
  {0x1FA, 2, 10,  0U, 0U}, // 506: CLUSTER_SPEED_LIMIT
  {0x0EA, 2, 100, 0U, 0U}, // 234: MDPS
  {0x2AF, 2, 10,  0U, 0U}, // 687: STEER_TOUCH_2AF
  {0x4A3, 2, 5,   0U, 0U}, // 1187: HDA_INFO_4A3
  {0x4B4, 2, 10,  0U, 0U}, // 1204: NEW_MSG_4B4
  {0x4BE, 2, 10,  0U, 0U}, // 1214: NEW_MSG_4BE
  {0x4B9, 2, 10,  0U, 0U}, // 1209: NEW_MSG_4B9

  {0, 0, 0, 0U, 0U},
};

// counter/checksum 보정용: addr 기준
CanfdCounterState canfd_counter_states[] = {
  //{0x50,  true, 0U, 0U, 0U, false, false},  // 80:  LKAS
  //{0x110, true, 0U, 0U, 0U, false, false},  // 272: LKAS_ALT
  //{0x12A, true, 0U, 0U, 0U, false, false},  // 298: LFA
  {0x1A0, true, 0U, 0U, 0U, false, false},  // 416: SCC_CONTROL
  //{0x2A4, true, 0U, 0U, 0U, false, false},  // 676: CAM_0x2a4
  //{0x362, true, 0U, 0U, 0U, false, false},  // 866: CAM_0x362
  //{0x1CF, true, 0U, 0U, 0U, false, false},  // 463: CRUISE_BUTTONS
  //{0x1AA, true, 0U, 0U, 0U, false, false},  // 426: CRUISE_BUTTONS_ALT
  //{0x175, true, 0U, 0U, 0U, false, false},  // 373: TCS
  //{0x0EA, true, 0U, 0U, 0U, false, false},  // 234: MDPS
  //{0x1E0, true, 0U, 0U, 0U, false, false},  // 480: LFAHDA_CLUSTER
  //{0x162, true, 0U, 0U, 0U, false, false},  // 354: CCNC_0x162
  {0, false, 0U, 0U, 0U, false, false},
};

CanfdAddrList canfd_addr_debug_bus1 = { {0, }, 0 };
CanfdAddrList canfd_addr_debug_bus2 = { {0, }, 0 };

static CanfdTxState* find_canfd_tx_state(int bus, int addr) {
  for (int i = 0; canfd_tx_states[i].addr > 0; i++) {
    if ((canfd_tx_states[i].addr == addr) && (canfd_tx_states[i].bus == bus)) {
      return &canfd_tx_states[i];
    }
  }
  return NULL;
}

static CanfdCounterState* find_canfd_counter_state(int addr) {
  for (int i = 0; canfd_counter_states[i].addr > 0; i++) {
    if (canfd_counter_states[i].addr == addr) {
      return &canfd_counter_states[i];
    }
  }
  return NULL;
}

static void canfd_debug_track_addr(CanfdAddrList* list, int addr, const char* prefix) {
  int i;
  for (i = 0; (i < list->count) && (i < 127); i++) {
    if (list->addrs[i] == addr) {
      break;
    }
  }

  if ((i == list->count) && (i < 127)) {
    list->addrs[list->count] = addr;
    list->count++;

    print(prefix);
    for (int j = 0; j < list->count; j++) {
      putui((uint32_t)list->addrs[j]);
      print(",");
    }
    print("\n");
  }
}

static uint8_t hyundai_canfd_get_counter_mask(const CANPacket_t* to_push) {
  return (GET_LEN(to_push) == 8U) ? 0xFU : 0xFFU;
}

static void hyundai_canfd_set_counter(CANPacket_t* to_push, uint8_t counter) {
  if (GET_LEN(to_push) == 8U) {
    to_push->data[1] = (to_push->data[1] & 0x0FU) | ((counter & 0x0FU) << 4);
  }
  else {
    to_push->data[2] = counter;
  }
}

static void hyundai_canfd_set_checksum(CANPacket_t* to_push, uint16_t checksum) {
  to_push->data[0] = (uint8_t)(checksum & 0xFFU);
  to_push->data[1] = (uint8_t)((checksum >> 8U) & 0xFFU);
}

static void hyundai_canfd_update_checksum(CANPacket_t* to_push) {
  to_push->data[0] = 0U;
  to_push->data[1] = 0U;
  uint32_t checksum = hyundai_common_canfd_compute_checksum(to_push);
  hyundai_canfd_set_checksum(to_push, (uint16_t)checksum);
}

static void canfd_update_counter_state_from_rx(const CANPacket_t* to_push) {
  int addr = GET_ADDR(to_push);
  CanfdCounterState* st = find_canfd_counter_state(addr);
  if ((st == NULL) || !st->check_counter) {
    return;
  }

  uint8_t counter = hyundai_canfd_get_counter(to_push);
  uint8_t mask = hyundai_canfd_get_counter_mask(to_push);

  if (st->counter_valid) {
    st->counter_step = (counter - st->last_counter_rx) & mask;
  }
  else {
    st->counter_step = 0U;
    st->counter_valid = true;
  }

  st->last_counter_rx = counter;
}

static void canfd_fix_counter_and_checksum(CANPacket_t* to_send) {
  int addr = GET_ADDR(to_send);
  CanfdCounterState* st = find_canfd_counter_state(addr);
  if ((st == NULL) || !st->check_counter || !st->counter_valid) {
    return;
  }

  uint8_t mask = hyundai_canfd_get_counter_mask(to_send);
  uint8_t step = (st->counter_step > 0U) ? st->counter_step : 1U;

  // tx 시작 전에는 마지막 rx 기준
  // tx가 시작된 뒤에는 마지막 tx 기준으로 계속 증가
  uint8_t base = st->tx_counter_valid ? st->last_counter_tx : st->last_counter_rx;
  uint8_t next_counter = (base + step) & mask;

  hyundai_canfd_set_counter(to_send, next_counter);
  hyundai_canfd_update_checksum(to_send);

  st->last_counter_tx = next_counter;
  st->tx_counter_valid = true;
}

static void canfd_record_tx_time(int bus, int addr, bool tx) {
  CanfdTxState* st = find_canfd_tx_state(bus, addr);
  if (st != NULL) {
    st->last_tx_us = tx ? microsecond_timer_get() : 0U;
  }
}

static bool canfd_should_block_fwd(int tx_bus, int addr, uint32_t now) {
  CanfdTxState* st = find_canfd_tx_state(tx_bus, addr);
  if (st == NULL) {
    return false;
  }
  return (now - st->last_tx_us) < st->timeout_us;
}

static void hyundai_canfd_rx_hook(const CANPacket_t *to_push) {
  int bus = GET_BUS(to_push);
  int addr = GET_ADDR(to_push);

  canfd_update_counter_state_from_rx(to_push);

  int pt_bus = hyundai_canfd_hda2 ? 1 : 0;
  const int scc_bus = hyundai_camera_scc ? 2 : pt_bus;

  if (hyundai_camera_scc) pt_bus = 0;

  if (bus == pt_bus) {
    // driver torque
    if (addr == 0xea) {
      int torque_driver_new = ((GET_BYTE(to_push, 11) & 0x1fU) << 8U) | GET_BYTE(to_push, 10);
      torque_driver_new -= 4095;
      update_sample(&torque_driver, torque_driver_new);
    }

    // cruise buttons
    const int button_addr = hyundai_canfd_alt_buttons ? 0x1aa : 0x1cf;
    if (addr == button_addr) {
      bool main_button = false;
      int cruise_button = 0;
      if (addr == 0x1cf) {
        cruise_button = GET_BYTE(to_push, 2) & 0x7U;
        main_button = GET_BIT(to_push, 19U);
      } else {
        cruise_button = (GET_BYTE(to_push, 4) >> 4) & 0x7U;
        main_button = GET_BIT(to_push, 34U);
      }
      hyundai_common_cruise_buttons_check(cruise_button, main_button);
    }

    // gas press, different for EV, hybrid, and ICE models
    if ((addr == 0x35) && hyundai_ev_gas_signal) {
      gas_pressed = GET_BYTE(to_push, 5) != 0U;
    } else if ((addr == 0x105) && hyundai_hybrid_gas_signal) {
      gas_pressed = GET_BIT(to_push, 103U) || (GET_BYTE(to_push, 13) != 0U) || GET_BIT(to_push, 112U);
    } else if ((addr == 0x100) && !hyundai_ev_gas_signal && !hyundai_hybrid_gas_signal) {
      gas_pressed = GET_BIT(to_push, 176U);
    } else {
    }

    // brake press
    if (addr == 0x175) {
      brake_pressed = GET_BIT(to_push, 81U);
    }

    // vehicle moving
    if (addr == 0xa0) {
      uint32_t fl = (GET_BYTES(to_push, 8, 2)) & 0x3FFFU;
      uint32_t fr = (GET_BYTES(to_push, 10, 2)) & 0x3FFFU;
      uint32_t rl = (GET_BYTES(to_push, 12, 2)) & 0x3FFFU;
      uint32_t rr = (GET_BYTES(to_push, 14, 2)) & 0x3FFFU;
      vehicle_moving = (fl > HYUNDAI_STANDSTILL_THRSLD) || (fr > HYUNDAI_STANDSTILL_THRSLD) ||
                       (rl > HYUNDAI_STANDSTILL_THRSLD) || (rr > HYUNDAI_STANDSTILL_THRSLD);

      // average of all 4 wheel speeds. Conversion: raw * 0.03125 / 3.6 = m/s
      UPDATE_VEHICLE_SPEED((fr + rr + rl + fl) / 4.0 * 0.03125 / 3.6);
    }
  }

  if (bus == scc_bus) {
    // cruise state
    if ((addr == 0x1a0) && !hyundai_longitudinal) {
      // 1=enabled, 2=driver override
      int cruise_status = ((GET_BYTE(to_push, 8) >> 4) & 0x7U);
      bool cruise_engaged = (cruise_status == 1) || (cruise_status == 2);
      hyundai_common_cruise_state_check(cruise_engaged);
    }
  }

  const int steer_addr = hyundai_canfd_hda2 ? hyundai_canfd_hda2_get_lkas_addr() : 0x12a;
  bool stock_ecu_detected = (addr == steer_addr) && (bus == 0);
  if (hyundai_longitudinal) {
    // on HDA2, ensure ADRV ECU is still knocked out
    // on others, ensure accel msg is blocked from camera
    const int stock_scc_bus = hyundai_canfd_hda2 ? 1 : 0;
    stock_ecu_detected = stock_ecu_detected || ((addr == 0x1a0) && (bus == stock_scc_bus));
  }
  generic_rx_checks(stock_ecu_detected);

}

static bool hyundai_canfd_tx_hook(const CANPacket_t *to_send_const) {
  CANPacket_t* to_send = (CANPacket_t*)to_send_const;

  const TorqueSteeringLimits HYUNDAI_CANFD_STEERING_LIMITS = {
    .max_steer = 512,
    .max_rt_delta = 112,
    .max_rt_interval = 250000,
    .max_rate_up = 10,
    .max_rate_down = 10,
    .driver_torque_allowance = 250,
    .driver_torque_multiplier = 2,
    .type = TorqueDriverLimited,

    // the EPS faults when the steering angle is above a certain threshold for too long. to prevent this,
    // we allow setting torque actuation bit to 0 while maintaining the requested torque value for two consecutive frames
    .min_valid_request_frames = 89,
    .max_invalid_request_frames = 2,
    .min_valid_request_rt_interval = 810000,  // 810ms; a ~10% buffer on cutting every 90 frames
    .has_steer_req_tolerance = true,
  };

  bool tx = true;
  int addr = GET_ADDR(to_send);

  canfd_fix_counter_and_checksum(to_send);

  // steering
  const int steer_addr = (hyundai_canfd_hda2 && !hyundai_longitudinal) ? hyundai_canfd_hda2_get_lkas_addr() : 0x12a;
  if (addr == steer_addr) {
    int desired_torque = (((GET_BYTE(to_send, 6) & 0xFU) << 7U) | (GET_BYTE(to_send, 5) >> 1U)) - 1024U;
    bool steer_req = GET_BIT(to_send, 52U);

    if (steer_torque_cmd_checks(desired_torque, steer_req, HYUNDAI_CANFD_STEERING_LIMITS)) {
      //tx = false;
    }
  }

#if 0
  // cruise buttons check
  if (addr == 0x1cf) {
    int button = GET_BYTE(to_send, 2) & 0x7U;
    bool is_cancel = (button == HYUNDAI_BTN_CANCEL);
    bool is_resume = (button == HYUNDAI_BTN_RESUME);
    bool is_set = (button == HYUNDAI_BTN_SET);

    bool allowed = (is_cancel && cruise_engaged_prev) || (is_resume && controls_allowed) || (is_set && controls_allowed);
    if (!allowed) {
      tx = false;
    }
  }
#endif

  // UDS: only tester present ("\x02\x3E\x80\x00\x00\x00\x00\x00") allowed on diagnostics address
  if ((addr == 0x730) && hyundai_canfd_hda2) {
    if ((GET_BYTES(to_send, 0, 4) != 0x00803E02U) || (GET_BYTES(to_send, 4, 4) != 0x0U)) {
      tx = false;
    }
  }

  // ACCEL: safety check
  if (addr == 0x1a0) {
    int desired_accel_raw = (((GET_BYTE(to_send, 17) & 0x7U) << 8) | GET_BYTE(to_send, 16)) - 1023U;
    int desired_accel_val = ((GET_BYTE(to_send, 18) << 4) | (GET_BYTE(to_send, 17) >> 4)) - 1023U;

    bool violation = false;

    if (hyundai_longitudinal) {
      int cruise_status = ((GET_BYTE(to_send, 8) >> 4) & 0x7U);
      bool cruise_engaged = (cruise_status == 1) || (cruise_status == 2) || (cruise_status == 4);
      if (cruise_engaged) {
        if (!controls_allowed) print("automatic controls_allowed enabled....\n");
        controls_allowed = true;
      }
      violation |= longitudinal_accel_checks(desired_accel_raw, HYUNDAI_LONG_LIMITS);
      violation |= longitudinal_accel_checks(desired_accel_val, HYUNDAI_LONG_LIMITS);
      if (violation) {
          print("long violation"); putui((uint32_t)desired_accel_raw); print(","); putui((uint32_t)desired_accel_val); print("\n");
      }

    } else {
      // only used to cancel on here
      if ((desired_accel_raw != 0) || (desired_accel_val != 0)) {
        violation = true;
        print("no long violation\n");
      }
    }

    if (violation) {
      tx = false;
    }
  }

  canfd_record_tx_time(GET_BUS(to_send), addr, tx);

  return tx;
}

// fwd_hook 전체 교체
static int hyundai_canfd_fwd_hook(int bus_num, int addr) {
  int bus_fwd = -1;
  uint32_t now = microsecond_timer_get();

  if (bus_num == 0) {
    bus_fwd = 2;

    if (canfd_should_block_fwd(2, addr, now)) {
      bus_fwd = -1;
    }

    if (addr == 0x4B9) {
      bus_fwd = -1;
    }
  }

  if (bus_num == 1) {
    canfd_debug_track_addr(&canfd_addr_debug_bus1, addr, "!!!!! bus1_list=");
  }

  if (bus_num == 2) {
    canfd_debug_track_addr(&canfd_addr_debug_bus2, addr, "@@@@ bus2_list=");

    bus_fwd = 0;
    if (canfd_should_block_fwd(0, addr, now)) {
      bus_fwd = -1;
    }
  }

  return bus_fwd;
}

static safety_config hyundai_canfd_init(uint16_t param) {

  for (int i = 0; canfd_tx_states[i].addr > 0; i++) {
    canfd_tx_states[i].timeout_us = (uint32_t)(1000000.0 / canfd_tx_states[i].hz) + 20000U;
    canfd_tx_states[i].last_tx_us = 0U;
  }

  for (int i = 0; canfd_counter_states[i].addr > 0; i++) {
    canfd_counter_states[i].last_counter_rx = 0U;
    canfd_counter_states[i].last_counter_tx = 0U;
    canfd_counter_states[i].counter_step = 0U;
    canfd_counter_states[i].counter_valid = false;
    canfd_counter_states[i].tx_counter_valid = false;
  }

  canfd_addr_debug_bus1.count = 0;
  canfd_addr_debug_bus2.count = 0;

  hyundai_common_init(param);

  gen_crc_lookup_table_16(0x1021, hyundai_canfd_crc_lut);
  hyundai_canfd_alt_buttons = GET_FLAG(param, HYUNDAI_PARAM_CANFD_ALT_BUTTONS);
  hyundai_canfd_hda2_alt_steering = GET_FLAG(param, HYUNDAI_PARAM_CANFD_HDA2_ALT_STEERING);

  // no long for radar-SCC HDA1 yet
  //if (!hyundai_canfd_hda2 && !hyundai_camera_scc) {
  //    hyundai_longitudinal = false;
  //}
  safety_config ret;
  if (hyundai_longitudinal) {
    if (hyundai_canfd_hda2) {
        print("hyundai safety canfd_hda2 long-");
        if(hyundai_camera_scc) print("camera_scc \n");
        else print("no camera_scc \n");
        if (hyundai_canfd_alt_buttons) {          // carrot : for CANIVAL 4TH HDA2
            print("hyundai safety canfd_hda2 long_alt_buttons\n");
            if (hyundai_camera_scc) ret = BUILD_SAFETY_CFG(hyundai_canfd_hda2_long_alt_buttons_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);                
            else ret = BUILD_SAFETY_CFG(hyundai_canfd_hda2_long_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
        }
        else {
            if (hyundai_camera_scc) ret = BUILD_SAFETY_CFG(hyundai_canfd_hda2_long_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
            else ret = BUILD_SAFETY_CFG(hyundai_canfd_hda2_long_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
        }
    } else {
      if(hyundai_canfd_alt_buttons) print("hyundai safety canfd_hda1 long alt_buttons\n");
      else print("hyundai safety canfd_hda1 long general_buttons\n");

      ret = hyundai_canfd_alt_buttons ? BUILD_SAFETY_CFG(hyundai_canfd_long_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS) : \
                                        BUILD_SAFETY_CFG(hyundai_canfd_long_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS);
    }
  } else {
    print("hyundai safety canfd_hda2 stock");
    if (hyundai_camera_scc) print("camera_scc \n");
    else print("no camera_scc \n");
    if (hyundai_canfd_hda2 && hyundai_camera_scc) {
      if (hyundai_canfd_alt_buttons) { // carrot : for CANIVAL 4TH HDA2
        ret = hyundai_canfd_hda2_alt_steering ? BUILD_SAFETY_CFG(hyundai_canfd_hda2_alt_buttons_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS) : \
          BUILD_SAFETY_CFG(hyundai_canfd_hda2_alt_buttons_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
      }
      else {
        ret = hyundai_canfd_hda2_alt_steering ? BUILD_SAFETY_CFG(hyundai_canfd_hda2_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS) : \
          BUILD_SAFETY_CFG(hyundai_canfd_hda2_rx_checks_scc2, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
      }
    }else if (hyundai_canfd_hda2) {
        if (hyundai_canfd_alt_buttons) { // carrot : for CANIVAL 4TH HDA2
            ret = hyundai_canfd_hda2_alt_steering ? BUILD_SAFETY_CFG(hyundai_canfd_hda2_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS) : \
                BUILD_SAFETY_CFG(hyundai_canfd_hda2_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
        }
        else {
            ret = hyundai_canfd_hda2_alt_steering ? BUILD_SAFETY_CFG(hyundai_canfd_hda2_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS) : \
                BUILD_SAFETY_CFG(hyundai_canfd_hda2_rx_checks, HYUNDAI_CANFD_HDA2_LONG_TX_MSGS);
        }
    } else if (!hyundai_camera_scc) {
      static RxCheck hyundai_canfd_radar_scc_alt_buttons_rx_checks[] = {
        HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
        HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
        HYUNDAI_CANFD_SCC_ADDR_CHECK(0)
      };

      // Radar sends SCC messages on these cars instead of camera
      static RxCheck hyundai_canfd_radar_scc_rx_checks[] = {
        HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
        HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)
        HYUNDAI_CANFD_SCC_ADDR_CHECK(0)
      };

      ret = hyundai_canfd_alt_buttons ? BUILD_SAFETY_CFG(hyundai_canfd_radar_scc_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS) : \
                                        BUILD_SAFETY_CFG(hyundai_canfd_radar_scc_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS);
    } else {
      // *** Non-HDA2 checks ***
      static RxCheck hyundai_canfd_alt_buttons_rx_checks[] = {
        HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
        HYUNDAI_CANFD_ALT_BUTTONS_ADDR_CHECK(0)
        HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
      };

      // Camera sends SCC messages on HDA1.
      // Both button messages exist on some platforms, so we ensure we track the correct one using flag
      static RxCheck hyundai_canfd_rx_checks[] = {
        HYUNDAI_CANFD_COMMON_RX_CHECKS(0)
        HYUNDAI_CANFD_BUTTONS_ADDR_CHECK(0)
        HYUNDAI_CANFD_SCC_ADDR_CHECK(2)
      };

      ret = hyundai_canfd_alt_buttons ? BUILD_SAFETY_CFG(hyundai_canfd_alt_buttons_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS) : \
                                        BUILD_SAFETY_CFG(hyundai_canfd_rx_checks, HYUNDAI_CANFD_HDA1_TX_MSGS);
    }
  }

  return ret;
}

const safety_hooks hyundai_canfd_hooks = {
  .init = hyundai_canfd_init,
  .rx = hyundai_canfd_rx_hook,
  .tx = hyundai_canfd_tx_hook,
  .fwd = hyundai_canfd_fwd_hook,
  .get_counter = hyundai_canfd_get_counter,
  .get_checksum = hyundai_canfd_get_checksum,
  .compute_checksum = hyundai_common_canfd_compute_checksum,
};
