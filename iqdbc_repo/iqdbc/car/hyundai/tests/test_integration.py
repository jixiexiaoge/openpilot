import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, HyundaiFlagsIQ, HyundaiSafetyFlagsIQ


@pytest.mark.parametrize("candidate", list(CAR), ids=lambda candidate: candidate.value)
@pytest.mark.parametrize("alpha_long", (False, True), ids=("stock_long", "openpilot_long"))
def test_all_platform_state_controller_and_radar(candidate, alpha_long, monkeypatch, tmp_path):
  """Every declared HKG platform must initialize and execute one complete interface cycle."""
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / candidate.value))
  fingerprint = gen_empty_fingerprint()

  cp = CarInterface.get_params(candidate, fingerprint, [], alpha_long, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], alpha_long, False, False)
  interface = CarInterface(cp, cp_iq)

  state, state_iq = interface.update([])
  actuators, can_sends = interface.apply(structs.CarControl().as_reader(), structs.IQCarControl())
  radar = interface.RadarInterface(cp, cp_iq)
  radar_result = radar.update([])

  assert state.vEgo == 0.0
  assert state_iq is not None
  assert actuators is not None
  assert isinstance(can_sends, list)
  assert radar_result is None


def test_parameter_defaults_do_not_require_persisted_fingerprint(monkeypatch, tmp_path):
  """A clean installation must not crash when carrotpilot-specific Params have not been written yet."""
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  fingerprint = gen_empty_fingerprint()

  cp = CarInterface.get_params(CAR.HYUNDAI_SONATA, fingerprint, [], False, False, False)
  cp_iq = CarInterface.get_params_iq(cp, CAR.HYUNDAI_SONATA, fingerprint, [], False, False, False)
  interface = CarInterface(cp, cp_iq)

  state, _ = interface.update([])
  assert state.vEgo == 0.0


def test_classic_lfa_button_capability_survives_iq_module_removal(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  fingerprint = gen_empty_fingerprint()
  fingerprint[0][0x391] = 8

  cp = CarInterface.get_params(CAR.HYUNDAI_SONATA, fingerprint, [], False, False, False)
  cp_iq = CarInterface.get_params_iq(cp, CAR.HYUNDAI_SONATA, fingerprint, [], False, False, False)

  assert cp_iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON
  assert cp_iq.iqSafetyFlags & HyundaiSafetyFlagsIQ.HAS_LDA_BUTTON
