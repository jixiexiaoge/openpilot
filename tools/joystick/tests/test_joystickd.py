from cereal import car

from openpilot.tools.joystick.joystickd import get_lateral_joystick_outputs


class StubVehicleModel:
  def get_steer_from_curvature(self, curvature: float, v_ego: float, roll: float) -> float:
    return curvature


def test_angle_cars_use_angle_outputs():
  CP = car.CarParams.new_message()
  CP.steerControlType = car.CarParams.SteerControlType.angle

  torque, steering_angle_deg, curvature = get_lateral_joystick_outputs(CP, StubVehicleModel(), 20.0, 0.0, 0.5)

  assert torque == 0.0
  assert steering_angle_deg != 0.0
  assert curvature < 0.0


def test_torque_cars_keep_torque_outputs():
  CP = car.CarParams.new_message()
  CP.steerControlType = car.CarParams.SteerControlType.torque

  torque, steering_angle_deg, curvature = get_lateral_joystick_outputs(CP, StubVehicleModel(), 20.0, 0.0, 0.5)

  assert torque == 0.5
  assert steering_angle_deg != 0.0
  assert curvature < 0.0
