"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from openpilot.system.hardware.hw import Paths


_MODEL_ROOT = Path(Paths.model_root())
_OVERRIDE_KEYS = (
  "combinedRuntimeArtifact",
  "combinedSplitArtifact",
  "iqCombinedArtifact",
)
_SPLIT_ROLE_PATTERN = re.compile(r"^driving_(vision|policy|off_policy|on_policy)_(.+)_tinygrad\.pkl$")


def _bundle_models(bundle) -> list:
  models = getattr(bundle, "models", None)
  return list(models) if models is not None else []


def _bundle_override_map(bundle) -> dict[str, str]:
  result: dict[str, str] = {}
  for override in getattr(bundle, "overrides", None) or []:
    key = getattr(override, "key", None)
    value = getattr(override, "value", None)
    if key and value:
      result[str(key)] = str(value)
  return result


def _artifact_name(model) -> str:
  return getattr(getattr(model, "artifact", None), "fileName", "") or ""


def _split_suffixes(bundle) -> list[str]:
  suffixes: list[str] = []
  for model in _bundle_models(bundle):
    match = _SPLIT_ROLE_PATTERN.match(_artifact_name(model))
    if match:
      suffixes.append(match.group(2))
  return suffixes


def _derived_candidates(bundle) -> list[str]:
  seen: set[str] = set()
  candidates: list[str] = []

  for suffix in _split_suffixes(bundle):
    for candidate in (
      f"driving_combined_{suffix}.pkl",
      f"iqmodeld_combined_{suffix}.pkl",
    ):
      if candidate not in seen:
        seen.add(candidate)
        candidates.append(candidate)

  ref = getattr(bundle, "ref", None)
  if ref:
    short_ref = str(ref)[:8]
    for candidate in (
      f"driving_combined_{short_ref}.pkl",
      f"iqmodeld_combined_{short_ref}.pkl",
    ):
      if candidate not in seen:
        seen.add(candidate)
        candidates.append(candidate)

  return candidates


def combined_split_artifact_candidates(bundle) -> list[Path]:
  explicit_env = os.getenv("IQMODEL_COMBINED_PKL")
  if explicit_env:
    explicit_path = Path(explicit_env)
    return [explicit_path if explicit_path.is_absolute() else _MODEL_ROOT / explicit_path]

  overrides = _bundle_override_map(bundle)
  explicit_names = [overrides[key] for key in _OVERRIDE_KEYS if key in overrides]
  if explicit_names:
    return [_MODEL_ROOT / name for name in explicit_names]

  return [_MODEL_ROOT / name for name in _derived_candidates(bundle)]


def resolve_combined_split_artifact(bundle) -> Path | None:
  for candidate in combined_split_artifact_candidates(bundle):
    if candidate.is_file():
      return candidate
  return None


def has_combined_split_artifact(bundle) -> bool:
  return resolve_combined_split_artifact(bundle) is not None
