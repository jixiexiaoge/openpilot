from opendbc.car.changan.values import DBC, CarControllerParams, EPS_SCALE
from opendbc.car import structs, get_safety_config
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.changan.carcontroller import CarController
from opendbc.car.changan.carstate import CarState
from opendbc.car.changan.radar_interface import RadarInterface

SteerControlType = structs.CarParams.SteerControlType


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    # 动态调整加速和减速限制，根据车速提供更合适的控制
    if current_speed < 10 * CV.KPH_TO_MS:  # 低速区域
      return CarControllerParams.ACCEL_MIN, min(CarControllerParams.ACCEL_MAX * 1.2, 2.5)  # 低速提供更强加速能力
    elif current_speed > 80 * CV.KPH_TO_MS:  # 高速区域
      return max(CarControllerParams.ACCEL_MIN * 0.8, -4.5), CarControllerParams.ACCEL_MAX * 0.8  # 高速降低加减速强度
    else:  # 中速区域
      return CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams: # type: ignore
    ret.brand = "changan"
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.changan)]

    # 调整转向延迟和限制参数以提高转向响应性
    ret.steerActuatorDelay = 0.08  # 降低转向延迟以提高响应速度
    ret.steerLimitTimer = 0.5  # 增加转向限制时间，使转向持续时间更长

    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.centerToFront = ret.wheelbase * 0.44 # 其他车没有 不清楚

    # TODO: Some TSS-P platforms have BSM, but are flipped based on region or driving direction.
    # Detect flipped signals and enable for C-HR and others
    ret.enableBsm = True # 盲区检测

    # No radar dbc for cars without DSU which are not TSS 2.0
    # TODO: make an adas dbc file for dsu-less models
    ret.radarUnavailable = True

    # if the smartDSU is detected, openpilot can send ACC_CONTROL and the smartDSU will block it from the DSU or radar.
    # since we don't yet parse radar on TSS2/TSS-P radar-based ACC cars, gate longitudinal behind experimental toggle
    ret.experimentalLongitudinalAvailable = True # ? 不清楚

    # openpilot longitudinal enabled by default:
    #  - non-(TSS2 radar ACC cars) w/ smartDSU installed
    #  - cars w/ DSU disconnected
    #  - TSS2 cars with camera sending ACC_CONTROL where we can block it
    # openpilot longitudinal behind experimental long toggle:
    #  - TSS2 radar ACC cars w/ smartDSU installed
    #  - TSS2 radar ACC cars w/o smartDSU installed (disables radar)
    #  - TSS-P DSU-less cars w/ CAN filter installed (no radar parser yet)
    ret.openpilotLongitudinalControl = True
    ret.autoResumeSng = ret.openpilotLongitudinalControl

    # if not ret.openpilotLongitudinalControl:
    #   ret.safetyConfigs[0].safetyParam |= Panda.FLAG_TOYOTA_STOCK_LONGITUDINAL

    # if ret.enableGasInterceptor:
    #   ret.safetyConfigs[0].safetyParam |= Panda.FLAG_TOYOTA_GAS_INTERCEPTOR

    # min speed to enable ACC. if car can do stop and go, then set enabling speed
    # to a negative value, so it won't matter.
    ret.minEnableSpeed = -1.

    # 调整纵向控制参数以提高加减速舒适性和响应性
    tune = ret.longitudinalTuning

    # 更新加速度控制参数
    tune.kpBP = [0., 5., 20., 40.]
    tune.kpV = [0.8, 0.6, 0.4, 0.3]  # 提高低速响应性，降低高速敏感度
    tune.kiBP = [0., 5., 12., 20., 27.]
    tune.kiV = [0.2, 0.15, 0.12, 0.08, 0.05]  # 增加积分增益以减少稳态误差
    # 添加微分控制以减少超调
    tune.kdBP = [0., 10., 20., 30.]
    tune.kdV = [0.0, 0.1, 0.2, 0.3]  # 添加微分控制

    # 调整停车和起步参数
    ret.vEgoStopping = 0.3  # 降低停车速度阈值
    ret.vEgoStarting = 0.3  # 降低起步速度阈值
    ret.stoppingDecelRate = 0.15  # 降低停车减速率，使停车更平稳

    ret.minSteerSpeed = 0
    ret.startingState = True
    ret.startAccel = 0.5  # 提高起步加速度
    ret.stopAccel = -0.3  # 降低停车减速度以使停车更平稳
    ret.longitudinalActuatorDelay = 0.6  # 降低纵向控制延迟
    # 添加加速度变化率限制
    ret.accelRate = 0.5  # 降低加速度变化率
    ret.decelRate = 0.5  # 降低减速度变化率

    return ret

