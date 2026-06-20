from parameterized import parameterized

from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA
from opendbc.car.hyundai.values import CAR as HYUNDAI
from opendbc.car.toyota.values import CAR as TOYOTA
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.iqpilot.selfdrive.car import interfaces as iqpilot_interfaces


class TestNNTorqueModel:

  @parameterized.expand([HONDA.HONDA_CIVIC, TOYOTA.TOYOTA_RAV4, HYUNDAI.HYUNDAI_SANTA_CRUZ_1ST_GEN])
  def test_load_model(self, car_name):
    params = Params()
    params.put_bool("NeuralNetworkFeedForward", True)

    CarInterface = interfaces[car_name]
    CP = CarInterface.get_non_essential_params(car_name)
    CP_IQ = CarInterface.get_non_essential_params_iq(CP, car_name)
    CI = CarInterface(CP, CP_IQ)

    iqpilot_interfaces.setup_interfaces(CI, params)

    CP_IQ = convert_to_capnp(CP_IQ)

    controller = LatControlTorque(CP.as_reader(), CP_IQ.as_reader(), CI, DT_CTRL)

    assert controller.extension.has_nn_model
