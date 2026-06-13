"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from openpilot.iqpilot.selfdrive.controls.lib.neural_network_feed_forward.nnff import NeuralNetworkFeedForward
from openpilot.iqpilot.selfdrive.controls.lib.helpers.torque_override import LatControlTorqueExtOverride


class LatControlTorqueExt(NeuralNetworkFeedForward, LatControlTorqueExtOverride):
  def __init__(self, lac_torque, CP, CP_IQ, CI):
    NeuralNetworkFeedForward.__init__(self, lac_torque, CP, CP_IQ, CI)
    LatControlTorqueExtOverride.__init__(self, lac_torque, CP)

  def _snapshot_cycle(self,
                      feedforward_seed,
                      pid_core,
                      pid_trace,
                      torque_goal,
                      torque_actual,
                      roll_bias,
                      deadzone,
                      lat_accel_goal,
                      lat_accel_actual,
                      curvature_goal,
                      curvature_actual,
                      gravity_lat_accel,
                      safety_limited,
                      torque_output) -> None:
    self._ff = feedforward_seed
    self._pid = pid_core
    self._pid_log = pid_trace
    self._setpoint = torque_goal
    self._measurement = torque_actual
    self._roll_compensation = roll_bias
    self._lateral_accel_deadzone = deadzone
    self._desired_lateral_accel = lat_accel_goal
    self._actual_lateral_accel = lat_accel_actual
    self._desired_curvature = curvature_goal
    self._actual_curvature = curvature_actual
    self._gravity_adjusted_lateral_accel = gravity_lat_accel
    self._steer_limited_by_safety = safety_limited
    self._output_torque = torque_output

  def update(self,
             car_state,
             vehicle_model,
             pid_core,
             calibrator,
             feedforward_seed,
             pid_trace,
             torque_goal,
             torque_actual,
             calibrated_pose,
             roll_bias,
             lat_accel_goal,
             lat_accel_actual,
             deadzone,
             gravity_lat_accel,
             curvature_goal,
             curvature_actual,
             safety_limited,
             torque_output):
    self._snapshot_cycle(
      feedforward_seed,
      pid_core,
      pid_trace,
      torque_goal,
      torque_actual,
      roll_bias,
      deadzone,
      lat_accel_goal,
      lat_accel_actual,
      curvature_goal,
      curvature_actual,
      gravity_lat_accel,
      safety_limited,
      torque_output,
    )
    self.update_calculations(car_state, vehicle_model, lat_accel_goal)
    self.update_neural_network_feedforward(car_state, calibrator, calibrated_pose)
    self._output_torque = self.update_nav_torque_nudge(True, car_state, self._output_torque)
    return self._pid_log, self._output_torque
