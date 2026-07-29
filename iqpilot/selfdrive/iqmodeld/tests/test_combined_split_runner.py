from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from openpilot.iqpilot.selfdrive.iqmodeld.models.combined_artifact import resolve_combined_split_artifact
import openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner as runner_helpers
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.combined_split_runner import TinygradCombinedSplitRunner
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad import combined_split_runner as combined_runner_mod
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelType
from openpilot.iqpilot.selfdrive.iqmodeld.parser import PhaseParser
from openpilot.iqpilot.selfdrive.iqmodeld.tests.test_iqmodeld_contracts import _phase_sample


@dataclass
class _TypeWrap:
  raw: int


@dataclass
class _Artifact:
  fileName: str


class _Model:
  def __init__(self, model_type: int, artifact_name: str):
    self.type = _TypeWrap(model_type)
    self.artifact = _Artifact(artifact_name)


class _Override:
  def __init__(self, key: str, value: str):
    self.key = key
    self.value = value


class _Bundle:
  def __init__(self, models: list[_Model], overrides: list[_Override] | None = None, generation: int = 10):
    self.models = models
    self.overrides = overrides or []
    self.generation = generation


class _FakeTensor:
  def __init__(self, values):
    self._values = np.asarray(values, dtype=np.float32)

  def numpy(self):
    return self._values


class _FakeVisionBuf:
  width = 1928
  height = 1208
  data = memoryview(b"\x00" * 64)


def _slice_pack(outputs: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, slice]]:
  chunks = []
  slices: dict[str, slice] = {}
  cursor = 0
  for name, value in outputs.items():
    flat = value.reshape(-1)
    slices[name] = slice(cursor, cursor + flat.size)
    chunks.append(flat)
    cursor += flat.size
  return np.concatenate(chunks).astype(np.float32), slices


def test_resolve_combined_split_artifact_prefers_override(tmp_path: Path, monkeypatch):
  bundle = _Bundle(
    [_Model(ModelType.vision, "driving_vision_demo_tinygrad.pkl"), _Model(ModelType.policy, "driving_policy_demo_tinygrad.pkl")],
    overrides=[_Override("combinedRuntimeArtifact", "driving_combined_demo.pkl")],
  )
  expected = tmp_path / "driving_combined_demo.pkl"
  expected.write_bytes(b"iq")

  monkeypatch.setattr("openpilot.iqpilot.selfdrive.iqmodeld.models.combined_artifact._MODEL_ROOT", tmp_path)

  assert resolve_combined_split_artifact(bundle) == expected


def test_get_model_runner_prefers_combined_split_artifact(monkeypatch):
  bundle = _Bundle([
    _Model(ModelType.vision, "driving_vision_demo_tinygrad.pkl"),
    _Model(ModelType.policy, "driving_policy_demo_tinygrad.pkl"),
  ], generation=11)

  marker = object()
  monkeypatch.setattr(runner_helpers, "get_active_bundle", lambda: bundle)
  monkeypatch.setattr(runner_helpers, "has_combined_split_artifact", lambda _: True)
  monkeypatch.setattr(combined_runner_mod, "TinygradCombinedSplitRunner", lambda: marker)

  assert runner_helpers.get_model_runner() is marker


def test_get_model_runner_keeps_split_bundle_on_existing_runner_without_combined_artifact(monkeypatch):
  bundle = _Bundle([
    _Model(ModelType.vision, "driving_vision_demo_tinygrad.pkl"),
    _Model(ModelType.policy, "driving_policy_demo_tinygrad.pkl"),
  ], generation=12)

  marker = object()
  monkeypatch.setattr(runner_helpers, "get_active_bundle", lambda: bundle)
  monkeypatch.setattr(runner_helpers, "has_combined_split_artifact", lambda _: False)
  monkeypatch.setattr(runner_helpers, "TinygradSplitRunner", lambda: marker)

  assert runner_helpers.get_model_runner() is marker


def test_combined_split_runner_parses_single_policy_payload(monkeypatch):
  vision_raw = _phase_sample(np.random.default_rng(11))
  policy_raw = _phase_sample(np.random.default_rng(17))
  vision_blob, vision_slices = _slice_pack(vision_raw)
  policy_blob, policy_slices = _slice_pack(policy_raw)

  runner = TinygradCombinedSplitRunner.__new__(TinygradCombinedSplitRunner)
  runner._vision_meta = {
    "input_shapes": {"img": (1, 12, 128, 256), "big_img": (1, 12, 128, 256)},
    "output_slices": vision_slices,
  }
  runner._meta_by_role = {
    "vision": runner._vision_meta,
    "policy": {
      "input_shapes": {
        "features_buffer": (1, 25, 512),
        "desire_pulse": (1, 25, 8),
        "traffic_convention": (1, 2),
        "action_t": (1, 2),
      },
      "output_slices": policy_slices,
    },
  }
  runner._policy_roles = ["policy"]
  runner._desired_key = "desire_pulse"
  runner._road_key = "img"
  runner._wide_key = "big_img"
  runner._extra_policy_keys = []
  runner._queue_tensors = {
    "img_q": object(),
    "big_img_q": object(),
    "feat_q": object(),
    "desire_q": object(),
    "tfm": object(),
    "big_tfm": object(),
    "desire": object(),
    "traffic_convention": object(),
    "action_t": object(),
  }
  runner._numpy_state = {
    "tfm": np.zeros((3, 3), dtype=np.float32),
    "big_tfm": np.zeros((3, 3), dtype=np.float32),
    "desire": np.zeros(8, dtype=np.float32),
    "traffic_convention": np.zeros((1, 2), dtype=np.float32),
    "action_t": np.zeros((1, 2), dtype=np.float32),
  }
  runner._camera_shape = (1928, 1208)
  runner._camera_programs = {
    (1928, 1208): {"stage_inputs": lambda **kwargs: ("road", "wide")},
  }
  runner._execute_bundle = lambda **kwargs: (_FakeTensor(vision_blob), _FakeTensor(policy_blob))
  runner._parser = PhaseParser()
  runner._last_desire = np.zeros(8, dtype=np.float32)
  runner._blob_cache = {}

  monkeypatch.setattr(TinygradCombinedSplitRunner, "_allocate_runtime_state", lambda self, w, h: None)
  monkeypatch.setattr(TinygradCombinedSplitRunner, "_frame_blob", lambda self, name, buf: object())

  outputs = runner.run_fused(
    {"img": _FakeVisionBuf(), "big_img": _FakeVisionBuf()},
    {"img": np.eye(3, dtype=np.float32), "big_img": np.eye(3, dtype=np.float32)},
    {
      "desire_pulse": np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
      "traffic_convention": np.zeros((1, 2), dtype=np.float32),
      "action_t": np.zeros((1, 2), dtype=np.float32),
    },
  )

  assert "pose" in outputs
  assert "plan" in outputs
  assert outputs["plan"].shape == (1, 33, 15)
  assert outputs["action"].shape == (1, 2)
