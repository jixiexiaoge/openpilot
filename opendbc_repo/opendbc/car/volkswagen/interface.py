import time

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car import get_safety_config, structs, uds
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.isotp_parallel_query import IsoTpParallelQuery
from opendbc.car.volkswagen.carcontroller import CarController
from opendbc.car.volkswagen.carstate import CarState
from opendbc.car.volkswagen.values import CanBus, CAR, DashcamOnlyReason, NetworkLocation, RADAR_DISABLE_STATE, TransmissionType, VolkswagenFlags, VolkswagenSafetyFlags, VolkswagenFlagsIQ
from opendbc.car.volkswagen.radar_interface import RadarInterface
from opendbc.car.common.conversions import Conversions as CV
import sys
import os
iqpilot_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.insert(0, iqpilot_path)
try:
  from openpilot.common.params import Params
except ImportError:
  pass


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  DRIVABLE_GEARS = (structs.CarState.GearShifter.eco, structs.CarState.GearShifter.sport,
                    structs.CarState.GearShifter.manumatic, structs.CarState.GearShifter.neutral)

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate: CAR, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "volkswagen"
    ret.radarUnavailable = True
    _params = Params()
    angle_lat_enabled = _params.get_bool("AngleLateralControl")
    joystick_mode = _params.get_bool("JoystickDebugMode")

    if ret.flags & VolkswagenFlags.PQ:
      # Set global PQ35/PQ46/NMS parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenPq)]
      if angle_lat_enabled:
        ret.flags |= VolkswagenFlagsIQ.IQ_LVBS_ALC_MODULE.value
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.PQ_ALC_MODULE.value
      ret.enableBsm = 0x3BA in fingerprint[0]  # SWA_1

      if 0x440 in fingerprint[0] or docs:  # Getriebe_1
        ret.transmissionType = TransmissionType.automatic
      else:
        ret.transmissionType = TransmissionType.manual

      # Auto-detect CC only mode by checking for ACC / AWV presence
      # ACC_System = 0x368, ACC_GRA_Anzeige = 0x56A, AWV = 0x366
      has_acc = 0x368 in fingerprint[0] or 0x56A in fingerprint[0]
      if not has_acc:
        has_radar = 0x366 in fingerprint[0]  # AWV for FCW/AEB
        if has_radar:
          ret.flags |= VolkswagenFlagsIQ.IQ_CC_ONLY.value
        else:
          ret.flags |= VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR.value

      if any(msg in fingerprint[1] for msg in (0x1A0, 0xC2)):  # Bremse_1, Lenkwinkel_1
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      ret.dashcamOnly = False

    elif ret.flags & VolkswagenFlags.MLB:
      # Set global MLB parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenMlb)]
      ret.enableBsm = 0x30F in fingerprint[0]  # SWA_01
      ret.networkLocation = NetworkLocation.gateway
      ret.dashcamOnly = False

    elif ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      if ret.flags & VolkswagenFlags.MEB:
        safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenMeb)]
      else:
        safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenMqbEvo)]

      if ret.flags & VolkswagenFlags.MEB_GEN2:
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.ALT_CRC_VARIANT_1.value
      if ret.flags & VolkswagenFlags.MQB_EVO:
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.NO_GAS_OFFSET.value

      ret.enableBsm = 0x24C in fingerprint[0]  # MEB_Side_Assist_01
      ret.transmissionType = TransmissionType.direct
      ret.steerControlType = structs.CarParams.SteerControlType.curvatureDEPRECATED
      ret.steerAtStandstill = True

      if any(msg in fingerprint[1] for msg in (0x520, 0x86, 0xFD, 0x13D)):  # Airbag_02, LWI_01, ESP_21, QFK_01
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      if ret.networkLocation == NetworkLocation.gateway:
        ret.radarUnavailable = False

      if ret.networkLocation == NetworkLocation.fwdCamera:
        ret.flags |= VolkswagenFlags.DISABLE_RADAR.value
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.DISABLE_RADAR.value

      if 0x30B in fingerprint[0]:  # Kombi_01
        ret.flags |= VolkswagenFlags.KOMBI_PRESENT.value
      if 0x25D in fingerprint[0]:  # KLR_01
        ret.flags |= VolkswagenFlags.STOCK_KLR_PRESENT.value
      if all(msg in fingerprint[1] for msg in (0x462, 0x463, 0x464)):  # PSD_04, PSD_05, PSD_06
        ret.flags |= VolkswagenFlags.STOCK_PSD_PRESENT.value
      if 0x464 in fingerprint[0]:  # PSD_06
        ret.flags |= VolkswagenFlags.STOCK_PSD_06_PRESENT.value
      if 0x6B2 in fingerprint[0]:  # Diagnose_01
        ret.flags |= VolkswagenFlags.STOCK_DIAGNOSE_01_PRESENT.value
      if 0x3DC in fingerprint[0]:  # Gateway_73
        ret.flags |= VolkswagenFlags.ALT_GEAR.value

    else:
      # Set global MQB parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagen)]
      ret.enableBsm = 0x30F in fingerprint[0]  # SWA_01

      if 0xAD in fingerprint[0] or docs:  # Getriebe_11
        ret.transmissionType = TransmissionType.automatic
      elif 0x187 in fingerprint[0]:  # Motor_EV_01
        ret.transmissionType = TransmissionType.direct
      else:
        ret.transmissionType = TransmissionType.manual

      if any(msg in fingerprint[1] for msg in (0x40, 0x86, 0xB2, 0xFD)):  # Airbag_01, LWI_01, ESP_19, ESP_21
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      if 0x126 in fingerprint[2]:  # HCA_01
        ret.flags |= VolkswagenFlags.STOCK_HCA_PRESENT.value
      if 0x6B8 in fingerprint[0]:  # Kombi_03
        ret.flags |= VolkswagenFlags.KOMBI_PRESENT.value

      # Auto-detect CC only mode by checking for ACC_06/ACC_07 presence
      # ACC_06 = 0x122, ACC_07 = 0x12E, ACC_10 = 0x117
      has_acc = 0x122 in fingerprint[0] or 0x12E in fingerprint[0]
      if not has_acc:
        has_radar = 0x117 in fingerprint[0]  # ACC_10 for FCW/AEB
        if has_radar:
          ret.flags |= VolkswagenFlagsIQ.IQ_CC_ONLY.value
        else:
          ret.flags |= VolkswagenFlagsIQ.IQ_CC_ONLY_NO_RADAR.value

    # Global lateral tuning defaults, can be overridden per-vehicle

    ret.steerLimitTimer = 0.4
    if ret.flags & VolkswagenFlags.PQ:
      ret.steerActuatorDelay = 0.2
      ret.longitudinalTuning.kfDEPRECATED = 1.2
      ret.longitudinalTuning.kpBP = [0.]
      ret.longitudinalTuning.kpV = [.45]
      ret.longitudinalTuning.kiBP = [0.]
      ret.longitudinalTuning.kiV = [.69]
      ret.longitudinalActuatorDelay = 0.6
      if angle_lat_enabled:
        ret.steerControlType = structs.CarParams.SteerControlType.angle
        ret.steerAtStandstill = bool(joystick_mode)
      else:
        CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    elif ret.flags & VolkswagenFlags.MLB:
      ret.steerActuatorDelay = 0.2
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    elif ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.steerActuatorDelay = 0.3
    else:
      ret.steerActuatorDelay = 0.1
      ret.lateralTuning.pid.kpBP = [0.]
      ret.lateralTuning.pid.kiBP = [0.]
      ret.lateralTuning.pid.kf = 0.00006
      ret.lateralTuning.pid.kpV = [0.6]
      ret.lateralTuning.pid.kiV = [0.2]
      if angle_lat_enabled:
        ret.steerControlType = structs.CarParams.SteerControlType.angle
        ret.steerAtStandstill = bool(joystick_mode)

    # Global longitudinal tuning defaults, can be overridden per-vehicle

    if ret.flags & VolkswagenFlags.MEB:
      ret.longitudinalActuatorDelay = 0.5
      ret.radarDelay = 0.8
      ret.longitudinalTuning.kiBP = [0., 30.]
      ret.longitudinalTuning.kiV = [0.4, 0.]

    ret.alphaLongitudinalAvailable = ret.networkLocation == NetworkLocation.gateway or docs or bool(ret.flags & VolkswagenFlags.DISABLE_RADAR)
    if alpha_long:
      # Proof-of-concept, prep for E2E only. No radar points available. Panda ALLOW_DEBUG firmware required.
      ret.openpilotLongitudinalControl = True
      safety_configs[0].safetyParam |= VolkswagenSafetyFlags.LONG_CONTROL.value
      safety_configs[0].safetyParam |= VolkswagenSafetyFlags.ALLOW_LONG_ACCEL_WITH_GAS_PRESSED.value
      if ret.transmissionType == TransmissionType.manual:
        ret.minEnableSpeed = 4.5

    # Per-vehicle overrides

    if candidate == CAR.PORSCHE_MACAN_MK1:
      ret.steerActuatorDelay = 0.07

    ret.pcmCruise = not ret.openpilotLongitudinalControl
    if ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.startingState = True
      ret.startAccel = 0.8
      ret.vEgoStarting = 0.5
      ret.vEgoStopping = 0.1
      ret.stopAccel = -0.55
    else:
      ret.stopAccel = -0.55
      ret.vEgoStarting = 0.1
      ret.vEgoStopping = 1.5 * CV.KPH_TO_MS if ret.flags & VolkswagenFlags.PQ else 0.1
    ret.autoResumeSng = ret.minEnableSpeed == -1
    CAN = CanBus(fingerprint=fingerprint)
    if CAN.pt >= 4:
      safety_configs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
    ret.safetyConfigs = safety_configs

    return ret

  @staticmethod
  def pre_init(CP: structs.CarParams, CP_IQ: structs.IQCarParams, can_recv, can_send):
    # Engine-on check moved to init(): if radar can't be disabled, radarDisableFailed=True
    # gates only long control (carcontroller line ~308) while lateral still works.
    # Full dashcam mode here was too aggressive — lateral doesn't need radar disabled.
    pass

  @staticmethod
  def init(CP: structs.CarParams, CP_IQ: structs.IQCarParams, can_recv, can_send):
    # Disable radar via UDS programming session so openpilot can take over longitudinal.
    # The radar stops transmitting AWV_03/Strukturen_01 and carcontroller replaces those messages.
    if CP.openpilotLongitudinalControl and (CP.flags & VolkswagenFlags.DISABLE_RADAR):
      RADAR_DISABLE_STATE["error"] = False
      if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        if CarInterface._is_engine_state_allowed_meb(can_recv):
          carlog.warning("VW MEB/MQBevo: disabling radar for longitudinal control")
          if not CarInterface._radar_communication_control(CP, can_recv, can_send):
            RADAR_DISABLE_STATE["error"] = True
        else:
          RADAR_DISABLE_STATE["error"] = True
          carlog.warning("VW MEB/MQBevo: radar cannot be disabled — engine is on")

  @staticmethod
  def deinit(CP: structs.CarParams, can_recv, can_send):
    # Re-enable radar TX on exit (currently never called by openpilot, car recovers after ignition cycle)
    if CP.openpilotLongitudinalControl and (CP.flags & VolkswagenFlags.DISABLE_RADAR):
      if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
        CarInterface._radar_communication_control(CP, can_recv, can_send, disable=False)

  @staticmethod
  def _radar_communication_control(CP, can_recv, can_send, disable=True) -> bool:
    # Send UDS commands to put the radar (addr 0x757) into programming session,
    # which silences its CAN TX so openpilot can send replacement messages.
    bus = CanBus(CP).pt
    addr_radar = 0x757
    addr_diag = 0x700       # Functional address for TesterPresent broadcast
    vw_rx_offset = 0x6A

    tp_req       = bytes([uds.SERVICE_TYPE.TESTER_PRESENT, 0x00])
    tp_resp      = bytes([uds.SERVICE_TYPE.TESTER_PRESENT + 0x40, 0x00])
    ext_diag_req  = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL, uds.SESSION_TYPE.EXTENDED_DIAGNOSTIC])
    ext_diag_resp = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL + 0x40, uds.SESSION_TYPE.EXTENDED_DIAGNOSTIC])
    flash_req    = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL, uds.SESSION_TYPE.PROGRAMMING])
    empty_resp   = b''

    txt = "disable" if disable else "enable"

    for attempt in range(3):
      try:
        if disable:
          # Step 1: TesterPresent — wake up the radar
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)],
                                     [tp_req], [tp_resp], vw_rx_offset, functional_addrs=[addr_diag])
          if not query.get_data(0.5):
            carlog.warning(f"VW radar {txt}: TesterPresent no response on attempt {attempt + 1}")
            continue

          # Step 2: Extended diagnostic session
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)],
                                     [ext_diag_req], [ext_diag_resp], vw_rx_offset)
          if not query.get_data(0.5):
            carlog.warning(f"VW radar {txt}: ExtendedDiagSession no response on attempt {attempt + 1}")
            continue

          # Step 3: Programming session — radar stops transmitting
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)],
                                     [flash_req], [empty_resp], vw_rx_offset)
          query.get_data(0)   # fire-and-forget, no wait needed
          carlog.warning(f"VW radar {txt}: programming session sent on attempt {attempt + 1}")

        return True

      except Exception as e:
        carlog.error(f"VW radar {txt}: exception on attempt {attempt + 1}: {repr(e)}")
        continue

    carlog.error(f"VW radar {txt}: all attempts failed")
    return False

  @staticmethod
  def _is_engine_state_allowed_meb(can_recv, timeout: float = 0.5) -> bool:
    # Read Motor_54 (0x14C) to check Engine_On bit before attempting radar disable.
    # Programming session is rejected by radar when engine is running.
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
      packets = can_recv(wait_for_one=True) or []
      for packet in packets:
        for msg in packet:
          if msg.address != 0x14C:
            continue
          engine_on = bool((msg.dat[9] >> 5) & 0x01)
          if engine_on:
            carlog.warning(f"VW radar disable: engine is on, skipping")
            return False
          else:
            carlog.warning(f"VW radar disable: engine is off, proceeding")
            return True
    carlog.warning("VW radar disable: Motor_54 not seen within timeout, assuming allowed")
    return True

  @staticmethod
  def _get_params_iq(stock_cp: structs.CarParams, ret: structs.IQCarParams, candidate, fingerprint: dict[int, dict[int, int]], car_fw: list[structs.CarParams.CarFw], alpha_long: bool, is_release_iq: bool, docs: bool) -> structs.IQCarParams:
    return ret
