from opendbc.car import get_safety_config, structs
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.volkswagen.carcontroller import CarController
from opendbc.car.volkswagen.carstate import CarState
from opendbc.car.volkswagen.values import CAR, NetworkLocation, TransmissionType, VolkswagenFlags, VolkswagenSafetyFlags


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate: CAR, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "volkswagen"
    ret.radarUnavailable = True

    if ret.flags & VolkswagenFlags.PQ:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenPq)]
      ret.enableBsm = 0x3BA in fingerprint[0]
      if 0x440 in fingerprint[0] or docs:
        ret.transmissionType = TransmissionType.automatic
      else:
        ret.transmissionType = TransmissionType.manual
      if any(msg in fingerprint[1] for msg in (0x1A0, 0xC2)):
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera
      ret.dashcamOnly = True

    elif ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenMeb)]
      ret.enableBsm = 0x30F in fingerprint[0]

      if 0x187 in fingerprint[0]:
        ret.transmissionType = TransmissionType.direct
      else:
        ret.transmissionType = TransmissionType.automatic

      if any(msg in fingerprint[1] for msg in (0x40, 0x86, 0xB2, 0xFD)):
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      # MEB/MQBevo feature detection
      if 0x25D in fingerprint[0]:
        ret.flags |= VolkswagenFlags.STOCK_KLR_PRESENT.value
      if 0x30B in fingerprint[0]:
        ret.flags |= VolkswagenFlags.STOCK_PSD_PRESENT.value
      if 0x2C0 in fingerprint[0]:
        ret.flags |= VolkswagenFlags.STOCK_DIAGNOSE_01_PRESENT.value

      ret.radarUnavailable = False

    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.volkswagen)]
      ret.enableBsm = 0x30F in fingerprint[0]

      if 0xAD in fingerprint[0] or docs:
        ret.transmissionType = TransmissionType.automatic
      elif 0x187 in fingerprint[0]:
        ret.transmissionType = TransmissionType.direct
      else:
        ret.transmissionType = TransmissionType.manual

      if any(msg in fingerprint[1] for msg in (0x40, 0x86, 0xB2, 0xFD)):
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      if 0x126 in fingerprint[2]:
        ret.flags |= VolkswagenFlags.STOCK_HCA_PRESENT.value

    # Lateral tuning
    ret.steerLimitTimer = 0.4
    if ret.flags & VolkswagenFlags.PQ:
      ret.steerActuatorDelay = 0.2
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    elif ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.steerActuatorDelay = 0.1
      ret.steerControlType = structs.CarParams.SteerControlType.curvature
    else:
      ret.steerActuatorDelay = 0.1
      ret.lateralTuning.pid.kpBP = [0.]
      ret.lateralTuning.pid.kiBP = [0.]
      ret.lateralTuning.pid.kf = 0.00006
      ret.lateralTuning.pid.kpV = [0.6]
      ret.lateralTuning.pid.kiV = [0.2]

    # Longitudinal tuning
    ret.alphaLongitudinalAvailable = ret.networkLocation == NetworkLocation.gateway or docs
    if alpha_long:
      ret.openpilotLongitudinalControl = True
      ret.safetyConfigs[0].safetyParam |= VolkswagenSafetyFlags.LONG_CONTROL.value
      if ret.flags & VolkswagenFlags.MEB_GEN2:
        ret.safetyConfigs[0].safetyParam |= VolkswagenSafetyFlags.ALT_CRC_VARIANT_1.value
      if ret.transmissionType == TransmissionType.manual:
        ret.minEnableSpeed = 4.5

    ret.pcmCruise = not ret.openpilotLongitudinalControl
    ret.stopAccel = -0.55
    ret.vEgoStarting = 0.1
    ret.vEgoStopping = 0.5
    ret.autoResumeSng = ret.minEnableSpeed == -1

    return ret
