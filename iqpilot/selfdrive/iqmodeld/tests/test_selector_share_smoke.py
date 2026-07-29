from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from tinygrad.nn.onnx import OnnxRunner
from tinygrad.tensor import Tensor

import openpilot.iqpilot.selfdrive.iqmodeld.models.helpers as bundle_helpers
import openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner as model_runner_mod
import openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.tinygrad_runner as tinygrad_runner_mod
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelType
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.tinygrad_runner import TinygradRunner


SHARE_ROOT = Path(os.getenv("IQPILOT_SELECTOR_SHARE", "/Volumes/New New Vault/IQModels/models/recompiled16"))


@dataclass
class _TypeWrap:
  raw: int


@dataclass
class _Artifact:
  fileName: str


class _Model:
  def __init__(self, model_type: int, artifact_name: str, metadata_name: str):
    self.type = _TypeWrap(model_type)
    self.artifact = _Artifact(artifact_name)
    self.metadata = _Artifact(metadata_name)


class _Bundle:
  def __init__(self, models: list[_Model], is_20hz: bool = False):
    self.models = models
    self.is20hz = is_20hz


def _find_selector_dirs(limit: int = 3, require_onnx: bool = False) -> list[Path]:
  found: list[Path] = []
  if not SHARE_ROOT.is_dir():
    return found

  for bundle_dir in sorted(SHARE_ROOT.iterdir()):
    if not bundle_dir.is_dir():
      continue
    vision = next(bundle_dir.glob("driving_vision*_tinygrad.pkl"), None)
    policy = next(bundle_dir.glob("driving_policy*_tinygrad.pkl"), None)
    vision_meta = next(bundle_dir.glob("driving_vision*_metadata.pkl"), None)
    policy_meta = next(bundle_dir.glob("driving_policy*_metadata.pkl"), None)
    has_onnx = (bundle_dir / "driving_vision.onnx").is_file() and (bundle_dir / "driving_policy.onnx").is_file()
    if vision and policy and vision_meta and policy_meta and (has_onnx or not require_onnx):
      found.append(bundle_dir)
    if len(found) >= limit:
      break
  return found


def _seed_runner_inputs(runner: TinygradRunner) -> None:
  for name, shape in runner.input_shapes.items():
    runner.inputs[name] = Tensor(
      np.zeros(shape, dtype=np.float32),
      device=runner.input_to_device[name],
      dtype=runner.input_to_dtype[name],
    ).realize()


def _bundle_for_dir(bundle_dir: Path) -> _Bundle:
  vision = next(bundle_dir.glob("driving_vision*_tinygrad.pkl"))
  policy = next(bundle_dir.glob("driving_policy*_tinygrad.pkl"))
  vision_meta = next(bundle_dir.glob("driving_vision*_metadata.pkl"))
  policy_meta = next(bundle_dir.glob("driving_policy*_metadata.pkl"))
  return _Bundle([
    _Model(ModelType.vision, vision.name, vision_meta.name),
    _Model(ModelType.policy, policy.name, policy_meta.name),
  ])


def _run_tinygrad_bundle(bundle_dir: Path, monkeypatch):
  bundle = _bundle_for_dir(bundle_dir)
  monkeypatch.setattr(bundle_helpers, "get_active_bundle", lambda params=None: bundle, raising=False)
  monkeypatch.setattr(model_runner_mod, "get_active_bundle", lambda params=None: bundle, raising=False)
  monkeypatch.setattr(tinygrad_runner_mod, "CUSTOM_MODEL_PATH", str(bundle_dir), raising=False)
  monkeypatch.setattr(model_runner_mod, "CUSTOM_MODEL_PATH", str(bundle_dir), raising=False)

  vision_runner = TinygradRunner(ModelType.vision)
  _seed_runner_inputs(vision_runner)
  vision_outputs = vision_runner.run_model()

  policy_runner = TinygradRunner(ModelType.policy)
  _seed_runner_inputs(policy_runner)
  policy_outputs = policy_runner.run_model()

  return vision_outputs, policy_outputs


def _run_onnx_bundle(bundle_dir: Path):
  vision_session = OnnxRunner(bundle_dir / "driving_vision.onnx")
  policy_session = OnnxRunner(bundle_dir / "driving_policy.onnx")

  def seed_inputs(session):
    seeded = {}
    for name, spec in session.graph_inputs.items():
      dtype_text = str(spec.dtype).lower()
      if "uchar" in dtype_text or "uint8" in dtype_text:
        seeded[name] = Tensor(np.zeros(spec.shape, dtype=np.uint8))
      elif "half" in dtype_text or "float16" in dtype_text:
        seeded[name] = Tensor(np.zeros(spec.shape, dtype=np.float16))
      else:
        seeded[name] = Tensor(np.zeros(spec.shape, dtype=np.float32))
    return seeded

  return (
    vision_session(seed_inputs(vision_session))["outputs"].numpy().flatten(),
    policy_session(seed_inputs(policy_session))["outputs"].numpy().flatten(),
  )


@pytest.mark.skipif(not SHARE_ROOT.is_dir(), reason="selector model share is not mounted")
def test_three_selector_models_parse_via_share_onnx():
  selector_dirs = _find_selector_dirs(limit=3, require_onnx=True)
  assert len(selector_dirs) >= 3

  for bundle_dir in selector_dirs:
    vision_raw, policy_raw = _run_onnx_bundle(bundle_dir)
    assert vision_raw.size > 0
    assert policy_raw.size > 0


@pytest.mark.skipif(not SHARE_ROOT.is_dir(), reason="selector model share is not mounted")
def test_selector_tinygrad_pkls_execute_when_host_compatible(monkeypatch):
  selector_dirs = _find_selector_dirs(limit=10)
  attempted = 0
  executed = 0

  for bundle_dir in selector_dirs:
    attempted += 1
    try:
      vision_outputs, policy_outputs = _run_tinygrad_bundle(bundle_dir, monkeypatch)
    except AssertionError as exc:
      if "Model was built on C3 or C3X" in str(exc):
        continue
      raise
    except FileNotFoundError as exc:
      if "/dev/kgsl-3d0" in str(exc):
        continue
      raise

    assert "pose" in vision_outputs
    assert "plan" in policy_outputs
    executed += 1
    if executed >= 3:
      break

  if executed == 0:
    pytest.skip(f"share tinygrad pkls are QCOM-only on this host; inspected {attempted} bundles")
