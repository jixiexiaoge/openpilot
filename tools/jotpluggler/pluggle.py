#!/usr/bin/env python3
"""Thin launcher for the jotpluggler C++ binary.

Builds it on first run via scons (with the `tools` uv extra so the
imgui / libusb prebuilt wheels are available), then execs it with the
caller's args.
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
BINARY = SCRIPT_DIR / "jotpluggler"


def _run(args: list[str]) -> int:
  env = os.environ.copy()
  env.setdefault("PYTHONPATH", str(REPO_ROOT))

  if not BINARY.exists():
    build_cmd = ["uv", "run", "--extra", "tools", "scons", "-j4", "tools/jotpluggler/"]
    build = subprocess.run(build_cmd, cwd=REPO_ROOT, env=env)
    if build.returncode != 0:
      return build.returncode

  return subprocess.call([str(BINARY), *args], cwd=REPO_ROOT, env=env)


if __name__ == "__main__":
  raise SystemExit(_run(sys.argv[1:]))
