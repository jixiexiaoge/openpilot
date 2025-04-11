from opendbc.car.mazda.values import Buttons, MazdaFlags


def create_steering_control(packer, CP, frame, apply_torque, lkas):

  tmp = apply_torque + 2048

  lo = tmp & 0xFF
  hi = tmp >> 8

  # copy values from camera
  b1 = int(lkas["BIT_1"])
  er1 = int(lkas["ERR_BIT_1"])
  lnv = 0
  ldw = 0
  er2 = int(lkas["ERR_BIT_2"])

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
      "LKAS_REQUEST": apply_torque,
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
  values = {s: cam_msg[s] for s in [
    "LINE_VISIBLE",
    "LINE_NOT_VISIBLE",
    "LANE_LINES",
    "BIT1",
    "BIT2",
    "BIT3",
    "NO_ERR_BIT",
    "S1",
    "S1_HBEAM",
  ]}
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

  can = int(button == Buttons.CANCEL)
  res = int(button == Buttons.RESUME)
  inc = int(button == Buttons.SET_PLUS)
  dec = int(button == Buttons.SET_MINUS)

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


def create_radar_command(packer, CP, radar_data):
  """
  创建雷达控制命令
  Args:
    packer: can包装器
    CP: 车辆参数
    radar_data: 雷达数据字典，包含distance和rel_speed
  """
  if CP.flags & MazdaFlags.GEN1:
    values = {
      "RADAR_TRACK_ACTIVE": 1 if radar_data.get("distance", 0) > 0 else 0,
      "RADAR_TRACK_VALID": 1 if radar_data.get("distance", 0) > 0 else 0,
      "RADAR_DISTANCE": radar_data.get("distance", 0),
      "RADAR_REL_SPEED": radar_data.get("rel_speed", 0),
      "RADAR_COUNTER": (radar_data.get("counter", 0) + 1) % 16,
      "RADAR_FAULT": 0,  # 默认无故障
      "RADAR_CAN_ID": radar_data.get("track_id", 0),
      "RADAR_CROSS_FLAG": 0,  # 默认无横向移动
      "RADAR_HUD_ALERT": 0,  # 默认无HUD警告
    }
    return packer.make_can_msg("RADAR_HUD", 0, values)
  return None


def create_radar_track(packer, CP, track_id, track_data):
  """
  创建雷达目标跟踪消息
  Args:
    packer: can包装器
    CP: 车辆参数
    track_id: 目标ID
    track_data: 目标数据字典
  """
  if CP.flags & MazdaFlags.GEN1:
    values = {
      "TRACK_ID": track_id,
      "TRACK_VALID": 1 if track_data.get("valid", False) else 0,
      "TRACK_RANGE": track_data.get("distance", 0),
      "TRACK_RANGE_RATE": track_data.get("rel_speed", 0),
      "TRACK_ANGLE": track_data.get("angle", 0),
      "TRACK_LATERAL_RATE": track_data.get("lat_speed", 0),
      "TRACK_WIDTH": track_data.get("width", 0),
      "TRACK_TYPE": track_data.get("type", 0),
      "TRACK_PROB": track_data.get("probability", 0),
    }
    return packer.make_can_msg(f"RADAR_TRACK_{track_id}", 0, values)
  return None
