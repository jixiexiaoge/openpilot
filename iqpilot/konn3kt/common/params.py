"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import base64
import gzip
import json
from openpilot.common.params import Params, ParamKeyType


def param_to_bytes(param_name: str, params=None, get_default=False) -> bytes | None:
  params = params or Params()
  param = params.get(param_name) if not get_default else params.get_default_value(param_name)

  if param is None:
    return None

  param_type = params.get_type(param_name)
  return _encode_param_bytes(param, param_type)


def _encode_param_bytes(param: bytes, param_type: ParamKeyType) -> bytes | None:
  if param_type == ParamKeyType.BYTES:
    return bytes(param)
  elif param_type == ParamKeyType.JSON:
    return json.dumps(param).encode('utf-8')
  return str(param).encode('utf-8')


def param_from_base64(param_name: str, base64_data: str, is_compressed=False) -> None:
  params = Params()
  param_type = params.get_type(param_name)
  value = base64.b64decode(base64_data)

  if is_compressed:
    value = gzip.decompress(value)

  param_value = _decode_param_value(value, param_type)
  params.put(param_name, param_value)


def _decode_param_value(value: bytes, param_type: ParamKeyType) -> bytes | str | int | float | bool | dict | None:
  if param_type != ParamKeyType.BYTES:
    value = value.decode('utf-8')

  if param_type == ParamKeyType.STRING:
    value = value
  elif param_type == ParamKeyType.BOOL:
    value = value.lower() in ('true', '1', 'yes')
  elif param_type == ParamKeyType.INT:
    value = int(value)
  elif param_type == ParamKeyType.FLOAT:
    value = float(value)
  elif param_type == ParamKeyType.TIME:
    value = str(value)
  elif param_type == ParamKeyType.JSON:
    value = json.loads(value)

  return value