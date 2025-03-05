from opendbc.car.mazda.values import Buttons, MazdaFlags
from opendbc.car.common.conversions import Conversions as CV


def create_steering_control(packer, CP, frame, apply_steer, lkas):

  tmp = apply_steer + 2048

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


def create_mazda_acc_spam_command(packer, controller, CS, slcSet, Vego, is_metric=True, experimental_mode=False, accel=0):
  """
  创建自动控制车速的CAN消息

  参数:
  - packer: CAN消息打包器
  - controller: 车辆控制器
  - CS: 车辆状态
  - slcSet: 目标速度(m/s)
  - Vego: 当前车速(m/s)
  - is_metric: 是否使用公制单位
  - experimental_mode: 是否使用实验模式
  - accel: 加速度

  返回:
  - CAN消息列表
  """
  cruiseBtn = Buttons.NONE

  MS_CONVERT = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH

  speedSetPoint = int(round(CS.out.cruiseState.speed * MS_CONVERT))
  slcSet = int(round(slcSet * MS_CONVERT))

  if not experimental_mode:
    if slcSet + 5 < Vego * MS_CONVERT:
      slcSet = slcSet - 10  # 降低10单位以增加减速效果，直到与当前速度差小于5
  else:
    slcSet = int(round((Vego + 5 * accel) * MS_CONVERT))

  if is_metric:  # 公制单位时按5km/h的步长调整
    slcSet = int(round(slcSet/5.0)*5.0)
    speedSetPoint = int(round(speedSetPoint/5.0)*5.0)

  if slcSet < speedSetPoint and speedSetPoint > (30 if is_metric else 20):
    cruiseBtn = Buttons.SET_MINUS
  elif slcSet > speedSetPoint:
    cruiseBtn = Buttons.SET_PLUS
  else:
    cruiseBtn = Buttons.NONE

  if (cruiseBtn != Buttons.NONE):
    return [create_button_cmd(packer, controller.CP, controller.frame // 10, cruiseBtn)]
  else:
    return []
