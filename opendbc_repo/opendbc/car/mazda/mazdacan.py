from opendbc.car.mazda.values import Buttons, MazdaFlags


def create_steering_control(packer, CP, frame, apply_steer, lkas):
  """创建转向控制CAN消息

  Args:
      packer: CAN消息打包器
      CP: 车辆参数
      frame: 当前帧计数
      apply_steer: 转向力矩值
      lkas: 相机LKAS数据

  Returns:
      packer.make_can_msg: 打包好的转向控制CAN消息
  """
  # 安全检查和错误处理
  if lkas is None or not isinstance(lkas, dict):
    lkas = {"BIT_1": 0, "ERR_BIT_1": 0, "ERR_BIT_2": 0}

  # 确保apply_steer值在合理范围内
  apply_steer = int(max(-2047, min(apply_steer, 2047)))

  tmp = apply_steer + 2048

  lo = tmp & 0xFF
  hi = tmp >> 8

  # 安全获取LKAS数据，使用get方法避免KeyError
  b1 = int(lkas.get("BIT_1", 0))
  er1 = int(lkas.get("ERR_BIT_1", 0))
  lnv = int(lkas.get("LINE_NOT_VISIBLE", 0))
  ldw = int(lkas.get("LDW", 0))
  er2 = int(lkas.get("ERR_BIT_2", 0))

  # Some older models do have these, newer models don't.
  # Either way, they all work just fine if set to zero.
  steering_angle = 0
  b2 = 0

  tmp = steering_angle + 2048
  ahi = tmp >> 10
  amd = (tmp & 0x3FF) >> 2
  amd = (amd >> 4) | (( amd & 0xF) << 4)
  alo = (tmp & 0x3) << 2

  # 计数器范围限制
  ctr = frame % 16

  # 计算校验和
  # bytes:     [    1  ] [ 2 ] [             3               ]  [           4         ]
  csum = 249 - ctr - hi - lo - (lnv << 3) - er1 - (ldw << 7) - ( er2 << 4) - (b1 << 5)

  # bytes      [ 5 ] [ 6 ] [    7   ]
  csum = csum - ahi - amd - alo - b2

  if ahi == 1:
    csum = csum + 15

  if csum < 0:
    if csum < -256:
      csum = csum + 512
    else:
      csum = csum + 256

  csum = csum % 256

  values = {}
  if CP.flags & MazdaFlags.GEN1:
    values = {
      "LKAS_REQUEST": apply_steer,
      "CTR": ctr,
      "ERR_BIT_1": er1,
      "LINE_NOT_VISIBLE" : lnv,
      "LDW": ldw,
      "BIT_1": b1,
      "ERR_BIT_2": er2,
      "STEERING_ANGLE": steering_angle,
      "ANGLE_ENABLED": b2,
      "CHKSUM": csum
    }

  return packer.make_can_msg("CAM_LKAS", 0, values)


def create_alert_command(packer, cam_msg: dict, ldw: bool, steer_required: bool):
  """创建警告提示CAN消息

  Args:
      packer: CAN消息打包器
      cam_msg: 相机消息数据
      ldw: 车道偏离警告标志
      steer_required: 需要司机转向标志

  Returns:
      packer.make_can_msg: 打包好的警告CAN消息
  """
  # 安全检查和错误处理
  if cam_msg is None or not isinstance(cam_msg, dict):
    cam_msg = {}

  # 需要确保的关键字段
  required_keys = [
    "LINE_VISIBLE", "LINE_NOT_VISIBLE", "LANE_LINES",
    "BIT1", "BIT2", "BIT3", "NO_ERR_BIT", "S1", "S1_HBEAM"
  ]

  # 创建一个包含所有必需键的默认值字典
  default_values = {key: 0 for key in required_keys}

  # 使用字典推导式安全地获取值
  values = {s: cam_msg.get(s, default_values.get(s, 0)) for s in required_keys}

  # 添加警告相关的值
  values.update({
    # 手把手警告参数
    "HANDS_WARN_3_BITS": 0b111 if steer_required else 0,
    "HANDS_ON_STEER_WARN": steer_required,
    "HANDS_ON_STEER_WARN_2": steer_required,

    # 车道偏离警告参数
    "LDW_WARN_LL": int(ldw),  # 左车道警告
    "LDW_WARN_RL": int(ldw),  # 右车道警告
  })

  return packer.make_can_msg("CAM_LANEINFO", 0, values)


def create_button_cmd(packer, CP, counter, button):
  """创建按钮命令CAN消息

  Args:
      packer: CAN消息打包器
      CP: 车辆参数
      counter: 计数器值
      button: 按钮类型

  Returns:
      packer.make_can_msg: 打包好的按钮命令CAN消息，如果不支持则返回None
  """
  # 检查输入参数合法性
  if packer is None or CP is None:
    return None

  # 确保button是有效的按钮值
  if button not in [Buttons.NONE, Buttons.SET_PLUS, Buttons.SET_MINUS,
                   Buttons.RESUME, Buttons.CANCEL, Buttons.TURN_ON]:
    button = Buttons.NONE  # 默认为NONE

  # 确保counter在有效范围内
  counter = max(0, min(counter, 15))  # 限制在0-15范围内

  # 根据按钮类型设置对应的标志位
  can = int(button == Buttons.CANCEL)
  res = int(button == Buttons.RESUME)
  inc = int(button == Buttons.SET_PLUS)
  dec = int(button == Buttons.SET_MINUS)
  turn_on = int(button == Buttons.TURN_ON)

  # 检查车辆标志
  if hasattr(CP, 'flags') and CP.flags & MazdaFlags.GEN1:
    # 设置按钮值及其反转值，确保符合Mazda的CAN协议
    values = {
      "CAN_OFF": can,
      "CAN_OFF_INV": (can + 1) % 2,  # 反转值

      "SET_P": inc,
      "SET_P_INV": (inc + 1) % 2,

      "RES": res,
      "RES_INV": (res + 1) % 2,

      "SET_M": dec,
      "SET_M_INV": (dec + 1) % 2,

      # 距离调整按钮 - 目前未实际使用
      "DISTANCE_LESS": 0,
      "DISTANCE_LESS_INV": 1,

      "DISTANCE_MORE": 0,
      "DISTANCE_MORE_INV": 1,

      # 模式按钮 - 目前未实际使用
      "MODE_X": 0,
      "MODE_X_INV": 1,

      "MODE_Y": 0,
      "MODE_Y_INV": 1,

      # 固定位和计数器
      "BIT1": 1,
      "BIT2": 1,
      "BIT3": 1,
      "CTR": (counter + 1) % 16,  # 计数器递增并循环
    }

    try:
      return packer.make_can_msg("CRZ_BTNS", 0, values)
    except Exception as e:
      print(f"Error creating button command: {e}")
      return None

  # 如果CP.flags不包含MazdaFlags.GEN1，则返回None
  return None
