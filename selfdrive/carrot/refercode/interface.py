from opendbc.car.changan.values import DBC, CarControllerParams, EPS_SCALE
from opendbc.car import structs, get_safety_config
from opendbc.car.disable_ecu import disable_ecu
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
    def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams: # type: ignore
        ret.brand = "changan"
        ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.changan)]

        # 调整转向参数以适应480度单边打满
        ret.steerActuatorDelay = 0.1  # 略微增加延迟以确保稳定性
        ret.steerLimitTimer = 0.8  # 增加转向限制时间，适应更大的转向角度范围
        
        # 使用角度控制以实现480度打满
        ret.steerControlType = SteerControlType.angle
        
        # 调整转向比例和限制以适应480度范围
        ret.steerRatio = 15.0  # 根据车型调整转向比
        ret.steerMax = 480  # 设置最大转向角度为480度
        
        # 设置转向角度速率限制，防止过载
        ret.steerRateCost = 0.5  # 降低转向速率成本
        ret.steerMaxBP = [0.]  # 转向角度限制断点
        ret.steerMaxV = [480]  # 最大转向角度值
        
        ret.centerToFront = ret.wheelbase * 0.44

        # 盲区检测
        ret.enableBsm = True

        # 雷达设置
        ret.radarUnavailable = True

        # 实验性纵向控制可用性
        ret.experimentalLongitudinalAvailable = True

        # 启用openpilot纵向控制
        ret.openpilotLongitudinalControl = True
        ret.autoResumeSng = ret.openpilotLongitudinalControl

        # 最小启用速度
        ret.minEnableSpeed = -1.

        # 调整纵向控制参数以适应新的转向特性
        tune = ret.longitudinalTuning

        # 更新加速度控制参数
        tune.kpBP = [0., 5., 20., 40.]
        tune.kpV = [1.2, 1.0, 0.7, 0.5]  # 降低增益以适应更大的转向角度
        tune.kiBP = [0., 5., 12., 20., 27.]
        tune.kiV = [0.3, 0.25, 0.2, 0.15, 0.1]  # 调整积分增益

        # 调整停车和起步参数
        ret.vEgoStopping = 0.25  # 略微提高停车速度阈值
        ret.vEgoStarting = 0.25  # 略微提高起步速度阈值
        ret.stoppingDecelRate = 0.3  # 调整停车减速率

        # 调整转向速度相关参数
        ret.minSteerSpeed = 0.1  # 略微提高最小转向速度
        ret.startingState = True
        ret.startAccel = 0.8  # 略微降低起步加速度
        ret.stopAccel = -0.35  # 调整停车减速度
        ret.longitudinalActuatorDelay = 0.35  # 降低纵向控制延迟

        # 添加转向角度过载保护
        ret.steerOverrideAlert = True
        ret.steerWarningLimit = 450  # 设置警告限制为450度，留有余量
        ret.steerErrorLimit = 470  # 设置错误限制为470度，接近480度极限

        return ret

    # 添加转向角度保护方法
    @staticmethod
    def apply_steer_angle_limits(current_angle, desired_angle, CS):
        """应用转向角度限制，防止超过480度"""
        max_angle = 480  # 单边最大480度
        min_angle = -480  # 单边最小-480度
        
        # 检查是否接近极限
        if abs(current_angle) > 450:
            # 接近极限时，限制转向变化率
            max_change = 5  # 度/周期
        else:
            max_change = 15  # 正常转向变化率
            
        # 限制期望角度的变化率
        angle_diff = desired_angle - current_angle
        if abs(angle_diff) > max_change:
            desired_angle = current_angle + max_change * (1 if angle_diff > 0 else -1)
        
        # 确保不超过角度限制
        desired_angle = max(min(desired_angle, max_angle), min_angle)
        
        return desired_angle

    # 重写转向控制方法以应用角度限制
    def update(self, c, can_strings):
        """重写update方法以应用转向角度限制"""
        # 调用父类方法
        ret = super().update(c, can_strings)
        
        # 应用转向角度限制
        if ret.steeringControlType == SteerControlType.angle:
            ret.steeringAngleDesired = self.apply_steer_angle_limits(
                self.CS.steeringAngle, ret.steeringAngleDesired, self.CS
            )
        
        return ret