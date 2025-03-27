from openpilot.selfdrive.car.mazda.values import Buttons, MazdaFlags
from openpilot.common.conversions import Conversions as CV

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

def create_mazda_acc_spam_command(packer, controller, CS, slcSet, Vego, frogpilot_variables, accel):
  cruiseBtn = Buttons.NONE

  MS_CONVERT = CV.MS_TO_KPH if frogpilot_variables.is_metric else CV.MS_TO_MPH

  speedSetPoint = int(round(CS.out.cruiseState.speed * MS_CONVERT))
  slcSet = int(round(slcSet * MS_CONVERT))
  current_speed = Vego * MS_CONVERT

  # 低速控制逻辑（15-30km/h）
  low_speed_control = False
  min_speed_threshold = 15 if frogpilot_variables.is_metric else 9  # 15km/h 或 9mph
  max_speed_threshold = 30 if frogpilot_variables.is_metric else 18  # 30km/h 或 18mph

  if min_speed_threshold <= current_speed < max_speed_threshold:
    low_speed_control = True
    # 在低速范围内，我们使用不同的逻辑来计算目标速度
    if not frogpilot_variables.experimentalMode:
      # 计算一个更温和的减速目标，确保不会太激进
      speed_diff = current_speed - slcSet
      if speed_diff > 0:  # 需要减速
        # 根据当前速度调整减速幅度，速度越低减速越温和
        reduction_factor = (current_speed - min_speed_threshold) / (max_speed_threshold - min_speed_threshold)
        max_reduction = min(3 + (2 * reduction_factor), speed_diff)  # 减速幅度从3km/h到5km/h
        slcSet = int(round(current_speed - max_reduction))
    else:
      # 实验模式使用基于加速度的计算，但更温和
      accel_factor = min(3.0, max(1.0, current_speed / max_speed_threshold * 3.0))
      slcSet = int(round((Vego + accel_factor * accel) * MS_CONVERT))
  else:
    # 正常速度范围的逻辑
    if not frogpilot_variables.experimentalMode:
      if slcSet + 5 < current_speed:
        slcSet = slcSet - 10  # 10 lower to increase deceleration until with 5
    else:
      slcSet = int(round((Vego + 5 * accel) * MS_CONVERT))

  if frogpilot_variables.is_metric:  # Default is by 5 kph
    slcSet = int(round(slcSet/5.0)*5.0)
    speedSetPoint = int(round(speedSetPoint/5.0)*5.0)

  # 确保目标速度不低于最小阈值
  slcSet = max(slcSet, min_speed_threshold)

  # 修改逻辑，低速控制时也允许发送减速命令
  if low_speed_control:
    # 避免频繁发送命令，只有当目标速度与当前设定速度差异足够大时才发送
    speed_diff = abs(slcSet - speedSetPoint)
    if speed_diff >= 3:  # 至少3km/h的差异才发送命令
      if slcSet < speedSetPoint:
        cruiseBtn = Buttons.SET_MINUS
      elif slcSet > speedSetPoint:
        cruiseBtn = Buttons.SET_PLUS
  else:
    # 原有逻辑，只在速度大于阈值时发送命令
    min_cruise_speed = 30 if frogpilot_variables.is_metric else 20
    if slcSet < speedSetPoint and speedSetPoint > min_cruise_speed:
      cruiseBtn = Buttons.SET_MINUS
    elif slcSet > speedSetPoint:
      cruiseBtn = Buttons.SET_PLUS

  if (cruiseBtn != Buttons.NONE):
    return [create_button_cmd(packer, controller.CP, controller.frame // 10, cruiseBtn)]
  else:
    return []
