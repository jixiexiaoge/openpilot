from cereal import car
from selfdrive.car.interfaces import CANParser

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