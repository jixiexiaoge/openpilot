import os
import capnp
from opendbc.car.common.basedir import BASEDIR

# TODO: remove car from cereal/__init__.py and always import from opendbc
try:
  from cereal import car
except ImportError:
  capnp.remove_import_hook()
  car = capnp.load(os.path.join(BASEDIR, "car.capnp"))

CarState = car.CarState
RadarData = car.RadarData
CarControl = car.CarControl
CarParams = car.CarParams

CarStateT = capnp.lib.capnp._StructModule
RadarDataT = capnp.lib.capnp._StructModule
CarControlT = capnp.lib.capnp._StructModule
CarParamsT = capnp.lib.capnp._StructModule

class DPFlags:
  LatALKA = 1
  ExtRadar = 2
  ToyotaLockCtrl = 2 ** 2
  ToyotaTSS1SnG = 2 ** 3
  ToyotaStockLon = 2 ** 4
  VagA0SnG = 2 ** 5
  VAGPQSteeringPatch = 2 ** 6
  VagAvoidEPSLockout = 2 ** 7
  pass
