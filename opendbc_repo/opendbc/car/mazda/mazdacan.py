from opendbc.car.mazda.values import Buttons, MazdaFlags


def create_steering_control(packer, CP, frame, apply_steer, lkas):
  # 安全检查和错误处理
  if lkas is None or not isinstance(lkas, dict):
    lkas = {"BIT_1": 0, "ERR_BIT_1": 0, "ERR_BIT_2": 0}

  tmp = apply_steer + 2048

  lo = tmp & 0xFF
  hi = tmp >> 8

  # copy values from camera - 添加安全获取
  b1 = int(lkas.get("BIT_1", 0))
  er1 = int(lkas.get("ERR_BIT_1", 0))
  lnv = 0
  ldw = 0
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

  ctr = frame % 16
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

  values.update({
    # TODO: what's the difference between all these? do we need to send all?
    "HANDS_WARN_3_BITS": 0b111 if steer_required else 0,
    "HANDS_ON_STEER_WARN": steer_required,
    "HANDS_ON_STEER_WARN_2": steer_required,

    # TODO: right lane works, left doesn't
    # TODO: need to do something about L/R
    "LDW_WARN_LL": 0,
    "LDW_WARN_RL": 0,
  })
  return packer.make_can_msg("CAM_LANEINFO", 0, values)


def create_button_cmd(packer, CP, counter, button):
  # 确保button是有效的按钮值
  if button not in [Buttons.NONE, Buttons.SET_PLUS, Buttons.SET_MINUS,
                   Buttons.RESUME, Buttons.CANCEL, Buttons.TURN_ON]:
    button = Buttons.NONE  # 默认为NONE

  # 确保counter在有效范围内
  counter = max(0, min(counter, 15))  # 限制在0-15范围内

  can = int(button == Buttons.CANCEL)
  res = int(button == Buttons.RESUME)
  inc = int(button == Buttons.SET_PLUS)
  dec = int(button == Buttons.SET_MINUS)
  turn_on = int(button == Buttons.TURN_ON)

  if CP.flags & MazdaFlags.GEN1:
    values = {
      "CAN_OFF": can,
      "CAN_OFF_INV": (can + 1) % 2,

      "SET_P": inc,
      "SET_P_INV": (inc + 1) % 2,

      "RES": res,
      "RES_INV": (res + 1) % 2,

      "SET_M": dec,
      "SET_M_INV": (dec + 1) % 2,

      "DISTANCE_LESS": 0,
      "DISTANCE_LESS_INV": 1,

      "DISTANCE_MORE": 0,
      "DISTANCE_MORE_INV": 1,

      "MODE_X": 0,
      "MODE_X_INV": 1,

      "MODE_Y": 0,
      "MODE_Y_INV": 1,

      "BIT1": 1,
      "BIT2": 1,
      "BIT3": 1,
      "CTR": (counter + 1) % 16,
    }

    return packer.make_can_msg("CRZ_BTNS", 0, values)

  # 如果CP.flags不包含MazdaFlags.GEN1，则返回None
  return None
