from cereal import car
from selfdrive.car.byd.values import DBC

class CarState:
  def __init__(self, CP):
    self.CP = CP
    self.cruise_buttons = 0

  def update(self, cp):
    ret = car.CarState.new_message()
    
    # Steering
    ret.steeringAngleDeg = cp.vl["STEERING_ANGLE"]["Steering_Angle"] * 0.1
    ret.steeringPressed = abs(cp.vl["STEERING_ANGLE"]["Steering_Angle_Rate"]) > 0.5
    
    # Vehicle
    ret.vEgo = cp.vl["VEHICLE_SPEED"]["Vehicle_Speed"] * 0.01 / 3.6  # km/h -> m/s
    ret.aEgo = cp.vl["VEHICLE_SPEED"]["Vehicle_Acceleration"] * 0.001
    
    # Brake
    ret.brakePressed = cp.vl["BRAKE_STATUS"]["Brake_Pressed"]
    ret.brake = cp.vl["BRAKE_STATUS"]["Brake_Pressure"] / 255.0
    
    # Throttle
    ret.gas = cp.vl["THROTTLE_POSITION"]["Throttle_Percent"] / 100.0
    
    # Gear
    gear_map = {0: "P", 1: "R", 2: "N", 3: "D"}
    ret.gearShifter = gear_map.get(cp.vl["GEAR_POSITION"]["Gear"], "unknown")
    
    # Cruise
    ret.cruiseState.enabled = cp.vl["CRUISE_CONTROL"]["ACC_Active"]
    ret.cruiseState.speed = cp.vl["CRUISE_CONTROL"]["ACC_Speed_Setting"] * 1.0
    
    # Vehicle Status
    power_mode_map = {0: "off", 1: "acc", 2: "on", 3: "start"}
    ret.powerMode = power_mode_map.get(cp.vl["VEHICLE_STATUS"]["Power_Mode"], "unknown")
    
    return ret