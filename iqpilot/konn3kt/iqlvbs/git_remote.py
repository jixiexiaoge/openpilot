#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Public shim for the proprietary IQ.Lvbs git read-auth helper.

The token + git config logic live in the standalone, signed bundle
``iqpilot_private.updater.git_remote`` (artifact iqpilot_updater_private) -- a
dedicated bundle so the read-only PAT can be rotated by rebuilding only that tiny
bundle, never touching ALC. Never in the open tree.

The private module exports:
    configure(repo_dir: str) -> None
        Install the read-only token as an ephemeral http.<host>.extraHeader on
        repo_dir (the only auth method that survives the WAF's 403-to-anonymous).
"""
from openpilot.iqpilot._proprietary_loader import load_private_module

load_private_module(__name__, "iqpilot_private.updater.git_remote")
