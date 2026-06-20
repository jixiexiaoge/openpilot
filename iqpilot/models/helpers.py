#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.models.helpers")
except ProprietaryModuleMissing:
  try:
    from iqpilot.models_private_src.helpers import *
  except ImportError:
    pass

# Public fallback for default-bundle selection (non-proprietary). Older bundles
# don't export it; a newer bundle that does wins via the guard.
if "get_default_model_bundle" not in globals():
  _DEFAULT_MODEL_NAMES = ("Pop!", "Pop", "Pop (Default)")

  def _default_model_key(name):
    if not name:
      return ""
    return "".join(ch for ch in name.lower().replace("default", "") if ch.isalnum())

  def get_default_model_bundle(bundles):
    """Find the manifest bundle that represents the compiled default model."""
    default_keys = {_default_model_key(n) for n in _DEFAULT_MODEL_NAMES}
    for bundle in bundles:
      if getattr(bundle, "internalName", None) in _DEFAULT_MODEL_NAMES:
        return bundle
    for bundle in bundles:
      if _default_model_key(getattr(bundle, "internalName", None)) in default_keys:
        return bundle
    for bundle in bundles:
      if _default_model_key(getattr(bundle, "displayName", None)) in default_keys:
        return bundle
    return None
