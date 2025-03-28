from cereal import car
from opendbc.can.parser import CANParser

class CAR:
  # 比亚迪车型定义
  BYD_SEAL = "BYD SEAL"
  BYD_SEAL_2024 = "BYD SEAL 2024"
  BYD_SEAL_2024_2 = "BYD SEAL 2024 2"
  BYD_SEAL_2024_3 = "BYD SEAL 2024 3"
  BYD_SEAL_2024_4 = "BYD SEAL 2024 4"
  BYD_SEAL_2024_5 = "BYD SEAL 2024 5"
  BYD_SEAL_2024_6 = "BYD SEAL 2024 6"
  BYD_SEAL_2024_7 = "BYD SEAL 2024 7"
  BYD_SEAL_2024_8 = "BYD SEAL 2024 8"
  BYD_SEAL_2024_9 = "BYD SEAL 2024 9"
  BYD_SEAL_2024_10 = "BYD SEAL 2024 10"

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