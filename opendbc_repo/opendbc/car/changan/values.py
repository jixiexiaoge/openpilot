from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag

from opendbc.car import Bus, DbcDict, PlatformConfig, Platforms, CarSpecs, AngleSteeringLimits, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.docs_definitions import CarDocs, CarParts, CarHarness

Ecu = structs.CarParams.Ecu

# Minimum speed to enable ACC (stop-and-go capable, so set to -1 in interface.py)
MIN_ACC_SPEED = 19. * CV.MPH_TO_MS
PEDAL_TRANSITION = 10. * CV.MPH_TO_MS


class ChanganSafetyFlags(IntFlag):
  """Safety configuration flags passed to panda safety code."""
  IDD_VARIANT = 1  # Hybrid (iDD) variant uses different pedal/speed messages


class ChanganFlags(IntFlag):
  """Platform-specific feature flags."""
  CHANGAN_Z6 = 1
  CHANGAN_Z6_IDD = 2
  IDD = 2  # 这一行是关键修复
  QIYUAN_A05 = 4


class CarControllerParams:
  """Controller parameters and limits for Changan vehicles."""

  # Longitudinal limits
  ACCEL_MAX = 2.0  # m/s^2
  ACCEL_MIN = -3.5  # m/s^2

  # Longitudinal windup limits (inspired by Toyota)
  ACCEL_WINDUP_LIMIT = 0.4  # Maximum positive accel rate change
  ACCEL_WINDDOWN_LIMIT = -0.4  # Maximum negative accel rate change

  # Lateral (steering) limits
  STEER_STEP = 1  # control frames between commands
  STEER_MAX = 480  # max steering angle command in degrees
  STEER_ERROR_MAX = 650  # max error between commanded and actual
  MAX_STEERING_ANGLE = 480.0  # physical steering angle limit
  STEERING_SMOOTHING_FACTOR = 0.3  # smoothing factor for angle commands

  # Angle rate limits per vehicle speed
  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    480,  # max angle in degrees
    ([10, 50], [1.4, 1.4]),  # angle_rate_up (speed_bp, rate_bp)
    ([10, 50], [1.4, 1.4]),  # angle_rate_down (speed_bp, rate_bp)
  )

  def __init__(self, CP):
    """Initialize controller parameters based on car platform."""
    if CP.lateralTuning.which == "torque":
      self.STEER_DELTA_UP = 15  # torque ramp up rate
      self.STEER_DELTA_DOWN = 25  # torque ramp down rate
    else:
      self.STEER_DELTA_UP = 10  # angle control ramp up
      self.STEER_DELTA_DOWN = 25  # angle control ramp down


def dbc_dict(pt_dbc: str, cam_dbc: str) -> DbcDict:
  """Helper to create DBC dictionary for powertrain and camera buses.

  Args:
    pt_dbc: Name of the powertrain DBC file (without .dbc extension)
    cam_dbc: Name of the camera DBC file (without .dbc extension)

  Returns:
    DbcDict mapping bus numbers to DBC file names
  """
  return DbcDict({Bus.pt: pt_dbc, Bus.cam: cam_dbc})


@dataclass
class ChangAnCarDocs(CarDocs):
  """Documentation metadata for Changan vehicles."""
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))


class CAR(Platforms):
  """Supported Changan vehicle platforms."""
  CHANGAN_Z6 = PlatformConfig(
    [ChangAnCarDocs("Changan Z6")],
    CarSpecs(mass=2205, wheelbase=2.80, steerRatio=15.0, tireStiffnessFactor=0.444),
    DbcDict({Bus.pt: "changan_can", Bus.cam: "changan_can"}),
  )
  CHANGAN_Z6_IDD = PlatformConfig(
    [ChangAnCarDocs("Changan Z6 iDD")],
    CHANGAN_Z6.specs,
    CHANGAN_Z6.dbc_dict,
    flags=ChanganFlags.IDD,  # 现在这行应该不会报错
  )


# Steering torque threshold for driver override detection
STEER_THRESHOLD = 15

# EPS torque scale factors per platform (1 = 1%, 100 = 100%)
# Default is 73% for most Changan vehicles
EPS_SCALE = defaultdict(lambda: 73, {
  CAR.CHANGAN_Z6: 73,
  CAR.CHANGAN_Z6_IDD: 73,
})

# Auto-resume capable cars (support stop-and-go)
NO_STOP_TIMER_CAR = {CAR.CHANGAN_Z6, CAR.CHANGAN_Z6_IDD}

# Create DBC mapping for all platforms
DBC = CAR.create_dbc_map()


if __name__ == "__main__":
  cars = []
  for platform in CAR:
    for doc in platform.config.car_docs:
      cars.append(doc.name)
  cars.sort()
  for c in cars:
    print(c)