from iqdbc.car import Bus, get_safety_config, structs
from iqdbc.car.interfaces import CarInterfaceBase
from iqdbc.car.tesla.carcontroller import CarController
from iqdbc.car.tesla.carstate import CarState
from iqdbc.car.tesla.values import TeslaSafetyFlags, TeslaFlags, CANBUS, CAR, DBC, LEGACY_DAS_STEERING_FW, Ecu
from iqdbc.car.tesla.radar_interface import RadarInterface, RADAR_START_ADDR

from iqdbc.iqpilot.car.tesla.values import TeslaFlagsIQ, TeslaSafetyFlagsIQ


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "tesla"

    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla)]

    ret.steerLimitTimer = 0.4
    ret.steerActuatorDelay = 0.1
    ret.steerAtStandstill = True

    ret.steerControlType = structs.CarParams.SteerControlType.angle

    # Model X and HW 2.5 vehicles are missing DAS_settings
    if 0x293 not in fingerprint[CANBUS.autopilot_party]:
      ret.flags |= TeslaFlags.MISSING_DAS_SETTINGS.value

    # Radar support is intended to work for:
    # - Tesla Model 3 vehicles built approximately mid-2017 through early-2021
    # - Tesla Model Y vehicles built approximately mid-2020 through early-2021
    # - Vehicles equipped with the Continental ARS4-B radar (used on HW2 / HW2.5 / early HW3)
    # - Radar CAN lines must be tapped and connected to CAN bus 1 (normally not used for tesla vehicles)
    ret.radarUnavailable = RADAR_START_ADDR not in fingerprint[1] or Bus.radar not in DBC[candidate]

    ret.alphaLongitudinalAvailable = True
    if alpha_long:
      ret.openpilotLongitudinalControl = True
      ret.safetyConfigs[0].safetyParam |= TeslaSafetyFlags.LONG_CONTROL.value

    legacy_das = any(fw.ecu == Ecu.eps and fw.fwVersion in LEGACY_DAS_STEERING_FW.get(candidate, []) for fw in car_fw)
    if legacy_das:
      ret.flags |= TeslaFlags.LEGACY_DAS_STEERING.value
      ret.safetyConfigs[0].safetyParam |= TeslaSafetyFlags.LEGACY_DAS_STEERING.value

    ret.dashcamOnly = candidate in (CAR.TESLA_MODEL_X,)  # dashcam only, pending find invalidLkasSetting signal

    return ret

  @staticmethod
  def _get_params_iq(stock_cp: structs.CarParams, ret: structs.IQCarParams, candidate, fingerprint: dict[int, dict[int, int]],
                     car_fw: list[structs.CarParams.CarFw], alpha_long: bool, is_release_iq: bool, docs: bool) -> structs.IQCarParams:

    stock_cp.enableBsm = True

    if candidate == CAR.TESLA_MODEL_X:
      stock_cp.dashcamOnly = False

    # Vehicle-bus messages can be slow enough to miss the initial capture window.
    # Accept either the established 0x3DF marker or the absolute odometer frame.
    vehicle_bus_seen = any(0x3DF in bus or 0x3B6 in bus for bus in fingerprint.values())
    if vehicle_bus_seen:
      ret.flags |= TeslaFlagsIQ.HAS_VEHICLE_BUS.value
      ret.iqSafetyFlags |= TeslaSafetyFlagsIQ.HAS_VEHICLE_BUS

    return ret
