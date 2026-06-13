from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.values import CAR, ToyotaFlags
from opendbc.iqpilot.car.toyota.values import ToyotaFlagsIQ


def test_forced_secoc_toyota_clears_dashcam_mode():
  candidate = CAR.TOYOTA_SIENNA_4TH_GEN
  cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], False, True, False)
  assert cp.dashcamOnly

  cp.fingerprintSource = structs.CarParams.FingerprintSource.fixed
  CarInterface.get_params_iq(cp, candidate, gen_empty_fingerprint(), [], False, True, False)

  assert not cp.dashcamOnly


def test_automatic_secoc_toyota_release_stays_dashcam():
  candidate = CAR.TOYOTA_SIENNA_4TH_GEN
  cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], False, True, False)
  assert cp.dashcamOnly

  cp.fingerprintSource = structs.CarParams.FingerprintSource.can
  CarInterface.get_params_iq(cp, candidate, gen_empty_fingerprint(), [], False, True, False)

  assert cp.dashcamOnly


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
