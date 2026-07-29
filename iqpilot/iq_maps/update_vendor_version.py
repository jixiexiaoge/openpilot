#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Maintainer utility: pin a new pfeiferj/mapd release tag and refresh the checked-in
binary hash. Not used at runtime.
"""
import argparse
import os
import re
import sys

from openpilot.common.basedir import BASEDIR
from openpilot.iqpilot.iq_maps import VENDOR_MAPD_PATH
from openpilot.iqpilot.iq_maps.vendor_mapd_installer import (
  VENDOR_RELEASE_TAG,
  sha256_of_file,
)

_RELEASE_SYMBOL = "VENDOR_RELEASE_TAG"
_INSTALLER_SRC = os.path.join(BASEDIR, "iqpilot", "iq_maps", "vendor_mapd_installer.py")
# public: the checked-in hash the version test compares the installed binary against
HASH_FILE = os.path.join(BASEDIR, "iqpilot", "iq_maps", "tests", "mapd_hash")
_HASH_FILE = HASH_FILE
_TAG_ASSIGN = re.compile(rf'^{_RELEASE_SYMBOL}\s*=\s*["\'][^"\']*["\']', re.MULTILINE)


def rewrite_pinned_tag(new_tag: str) -> bool:
  with open(_INSTALLER_SRC) as f:
    src = f.read()

  patched, count = _TAG_ASSIGN.subn(f'{_RELEASE_SYMBOL} = "{new_tag}"', src, count=1)
  if count != 1:
    print(f"could not locate the {_RELEASE_SYMBOL} assignment in {_INSTALLER_SRC}; nothing written")
    return False

  with open(_INSTALLER_SRC, "w") as f:
    f.write(patched)
  print(f"pinned {_RELEASE_SYMBOL} -> {new_tag}")
  return True


def refresh_hash_file() -> None:
  digest = sha256_of_file(VENDOR_MAPD_PATH)
  with open(_HASH_FILE, "w") as f:
    f.write(digest)
  print(f"wrote binary hash {digest} -> {_HASH_FILE}")


def main() -> int:
  parser = argparse.ArgumentParser(description="Pin a new mapd release tag and refresh its hash")
  parser.add_argument("--new_ver", type=str, help='e.g. --new_ver "v2.1.0"')
  args = parser.parse_args()

  if not args.new_ver:
    parser.print_help()
    print(f'\ncurrently pinned: {VENDOR_RELEASE_TAG} (unchanged)')
    return 0

  target = args.new_ver.strip()
  if target == VENDOR_RELEASE_TAG:
    reply = input(f"{target} is already the pinned tag — re-run anyway? (y/N): ").strip().lower()
    if reply != "y":
      print("aborted; nothing changed")
      return 0

  if not rewrite_pinned_tag(target):
    return 1
  refresh_hash_file()
  return 0


if __name__ == "__main__":
  sys.exit(main())
