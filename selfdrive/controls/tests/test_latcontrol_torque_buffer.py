from parameterized import parameterized

from cereal import car, log
from opendbc.car.car_helpers import interfaces
from opendbc.car.toyota.values import CAR as TOYOTA
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque, LAT_ACCEL_REQUEST_BUFFER_SECONDS

from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.locationd.helpers import Pose
from openpilot.common.mock.generators import generate_livePose
from openpilot.iqpilot.selfdrive.car import interfaces as iqpilot_interfaces

def get_controller(car_name):
  CarInterface = interfaces[car_name]
  CP = CarInterface.get_non_essential_params(car_name)
  CP_IQ = CarInterface.get_non_essential_params_iq(CP, car_name)
  CI = CarInterface(CP, CP_IQ)
  iqpilot_interfaces.setup_interfaces(CI)
  CP_IQ = convert_to_capnp(CP_IQ)
  VM = VehicleModel(CP)
  controller = LatControlTorque(CP.as_reader(), CP_IQ.as_reader(), CI, DT_CTRL)
  return controller, VM

class TestLatControlTorqueBuffer:

  @parameterized.expand([(TOYOTA.TOYOTA_COROLLA_TSS2,)])
  def test_request_buffer_consistency(self, car_name):
    buffer_steps = int(LAT_ACCEL_REQUEST_BUFFER_SECONDS / DT_CTRL)
    controller, VM = get_controller(car_name)

    CS = car.CarState.new_message()
    CS.vEgo = 30
    CS.steeringPressed = False
    params = log.LiveParametersData.new_message()

    lp = generate_livePose()
    pose = Pose.from_live_pose(lp.livePose)

    for _ in range(buffer_steps):
      controller.update(True, CS, VM, params, False, 0.001, pose, False, 0.2)
    assert all(val != 0 for val in controller.lat_accel_request_buffer)

    for _ in range(buffer_steps):
      controller.update(False, CS, VM, params, False, 0.0, pose, False, 0.2)
    assert all(val == 0 for val in controller.lat_accel_request_buffer)
