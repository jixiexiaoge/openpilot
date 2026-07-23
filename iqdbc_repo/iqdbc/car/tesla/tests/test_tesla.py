from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.tesla.interface import CarInterface
from iqdbc.car.tesla.teslacan import TeslaCAN
from iqdbc.car.tesla.radar_interface import RADAR_START_ADDR
from iqdbc.car.tesla.carcontroller import CarController
from iqdbc.car.tesla.values import CAR
from iqdbc.can import CANPacker, CANParser


class TestTeslaFingerprint:
  def test_radar_detection(self):
    # Test radar availability detection for cars with radar DBC defined
    for radar in (True, False):
      fingerprint = gen_empty_fingerprint()
      if radar:
        fingerprint[1][RADAR_START_ADDR] = 8
      CP = CarInterface.get_params(CAR.TESLA_MODEL_3, fingerprint, [], False, False, False)
      assert CP.radarUnavailable != radar

  def test_no_radar_car(self):
    # Model X doesn't have radar DBC defined, should always be unavailable
    for radar in (True, False):
      fingerprint = gen_empty_fingerprint()
      if radar:
        fingerprint[1][RADAR_START_ADDR] = 8
      CP = CarInterface.get_params(CAR.TESLA_MODEL_X, fingerprint, [], False, False, False)
      assert CP.radarUnavailable  # Always unavailable since no radar DBC


class TestTeslaCan:
  class DummyPacker:
    def make_can_msg(self, name, bus, values):
      return name, bus, values

  def test_vehicle_bus_odometer_decodes_kilometers(self):
    packer = CANPacker("tesla_model3_vehicle")
    parser = CANParser("tesla_model3_vehicle", [("ID3B6UI_odometer", 1)], 1)

    message = packer.make_can_msg("ID3B6UI_odometer", 1, {
      "UI_odometer": 29150.377,
      "UI_odometerCounter": 1,
      "UI_odometerChecksum": 0,
    })
    parser.update([1_000_000_000, [message]])

    assert parser.vl["ID3B6UI_odometer"]["UI_odometer"] == 29150.377

  def test_longitudinal_command_does_not_reference_missing_jerk_attr(self):
    CP = CarInterface.get_non_essential_params(CAR.TESLA_MODEL_3)
    tesla_can = TeslaCAN(CP, self.DummyPacker())

    name, bus, values = tesla_can.create_longitudinal_command(4, 1.0, 0, 20.0, True, False)

    assert name == "DAS_control"
    assert bus == 0
    assert values["DAS_jerkMax"] <= 4.9
    assert values["DAS_jerkMax"] >= 0.0

  def test_longitudinal_command_uses_explicit_set_speed(self):
    CP = CarInterface.get_non_essential_params(CAR.TESLA_MODEL_3)
    tesla_can = TeslaCAN(CP, self.DummyPacker())

    name, bus, values = tesla_can.create_longitudinal_command(4, 1.0, 0, 20.0, True, False, set_speed_kph=64.0)

    assert name == "DAS_control"
    assert bus == 0
    assert values["DAS_setSpeed"] == 64.0

  def test_longitudinal_command_preserves_decel_when_explicit_set_speed_present(self):
    CP = CarInterface.get_non_essential_params(CAR.TESLA_MODEL_3)
    tesla_can = TeslaCAN(CP, self.DummyPacker())

    name, bus, values = tesla_can.create_longitudinal_command(4, -0.5, 0, 20.0, True, False, set_speed_kph=64.0)

    assert name == "DAS_control"
    assert bus == 0
    assert values["DAS_setSpeed"] == 0
    assert values["DAS_accelMin"] < 0


class TestTeslaCarControllerIQParams:
  def test_iq_params_override_set_speed(self):
    CP = CarInterface.get_non_essential_params(CAR.TESLA_MODEL_3)
    CP.openpilotLongitudinalControl = True
    controller = CarController(CAR.TESLA_MODEL_3.config.dbc_dict, CP, structs.IQCarParams())

    class DummyCruise:
      cancel = False

    class DummyActuators:
      steeringAngleDeg = 0.0
      accel = 1.0

      def as_builder(self):
        return self

    class DummyCarControl:
      actuators = DummyActuators()
      latActive = False
      longActive = True
      cruiseControl = DummyCruise()

    class DummyCarState:
      hands_on_level = 0
      out = type("Out", (), {"vEgoRaw": 20.0, "steeringAngleDeg": 0.0, "steeringRateDeg": 0.0, "steeringTorque": 0.0, "vEgo": 20.0})()
      das_accCancel = False
      cruise_override = False
      das_control = {"DAS_controlCounter": 0}

    cc_iq = structs.IQCarControl(params=[
      structs.IQCarControl.Param(
        key="enhancedStockLongitudinalControl.setSpeedKph",
        type="float",
        value=b"64.0",
      )
    ])

    captured = {}

    def fake_longitudinal_command(state, accel, cntr, v_ego, active, cruise_override, set_speed_kph=None):
      captured["set_speed_kph"] = set_speed_kph
      return ("DAS_control", 0, {"DAS_setSpeed": set_speed_kph})

    controller.tesla_can.create_longitudinal_command = fake_longitudinal_command

    controller.update(DummyCarControl(), cc_iq, DummyCarState(), 0)
    assert captured["set_speed_kph"] == 64.0
