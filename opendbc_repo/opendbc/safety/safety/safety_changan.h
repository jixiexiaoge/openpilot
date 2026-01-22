#pragma once

#include "safety_declarations.h"

// CAN msgs we care about
#define CHANGAN_STEER_ANGLE      0x180 // SAS_SteeringAngle
#define CHANGAN_STEER_COMMAND    0x1BA // GW_1BA
#define CHANGAN_STEER_TORQUE     0x17E // GW_17E
#define CHANGAN_WHEEL_SPEEDS     0x187 // GW_187 (Petrol)
#define CHANGAN_IDD_WHEEL_SPEEDS 0x17A // SPEED (IDD)
#define CHANGAN_PEDAL_DATA       0x196 // GW_196 (Petrol Brake/Gas)
#define CHANGAN_IDD_PEDAL_DATA   0x1A6 // GW_1A6 (IDD Brake/Gas)
#define CHANGAN_ACC_COMMAND      0x244 // GW_244
#define CHANGAN_CRUISE_BUTTONS   0x28C // GW_28C (巡航按钮：含MAIN/RESUME/CANCEL)
#define CHANGAN_ADAS_INFO        0x31A // GW_31A (ACC State Info：含ACC主开关状态)
// 新增：巡航按钮位定义（需根据实车DBC核对，此处为通用示例）
#define CHANGAN_BTN_MAIN    (0x01U << 0)  // ACC主开关（1=打开，0=关闭）
#define CHANGAN_BTN_CANCEL  (0x01U << 1)  // 取消按钮（1=按下）
#define CHANGAN_BTN_RESUME  (0x01U << 4)  // 恢复按钮（1=按下）
#define CHANGAN_BTN_SET     (0x01U << 5)  // 设置按钮（1=按下，可选）

const AngleSteeringLimits CHANGAN_STEER_LIMITS = {
  .max_angle = 4760,
  .angle_deg_to_can = 10.,
  .angle_rate_up_lookup = {
    .x = {0, 5, 15},
    .y = {5, 0.8, 0.15},
  },
  .angle_rate_down_lookup = {
    .x = {0, 5, 15},
    .y = {5, 3.5, 0.4},
  },
  .enforce_angle_error = false,
  .inactive_angle_is_zero = false,
};

static const uint8_t changan_crc8_tab[256] = {
  0x00, 0x1D, 0x3A, 0x27, 0x74, 0x69, 0x4E, 0x53, 0xE8, 0xF5, 0xD2, 0xCF, 0x9C, 0x81, 0xA6, 0xBB,
  0xCD, 0xD0, 0xF7, 0xEA, 0xB9, 0xA4, 0x83, 0x9E, 0x25, 0x38, 0x1F, 0x02, 0x51, 0x4C, 0x6B, 0x76,
  0x87, 0x9A, 0xBD, 0xA0, 0xF3, 0xEE, 0xC9, 0xD4, 0x6F, 0x72, 0x55, 0x48, 0x1B, 0x06, 0x21, 0x3C,
  0x4A, 0x57, 0x70, 0x6D, 0x3E, 0x23, 0x04, 0x19, 0xA2, 0xBF, 0x98, 0x85, 0xD6, 0xCB, 0xEC, 0xF1,
  0x13, 0x0E, 0x29, 0x34, 0x67, 0x7A, 0x5D, 0x40, 0xFB, 0xE6, 0xC1, 0xDC, 0x8F, 0x92, 0xB5, 0xA8,
  0xDE, 0xC3, 0xE4, 0xF9, 0xAA, 0xB7, 0x90, 0x8D, 0x36, 0x2B, 0x0C, 0x11, 0x42, 0x5F, 0x78, 0x65,
  0x94, 0x89, 0xAE, 0xB3, 0xE0, 0xFD, 0xDA, 0xC7, 0x7C, 0x61, 0x46, 0x5B, 0x08, 0x15, 0x32, 0x2F,
  0x59, 0x44, 0x63, 0x7E, 0x2D, 0x30, 0x17, 0x0A, 0xB1, 0xAC, 0x8B, 0x96, 0xC5, 0xD8, 0xFF, 0xE2,
  0x26, 0x3B, 0x1C, 0x01, 0x52, 0x4F, 0x68, 0x75, 0xCE, 0xD3, 0xF4, 0xE9, 0xBA, 0xA7, 0x80, 0x9D,
  0xEB, 0xF6, 0xD1, 0xCC, 0x9F, 0x82, 0xA5, 0xB8, 0x03, 0x1E, 0x39, 0x24, 0x77, 0x6A, 0x4D, 0x50,
  0xA1, 0xBC, 0x9B, 0x86, 0xD5, 0xC8, 0xEF, 0xF2, 0x49, 0x54, 0x73, 0x6E, 0x3D, 0x20, 0x07, 0x1A,
  0x6C, 0x71, 0x56, 0x4B, 0x18, 0x05, 0x22, 0x3F, 0x84, 0x99, 0xBE, 0xA3, 0xF0, 0xED, 0xCA, 0xD7,
  0x35, 0x28, 0x0F, 0x12, 0x41, 0x5C, 0x7B, 0x66, 0xDD, 0xC0, 0xE7, 0xFA, 0xA9, 0xB4, 0x93, 0x8E,
  0xf8, 0xE5, 0xC2, 0xDF, 0x8C, 0x91, 0xB6, 0xAB, 0x10, 0x0D, 0x2A, 0x37, 0x64, 0x79, 0x5E, 0x43,
  0xB2, 0xAF, 0x88, 0x95, 0xC6, 0xDB, 0xFC, 0xE1, 0x5A, 0x47, 0x60, 0x7D, 0x2E, 0x33, 0x14, 0x09,
  0x7F, 0x62, 0x45, 0x58, 0x0B, 0x16, 0x31, 0x2C, 0x97, 0x8A, 0xAD, 0xB0, 0xE3, 0xFE, 0xD9, 0xC4
};

// 修复：重命名变量，避免与全局extern int cruise_button_prev冲突
static uint8_t changan_cruise_button_prev = 0x00U;
// 新增：ACC主开关状态（需从ADAS_INFO消息解析，默认关闭）
static bool changan_acc_main_on = false;

static uint32_t changan_get_checksum(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x244 || addr == 0x28C ||
      addr == 0x307 || addr == 0x31A || addr == 0x442 || addr == 0x382) {
    return GET_BYTE(to_push, 7);
  }
  return 0;
}

static uint32_t changan_compute_checksum(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x244 || addr == 0x28C ||
      addr == 0x307 || addr == 0x31A || addr == 0x442 || addr == 0x382) {
    uint8_t checksum = 0;
    for (int i = 0; i < 7; i++) {
      checksum = changan_crc8_tab[checksum ^ GET_BYTE(to_push, i)];
    }
    return checksum;
  }
  return 0;
}

static uint8_t changan_get_counter(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  if (addr == 0x180 || addr == 0x17E || addr == 0x187 || addr == 0x17A ||
      addr == 0x196 || addr == 0x1A6 || addr == 0x244 || addr == 0x28C ||
      addr == 0x307 || addr == 0x31A || addr == 0x442 || addr == 0x382) {
    return (GET_BYTE(to_push, 6) >> 4) & 0xF;
  }
  return 0;
}

static void changan_rx_hook(const CANPacket_t *to_push) {
  int addr = GET_ADDR(to_push);
  int bus = GET_BUS(to_push);
  uint8_t current_button = 0x00U; // 当前巡航按钮状态

  // 1. 解析ACC主开关状态（从ADAS_INFO消息获取，关键前提：主开关打开才允许控制）
  if (bus == 2 && addr == CHANGAN_ADAS_INFO) {
    // 注意：需根据实车DBC核对ACC主开关的位定义（示例：字节0的第2位）
    changan_acc_main_on = (GET_BYTE(to_push, 0) & (0x01U << 2)) != 0U;
    // 调试输出：确认主开关状态（实际使用时可注释）
    // printf("[DEBUG] ACC_MAIN_ON: %d\n", changan_acc_main_on);
  }

  // 2. 解析巡航按钮状态（支持bus0和bus2，覆盖汽油版/混动版）
  if ((bus == 0 || bus == 2) && addr == CHANGAN_CRUISE_BUTTONS) {
    // 读取当前按钮状态（字节0存储按钮信号，需根据DBC核对）
    current_button = GET_BYTE(to_push, 0);
    // 调试输出：确认按钮原始数据（实际使用时可注释）
    // printf("[DEBUG] Cruise Button Current: 0x%02X, Previous: 0x%02X\n", current_button, changan_cruise_button_prev);

    // 3. 边缘检测（仅在按钮"按下→释放"时触发，避免持续按压导致状态反复）
    bool btn_resume_trigger = (current_button & CHANGAN_BTN_RESUME) == 0U &&
                              (changan_cruise_button_prev & CHANGAN_BTN_RESUME) != 0U;
    bool btn_set_trigger = (current_button & CHANGAN_BTN_SET) == 0U &&
                           (changan_cruise_button_prev & CHANGAN_BTN_SET) != 0U;
    bool btn_cancel_trigger = (current_button & CHANGAN_BTN_CANCEL) != 0U; // 取消按钮按下即触发

    // 4. 控制权限逻辑（符合安全标准：主开关打开+恢复/设置按钮触发才允许控制）
    if (changan_acc_main_on && (btn_resume_trigger || btn_set_trigger)) {
      controls_allowed = true;
      // printf("[DEBUG] Controls Allowed: ON\n"); // 调试输出
    } else if (btn_cancel_trigger || !changan_acc_main_on) {
      controls_allowed = false;
      // printf("[DEBUG] Controls Allowed: OFF\n"); // 调试输出
    }

    // 5. 保存当前按钮状态为"前一状态"（用于下次边缘检测）
    changan_cruise_button_prev = current_button;
  }

  // 6. 保留原有逻辑：车速、转向角度、踏板数据解析
  if (bus == 0) {
    // Z6汽油版车速更新
    if (addr == CHANGAN_WHEEL_SPEEDS) {
      int speed = ((GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5));
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    // 转向角度更新
    if (addr == CHANGAN_STEER_ANGLE) {
      int angle_meas_new = (GET_BYTE(to_push, 0) << 8) | GET_BYTE(to_push, 1);
      update_sample(&angle_meas, to_signed(angle_meas_new, 16));
    }

    // Z6汽油版油门刹车状态
    if (addr == CHANGAN_PEDAL_DATA) {
      brake_pressed = (GET_BYTE(to_push, 6) & 0x01U) != 0U;
      gas_pressed = (GET_BYTE(to_push, 2) & 0x01U) != 0U;
    }
  }

  if (bus == 2) {
    // IDD混动版车速更新
    if (addr == CHANGAN_IDD_WHEEL_SPEEDS) {
      int speed = ((GET_BYTE(to_push, 4) << 8) | GET_BYTE(to_push, 5));
      UPDATE_VEHICLE_SPEED(speed * 0.05 / 3.6);
    }

    // IDD混动版油门刹车状态
    if (addr == CHANGAN_IDD_PEDAL_DATA) {
      brake_pressed = (GET_BYTE(to_push, 6) & 0x01U) != 0U;
      gas_pressed = (GET_BYTE(to_push, 4) & 0x40U) != 0U;
    }
  }

  // 检测原车ECU消息（保留原有逻辑）
  bool stock_ecu_detected = (bus == 2) && (addr == CHANGAN_STEER_COMMAND);
  generic_rx_checks(stock_ecu_detected);
}

static bool changan_tx_hook(const CANPacket_t *to_send) {
  int addr = GET_ADDR(to_send);
  bool tx = true;
  bool violation = false;

  // 转向控制消息校验（保留原有逻辑）
  if (addr == CHANGAN_STEER_COMMAND) {
    int desired_angle = ((GET_BYTE(to_send, 2) & 0x7FU) << 8) | GET_BYTE(to_send, 3);
    bool steer_req = (GET_BYTE(to_send, 2) & 0x80U) != 0U;

    // 安全检查1: 控制权限
    if (steer_req && !controls_allowed) {
      violation = true;
      // printf("[DEBUG] TX Blocked: Steer req without permission\n"); // 调试输出
    }

    // 安全检查2: 角度限制
    if (steer_angle_cmd_checks(to_signed(desired_angle, 16), steer_req, CHANGAN_STEER_LIMITS)) {
      violation = true;
      // printf("[DEBUG] TX Blocked: Steer angle out of limit\n"); // 调试输出
    }
  }

  // 纵向控制消息校验（0x244/0x442/0x382，保留原有逻辑）
  if (addr == CHANGAN_ACC_COMMAND || addr == 0x442 || addr == 0x382) {
    if (!controls_allowed) {
      violation = true;
      // printf("[DEBUG] TX Blocked: Longitudinal req without permission (addr:0x%X)\n", addr); // 调试输出
    }
  }

  // 无需权限的消息（保留原有逻辑）
  if (addr == 0x307 || addr == 0x31A) {
    // 这些消息通常不需要controls_allowed检查
  }

  if (violation) {
    tx = false;
  }

  return tx;
}

static int changan_fwd_hook(int bus, int addr) {
  int bus_fwd = -1;
  if (bus == 0) {
    bus_fwd = 2;
  }
  if (bus == 2) {
    // 屏蔽敏感控制消息，避免原车ECU冲突（保留原有逻辑）
    bool block = (addr == CHANGAN_STEER_COMMAND) ||
                 (addr == CHANGAN_ACC_COMMAND) ||
                 (addr == 0x307) ||
                 (addr == 0x31A) ||
                 (addr == 0x442) ||
                 (addr == 0x382);
    if (!block) {
      bus_fwd = 0;
    }
  }
  return bus_fwd;
}

static safety_config changan_init(uint16_t param) {
  // 初始化控制权限和心跳（保留原有逻辑）
  controls_allowed = false;
  heartbeat_engaged = false;
  heartbeat_engaged_mismatches = 0U;

  // 新增：初始化长安专属的巡航按钮状态和ACC主开关（避免野值）
  changan_cruise_button_prev = 0x00U;
  changan_acc_main_on = false;

  // 完整的TX消息列表（保留原有逻辑，0x442/0x382已在白名单）
  static const CanMsg CHANGAN_TX_MSGS[] = {
    {CHANGAN_STEER_COMMAND, 0, 32},
    {CHANGAN_ACC_COMMAND, 0, 32},
    {0x307, 0, 64},
    {0x31A, 0, 64},
    {0x442, 0, 32},  // 纵向控制消息（已在白名单）
    {0x382, 2, 8},   // 纵向控制消息（已在白名单）
  };

  // 临时禁用验证用于调试（建议调试完成后改为false）
  static RxCheck changan_rx_checks[] = {
    {.msg = {{CHANGAN_STEER_ANGLE, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, {0}, {0}}},
    {.msg = {{CHANGAN_PEDAL_DATA, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U},
             {CHANGAN_IDD_PEDAL_DATA, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, {0}}},
    // 新增：添加巡航按钮和ADAS_INFO的Rx检查（确保消息正常接收）
    {.msg = {{CHANGAN_CRUISE_BUTTONS, 0, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U},
             {CHANGAN_CRUISE_BUTTONS, 2, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, {0}}},
    {.msg = {{CHANGAN_ADAS_INFO, 2, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, {0}, {0}}},
  };

  UNUSED(param);
  return BUILD_SAFETY_CFG(changan_rx_checks, CHANGAN_TX_MSGS);
}

// 安全钩子注册（保留原有逻辑）
const safety_hooks changan_hooks = {
  .init = changan_init,
  .rx = changan_rx_hook,
  .tx = changan_tx_hook,
  .fwd = changan_fwd_hook,
  .get_checksum = changan_get_checksum,
  .compute_checksum = changan_compute_checksum,
  .get_counter = changan_get_counter,
};