"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import base64
import pickle
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import onnx

from openpilot.system.hardware.hw import Paths

_MODEL_STEMS = ("driving_off_policy", "driving_on_policy", "driving_policy", "driving_vision")


@dataclass(frozen=True)
class _ModelBundle:
  stem: str
  onnx_path: Path
  artifact_path: Path
  metadata_path: Path


def _tensor_shape(value_info) -> tuple[int, ...]:
  return tuple(int(dim.dim_value) for dim in value_info.type.tensor_type.shape.dim)


def _metadata_property(graph_model, key: str) -> str | None:
  for property_item in graph_model.metadata_props:
    if property_item.key == key:
      return property_item.value
  return None


def _decode_output_slices(encoded_value: str):
  return pickle.loads(base64.b64decode(encoded_value.encode()))


def _metadata_record(graph_model) -> dict:
  encoded_slices = _metadata_property(graph_model, "output_slices")
  if encoded_slices is None:
    raise ValueError("output_slices metadata missing")
  return {
    "model_checkpoint": _metadata_property(graph_model, "model_checkpoint"),
    "output_slices": _decode_output_slices(encoded_slices),
    "input_shapes": {item.name: _tensor_shape(item) for item in graph_model.graph.input},
    "output_shapes": {item.name: _tensor_shape(item) for item in graph_model.graph.output},
  }


def generate_metadata_pkl(model_path, output_path):
  try:
    graph_model = onnx.load(str(model_path))
    metadata = _metadata_record(graph_model)
  except Exception:
    return False

  with open(output_path, "wb") as handle:
    pickle.dump(metadata, handle)
  return True


def _discover_model_bundles(model_dir: Path) -> list[_ModelBundle]:
  bundles: list[_ModelBundle] = []
  for stem in _MODEL_STEMS:
    onnx_path = model_dir / f"{stem}.onnx"
    if not onnx_path.exists():
      continue
    bundles.append(_ModelBundle(
      stem=stem,
      onnx_path=onnx_path,
      artifact_path=model_dir / f"{stem}_tinygrad.pkl",
      metadata_path=model_dir / f"{stem}_metadata.pkl",
    ))
  return bundles


def _prompt_short_name(found_stems: list[str]) -> str | None:
  try:
    response = input(f"Found models ({', '.join(found_stems)}). Enter model short name (e.g. wmiv4): ").strip()
  except EOFError:
    return None
  return response or None


def _ensure_metadata_file(bundle: _ModelBundle) -> None:
  if bundle.metadata_path.exists():
    return
  generate_metadata_pkl(bundle.onnx_path, bundle.metadata_path)


def _install_bundle(bundle: _ModelBundle, suffix: str, destination_root: Path) -> None:
  _ensure_metadata_file(bundle)
  renamed_artifact = destination_root / f"{bundle.stem}_{suffix}_tinygrad.pkl"
  renamed_metadata = destination_root / f"{bundle.stem}_{suffix}_metadata.pkl"
  if bundle.artifact_path.exists():
    shutil.move(str(bundle.artifact_path), str(renamed_artifact))
  if bundle.metadata_path.exists():
    shutil.move(str(bundle.metadata_path), str(renamed_metadata))


def install_models(model_dir):
  source_root = Path(model_dir)
  bundles = _discover_model_bundles(source_root)
  if not bundles:
    return

  short_name = _prompt_short_name([bundle.stem for bundle in bundles])
  if short_name is None:
    print("No name provided, skipping installation.")
    return

  destination_root = Path(Paths.model_root())
  destination_root.mkdir(parents=True, exist_ok=True)
  for bundle in bundles:
    _install_bundle(bundle, short_name, destination_root)


if __name__ == "__main__":
  if len(sys.argv) < 2:
    print("Usage: install_models_pc.py <model_dir>")
    sys.exit(1)
  install_models(sys.argv[1])
