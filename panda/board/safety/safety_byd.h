// 需要处理的CAN消息定义
#define BYD_CANADDR_IPB              0x1F0
#define BYD_CANADDR_ACC_MPC_STATE     0x316
#define BYD_CANADDR_ACC_EPS_STATE     0x318
#define BYD_CANADDR_ACC_HUD_ADAS      0x32D
#define BYD_CANADDR_ACC_CMD           0x32E
#define BYD_CANADDR_ACC_AEB           0x32F
#define BYD_CANADDR_PCM_BUTTONS       0x3B0
#define BYD_CANADDR_DRIVE_STATE       0x242
#define BYD_CANADDR_PEDAL             0x342
#define BYD_CANADDR_EPS               0x11F
#define BYD_CANADDR_CARSPEED          0x121

// CAN总线编号定义
#define BYD_CANBUS_ESC  0               // ESC总线
#define BYD_CANBUS_MRR  1               // 雷达总线
#define BYD_CANBUS_MPC  2               // MPC总线

bool byd_force_can_transparent_mode = false;
bool byd_eps_cruiseactivated = false;

// 转向限制配置
const SteeringLimits BYD_STEERING_LIMITS = {
  .max_steer = 300,                     // 最大转向值
  .max_rate_up = 18,                    // 最大上升率
  .max_rate_down = 18,                  // 最大下降率
  .max_rt_delta = 243,                  // 最大实时变化 = 18 * 250/20 = 225 + 18 =
  .max_rt_interval = 250000,            // 最大实时间隔 = 250ms
  .max_torque_error = 80,               // motor torque limits
  .type = TorqueMotorLimited,           // 限制类型
};

// 定义byd_han21车辆要发送的 CAN 消息
const CanMsg BYD_TX_MSGS[] = {
  {BYD_CANADDR_ACC_CMD,         0, 8},  // ACC_CMD
  {BYD_CANADDR_ACC_MPC_STATE,   0, 8},  // ACC_MPC_STATE
  {BYD_CANADDR_ACC_EPS_STATE,   2, 8},
  //{BYD_CANADDR_ACC_HUD_ADAS,  0, 8},  // ACC_HUD_ADAS
};

// byd_han21 车型的接收检查结构体
RxCheck byd_han21_rx_checks[] = {
  {.msg = {{BYD_CANADDR_PCM_BUTTONS,      0, 8, .frequency = 20U}, { 0 }, { 0 }}},
  {.msg = {{BYD_CANADDR_ACC_EPS_STATE,    0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  {.msg = {{BYD_CANADDR_CARSPEED,         0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  {.msg = {{BYD_CANADDR_IPB,              0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  {.msg = {{BYD_CANADDR_DRIVE_STATE,      0, 8, .frequency = 50U}, { 0 }, { 0 }}},
};

// 接收CAN消息的钩子函数
static void byd_rx_hook(const CANPacket_t *to_push) {
  int bus = GET_BUS(to_push);
  int addr = GET_ADDR(to_push);

  if (bus == BYD_CANBUS_ESC) {
    if (addr == BYD_CANADDR_PEDAL) {
      gas_pressed = (GET_BYTE(to_push, 0) != 0U);
      brake_pressed = (GET_BYTE(to_push, 1) != 0U);

    } else if (addr == BYD_CANADDR_CARSPEED) {
      int speed_raw = (((GET_BYTE(to_push, 1) & 0x0FU) << 8) | GET_BYTE(to_push, 0));
      vehicle_moving = (speed_raw != 0);

    } else if (addr == BYD_CANADDR_ACC_EPS_STATE) {
      byd_eps_cruiseactivated = GET_BIT(to_push, 1U) != 0U; // CruiseActivated
      int torque_motor = (((GET_BYTE(to_push, 2) & 0x0FU) << 8) | GET_BYTE(to_push, 1)); // MainTorque
      if ( torque_motor >= 2048 )
        torque_motor -= 4096;

      update_sample(&torque_meas, torque_motor);

    }

    generic_rx_checks(addr == BYD_CANADDR_ACC_MPC_STATE);

  }else if (bus == BYD_CANBUS_MPC) {
    if (addr == BYD_CANADDR_ACC_CMD) {

    } else if (addr == BYD_CANADDR_ACC_HUD_ADAS) {
      int accstate = ((GET_BYTE(to_push, 2) >> 3) & 0x07U);
      bool cruise_engaged = (accstate == 0x3) || (accstate == 0x5) || byd_eps_cruiseactivated; // 3=acc_active, 5=user force accel
      pcm_cruise_check(cruise_engaged);

      //acc_main_on = GET_BIT(to_push, 22U) != 0U;
      //mads_acc_main_check(acc_main_on);
    }

  }else{
    //do nothing.
  }
}


// 发送CAN消息的函数
static bool byd_tx_hook(const CANPacket_t *to_send) {
  bool tx = true;
  int bus = GET_BUS(to_send); // 获取发送总线

  // 检查消息是否在主总线上发送
  if (bus == BYD_CANBUS_ESC) {
    //int addr = GET_ADDR(to_send); // 获取消息地址

    // LKAS torque check, disabled due to mpc will keep sending torque while op cruise is disabled
    // if (addr == BYD_CANADDR_ACC_MPC_STATE) {
    //   int desired_torque = ((GET_BYTE(to_send, 3) & 0x07U) << 8U) | GET_BYTE(to_send, 2);
    //   bool steer_req = GET_BIT(to_send, 28U); //LKAS_Active

    //   if ( desired_torque >= 1024 )
    //     desired_torque -= 2048;

    //   if (steer_torque_cmd_checks(desired_torque, steer_req, BYD_STEERING_LIMITS)) {
    //     tx = false;
    //   }
    // }

  }

  return tx; // 返回是否允许发送
}


// 转发函数
static int byd_fwd_hook(int bus, int addr) {
  int bus_fwd = -1; // 初始化转发总线为-1

  if (bus == BYD_CANBUS_ESC) { // if sent from esc
    if(addr != BYD_CANADDR_ACC_EPS_STATE) {
      bus_fwd = BYD_CANBUS_MPC;
    }

  } else if (bus == BYD_CANBUS_MPC) { // if sent from mpc
    bool block_msg = (addr == BYD_CANADDR_ACC_MPC_STATE) || (addr == BYD_CANADDR_ACC_CMD); // 检查是否过滤
    if (!block_msg) {
      bus_fwd = BYD_CANBUS_ESC; // 从摄像头总线转发到主总线
    }
  }

  return bus_fwd; // 返回转发的总线
}


// 安全配置初始化函数
static safety_config byd_init(uint16_t param) {
  UNUSED(param);
  return BUILD_SAFETY_CFG(byd_han21_rx_checks, BYD_TX_MSGS); // 构建安全配置
}

// 安全定义
const safety_hooks byd_hooks = {
  .init = byd_init,
  .rx = byd_rx_hook,
  .tx = byd_tx_hook,
  .fwd = byd_fwd_hook,
};
