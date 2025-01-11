from openpilot.selfdrive.car.mazda.values import Buttons, MazdaFlags
from openpilot.common.conversions import Conversions as CV


def create_steering_control(packer, CP, frame, apply_steer, lkas):
  """创建转向控制CAN消息"""

  # 转向值加上2048的偏移量
  tmp = apply_steer + 2048

  # 将转向值分解为高低字节
  lo = tmp & 0xFF
  hi = tmp >> 8

  # 从相机消息中复制值
  b1 = int(lkas["BIT_1"])
  er1 = int(lkas["ERR_BIT_1"])
  lnv = 0  # 车道线不可见标志
  ldw = 0  # 车道偏离警告标志
  er2 = int(lkas["ERR_BIT_2"])

  # 一些旧型号有这些参数，新型号没有
  # 无论如何，设置为零都能正常工作
  steering_angle = 0  # 方向盘角度
  b2 = 0

  # 处理方向盘角度数据
  tmp = steering_angle + 2048
  ahi = tmp >> 10
  amd = (tmp & 0x3FF) >> 2
  amd = (amd >> 4) | ((amd & 0xF) << 4)
  alo = (tmp & 0x3) << 2

  # 计算计数器（0-15循环）
  ctr = frame % 16

  # 计算校验和
  # 字节:     [    1  ] [ 2 ] [             3               ]  [           4         ]
  csum = 249 - ctr - hi - lo - (lnv << 3) - er1 - (ldw << 7) - (er2 << 4) - (b1 << 5)

  # 字节      [ 5 ] [ 6 ] [    7   ]
  csum = csum - ahi - amd - alo - b2

  # 校验和调整
  if ahi == 1:
    csum = csum + 15

  if csum < 0:
    if csum < -256:
      csum = csum + 512
    else:
      csum = csum + 256

  csum = csum % 256

  # 创建消息值字典
  values = {}
  if CP.flags & MazdaFlags.GEN1:
    values = {
      "LKAS_REQUEST": apply_steer,    # LKAS请求的转向值
      "CTR": ctr,                     # 计数器
      "ERR_BIT_1": er1,              # 错误位1
      "LINE_NOT_VISIBLE": lnv,        # 车道线不可见标志
      "LDW": ldw,                     # 车道偏离警告
      "BIT_1": b1,                    # 位1
      "ERR_BIT_2": er2,              # 错误位2
      "STEERING_ANGLE": steering_angle, # 方向盘角度
      "ANGLE_ENABLED": b2,            # 角度启用标志
      "CHKSUM": csum                  # 校验和
    }

  return packer.make_can_msg("CAM_LKAS", 0, values)


def create_alert_command(packer, cam_msg: dict, ldw: bool, steer_required: bool):
  """创建警告命令CAN消息"""

  # 从相机消息中复制特定值
  values = {s: cam_msg[s] for s in [
    "LINE_VISIBLE",        # 车道线可见
    "LINE_NOT_VISIBLE",    # 车道线不可见
    "LANE_LINES",         # 车道线
    "BIT1",              # 位1
    "BIT2",              # 位2
    "BIT3",              # 位3
    "NO_ERR_BIT",        # 无错误位
    "S1",                # S1标志
    "S1_HBEAM",          # S1远光灯
  ]}

  # 更新警告相关的值
  values.update({
    # TODO: 这些值之间有什么区别？我们需要全部发送吗？
    "HANDS_WARN_3_BITS": 0b111 if steer_required else 0,  # 三位手部警告
    "HANDS_ON_STEER_WARN": steer_required,                # 手握方向盘警告
    "HANDS_ON_STEER_WARN_2": steer_required,              # 手握方向盘警告2

    # TODO: 右侧车道工作，左侧不工作
    # TODO: 需要处理左/右问题
    "LDW_WARN_LL": 0,    # 左侧车道偏离警告
    "LDW_WARN_RL": 0,    # 右侧车道偏离警告
  })
  return packer.make_can_msg("CAM_LANEINFO", 0, values)


def create_button_cmd(packer, CP, counter, button):
  """创建按钮命令CAN消息"""

  # 根据按钮类型设置相应的标志
  can = int(button == Buttons.CANCEL)    # 取消按钮
  res = int(button == Buttons.RESUME)    # 恢复按钮
  inc = int(button == Buttons.SET_PLUS)  # 增加设定按钮
  dec = int(button == Buttons.SET_MINUS) # 减少设定按钮

  if CP.flags & MazdaFlags.GEN1:
    values = {
      "CAN_OFF": can,                # 取消按钮状态
      "CAN_OFF_INV": (can + 1) % 2,  # 取消按钮状态取反

      "SET_P": inc,                  # 增加设定按钮状态
      "SET_P_INV": (inc + 1) % 2,    # 增加设定按钮状态取反

      "RES": res,                    # 恢复按钮状态
      "RES_INV": (res + 1) % 2,      # 恢复按钮状态取反

      "SET_M": dec,                  # 减少设定按钮状态
      "SET_M_INV": (dec + 1) % 2,    # 减少设定按钮状态取反

      "DISTANCE_LESS": 0,            # 减少距离
      "DISTANCE_LESS_INV": 1,        # 减少距离取反

      "DISTANCE_MORE": 0,            # 增加距离
      "DISTANCE_MORE_INV": 1,        # 增加距离取反

      "MODE_X": 0,                   # 模式X
      "MODE_X_INV": 1,              # 模式X取反

      "MODE_Y": 0,                   # 模式Y
      "MODE_Y_INV": 1,              # 模式Y取反

      "BIT1": 1,                     # 位1
      "BIT2": 1,                     # 位2
      "BIT3": 1,                     # 位3
      "CTR": (counter + 1) % 16,     # 计数器（0-15循环）
    }

    return packer.make_can_msg("CRZ_BTNS", 0, values)

def create_mazda_acc_spam_command(packer, controller, CS, slcSet, Vego, frogpilot_variables, accel):
  """创建马自达ACC控制命令"""

  cruiseBtn = Buttons.NONE  # 初始化巡航按钮为无

  # 根据是否为公制单位选择速度转换系数
  MS_CONVERT = CV.MS_TO_KPH if frogpilot_variables.is_metric else CV.MS_TO_MPH

  # 计算当前设定速度和目标速度
  speedSetPoint = int(round(CS.out.cruiseState.speed * MS_CONVERT))
  slcSet = int(round(slcSet * MS_CONVERT))

  # 根据实验模式调整目标速度
  if not frogpilot_variables.experimentalMode:
    if slcSet + 5 < Vego * MS_CONVERT:
      slcSet = slcSet - 10  # 降低10以增加减速度直到差值小于5
  else:
    slcSet = int(round((Vego + 5 * accel) * MS_CONVERT))

  # 公制单位时按5km/h调整速度
  if frogpilot_variables.is_metric:  # 默认以5km/h为单位
    slcSet = int(round(slcSet/5.0)*5.0)
    speedSetPoint = int(round(speedSetPoint/5.0)*5.0)

  # 根据目标速度和当前设定速度的差值选择按钮操作
  if slcSet < speedSetPoint and speedSetPoint > (30 if frogpilot_variables.is_metric else 20):
    cruiseBtn = Buttons.SET_MINUS  # 需要减速
  elif slcSet > speedSetPoint:
    cruiseBtn = Buttons.SET_PLUS   # 需要加速
  else:
    cruiseBtn = Buttons.NONE       # 保持当前速度

  # 如果需要调整速度，创建按钮命令
  if (cruiseBtn != Buttons.NONE):
    return [create_button_cmd(packer, controller.CP, controller.frame // 10, cruiseBtn)]
  else:
    return []
