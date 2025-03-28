from cereal import car
from opendbc.can.parser import CANParser
from enum import StrEnum
from opendbc.car import CarSpecs, PlatformConfig, Platforms
from opendbc.car.docs_definitions import CarDocs
from opendbc.car.common.conversions import Conversions as CV

class BYDPlatformConfig(PlatformConfig):
  def init(self):
    pass

class CAR(Platforms):
  # BYD 比亚迪车型
  BYD_SEAL = BYDPlatformConfig(
    [CarDocs("BYD SEAL 2023-24", "All")],
    CarSpecs(mass=2200, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_seal_2023_pt'},
  )

  # 增加根据 fingerprints.py 中的车型
  BYD_HAN_DM_20 = BYDPlatformConfig(
    [CarDocs("BYD HAN DM 2020", "All")],
    CarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_han_dm_2020_pt'},
  )

  BYD_HAN_EV_20 = BYDPlatformConfig(
    [CarDocs("BYD HAN EV 2020", "All")],
    CarSpecs(mass=2050, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_han_ev_2020_pt'},
  )

  BYD_TANG_DM = BYDPlatformConfig(
    [CarDocs("BYD TANG DM", "All")],
    CarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_tang_dm_pt'},
  )

  BYD_TANG_DMI_21 = BYDPlatformConfig(
    [CarDocs("BYD TANG DMI 2021", "All")],
    CarSpecs(mass=2300, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_tang_dmi_2021_pt'},
  )

  BYD_SONG_PLUS_DMI_21 = BYDPlatformConfig(
    [CarDocs("BYD SONG PLUS DMI 2021", "All")],
    CarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_song_plus_dmi_2021_pt'},
  )

  BYD_SONG_PLUS_DMI_22 = BYDPlatformConfig(
    [CarDocs("BYD SONG PLUS DMI 2022", "All")],
    CarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_song_plus_dmi_2022_pt'},
  )

  BYD_SONG_PLUS_5G_DMI_22 = BYDPlatformConfig(
    [CarDocs("BYD SONG PLUS 5G DMI 2022", "All")],
    CarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_song_plus_5g_dmi_2022_pt'},
  )

  BYD_SONG_PLUS_DMI_23 = BYDPlatformConfig(
    [CarDocs("BYD SONG PLUS DMI 2023", "All")],
    CarSpecs(mass=1800, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_song_plus_dmi_2023_pt'},
  )

  BYD_SONG_PRO_DMI_22 = BYDPlatformConfig(
    [CarDocs("BYD SONG PRO DMI 2022", "All")],
    CarSpecs(mass=1700, wheelbase=2.70, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_song_pro_dmi_2022_pt'},
  )

  BYD_QIN_PLUS_DMI_23 = BYDPlatformConfig(
    [CarDocs("BYD QIN PLUS DMI 2023", "All")],
    CarSpecs(mass=1600, wheelbase=2.72, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_qin_plus_dmi_2023_pt'},
  )

  BYD_YUAN_PLUS_DMI_22 = BYDPlatformConfig(
    [CarDocs("BYD YUAN PLUS DMI 2022", "All")],
    CarSpecs(mass=1500, wheelbase=2.62, steerRatio=15.0, centerToFrontRatio=0.4, tireStiffnessFactor=0.7),
    {0: 'byd_yuan_plus_dmi_2022_pt'},
  )

def get_can_parser(CP):
  signals = [
    # Steering
    ("Steering_Angle", "STEERING_ANGLE", 0),
    ("Steering_Angle_Valid", "STEERING_ANGLE", 0),
    ("Steering_Angle_Rate", "STEERING_ANGLE", 0),

    # Vehicle
    ("Vehicle_Speed", "VEHICLE_SPEED", 0),
    ("Vehicle_Acceleration", "VEHICLE_SPEED", 0),

    # Brake
    ("Brake_Pressed", "BRAKE_STATUS", 0),
    ("Brake_Pressure", "BRAKE_STATUS", 0),

    # Throttle
    ("Throttle_Percent", "THROTTLE_POSITION", 0),

    # Gear
    ("Gear", "GEAR_POSITION", 0),

    # Cruise
    ("ACC_Active", "CRUISE_CONTROL", 0),
    ("ACC_Speed_Setting", "CRUISE_CONTROL", 0),

    # Vehicle Status
    ("Power_Mode", "VEHICLE_STATUS", 0),
    ("Vehicle_Ready", "VEHICLE_STATUS", 0),
    ("EPS_Status", "VEHICLE_STATUS", 0),
  ]

  checks = [
    ("STEERING_ANGLE", 100),
    ("VEHICLE_SPEED", 50),
    ("BRAKE_STATUS", 50),
    ("THROTTLE_POSITION", 50),
    ("GEAR_POSITION", 50),
    ("CRUISE_CONTROL", 50),
    ("VEHICLE_STATUS", 10),
  ]

  return CANParser(CP.carFingerprint, signals, checks, 0)