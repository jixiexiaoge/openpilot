import os
import sys
import time
import numpy as np
import logging
from cereal import messaging
from common.params import Params

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for unit conversions
class CV:
  MS_TO_KPH = 3.6

# Define constants
SLOW_DOWN_BP = [0., 10., 20., 30., 40., 50., 55., 60.]
SLOW_DOWN_DISTANCE = [20, 30., 50., 70., 80., 90., 105., 120.]
CITY_SPEED_LIMIT = 40.0  # km/h - defined speed for city driving
CRUISING_SPEED = 70.0    # km/h - defined cruising speed
PROBABILITY = 0.75       # threshold for condition detection
IDX_N = 192  # from selfdrive.modeld.constants import ModelConstants

def interp(x, xp, fp):
  return float(np.interp(x, xp, fp))

class MovingAverageCalculator:
  def __init__(self, window_size=5):
    self.window_size = window_size
    self.data = []

  def add_data(self, value):
    self.data.append(1.0 if value else 0.0)
    if len(self.data) > self.window_size:
      self.data.pop(0)

  def get_moving_average(self):
    return sum(self.data) / len(self.data) if self.data else 0

  def reset_data(self):
    self.data = []

class ConditionalSpeedControl:
  def __init__(self):
    self.params = Params()
    self.params_memory = Params("/dev/shm/params")

    # Condition flags
    self.curve_detected = False
    self.lead_stopped = False
    self.red_light_detected = False
    self.condition_active = False

    # Previous state memory
    self.previous_v_ego = 0
    self.previous_v_lead = 0

    # Moving average calculators for smoothing detections
    self.curvature_mac = MovingAverageCalculator()
    self.lead_detection_mac = MovingAverageCalculator()
    self.lead_slowing_down_mac = MovingAverageCalculator()
    self.slow_lead_mac = MovingAverageCalculator()
    self.slowing_down_mac = MovingAverageCalculator()
    self.stop_light_mac = MovingAverageCalculator()

    # Status value to track which condition triggered the control
    self.status_value = 0

  def update(self, carState, enabled, frogpilotNavigation, lead_distance, lead, modelData, road_curvature, slower_lead, v_ego, v_lead, frogpilot_toggles):
    # Update all condition detections
    self.update_conditions(lead_distance, lead.status, modelData, road_curvature, slower_lead, carState.standstill, v_ego, v_lead, frogpilot_toggles)

    # Check if any conditions are met
    old_condition_active = self.condition_active
    self.condition_active = self.check_conditions(carState, frogpilotNavigation, lead, modelData, v_ego, frogpilot_toggles) and enabled

    # When conditions change, update the SpeedFromPCM parameter
    if self.condition_active != old_condition_active:
      # Set SpeedFromPCM to 0 when conditions are met, otherwise don't modify
      if self.condition_active:
        self.params.put_int_nonblocking("SpeedFromPCM", 0)
        self.params_memory.put_int("ConditionalStatus", self.status_value)
      else:
        # When condition is no longer active, we don't reset SpeedFromPCM
        # as it should be handled by other parts of the system
        self.params_memory.put_int("ConditionalStatus", 0)

  def check_conditions(self, carState, frogpilotNavigation, lead, modelData, v_ego, frogpilot_toggles):
    if carState.standstill:
      self.status_value = 0
      return self.condition_active

    # Keep control active if stopping for a red light
    if self.red_light_detected and self.slowing_down(v_ego):
      self.status_value = 16
      return True

    # Navigation-related conditions
    if hasattr(frogpilot_toggles, 'conditional_navigation') and frogpilot_toggles.conditional_navigation:
      approaching_maneuver = modelData.navEnabled and (frogpilotNavigation.approachingIntersection or frogpilotNavigation.approachingTurn)
      if approaching_maneuver and (getattr(frogpilot_toggles, 'conditional_navigation_lead', False) or not self.lead_detected):
        self.status_value = 7 if frogpilotNavigation.approachingIntersection else 8
        return True

    # Speed limit conditions
    if hasattr(frogpilot_toggles, 'conditional_limit'):
      if (not self.lead_detected and v_ego <= frogpilot_toggles.conditional_limit) or \
         (self.lead_detected and v_ego <= getattr(frogpilot_toggles, 'conditional_limit_lead', frogpilot_toggles.conditional_limit)):
        self.status_value = 11 if self.lead_detected else 12
        return True

    # Slowing lead vehicle
    if hasattr(frogpilot_toggles, 'conditional_slower_lead') and frogpilot_toggles.conditional_slower_lead and self.slower_lead_detected:
      self.status_value = 12 if self.lead_stopped else 13
      return True

    # Turn signal condition
    if hasattr(frogpilot_toggles, 'conditional_signal') and frogpilot_toggles.conditional_signal and \
       v_ego <= CITY_SPEED_LIMIT and (carState.leftBlinker or carState.rightBlinker):
      self.status_value = 14
      return True

    # Curve detection
    if hasattr(frogpilot_toggles, 'conditional_curves') and frogpilot_toggles.conditional_curves and self.curve_detected:
      self.status_value = 15
      return True

    # Traffic light detection
    if hasattr(frogpilot_toggles, 'conditional_stop_lights') and frogpilot_toggles.conditional_stop_lights and self.red_light_detected:
      self.status_value = 16
      return True

    return False

  def update_conditions(self, lead_distance, lead_status, modelData, road_curvature, slower_lead, standstill, v_ego, v_lead, frogpilot_toggles):
    self.lead_detection(lead_status)
    self.road_curvature(road_curvature, v_ego, frogpilot_toggles)
    self.slow_lead(slower_lead, v_lead)
    self.stop_sign_and_light(lead_distance, modelData, standstill, v_ego, v_lead, frogpilot_toggles)

  def lead_detection(self, lead_status):
    self.lead_detection_mac.add_data(lead_status)
    self.lead_detected = self.lead_detection_mac.get_moving_average() >= PROBABILITY

  def lead_slowing_down(self, lead_distance, v_ego, v_lead):
    if self.lead_detected:
      lead_close = lead_distance < CITY_SPEED_LIMIT
      lead_far = lead_distance >= CITY_SPEED_LIMIT and (v_lead >= self.previous_v_lead > 1 or v_lead > v_ego or self.red_light_detected)
      lead_slowing_down = v_lead < self.previous_v_lead

      self.previous_v_lead = v_lead

      self.lead_slowing_down_mac.add_data((lead_close or lead_slowing_down or self.lead_stopped) and not lead_far)
      return self.lead_slowing_down_mac.get_moving_average() >= PROBABILITY
    else:
      self.lead_slowing_down_mac.reset_data()
      self.previous_v_lead = 0
      return False

  # Determine the road curvature
  def road_curvature(self, road_curvature, v_ego, frogpilot_toggles):
    conditional_curves_lead = getattr(frogpilot_toggles, 'conditional_curves_lead', True)
    if conditional_curves_lead or not self.lead_detected:
      curve_detected = (1 / road_curvature)**0.5 < v_ego
      curve_active = (0.9 / road_curvature)**0.5 < v_ego and self.curve_detected

      self.curvature_mac.add_data(curve_detected or curve_active)
      self.curve_detected = self.curvature_mac.get_moving_average() >= PROBABILITY
    else:
      self.curvature_mac.reset_data()
      self.curve_detected = False

  def slow_lead(self, slower_lead, v_lead):
    if self.lead_detected:
      self.lead_stopped = v_lead < 1
      self.slow_lead_mac.add_data(self.lead_stopped or slower_lead)
      self.slower_lead_detected = self.slow_lead_mac.get_moving_average() >= PROBABILITY
    else:
      self.slow_lead_mac.reset_data()
      self.lead_stopped = False
      self.slower_lead_detected = False

  def slowing_down(self, v_ego):
    slowing_down = v_ego <= self.previous_v_ego
    speed_check = v_ego < CRUISING_SPEED

    self.previous_v_ego = v_ego

    self.slowing_down_mac.add_data(slowing_down and speed_check)
    return self.slowing_down_mac.get_moving_average() >= PROBABILITY

  # Stop sign/stop light detection
  def stop_sign_and_light(self, lead_distance, modelData, standstill, v_ego, v_lead, frogpilot_toggles):
    conditional_stop_lights_lead = getattr(frogpilot_toggles, 'conditional_stop_lights_lead', True)
    lead_check = conditional_stop_lights_lead or not self.lead_slowing_down(lead_distance, v_ego, v_lead) or standstill
    model_stopping = modelData.position.x[IDX_N - 1] < interp(v_ego * CV.MS_TO_KPH, SLOW_DOWN_BP, SLOW_DOWN_DISTANCE)
    model_filtered = not (self.curve_detected or self.slower_lead_detected)

    self.stop_light_mac.add_data(lead_check and model_stopping and model_filtered)
    self.red_light_detected = self.stop_light_mac.get_moving_average() >= PROBABILITY

def conditional_speed_control_thread():
  try:
    logger.info("Starting conditional speed control thread")

    # Initialize sockets for messaging
    sm = None
    retry_count = 0
    max_retries = 5

    while sm is None and retry_count < max_retries:
      try:
        # Initialize with only required messages
        sm = messaging.SubMaster(['carState', 'controlsState', 'radarState'])
        logger.info("Successfully initialized messaging")
        break
      except Exception as e:
        retry_count += 1
        logger.error(f"Failed to initialize messaging (attempt {retry_count}/{max_retries}): {e}")
        time.sleep(1)

    if sm is None:
      logger.error("Failed to initialize messaging after max retries")
      return

    # Initialize the controller
    controller = ConditionalSpeedControl()
    logger.info("Initialized ConditionalSpeedControl")

    # Dummy frogpilot_toggles for testing
    class DummyToggles:
      def __init__(self):
        self.conditional_curves = True
        self.conditional_curves_lead = True
        self.conditional_navigation = False  # Disable navigation features
        self.conditional_navigation_lead = False
        self.conditional_signal = True
        self.conditional_stop_lights = False  # Disable stop light detection without modelData
        self.conditional_stop_lights_lead = True
        self.conditional_slower_lead = True
        self.conditional_limit = CITY_SPEED_LIMIT
        self.conditional_limit_lead = CITY_SPEED_LIMIT

    frogpilot_toggles = DummyToggles()

    logger.info("Entering main loop")
    while True:
      try:
        sm.update()

        if sm.updated['carState']:  # Only require carState to be updated
          # Get required data from messages
          car_state = sm['carState']
          radar_state = sm['radarState']
          controls_state = sm['controlsState']

          # Extract lead car information
          lead = radar_state.leadOne
          lead_distance = lead.dRel if lead.status else 0
          v_lead = lead.vRel + car_state.vEgo if lead.status else 0

          # Create dummy modelData when not available
          class DummyModelData:
            def __init__(self):
              self.position = type('Position', (), {'x': [0] * IDX_N, 'y': [0] * IDX_N})()
              self.navEnabled = False

          # Update the controller
          controller.update(
            carState=car_state,
            enabled=controls_state.enabled,
            frogpilotNavigation=None,  # Disable navigation features
            lead_distance=lead_distance,
            lead=lead,
            modelData=DummyModelData(),
            road_curvature=1000.0,  # Large value means straight road
            slower_lead=lead.status and v_lead < car_state.vEgo,
            v_ego=car_state.vEgo,
            v_lead=v_lead,
            frogpilot_toggles=frogpilot_toggles
          )
      except Exception as e:
        logger.error(f"Error in main loop: {e}")
        time.sleep(0.1)  # Add small delay on error

  except Exception as e:
    logger.error(f"Fatal error in conditional_speed_control_thread: {e}")
    raise

def main():
  try:
    conditional_speed_control_thread()
  except KeyboardInterrupt:
    logger.info("Shutting down conditional speed control")
  except Exception as e:
    logger.error(f"Error in main: {e}")
    sys.exit(1)

if __name__ == "__main__":
  main()