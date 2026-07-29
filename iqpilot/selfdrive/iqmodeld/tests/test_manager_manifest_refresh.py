"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass, field

from openpilot.iqpilot.selfdrive.iqmodeld.models.manager import IQModelManager, _DOWNLOAD_INDEX_KEY


@dataclass
class _DownloadUri:
  sha256: str = ""
  uri: str = ""


@dataclass
class _Artifact:
  fileName: str = ""
  downloadUri: _DownloadUri = field(default_factory=_DownloadUri)


@dataclass
class _Model:
  artifact: _Artifact = field(default_factory=_Artifact)
  metadata: _Artifact | None = None


@dataclass
class _Bundle:
  index: int = 0
  ref: str = ""
  internalName: str = ""
  displayName: str = ""
  models: list = field(default_factory=list)


class _FakeParams:
  def __init__(self):
    self.store = {}

  def get(self, key):
    return self.store.get(key)

  def put(self, key, value):
    self.store[key] = value

  def remove(self, key):
    self.store.pop(key, None)


def _bundle(index, name, sha, filename="driving_vision_test_tinygrad.pkl"):
  return _Bundle(
    index=index,
    ref=f"ref-{name}",
    internalName=name,
    displayName=f"{name} display",
    models=[_Model(artifact=_Artifact(fileName=filename, downloadUri=_DownloadUri(sha256=sha)))],
  )


def _manager(active, available):
  mgr = IQModelManager.__new__(IQModelManager)
  mgr.params = _FakeParams()
  mgr.active_bundle = active
  mgr.available_models = available
  mgr._validated_active_key = None
  mgr._manifest_refresh_key = None
  return mgr


def test_stale_active_bundle_queues_redownload_at_current_index():
  active = _bundle(55, "WMIV12", "a" * 64)
  counterpart = _bundle(12, "WMIV12", "b" * 64)
  mgr = _manager(active, [counterpart])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) == 12
  assert mgr.active_bundle is active


def test_matching_shas_do_not_queue():
  active = _bundle(55, "WMIV12", "a" * 64)
  counterpart = _bundle(12, "WMIV12", "A" * 64)
  mgr = _manager(active, [counterpart])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) is None


def test_retired_bundle_is_left_alone():
  active = _bundle(55, "WMIV12", "a" * 64)
  mgr = _manager(active, [_bundle(12, "OtherModel", "b" * 64)])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) is None
  assert mgr.active_bundle is active


def test_default_bundle_is_never_refreshed():
  active = _bundle(0, "Default", "a" * 64)
  active.ref = "default"
  mgr = _manager(active, [_bundle(0, "Default", "b" * 64)])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) is None


def test_pending_download_blocks_refresh():
  active = _bundle(55, "WMIV12", "a" * 64)
  mgr = _manager(active, [_bundle(12, "WMIV12", "b" * 64)])
  mgr.params.put(_DOWNLOAD_INDEX_KEY, 3)

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) == 3


def test_empty_manifest_hash_never_triggers():
  active = _bundle(55, "WMIV12", "a" * 64)
  mgr = _manager(active, [_bundle(12, "WMIV12", "")])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) is None


def test_refresh_queued_once_per_run():
  active = _bundle(55, "WMIV12", "a" * 64)
  mgr = _manager(active, [_bundle(12, "WMIV12", "b" * 64)])

  mgr._queue_active_manifest_refresh()
  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) == 12

  mgr.params.remove(_DOWNLOAD_INDEX_KEY)
  mgr._queue_active_manifest_refresh()
  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) is None


def test_counterpart_matched_by_name_not_index():
  active = _bundle(55, "WMIV12", "a" * 64)
  imposter = _bundle(55, "OtherModel", "c" * 64)
  counterpart = _bundle(12, "WMIV12", "b" * 64)
  mgr = _manager(active, [imposter, counterpart])

  mgr._queue_active_manifest_refresh()

  assert mgr.params.get(_DOWNLOAD_INDEX_KEY) == 12
