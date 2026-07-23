"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Unit checks for the NNFF model loader against the shipped model files.
"""
import json
import os

import numpy as np
import pytest

from openpilot.selfdrive.controls.lib.latcontrol_torque import NNTorqueModel
from openpilot.selfdrive.controls.lib.latcontrol_torque import TORQUE_NN_MODEL_PATH

MODEL_FILES = sorted(f for f in os.listdir(TORQUE_NN_MODEL_PATH) if f.endswith(".json"))
SAMPLE = [f for f in ("HYUNDAI_IONIQ_5.json", "TOYOTA_RAV4_TSS2_2022.json", "MOCK.json") if f in MODEL_FILES] \
         or MODEL_FILES[:3]


def _path(name):
  return os.path.join(TORQUE_NN_MODEL_PATH, name)


@pytest.mark.parametrize("name", MODEL_FILES, ids=[n[:-5] for n in MODEL_FILES])
def test_every_model_loads_and_is_finite(name):
  m = NNTorqueModel(_path(name))
  assert m.input_size >= 2
  assert m.output_size >= 1
  assert m.input_mean.shape == m.input_std.shape
  out = m.evaluate([0.0] * m.input_size)
  assert np.isfinite(out)
  assert isinstance(m.friction_override, (bool, np.bool_))


@pytest.mark.parametrize("name", SAMPLE, ids=[n[:-5] for n in SAMPLE])
class TestModelBehavior:
  def test_short_input_is_zero_padded(self, name):
    m = NNTorqueModel(_path(name))
    padded = m.evaluate([5.0, 1.0])
    explicit = m.evaluate([5.0, 1.0] + [0.0] * (m.input_size - 2))
    assert padded == explicit

  def test_too_short_input_raises(self, name):
    m = NNTorqueModel(_path(name))
    with pytest.raises(ValueError):
      m.evaluate([1.0])

  def test_zero_bias_matches_manual_bias_removal(self, name):
    m = NNTorqueModel(_path(name))
    mz = NNTorqueModel(_path(name), zero_bias=True)
    assert all(np.allclose(b, 0.0) for b in mz._biases)
    # weights and activations are unchanged
    assert len(mz._weights) == len(m._weights)

  def test_deterministic(self, name):
    m = NNTorqueModel(_path(name))
    vec = [float(v) for v in np.linspace(-1.5, 1.5, m.input_size)]
    assert m.evaluate(vec) == m.evaluate(list(vec))


def test_activation_registry_rejects_unknown(tmp_path):
  base = json.load(open(_path(SAMPLE[0])))
  base["layers"][-1]["activation"] = "not_a_real_activation"
  bad = tmp_path / "bad.json"
  bad.write_text(json.dumps(base))
  with pytest.raises(ValueError):
    NNTorqueModel(str(bad))


def test_sigmoid_identity_helpers():
  assert NNTorqueModel.identity(3.5) == 3.5
  assert 0.0 < float(NNTorqueModel.sigmoid(np.array([0.0]))[0]) < 1.0
  assert abs(float(NNTorqueModel.sigmoid(np.array([0.0]))[0]) - 0.5) < 1e-6
