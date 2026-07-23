#!/usr/bin/env python3
import codecs
import pathlib
import pickle
import sys
from collections.abc import Iterable
from typing import Any

from cereal import custom
from tinygrad.nn.onnx import OnnxPBParser

from openpilot.iqpilot.selfdrive.iqmodeld.models.helpers import get_active_bundle
from openpilot.iqpilot.selfdrive.iqmodeld.config import Meta


ModelBundle = custom.IQModelManager.ModelBundle


def _blank_proto_doc() -> dict[str, Any]:
  return {"graph": {"input": [], "output": []}, "metadata_props": []}


class TelemetryEnvelopeParser(OnnxPBParser):
  def _parse_ModelProto(self) -> dict:
    envelope = _blank_proto_doc()
    for fid, wire_type in self._parse_message(self.reader.len):
      if fid == 7:
        envelope["graph"] = self._parse_GraphProto()
      elif fid == 14:
        envelope["metadata_props"].append(self._parse_StringStringEntryProto())
      else:
        self.reader.skip_field(wire_type)
    return envelope


def _shape_fingerprint(value_info: dict[str, Any]) -> tuple[str, tuple[int, ...]]:
  resolved = []
  for axis in value_info["parsed_type"].shape:
    resolved.append(int(axis) if isinstance(axis, int) else 0)
  return value_info["name"], tuple(resolved)


def _lookup_metadata(props: Iterable[dict[str, Any]], wanted_key: str) -> str | Any:
  for entry in props:
    if entry["key"] == wanted_key:
      return entry["value"]
  return None


class Meta20hz(Meta):
  ENGAGED = slice(0, 1)
  GAS_DISENGAGE = slice(1, 31, 6)
  BRAKE_DISENGAGE = slice(2, 31, 6)
  STEER_OVERRIDE = slice(3, 31, 6)
  HARD_BRAKE_3 = slice(4, 31, 6)
  HARD_BRAKE_4 = slice(5, 31, 6)
  HARD_BRAKE_5 = slice(6, 31, 6)
  GAS_PRESS = slice(31, 55, 4)
  BRAKE_PRESS = slice(32, 55, 4)
  LEFT_BLINKER = slice(33, 55, 4)
  RIGHT_BLINKER = slice(34, 55, 4)


def select_meta_layout():
  active_bundle = get_active_bundle()
  return Meta20hz if active_bundle is not None and active_bundle.is20hz else Meta


def _decoded_slices(props: Iterable[dict[str, Any]]):
  encoded = _lookup_metadata(props, "output_slices")
  assert encoded is not None, "output_slices not found in metadata"
  return pickle.loads(codecs.decode(encoded.encode(), "base64"))


def _graph_shape_table(graph_doc: dict[str, Any], field_name: str) -> dict[str, tuple[int, ...]]:
  return dict(_shape_fingerprint(item) for item in graph_doc[field_name])


def build_metadata_record(model_path):
  parsed = TelemetryEnvelopeParser(model_path).parse()
  props = parsed["metadata_props"]
  graph = parsed["graph"]
  return {
    "model_checkpoint": _lookup_metadata(props, "model_checkpoint"),
    "output_slices": _decoded_slices(props),
    "input_shapes": _graph_shape_table(graph, "input"),
    "output_shapes": _graph_shape_table(graph, "output"),
  }


if __name__ == "__main__":
  model_path = pathlib.Path(sys.argv[1])
  metadata_path = model_path.parent / f"{model_path.stem}_metadata.pkl"
  with open(metadata_path, "wb") as handle:
    pickle.dump(build_metadata_record(model_path), handle)
  print(f"saved metadata to {metadata_path}")
