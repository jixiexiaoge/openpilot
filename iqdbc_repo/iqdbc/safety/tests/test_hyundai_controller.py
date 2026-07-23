import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR
from iqdbc.safety.tests.libsafety import libsafety_py


@pytest.mark.parametrize("candidate", list(CAR), ids=lambda candidate: candidate.value)
@pytest.mark.parametrize("alpha_long", (False, True), ids=("stock_long", "openpilot_long"))
def test_controller_frames_match_configured_safety(candidate, alpha_long, monkeypatch, tmp_path):
  """Run real controller output through the safety configuration selected for every HKG platform."""
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / candidate.value))
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], alpha_long, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], alpha_long, False, False)
  interface = CarInterface(cp, cp_iq)
  interface.update([])

  safety_config = cp.safetyConfigs[-1]
  safety = libsafety_py.libsafety
  assert safety.set_safety_hooks(safety_config.safetyModel.raw, safety_config.safetyParam) == 0
  safety.init_tests()
  safety.set_controls_allowed(True)

  control = structs.CarControl.new_message()
  control.enabled = True
  control.latActive = True
  control.longActive = alpha_long
  control.actuators.torque = 0.01
  control.actuators.accel = 0.0

  for frame in range(20):
    _, can_sends = interface.apply(control.as_reader(), structs.IQCarControl())
    assert isinstance(can_sends, list)
    for address, data, bus in can_sends:
      packet = libsafety_py.make_CANPacket(address, bus, data)
      rejection = f"{candidate.value} frame {frame}: safety rejected address={address:#x} bus={bus} data={data.hex()}"
      assert safety.safety_tx_hook(packet), rejection
