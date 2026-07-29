""" AUTO-FORMATTED USING iqdbc/car/debug/format_fingerprints.py, EDIT STRUCTURE THERE."""
from iqdbc.car.structs import CarParams
from iqdbc.car.psa.values import CAR

Ecu = CarParams.Ecu

FW_VERSIONS = {
  CAR.PSA_PEUGEOT_208: {
    (Ecu.fwdRadar, 0x6b6, None): [
      b'212053276',
    ],
  },
}
