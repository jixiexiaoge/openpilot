import time

from opendbc.car import get_safety_config, structs, uds, DT_CTRL
from opendbc.car.disable_ecu import disable_ecu
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.volkswagen.carcontroller import CarController
from opendbc.car.volkswagen.carstate import CarState
from opendbc.car.volkswagen.values import CanBus, CAR, NetworkLocation, TransmissionType, VolkswagenFlags, VolkswagenSafetyFlags, RADAR_DISABLE_STATE
from opendbc.car.volkswagen.radar_interface import RadarInterface
from opendbc.car.carlog import carlog
from opendbc.car.isotp_parallel_query import IsoTpParallelQuery

class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  DRIVABLE_GEARS = (structs.CarState.GearShifter.eco, structs.CarState.GearShifter.sport,
                    structs.CarState.GearShifter.manumatic)

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate: CAR, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    CAN = CanBus(fingerprint=fingerprint)
    ret.brand = "volkswagen"
    ret.radarUnavailable = True

    if ret.flags & VolkswagenFlags.PQ:
      # Set global PQ35/PQ46/NMS parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagenPq)]
      ret.enableBsm = 0x3BA in fingerprint[0]  # SWA_1

      if 0x440 in fingerprint[0] or docs:  # Getriebe_1
        ret.transmissionType = TransmissionType.automatic
      else:
        ret.transmissionType = TransmissionType.manual

      if any(msg in fingerprint[1] for msg in (0x1A0, 0xC2)):  # Bremse_1, Lenkwinkel_1
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera
        
      ret.dashcamOnly = is_release  # Release support needs HCA timeout fix, safety validation

    elif ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      # Set global MEB parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagen)]

      if ret.flags & (VolkswagenFlags.MEB_GEN2 | VolkswagenFlags.MQB_EVO_GEN2):
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.ALT_CRC_VARIANT_1.value
      
      ret.enableBsm = 0x24C in fingerprint[0]  # MEB_Side_Assist_01
      ret.transmissionType = TransmissionType.direct
      #ret.steerControlType = structs.CarParams.SteerControlType.angle
      ret.steerControlType = structs.CarParams.SteerControlType.curvatureDEPRECATED
      ret.steerAtStandstill = True

      if any(msg in fingerprint[1] for msg in (0x520, 0x86, 0xFD, 0x13D)):  # Airbag_02, LWI_01, ESP_21, QFK_01
        ret.networkLocation = NetworkLocation.gateway
      else:
        ret.networkLocation = NetworkLocation.fwdCamera

      if ret.networkLocation == NetworkLocation.gateway:
        if not (ret.flags & VolkswagenFlags.MQB_EVO_GEN2):
          ret.radarUnavailable = False
        
      if 0x30B in fingerprint[0]:  # Kombi_01
        ret.flags |= VolkswagenFlags.KOMBI_PRESENT.value

      if 0x25D in fingerprint[0]:  # KLR_01
        ret.flags |= VolkswagenFlags.STOCK_KLR_PRESENT.value

      if all(msg in fingerprint[1] for msg in (0x462, 0x463, 0x464)):  # PSD_04, PSD_05, PSD_06
        ret.flags |= VolkswagenFlags.STOCK_PSD_PRESENT.value

      if 0x464 in fingerprint[0]:  # PSD_06 on bus 0, used additionally for mph detection as long as no native stable speed limit unit flag is found
        ret.flags |= VolkswagenFlags.STOCK_PSD_06_PRESENT.value

      if 0x6B2 in fingerprint[0]: # Diagnose_01 for local time from car
        ret.flags |= VolkswagenFlags.STOCK_DIAGNOSE_01_PRESENT.value

      if 0x3DC in fingerprint[0]:  # Gatway_73
        ret.flags |= VolkswagenFlags.ALT_GEAR.value

      if ret.networkLocation == NetworkLocation.fwdCamera:
        ret.flags |= VolkswagenFlags.DISABLE_RADAR.value
        safety_configs[0].safetyParam |= VolkswagenSafetyFlags.DISABLE_RADAR.value

    elif ret.flags & VolkswagenFlags.MLB:
      # Set global MLB parameters
      safety_configs = [get_safety_config(structs.CarParams.SafetyModel.volkswagen)]
      ret.enableBsm = 0x30F in fingerprint[0]  # SWA_01
      ret.networkLocation = NetworkLocation.gateway
      ret.dashcamOnly = is_release  # Release support needs HCA timeout fix, safety validation, revised J533 harness

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

    # Global lateral tuning defaults, can be overridden per-vehicle
    ret.steerLimitTimer = 0.4

    if ret.flags & VolkswagenFlags.PQ:
      ret.steerActuatorDelay = 0.3
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

    # Global longitudinal tuning defaults, can be overridden per-vehicle

    if ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.longitudinalActuatorDelay = 0.5
      ret.radarDelay = 0.8
      #ret.longitudinalTuning.kpBP = [0., 5.]
      ret.longitudinalTuning.kiBP = [0., 30.]
      #ret.longitudinalTuning.kpV = [0.2, 0.] # (with usage of starting state otherwise starting jerk)
      ret.longitudinalTuning.kiV = [0.4, 0.]

    ret.alphaLongitudinalAvailable = ret.networkLocation == NetworkLocation.gateway or docs or bool(ret.flags & VolkswagenFlags.DISABLE_RADAR)
    if alpha_long and ret.alphaLongitudinalAvailable:
      # Proof-of-concept, prep for E2E only. No radar points available. Panda ALLOW_DEBUG firmware required.
      ret.openpilotLongitudinalControl = True
      safety_configs[0].safetyParam |= VolkswagenSafetyFlags.LONG_CONTROL.value
      if ret.transmissionType == TransmissionType.manual:
        ret.minEnableSpeed = 4.5

    # Per-vehicle overrides

    if candidate == CAR.PORSCHE_MACAN_MK1:
      ret.steerActuatorDelay = 0.07

    ret.pcmCruise = not ret.openpilotLongitudinalControl
    ret.autoResumeSng = ret.minEnableSpeed == -1

    if ret.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO):
      ret.startingState = True # OP long starting state is used: for very slow start the car can go into error (EPB car shutting down bug)
      ret.startAccel = 0.8
      ret.vEgoStarting = 0.5 # minimum ~0.5 m/s acc starting state is neccessary to not fault the car
      ret.vEgoStopping = 0.1
      ret.stopAccel = -0.55 # different stopping accels seen, good working value
    else:
      ret.vEgoStarting = 0.1
      ret.vEgoStopping = 0.5
      ret.stopAccel = -0.55

    if CAN.pt >= 4:
      safety_configs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
    ret.safetyConfigs = safety_configs

    return ret

  @staticmethod
  def _get_params_sp(stock_cp: structs.CarParams, ret: structs.CarParamsSP, candidate, fingerprint: dict[int, dict[int, int]],
                     car_fw: list[structs.CarParams.CarFw], alpha_long: bool, is_release_sp: bool, docs: bool) -> structs.CarParamsSP:

    ret.intelligentCruiseButtonManagementAvailable = stock_cp.pcmCruise
                       
    return ret

  @staticmethod
  def pre_init(CP, CP_SP, can_recv, can_send):
    # fork custom method in CarD called at a point, where car params can still be changed
    # check pre conditions for successful radar disable
    # put the device into dashcam mode if neccessary: no relay switching, no bus blocking with relay malfunction
    if CP.openpilotLongitudinalControl and (CP.flags & VolkswagenFlags.DISABLE_RADAR):
      if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO | VolkswagenFlags.MQB_EVO_GEN2):
        if not CarInterface._is_engine_state_allowed_meb(can_recv):
          CP.dashcamOnly = True
          CP.dashcamOnlyReason = DashcamOnlyReason.radarDisableEngineOn

  @staticmethod
  def init(CP, CP_SP, can_recv, can_send, communication_control=None):
    # communication control can be rejected with engine on
    # uds.CONTROL_TYPE.ENABLE_RX_DISABLE_TX is lost with engine on transition for newer MEB and MQBevo cars
    # uds.CONTROL_TYPE.DISABLE_RX_DISABLE_TX is probably not lost but the radar has to be revived manually
    # -> deinit is not called in OP -> errors in dash, recovers after second ignition cycle
    # Programming session is also rejected while engine on but recovers after key off on
    if CP.openpilotLongitudinalControl and (CP.flags & VolkswagenFlags.DISABLE_RADAR):
      RADAR_DISABLE_STATE["error"] = False
      if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO | VolkswagenFlags.MQB_EVO_GEN2):
        if CarInterface._is_engine_state_allowed_meb(can_recv): # prevent programming session request, it will not work
          carlog.warning("Trying to disable the radar")
          if not CarInterface._radar_communication_control(CP, can_recv, can_send):
            RADAR_DISABLE_STATE["error"] = True
        else:
          RADAR_DISABLE_STATE["error"] = True
          carlog.warning("The radar can not be disabled")

  @staticmethod
  def deinit(CP, can_recv, can_send):
    # deinit is currently never executed in current state of Openpilot
    # CarD is just killed, no reaction handling on SIGINT
    if CP.openpilotLongitudinalControl and (CP.flags & VolkswagenFlags.DISABLE_RADAR):
      if CP.flags & (VolkswagenFlags.MEB | VolkswagenFlags.MQB_EVO | VolkswagenFlags.MQB_EVO_GEN2):
        CarInterface._radar_communication_control(CP, can_recv, can_send, disable=False)

  @staticmethod
  def _radar_communication_control(CP, can_recv, can_send, disable=True):
    # disable/enable radar tx
    bus = CanBus(CP).pt
    addr_radar, addr_diag, volkswagen_rx_offset = 0x757, 0x700, 0x6A
    retry, timeout = 3, 0.5

    tp_req  = bytes([uds.SERVICE_TYPE.TESTER_PRESENT, 0x00])
    tp_resp = bytes([uds.SERVICE_TYPE.TESTER_PRESENT + 0x40, 0x00])
    ext_diag_req  = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL, uds.SESSION_TYPE.EXTENDED_DIAGNOSTIC])
    ext_diag_resp = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL + 0x40, uds.SESSION_TYPE.EXTENDED_DIAGNOSTIC])
    flash_req  = bytes([uds.SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL, uds.SESSION_TYPE.PROGRAMMING])
    empty_resp = b''

    txt = "disable" if disable else "enable"
	  
    for i in range(retry):
      try:
		# Tester Present
        if disable:
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)], [tp_req], [tp_resp], volkswagen_rx_offset, functional_addrs=[addr_diag])
          if not query.get_data(timeout):
            carlog.warning(f"Tester Present returned no data on attempt {i+1}")
            continue
		  
          # Extended Diagnostic Session
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)], [ext_diag_req], [ext_diag_resp], volkswagen_rx_offset)
          if not query.get_data(timeout):
            carlog.warning(f"Radar extended session returned no data on attempt {i+1}")
            continue

          # Programming Session
          query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr_radar, None)], [flash_req], [empty_resp], volkswagen_rx_offset)
          query.get_data(0) # no waiting time for this to begin sending our own commands as fast as possible to prevent cruise faults
          carlog.warning(f"Radar {txt} by programming session sent on attempt {i+1}")

        return True
            
      except Exception as e:
        carlog.error(f"Radar {txt} exception on attempt {i+1}: {repr(e)}")
        continue

    carlog.error(f"Radar {txt} failed")
    return False

  @staticmethod
  def _is_engine_state_allowed_meb(can_recv, timeout: float = 0.5) -> bool:
    # this is a safety measure
    # detect if the radar can be disabled by engine state
    # [Motor_54][Engine_On]
    end_time = time.monotonic() + timeout
  
    while time.monotonic() < end_time:
      packets = can_recv(wait_for_one=True) or []
      for packet in packets:
        for msg in packet:
          if msg.address != 0x14C:
            continue
  
          dat = msg.dat
          engine_on = bool((msg.dat[9] >> 5) & 0x01)

          if engine_on:
            carlog.warning(f"Engine state is not allowed: Engine_On={engine_on}")
            return False
          else:
            carlog.warning(f"Engine state is allowed: Engine_On={engine_on}")
            return True
  
    carlog.warning("Engine state state unknown")
    return True
