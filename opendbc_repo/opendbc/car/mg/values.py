from dataclasses import dataclass, field
from enum import IntFlag

from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms, structs
from opendbc.car.docs_definitions import CarHarness, CarDocs, CarParts
# FW query disabled for MG for now (see below) - restore when we can query FW on the MG ZS
# from opendbc.car import uds
# from opendbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries, p16


@dataclass
class MgCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.mg_a]))


@dataclass
class MgPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'mg', Bus.radar: 'mg'})


class CAR(Platforms):
  MG_ZS = MgPlatformConfig(
    [
      MgCarDocs("MG ZS 2025"),
    ],
    CarSpecs(mass=1295., wheelbase=2.58, steerRatio=15.8),
  )


# FW query is disabled for MG for now: the MG ZS has no captured FW versions yet
# and no CAN fingerprint, so it is identified by forced car selection only.
# Defining FW_QUERY_CONFIG would put MG in the FW-query path with zero ECUs, which
# crashes fingerprinting and fails the fingerprint tests. Restore this (and
# FW_VERSIONS in fingerprints.py) once we figure out how to query FW on the MG ZS.
#
# MG_VERSION_REQUEST = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER]) + \
#   p16(0xf1a0)
# MG_VERSION_RESPONSE = bytes([uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER + 0x40])
#
# FW_QUERY_CONFIG = FwQueryConfig(
#   requests=[
#     Request(
#       [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.MANUFACTURER_ECU_HARDWARE_NUMBER_REQUEST],
#       [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.MANUFACTURER_ECU_HARDWARE_NUMBER_RESPONSE],
#       bus=1,
#     ),
#   ],
# )

GEAR_MAP = {
  0: structs.CarState.GearShifter.unknown,
  1: structs.CarState.GearShifter.park,
  2: structs.CarState.GearShifter.reverse,
  3: structs.CarState.GearShifter.neutral,
  4: structs.CarState.GearShifter.drive,
}


class CarControllerParams:
  STEER_STEP = 2  # FVCM_HSC2_FrP03 message frequency 50Hz
  STEER_MAX = 300
  STEER_DELTA_UP = 10      # torque increase per refresh
  STEER_DELTA_DOWN = 15    # torque decrease per refresh
  STEER_DRIVER_ALLOWANCE = 100  # allowed driver torque before start limiting
  STEER_DRIVER_MULTIPLIER = 2  # weight driver torque
  STEER_DRIVER_FACTOR = 100

  ACCEL_MIN = -3.5  # m/s^2
  ACCEL_MAX = 2.0  # m/s^2

  def __init__(self, CP):
    pass


class MgSafetyFlags(IntFlag):
  LONG_CONTROL = 1
  ALT_BRAKE = 2
  NON_EV = 4


DBC = CAR.create_dbc_map()
