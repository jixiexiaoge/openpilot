from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.values import CAR, ToyotaFlags
from opendbc.iqpilot.car.toyota.values import ToyotaFlagsIQ


def test_secoc_toyota_not_dashcam_on_release():
  # SecOC Toyotas are controllable regardless of branch or fingerprint source.
  candidate = CAR.TOYOTA_SIENNA_4TH_GEN

  # is_release=True (release branch) must not force dashcam mode
  cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], False, True, False)
  assert cp.flags & ToyotaFlags.SECOC.value
  assert cp.secOcRequired
  assert not cp.dashcamOnly

  # fw/can-sourced fingerprint (not forced) must also stay controllable
  cp.fingerprintSource = structs.CarParams.FingerprintSource.can
  CarInterface.get_params_iq(cp, candidate, gen_empty_fingerprint(), [], False, True, False)
  assert not cp.dashcamOnly


def test_smart_dsu_clears_disable_radar_on_radar_acc_toyota():
  candidate = CAR.TOYOTA_CHR_TSS2
  fingerprint = gen_empty_fingerprint()
  fingerprint[0][0x2FF] = 8

  cp = CarInterface.get_params(candidate, fingerprint, [], True, False, False)
  assert cp.flags & ToyotaFlags.DISABLE_RADAR.value

  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], True, False, False)

  assert cp_iq.flags & ToyotaFlagsIQ.SMART_DSU.value
  assert not (cp.flags & ToyotaFlags.DISABLE_RADAR.value)
  assert cp.alphaLongitudinalAvailable
  assert cp.openpilotLongitudinalControl
