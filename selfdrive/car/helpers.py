import capnp
from typing import Any

from cereal import custom
from opendbc.car import structs

_FIELDS = '__dataclass_fields__'  # copy of dataclasses._FIELDS


def is_dataclass(obj):
  """Similar to dataclasses.is_dataclass without instance type check checking"""
  return hasattr(obj, _FIELDS)


def _asdictref_inner(obj) -> dict[str, Any] | Any:
  if is_dataclass(obj):
    ret = {}
    for field in getattr(obj, _FIELDS):  # similar to dataclasses.fields()
      ret[field] = _asdictref_inner(getattr(obj, field))
    return ret
  elif isinstance(obj, (tuple, list)):
    return type(obj)(_asdictref_inner(v) for v in obj)
  else:
    return obj


def asdictref(obj) -> dict[str, Any]:
  """
  Similar to dataclasses.asdict without recursive type checking and copy.deepcopy
  Note that the resulting dict will contain references to the original struct as a result
  """
  if not is_dataclass(obj):
    raise TypeError("asdictref() should be called on dataclass instances")

  return _asdictref_inner(obj)


def convert_to_capnp(struct: structs.IQCarParams | structs.IQCarState) -> capnp.lib.capnp._DynamicStructBuilder:
  struct_dict = asdictref(struct)

  if isinstance(struct, structs.IQCarParams):
    struct_capnp = custom.IQCarParams.new_message(**struct_dict)
  elif isinstance(struct, structs.IQCarState):
    struct_capnp = custom.IQCarState.new_message(**struct_dict)
  else:
    raise ValueError(f"Unsupported struct type: {type(struct)}")

  return struct_capnp


def convert_iq_car_control(struct: capnp.lib.capnp._DynamicStructReader) -> structs.IQCarControl:
  # NOTE: Avoid `to_dict()` here; it can throw on fuzzed messages when capnp
  # tries to resolve unknown/invalid union-like internals. Explicit mapping is
  # stable and keeps this conversion deterministic for tests.
  struct_dataclass = structs.IQCarControl()

  aol = struct.aol
  struct_dataclass.aol = structs.AlwaysOnLateral(
    state=str(aol.state),
    enabled=aol.enabled,
    active=aol.active,
    available=aol.available,
  )

  struct_dataclass.params = [
    structs.IQCarControl.Param(
      key=p.key,
      value=bytes(p.value),
      type=str(p.type),
    ) for p in struct.params
  ]
  struct_dataclass.angleOffsetDeg = float(getattr(struct, "angleOffsetDeg", 0.0))

  lead_one = struct.leadOne
  struct_dataclass.leadOne = structs.LeadData(
    dRel=lead_one.dRel,
    yRel=lead_one.yRel,
    vRel=lead_one.vRel,
    aRel=lead_one.aRel,
    vLead=lead_one.vLead,
    dPath=lead_one.dPath,
    vLat=lead_one.vLat,
    vLeadK=lead_one.vLeadK,
    aLeadK=lead_one.aLeadK,
    fcw=lead_one.fcw,
    status=lead_one.status,
    aLeadTau=lead_one.aLeadTau,
    modelProb=lead_one.modelProb,
    radar=lead_one.radar,
    radarTrackId=lead_one.radarTrackId,
  )

  lead_two = struct.leadTwo
  struct_dataclass.leadTwo = structs.LeadData(
    dRel=lead_two.dRel,
    yRel=lead_two.yRel,
    vRel=lead_two.vRel,
    aRel=lead_two.aRel,
    vLead=lead_two.vLead,
    dPath=lead_two.dPath,
    vLat=lead_two.vLat,
    vLeadK=lead_two.vLeadK,
    aLeadK=lead_two.aLeadK,
    fcw=lead_two.fcw,
    status=lead_two.status,
    aLeadTau=lead_two.aLeadTau,
    modelProb=lead_two.modelProb,
    radar=lead_two.radar,
    radarTrackId=lead_two.radarTrackId,
  )
  struct_dataclass.angleOffsetDeg = struct.angleOffsetDeg

  return struct_dataclass


def convert_iq_car_control_compact(struct: capnp.lib.capnp._DynamicStructReader, *, include_leads: bool) -> structs.IQCarControl:
  struct_dataclass = structs.IQCarControl()

  aol = struct.aol
  struct_dataclass.aol = structs.AlwaysOnLateral(
    state=str(aol.state),
    enabled=aol.enabled,
    active=aol.active,
    available=aol.available,
  )

  struct_dataclass.params = [
    structs.IQCarControl.Param(
      key=p.key,
      value=bytes(p.value),
      type=str(p.type),
    ) for p in struct.params
  ]
  struct_dataclass.angleOffsetDeg = float(getattr(struct, "angleOffsetDeg", 0.0))

  if include_leads:
    lead_one = struct.leadOne
    struct_dataclass.leadOne = structs.LeadData(
      dRel=lead_one.dRel,
      yRel=lead_one.yRel,
      vRel=lead_one.vRel,
      aRel=lead_one.aRel,
      vLead=lead_one.vLead,
      dPath=lead_one.dPath,
      vLat=lead_one.vLat,
      vLeadK=lead_one.vLeadK,
      aLeadK=lead_one.aLeadK,
      fcw=lead_one.fcw,
      status=lead_one.status,
      aLeadTau=lead_one.aLeadTau,
      modelProb=lead_one.modelProb,
      radar=lead_one.radar,
      radarTrackId=lead_one.radarTrackId,
    )

    lead_two = struct.leadTwo
    struct_dataclass.leadTwo = structs.LeadData(
      dRel=lead_two.dRel,
      yRel=lead_two.yRel,
      vRel=lead_two.vRel,
      aRel=lead_two.aRel,
      vLead=lead_two.vLead,
      dPath=lead_two.dPath,
      vLat=lead_two.vLat,
      vLeadK=lead_two.vLeadK,
      aLeadK=lead_two.aLeadK,
      fcw=lead_two.fcw,
      status=lead_two.status,
      aLeadTau=lead_two.aLeadTau,
      modelProb=lead_two.modelProb,
      radar=lead_two.radar,
      radarTrackId=lead_two.radarTrackId,
    )

  struct_dataclass.angleOffsetDeg = struct.angleOffsetDeg

  return struct_dataclass
