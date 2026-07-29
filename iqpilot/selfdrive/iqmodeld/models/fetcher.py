#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Public entry point for the model-manifest fetcher: prefers the compiled private
bundle, falling back to the in-tree source. The default-runner fallback lives in
ManifestDecoder now, so no post-import patching is needed.
"""
from openpilot.iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.models.fetcher")
except ProprietaryModuleMissing:
  from iqpilot.models_private_src.fetcher import *  # noqa: F403
