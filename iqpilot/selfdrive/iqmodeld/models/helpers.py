#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import os
import shutil
from pathlib import Path

from cereal import custom
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module
from openpilot.system.hardware.hw import Paths

try:
  load_private_module(__name__, "iqpilot_private.models.helpers")
except ProprietaryModuleMissing:
  try:
    from iqpilot.models_private_src.helpers import *  # noqa: F403
  except ImportError:
    pass


ModelBundle = custom.IQModelManager.ModelBundle
Runner = custom.IQModelManager.Runner
_MODEL_ROOT = Path(Paths.model_root())
_ACTIVE_BUNDLE_KEY = "ModelManager_ActiveBundle"
_MODELS_CACHE_KEY = "ModelManager_ModelsCache"
_RUNNER_CACHE_KEY = "ModelRunnerTypeCache"
_DOWNLOAD_INDEX_KEY = "ModelManager_DownloadIndex"
_PENDING_MODEL_RESTORE_FILE = "/data/k3_pending_model_restore"
_STOCK_RUNNER = int(Runner.stock)
_TINYGRAD_RUNNER = int(Runner.tinygrad)
_SNPE_RUNNER = int(Runner.snpe)

_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "default_model"
_DEFAULT_BUNDLE_JSON = _DEFAULT_MODEL_DIR / "bundle.json"
_DEFAULT_BUNDLE_REF = "default"


def get_default_model_bundle(_bundles):
  """Legacy compatibility hook: stock default is preinstalled, not a manifest bundle."""
  return None


def _coerce_runner_value(value) -> int | None:
  raw = getattr(value, "raw", value)
  try:
    return int(raw)
  except (TypeError, ValueError):
    return None


def _bundle_models(bundle) -> list:
  models = getattr(bundle, "models", None)
  return list(models) if models is not None else []


def _bundle_needs_runtime_upgrade(bundle) -> bool:
  if bundle is None:
    return False

  if _coerce_runner_value(getattr(bundle, "runner", None)) == _SNPE_RUNNER:
    return True

  for model in _bundle_models(bundle):
    file_name = getattr(getattr(model, "artifact", None), "fileName", "") or ""
    if file_name.endswith(".thneed"):
      return True

  return False


def _load_cached_manifest_bundles(params: Params):
  cached = params.get(_MODELS_CACHE_KEY) or {}
  bundles = []
  for raw_bundle in cached.get("bundles", []):
    try:
      min_selector_version = int(raw_bundle.get("minimumSelectorVersion", raw_bundle.get("minimum_selector_version", 0)))
      compatibility_view = dict(raw_bundle)
      compatibility_view["minimumSelectorVersion"] = min_selector_version
      is_compatible = globals().get("is_bundle_version_compatible")
      if is_compatible is not None and not is_compatible(compatibility_view):
        continue

      if "short_name" in raw_bundle:
        from openpilot.iqpilot.selfdrive.iqmodeld.models.fetcher import ManifestDecoder
        bundles.append(ManifestDecoder._decode_bundle(raw_bundle))
        continue

      if "internalName" in raw_bundle:
        bundles.append(ModelBundle(**raw_bundle))
        continue

      bundle = ModelBundle()
      bundle.index = int(raw_bundle["index"])
      bundle.internalName = raw_bundle.get("short_name")
      bundle.displayName = raw_bundle.get("display_name")
      bundle.status = 0
      bundle.generation = int(raw_bundle["generation"])
      bundle.environment = raw_bundle["environment"]
      bundle.runner = raw_bundle.get("runner", Runner.tinygrad)
      bundle.is20hz = raw_bundle.get("is_20hz", False)
      bundle.minimumSelectorVersion = int(min_selector_version)
      bundle.ref = raw_bundle.get("ref")
      bundle.overrides = []
      for key, value in raw_bundle.get("overrides", {}).items():
        override = custom.IQModelManager.Override()
        override.key = key
        override.value = value
        bundle.overrides.append(override)

      bundle.models = []
      for raw_model in raw_bundle.get("models", []):
        model = custom.IQModelManager.Model()
        model.type = raw_model.get("type")
        for attr_name in ("artifact", "metadata"):
          raw_artifact = raw_model.get(attr_name)
          if not raw_artifact:
            continue
          artifact = custom.IQModelManager.Artifact()
          artifact.fileName = raw_artifact.get("file_name")
          download_uri = custom.IQModelManager.DownloadUri()
          download_uri.uri = raw_artifact.get("download_uri", {}).get("url")
          download_uri.sha256 = raw_artifact.get("download_uri", {}).get("sha256")
          artifact.downloadUri = download_uri
          setattr(model, attr_name, artifact)
        bundle.models.append(model)

      bundles.append(bundle)
    except Exception:
      continue
  return bundles


def _bundle_match_key(bundle) -> tuple[str | None, str | None, str | None]:
  return (
    getattr(bundle, "ref", None),
    getattr(bundle, "internalName", None),
    getattr(bundle, "displayName", None),
  )


def _find_runtime_upgrade(bundle, params: Params, available_bundles=None):
  if not _bundle_needs_runtime_upgrade(bundle):
    return bundle

  candidate_bundles = available_bundles if available_bundles is not None else _load_cached_manifest_bundles(params)
  ref, internal_name, display_name = _bundle_match_key(bundle)

  for candidate in candidate_bundles:
    if getattr(candidate, "ref", None) and getattr(candidate, "ref", None) == ref:
      return candidate

  for candidate in candidate_bundles:
    if getattr(candidate, "internalName", None) == internal_name:
      return candidate

  for candidate in candidate_bundles:
    if getattr(candidate, "displayName", None) == display_name:
      return candidate

  return None


def bundle_files_ready(bundle) -> bool:
  if bundle is None:
    return False

  for model in _bundle_models(bundle):
    artifact = getattr(model, "artifact", None)
    metadata = getattr(model, "metadata", None)
    for file_name in (getattr(metadata, "fileName", None), getattr(artifact, "fileName", None)):
      if file_name and not (_MODEL_ROOT / file_name).is_file():
        return False
  return True


def persist_active_bundle(params: Params, bundle) -> None:
  params.put(_ACTIVE_BUNDLE_KEY, bundle.to_dict())
  params.remove(_RUNNER_CACHE_KEY)


def _load_default_bundle_dict() -> dict:
  return json.loads(_DEFAULT_BUNDLE_JSON.read_text())


def _default_bundle_filenames(bundle_dict: dict) -> list[str]:
  names = []
  for model in bundle_dict.get("models", []):
    for artifact in (model.get("metadata"), model.get("artifact")):
      file_name = artifact.get("fileName", "") if isinstance(artifact, dict) else ""
      if file_name:
        names.append(file_name)
  return names


def is_default_bundle(bundle) -> bool:
  return bool(bundle is not None and getattr(bundle, "ref", None) == _DEFAULT_BUNDLE_REF)


def ensure_default_model_files(bundle_dict: dict = None) -> None:
  bundle_dict = bundle_dict if bundle_dict is not None else _load_default_bundle_dict()
  try:
    _MODEL_ROOT.mkdir(parents=True, exist_ok=True)
  except OSError as e:
    cloudlog.exception(f"default_model: cannot create model root: {e}")
    return
  for file_name in _default_bundle_filenames(bundle_dict):
    src = _DEFAULT_MODEL_DIR / file_name
    dst = _MODEL_ROOT / file_name
    if not src.is_file():
      cloudlog.error(f"default_model: shipped asset missing {src}")
      continue
    if dst.is_file() and dst.stat().st_size == src.stat().st_size:
      continue
    try:
      shutil.copy2(src, dst)
      cloudlog.warning(f"default_model: staged {file_name} into model root")
    except OSError as e:
      cloudlog.exception(f"default_model: failed staging {file_name}: {e}")


def select_default_model(params: Params = None) -> None:
  params = Params() if params is None else params
  bundle_dict = _load_default_bundle_dict()
  ensure_default_model_files(bundle_dict)
  params.remove(_DOWNLOAD_INDEX_KEY)
  params.put(_ACTIVE_BUNDLE_KEY, bundle_dict)
  params.remove(_RUNNER_CACHE_KEY)
  params.put(_RUNNER_CACHE_KEY, _TINYGRAD_RUNNER)
  try:
    if os.path.isfile(_PENDING_MODEL_RESTORE_FILE):
      os.remove(_PENDING_MODEL_RESTORE_FILE)
  except OSError:
    pass


def seed_default_bundle_if_unset(params: Params = None) -> None:
  params = Params() if params is None else params
  if params.get(_ACTIVE_BUNDLE_KEY) or params.get(_DOWNLOAD_INDEX_KEY) is not None:
    return
  try:
    select_default_model(params)
    cloudlog.warning("default_model: seeded Default (CD210) as active bundle")
  except Exception as e:
    cloudlog.exception(f"default_model: failed to seed default bundle: {e}")


def get_runtime_bundle_upgrade(bundle, params: Params = None, available_bundles=None):
  params = Params() if params is None else params
  return _find_runtime_upgrade(bundle, params, available_bundles)


def get_active_bundle(params: Params = None):
  params = Params() if params is None else params

  try:
    active_bundle = params.get(_ACTIVE_BUNDLE_KEY) or {}
    if not active_bundle:
      return None
    is_compatible = globals().get("is_bundle_version_compatible")
    if is_compatible is not None and not is_compatible(active_bundle):
      return None
    bundle = ModelBundle(**active_bundle)
  except Exception:
    return None

  replacement = _find_runtime_upgrade(bundle, params)
  if replacement is not None and replacement is not bundle and bundle_files_ready(replacement):
    persist_active_bundle(params, replacement)
    return replacement

  return bundle


def get_active_model_runner(params: Params = None, force_check=False):
  params = Params() if params is None else params

  active_bundle = get_active_bundle(params)
  if not active_bundle:
    seed_default_bundle_if_unset(params)
    active_bundle = get_active_bundle(params)
    if not active_bundle:
      if params.get(_RUNNER_CACHE_KEY) != str(_TINYGRAD_RUNNER):
        params.put(_RUNNER_CACHE_KEY, _TINYGRAD_RUNNER)
      return _TINYGRAD_RUNNER

  cached_runner_type = params.get(_RUNNER_CACHE_KEY)
  if cached_runner_type and not force_check and isinstance(cached_runner_type, str) and cached_runner_type.isdigit():
    return int(cached_runner_type)

  runner_type = _coerce_runner_value(active_bundle.runner)
  if runner_type == _SNPE_RUNNER:
    replacement = _find_runtime_upgrade(active_bundle, params)
    if replacement is not None and replacement is not active_bundle and bundle_files_ready(replacement):
      persist_active_bundle(params, replacement)
      runner_type = _coerce_runner_value(replacement.runner)
    else:
      if replacement is not None and getattr(replacement, "index", None) is not None and params.get(_DOWNLOAD_INDEX_KEY) is None:
        params.put(_DOWNLOAD_INDEX_KEY, int(replacement.index))
        cloudlog.warning(f"Queued tinygrad migration for retired bundle {getattr(active_bundle, 'internalName', '<unknown>')}")
      runner_type = _TINYGRAD_RUNNER

  if cached_runner_type != runner_type:
    params.put(_RUNNER_CACHE_KEY, int(runner_type))

  return runner_type
