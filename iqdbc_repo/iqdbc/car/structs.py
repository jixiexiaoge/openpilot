from dataclasses import dataclass as _dataclass, field, is_dataclass
from enum import Enum, StrEnum as _StrEnum, auto
from typing import dataclass_transform, get_origin
import os
import capnp
from iqdbc.car.common.basedir import BASEDIR
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

AUTO_OBJ = object()
def auto_field():
  return AUTO_OBJ
@dataclass_transform()
def auto_dataclass(cls=None, /, **kwargs):
  cls_annotations = cls.__dict__.get('__annotations__', {})
  for name, typ in cls_annotations.items():
    current_value = getattr(cls, name)
    if current_value is AUTO_OBJ:
      origin_typ = get_origin(typ) or typ
      if isinstance(origin_typ, str):
        raise TypeError(f"Forward references are not supported for auto_field: '{origin_typ}'. Use a default_factory with lambda instead.")
      elif origin_typ in (int, float, str, bytes, list, tuple, bool) or is_dataclass(origin_typ):
        setattr(cls, name, field(default_factory=origin_typ))
      elif issubclass(origin_typ, Enum):  # first enum is the default
        setattr(cls, name, field(default=next(iter(origin_typ))))
      else:
        raise TypeError(f"Unsupported type for auto_field: {origin_typ}")
  return _dataclass(cls, **kwargs)

class StrEnum(_StrEnum):
  @staticmethod
  def _generate_next_value_(name, *args):
    return name

@auto_dataclass
class IQCarParams:
  flags: int = auto_field()
  iqSafetyFlags: int = auto_field()
  pcmCruiseSpeed: bool = auto_field()
  enableGasInterceptor: bool = auto_field()
  longitudinalStoppingSpeedOverride: float = auto_field()

  iqLateralNet: 'IQCarParams.LateralNet' = field(default_factory=lambda: IQCarParams.LateralNet())

  @auto_dataclass
  class LateralNet:
    model: 'IQCarParams.LateralNet.Model' = field(default_factory=lambda: IQCarParams.LateralNet.Model())
    fuzzyFingerprint: bool = auto_field()

    @auto_dataclass
    class Model:
      path: str = auto_field()
      name: str = auto_field()


@auto_dataclass
class AlwaysOnLateral:
  state: 'AlwaysOnLateral.AlwaysOnLateralState' = field(
    default_factory=lambda: AlwaysOnLateral.AlwaysOnLateralState.disabled
  )
  enabled: bool = auto_field()
  active: bool = auto_field()
  available: bool = auto_field()

  class AlwaysOnLateralState(StrEnum):
    disabled = auto()
    paused = auto()
    enabled = auto()
    softDisabling = auto()
    overriding = auto()


@auto_dataclass
class LeadData:
  dRel: float = auto_field()
  yRel: float = auto_field()
  vRel: float = auto_field()
  aRel: float = auto_field()
  vLead: float = auto_field()
  dPath: float = auto_field()
  vLat: float = auto_field()
  vLeadK: float = auto_field()
  aLeadK: float = auto_field()
  fcw: bool = auto_field()
  status: bool = auto_field()
  aLeadTau: float = auto_field()
  modelProb: float = auto_field()
  radar: bool = auto_field()
  radarTrackId: int = auto_field()

  aLeadDEPRECATED: float = auto_field()


@auto_dataclass
class IQCarControl:
  aol: 'AlwaysOnLateral' = field(default_factory=lambda: AlwaysOnLateral())
  params: list['IQCarControl.Param'] = auto_field()
  leadOne: 'LeadData' = field(default_factory=lambda: LeadData())
  leadTwo: 'LeadData' = field(default_factory=lambda: LeadData())
  angleOffsetDeg: float = auto_field()
  # VW PQ "Blend IQ.Pilot + Stock ACC Radar" intent (radar_manager -> RadarHandler)
  radarBlendActive: bool = auto_field()
  radarEngageReq: bool = auto_field()
  radarCancelReq: bool = auto_field()
  useRadarAccel: bool = auto_field()
  radarSetSpeedKph: float = auto_field()
  radarGapBars: int = auto_field()

  @auto_dataclass
  class Param:
    key: str = auto_field()
    value: bytes = auto_field()
    type: 'IQCarControl.ParamType' = field(
      default_factory=lambda: IQCarControl.ParamType.string
    )

  class ParamType(StrEnum):
    string = auto()
    bool = auto()
    int = auto()
    float = auto()
    time = auto()
    json = auto()
    bytes = auto()


@auto_dataclass
class IQCarState:
  speedLimit: float = auto_field()
  alcOverrideAlert: bool = auto_field()
