from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

import openpilot.iqpilot.selfdrive.iqmodeld.models.helpers as bundle_helpers
import openpilot.iqpilot.selfdrive.iqmodeld.models.runners.model_runner as runner_helpers
import openpilot.iqpilot.selfdrive.iqmodeld.daemon as iqmodeld_daemon


@dataclass
class StubOverride:
  key: str
  value: str


class StubBundle:
  def __init__(self, generation: int = 10):
    self.overrides = [StubOverride("lat", ".1"), StubOverride("long", ".3")]
    self.generation = generation


class StubRunner:
  def __init__(self, input_shapes: dict[str, tuple[int, ...]]) -> None:
    self.input_shapes = input_shapes
    self.constants = SimpleNamespace(
      FULL_HISTORY_BUFFER_LEN=100,
      FEATURE_LEN=512,
      DESIRE_LEN=8,
      PREV_DESIRED_CURV_LEN=1,
      INPUT_HISTORY_BUFFER_LEN=25,
      TEMPORAL_SKIP=4,
    )
    self.vision_input_names: list[str] = []
    self.is_20hz = input_shapes.get(next(iter(input_shapes)), (1, 0, 0))[1] == 25

  def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
    return None

  def run_model(self):
    return {
      "hidden_state": np.zeros((1, self.constants.FEATURE_LEN), dtype=np.float32),
      "desired_curvature": np.zeros((1, 1), dtype=np.float32),
    }


def _install_runtime(monkeypatch: pytest.MonkeyPatch, shapes: dict[str, tuple[int, ...]], generation: int = 10):
  bundle = StubBundle(generation=generation)
  runner = StubRunner(shapes)
  monkeypatch.setattr(bundle_helpers, "get_active_bundle", lambda params=None: bundle, raising=False)
  monkeypatch.setattr(runner_helpers, "get_model_runner", lambda: runner, raising=False)
  monkeypatch.setattr(iqmodeld_daemon, "get_active_bundle", lambda params=None: bundle, raising=False)
  monkeypatch.setattr(iqmodeld_daemon, "get_model_runner", lambda: runner, raising=False)
  return iqmodeld_daemon.NeuralEngineState(None), runner


def _expected_selector_indices(shape: tuple[int, ...], mode: str) -> np.ndarray | None:
  if mode == "split":
    full = 100
    return np.arange(full)[-1 - (4 * (25 - 1))::4]
  if mode == "20hz":
    step = int(-100 / shape[1])
    return np.arange(step, step * (shape[1] + 1), step)[::-1]
  if mode == "dense":
    return np.arange(shape[1])
  return None


@pytest.mark.parametrize(
  ("shapes", "mode"),
  [
    ({"desire": (1, 100, 8), "features_buffer": (1, 99, 512), "prev_desired_curv": (1, 100, 1)}, "dense"),
    ({"desire": (1, 25, 8), "features_buffer": (1, 24, 512)}, "20hz"),
    ({"desire_pulse": (1, 25, 8), "features_buffer": (1, 25, 512)}, "split"),
  ],
)
def test_replay_ledger_layout_matches_expected_history(monkeypatch: pytest.MonkeyPatch,
                                                       shapes: dict[str, tuple[int, ...]],
                                                       mode: str):
  state, _runner = _install_runtime(monkeypatch, shapes)

  for tensor_name, tensor_shape in shapes.items():
    history = state.temporal_buffers.get(tensor_name)
    selector = state.temporal_idxs_map.get(tensor_name)
    if history is None:
      continue

    if mode == "dense":
      expected_shape = (1, tensor_shape[1], tensor_shape[2])
    else:
      expected_shape = (1, 100, tensor_shape[2])

    assert history.shape == expected_shape
    expected_selector = _expected_selector_indices(tensor_shape, mode)
    if expected_selector is None:
      assert selector is None or selector.size == 0
    else:
      assert np.array_equal(selector, expected_selector)


def test_replay_ledger_rising_edge_and_hidden_state_updates(monkeypatch: pytest.MonkeyPatch):
  state, runner = _install_runtime(monkeypatch, {
    "desire": (1, 100, 8),
    "features_buffer": (1, 99, 512),
    "prev_desired_curv": (1, 100, 1),
  })

  pulse = np.zeros(8, dtype=np.float32)
  pulse[3] = 1.0
  state.run({}, {}, {"desire": pulse})
  first_export = state.numpy_inputs["desire"].copy()
  assert np.count_nonzero(first_export) == 1

  state.run({}, {}, {"desire": pulse})
  second_export = state.numpy_inputs["desire"].copy()
  assert np.count_nonzero(second_export) == 1
  assert second_export[0, -1, 3] == 0.0

  hidden_value = np.arange(runner.constants.FEATURE_LEN, dtype=np.float32)

  def hidden_state_run():
    return {
      "hidden_state": hidden_value.reshape(1, -1),
      "desired_curvature": np.array([[0.25]], dtype=np.float32),
    }

  state.model_runner.run_model = hidden_state_run
  state.run({}, {}, {"desire": np.zeros(8, dtype=np.float32)})

  np.testing.assert_allclose(state.numpy_inputs["features_buffer"][0, -1], hidden_value, rtol=0, atol=0)
  assert state.numpy_inputs["prev_desired_curv"][0, -1, 0] == pytest.approx(0.25)


def test_replay_ledger_zeroes_feedback_for_mlsim_generation(monkeypatch: pytest.MonkeyPatch):
  state, _runner = _install_runtime(monkeypatch, {
    "desire": (1, 100, 8),
    "features_buffer": (1, 99, 512),
    "prev_desired_curv": (1, 100, 1),
  }, generation=11)

  def ml_run():
    return {
      "hidden_state": np.zeros((1, 512), dtype=np.float32),
      "desired_curvature": np.array([[1.5]], dtype=np.float32),
    }

  state.model_runner.run_model = ml_run
  state.run({}, {}, {"desire": np.zeros(8, dtype=np.float32)})
  assert np.count_nonzero(state.numpy_inputs["prev_desired_curv"]) == 0
