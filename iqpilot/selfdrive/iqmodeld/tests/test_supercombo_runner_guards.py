from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cereal import custom
from openpilot.iqpilot.selfdrive.iqmodeld.models import helpers as model_helpers
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad import supercombo_runner as supercombo_runner_mod
from openpilot.iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.supercombo_runner import (
  TinygradSupercomboRunner,
)


class _Captured:
  def __init__(self, expected_names):
    self.expected_names = expected_names


class _FakeJit:
  def __init__(self, expected_names):
    self.captured = _Captured(expected_names)


class _Boom:
  def __init__(self, err: Exception):
    self.err = err

  def __call__(self, *args, **kwargs):
    raise self.err


class _FakeParams:
  def __init__(self, active_bundle=None):
    self.store = {}
    if active_bundle is not None:
      self.store["ModelManager_ActiveBundle"] = active_bundle

  def get(self, key):
    return self.store.get(key)

  def put(self, key, value):
    self.store[key] = value

  def remove(self, key):
    self.store.pop(key, None)


def test_verify_artifact_file_deletes_stale_cached_pkl(tmp_path: Path):
  pkl_path = tmp_path / "driving_supercombo_guard.pkl"
  pkl_path.write_bytes(b"stale-pkl")

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = str(pkl_path)
  runner._expected_sha256 = hashlib.sha256(b"fresh-pkl").hexdigest()

  with pytest.raises(RuntimeError, match="SHA mismatch"):
    runner._verify_artifact_file()

  assert not pkl_path.exists()


def test_validate_jit_names_accepts_current_runtime_contract():
  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = "/tmp/does-not-matter.pkl"
  runner._expected_sha256 = ""
  runner._run_policy = _FakeJit(['warped', 'img_q', 'big_img_q', 'feat_q', 'desire_q', 'packed_npy_inputs'])
  runner._warp_jits = {
    (1344, 760): _FakeJit(['tfm', 'big_tfm', 'frame', 'big_frame']),
  }

  runner._validate_jit_names()


def test_validate_jit_names_raises_clear_error_for_contract_mismatch():
  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = "/tmp/does-not-matter.pkl"
  runner._expected_sha256 = ""
  runner._run_policy = _FakeJit(['img', 'big_img', 'feat_q', 'desire_q', 'desire', 'traffic_convention', 'action_t'])
  runner._warp_jits = {
    (1344, 760): _FakeJit(['img_q', 'big_img_q', 'tfm', 'big_tfm', 'frame', 'big_frame']),
  }

  with pytest.raises(RuntimeError, match="JIT argument mismatch"):
    runner._validate_jit_names()


def test_handle_runtime_jit_mismatch_deletes_stale_cached_pkl(tmp_path: Path):
  pkl_path = tmp_path / "driving_supercombo_guard.pkl"
  pkl_path.write_bytes(b"stale-pkl")

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = str(pkl_path)
  runner._expected_sha256 = hashlib.sha256(b"fresh-pkl").hexdigest()

  with pytest.raises(RuntimeError, match="runtime JIT mismatch with stale cached SHA"):
    runner._handle_runtime_jit_mismatch(RuntimeError("args mismatch in JIT: stale bundle"))

  assert not pkl_path.exists()


def test_handle_runtime_jit_mismatch_raises_clear_error_without_sha_mismatch(tmp_path: Path):
  pkl_path = tmp_path / "driving_supercombo_guard.pkl"
  pkl_path.write_bytes(b"fresh-pkl")

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = str(pkl_path)
  runner._expected_sha256 = hashlib.sha256(b"fresh-pkl").hexdigest()

  with pytest.raises(RuntimeError, match="runtime JIT mismatch"):
    runner._handle_runtime_jit_mismatch(RuntimeError("args mismatch in JIT: wrong contract"))


def test_schedule_active_bundle_redownload_sets_download_index(monkeypatch: pytest.MonkeyPatch):
  params = _FakeParams({"index": 81})
  monkeypatch.setattr(supercombo_runner_mod, "Params", lambda: params)

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  msg = runner._schedule_active_bundle_redownload()

  assert params.get("ModelManager_DownloadIndex") == "81"
  assert msg == "; scheduled automatic re-download of the active model"


def test_no_active_bundle_seeds_default_tinygrad(monkeypatch: pytest.MonkeyPatch):
  monkeypatch.setattr(model_helpers, "ensure_default_model_files", lambda *a, **k: None)
  params = _FakeParams()

  runner = model_helpers.get_active_model_runner(params)

  assert runner == custom.IQModelManager.Runner.tinygrad
  active = params.get("ModelManager_ActiveBundle")
  assert active is not None and active.get("ref") == "default"


def test_select_default_model_clears_custom_download_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
  pending_restore = tmp_path / "pending_model_restore"
  pending_restore.write_text("Pop")
  monkeypatch.setattr(model_helpers, "_PENDING_MODEL_RESTORE_FILE", str(pending_restore))
  monkeypatch.setattr(model_helpers, "ensure_default_model_files", lambda *a, **k: None)

  params = _FakeParams({"index": 81, "ref": "pop"})
  params.put("ModelManager_DownloadIndex", "81")
  params.put("ModelRunnerTypeCache", int(custom.IQModelManager.Runner.tinygrad))

  model_helpers.select_default_model(params)

  assert params.get("ModelManager_DownloadIndex") is None
  active = params.get("ModelManager_ActiveBundle")
  assert active is not None and active.get("ref") == "default"
  assert int(params.get("ModelRunnerTypeCache")) == int(custom.IQModelManager.Runner.tinygrad)
  assert not pending_restore.exists()


def test_default_model_is_not_resolved_to_manifest_pop_bundle():
  pop_bundle = type("Bundle", (), {"internalName": "Pop (Default)", "displayName": "Pop (Default)"})()

  assert model_helpers.get_default_model_bundle([pop_bundle]) is None


def test_verify_artifact_file_schedules_redownload_for_stale_cached_pkl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
  params = _FakeParams({"index": 81})
  monkeypatch.setattr(supercombo_runner_mod, "Params", lambda: params)

  pkl_path = tmp_path / "driving_supercombo_guard.pkl"
  pkl_path.write_bytes(b"stale-pkl")

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = str(pkl_path)
  runner._expected_sha256 = hashlib.sha256(b"fresh-pkl").hexdigest()

  with pytest.raises(RuntimeError, match="scheduled automatic re-download"):
    runner._verify_artifact_file()

  assert params.get("ModelManager_DownloadIndex") == "81"
  assert not pkl_path.exists()


def test_run_fused_converts_raw_warp_jit_mismatch_to_runtime_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
  pkl_path = tmp_path / "driving_supercombo_guard.pkl"
  pkl_path.write_bytes(b"fresh-pkl")

  runner = TinygradSupercomboRunner.__new__(TinygradSupercomboRunner)
  runner._pkl_path = str(pkl_path)
  runner._expected_sha256 = hashlib.sha256(b"fresh-pkl").hexdigest()
  runner._frame_skip = 4
  runner._cam = (1344, 760)
  runner._queues = {
    "tfm": object(),
    "big_tfm": object(),
    "img_q": object(),
    "big_img_q": object(),
    "feat_q": object(),
    "desire_q": object(),
    "packed_npy_inputs": object(),
  }
  runner._npy = {
    "tfm": [0.0],
    "big_tfm": [0.0],
    "desire": [0.0],
    "prev_feat": [0.0],
  }
  runner._prev_desire = [0.0]
  runner._warp_jits = {
    (1344, 760): _Boom(RuntimeError("args mismatch in JIT: self.captured.expected_names=['big_frame'] != ['frame']")),
  }
  runner._run_policy = _FakeJit(["warped", "img_q", "big_img_q", "feat_q", "desire_q", "packed_npy_inputs"])
  runner._hidden_slice = slice(0, 1)
  runner._slices = {"out": slice(0, 1)}
  runner._parser = type("P", (), {"parse_vision_outputs": staticmethod(lambda sliced: sliced)})()
  runner._frame_tensor = lambda *args, **kwargs: object()

  monkeypatch.setattr(TinygradSupercomboRunner, "_ensure_queues", lambda self, cam_w, cam_h: None)

  class _Buf:
    width = 1344
    height = 760
    data = memoryview(b"\x00")

  with pytest.raises(RuntimeError, match="runtime JIT mismatch"):
    runner.run_fused(
      {"img": _Buf(), "big_img": _Buf()},
      {"img": [0.0], "big_img": [0.0]},
      {},
    )
