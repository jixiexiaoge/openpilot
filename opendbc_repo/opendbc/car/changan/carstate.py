import copy
from opendbc.can.parser import CANParser, CANDefine
from opendbc.car import Bus, DT_CTRL, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.common.filter_simple import FirstOrderFilter
from opendbc.car.interfaces import CarStateBase
from opendbc.car.changan.values import DBC, EPS_SCALE, CAR


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    # 档位解析映射获取
    self.shifter_values = can_define.dv["GEAR"]["gearShifter"]
    self.eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0

    # 巡航状态变量 (遵循 Carrot 参考逻辑)
    self.cruiseEnable = False
    self.cruiseEnablePrev = False
    self.cruiseSpeed = 0
    self.buttonPlus = 0    # RES+ 键状态追踪
    self.buttonReduce = 0  # SET- 键状态追踪

    self.steeringPressed = False
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 3
    else:
      self.steeringPressedMin = 1
      self.steeringPressedMax = 6

    self.iacc_enable_switch_button_prev = 0
    self.iacc_enable_switch_button_rising_edge = False

    # 信号快照 (供 CarController 使用)
    self.sigs244 = {}
    self.sigs1ba = {}
    self.sigs17e = {}
    self.sigs307 = {}
    self.sigs31a = {}

    # 计数器存储 (对应 DBC 标签)
    self.counter_244 = 0
    self.counter_1ba = 0
    self.counter_17e = 0
    self.counter_307 = 0
    self.counter_31a = 0

    self.prev_distance_button = 0
    self.distance_button = 0

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()

    # 基础状态：门开/安全带
    ret.doorOpen = cp.vl["GW_28B"]["doorOpen"] == 1
    ret.seatbeltUnlatched = cp.vl["GW_50"]["seatbeltUnlatched"] == 1
    ret.parkingBrake = False

    # 1. 车辆速度处理 (解析 iDD vs 燃油版)
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      carspd = cp.vl["SPEED"]["wheelSpeeds"]  # iDD 车型 0x17A 正确
    else:
      carspd = cp.vl["GW_187"]["ESP_VehicleSpeed"] # 燃油版 0x187 正确

    # 长安原厂速度补偿因数
    speed = carspd if carspd <= 5 else ((carspd / 0.98) + 2)
    ret.vEgoRaw = speed * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.vEgoCluster = ret.vEgo
    ret.standstill = abs(ret.vEgoRaw) < 1e-3 # 车辆静止判断

    # 2. 档位识别 (基于 0x338 TCU 映射)
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(int(cp.vl["GEAR"]["gearShifter"]), None))

    # 3. 驱动/刹车踏板解析
    if self.CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      ret.brakePressed = cp.vl["GW_1A6"]["brakePressed"] != 0
      ret.gasPressed = cp.vl["GW_1A6"]["gasPressed"] != 0
    else:
      ret.brakePressed = cp.vl["GW_196"]["brakePressed"] != 0
      ret.gasPressed = cp.vl["GW_196"]["gasPressed"] != 0

    # 4. 转向角度与扭矩 (0x180 & 0x17E)
    ret.steeringAngleDeg = cp.vl["GW_180"]["steeringAngleDeg"]
    ret.steeringRateDeg = cp.vl["GW_180"]["SAS_SteeringAngleSpeed"] # 转向速率
    ret.steeringTorque = cp.vl["GW_17E"]["EPS_MeasuredTorsionBarTorque"]
    ret.steeringTorqueEps = cp.vl["GW_170"]["EPS_ActualTorsionBarTorq"] * self.eps_torque_scale

    # 简化脱手/压盘检测 (User preference)
    self.steeringPressed = abs(ret.steeringTorque) > 2.5
    ret.steeringPressed = self.steeringPressed

    # 转向故障位捕捉
    ret.steerFaultTemporary = cp.vl["GW_17E"]["EPS_LatCtrlAvailabilityStatus"] == 2

    # 5. 核心三键巡航逻辑 (ID 0x28C / buttonEvents)
    # 获取 IACC 主开关信号 (支持多总线冗余)
    btn_val = 0
    if "buttonEvents" in cp.vl and cp.vl["buttonEvents"]["Button_iACC"] != 0:
      btn_val = cp.vl["buttonEvents"]["Button_iACC"]
    elif "buttonEvents" in cp_cam.vl:
      btn_val = cp_cam.vl["buttonEvents"]["Button_iACC"]

    # IACC 键上升沿触发逻辑
    self.iacc_enable_switch_button_rising_edge = (btn_val == 1 and self.iacc_enable_switch_button_prev == 0)
    self.iacc_enable_switch_button_prev = btn_val

    if self.iacc_enable_switch_button_rising_edge:
      self.cruiseEnable = not self.cruiseEnable # 按一下切换开关状态
    elif ret.brakePressed:
      self.cruiseEnable = False                  # 刹车立即强制退出

    # 巡航限速调整：RES+ (增加) / SET- (减少)
    if self.cruiseEnable and not self.cruiseEnablePrev:
      self.cruiseSpeed = carspd if self.cruiseSpeed == 0 else self.cruiseSpeed

    # 仅检测 pt 总线的加减键
    btn_res = cp.vl["buttonEvents"].get("Button_ACC_RESPlus", 0)
    btn_set = cp.vl["buttonEvents"].get("Button_SETReduce", 0)

    # 5km/h 阶梯式调速
    if btn_res == 1 and self.buttonPlus == 0 and self.cruiseEnable:
      self.cruiseSpeed = ((self.cruiseSpeed // 5) + 1) * 5
    if btn_set == 1 and self.buttonReduce == 0 and self.cruiseEnable:
      self.cruiseSpeed = max((((self.cruiseSpeed // 5) - 1) * 5), 0)

    # 状态持久化
    self.buttonPlus = btn_res
    self.buttonReduce = btn_set
    self.cruiseEnablePrev = self.cruiseEnable

    ret.cruiseState.available = True
    ret.cruiseState.enabled = self.cruiseEnable
    ret.cruiseState.speed = self.cruiseSpeed * CV.KPH_TO_MS

    # 6. 车载安全预警信号镜像 (防 AEB 图标闪烁核心)
    ret.accFaulted = cp_cam.vl["GW_244"]["ACC_ACCMode"] == 7 or cp_cam.vl["GW_31A"]["ACC_IACCHWAMode"] == 7
    ret.stockFcw = cp_cam.vl["GW_244"]["ACC_FCWPreWarning"] == 1 # 前碰撞预警镜像
    ret.stockAeb = cp_cam.vl["GW_244"]["ACC_AEBCtrlType"] > 0    # 自动制动镜像

    # 7. 控制器所需信号镜像快照
    self.sigs244 = copy.copy(cp_cam.vl["GW_244"])
    self.sigs1ba = copy.copy(cp_cam.vl["GW_1BA"])
    self.sigs17e = copy.copy(cp.vl["GW_17E"])
    self.sigs307 = copy.copy(cp_cam.vl["GW_307"])
    self.sigs31a = copy.copy(cp_cam.vl["GW_31A"])

    # 计数器 labels 必须与 changan_can.dbc 定义完全一致
    self.counter_244 = cp_cam.vl["GW_244"]["ACC_RollingCounter_24E"]
    self.counter_1ba = cp_cam.vl["GW_1BA"]["Counter_1BA"]
    self.counter_17e = cp.vl["GW_17E"]["EPS_RollingCounter_17E"]
    self.counter_307 = cp_cam.vl["GW_307"]["Counter_35E"]
    self.counter_31a = cp_cam.vl["GW_31A"]["Counter_36D"]

    return ret

  @staticmethod
  def get_can_parsers(CP):
    pt_messages = [
      ("GW_180", 100), ("GW_17E", 50), ("buttonEvents", 10), ("GEAR", 10), ("GW_50", 1),
      ("GW_28B", 10), ("GW_170", 100), ("GW_24F", 20),
    ]
    if CP.carFingerprint == CAR.CHANGAN_Z6_IDD:
      pt_messages += [("SPEED", 50), ("GW_1A6", 50)]
    else:
      pt_messages += [("GW_187", 50), ("GW_196", 50)]

    cam_messages = [
      ("GW_1BA", 100), ("GW_244", 50), ("GW_307", 10), ("GW_31A", 10), ("buttonEvents", 10),
    ]

    return {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, 2),
    }
