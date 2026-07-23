#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(text: str, code: str) -> str:
  return f"\033[{code}m{text}\033[0m" if _COLOR else text


ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / "artifacts" / "runtime" / "boot_branding"
BG_ASSET = ASSET_DIR / "bg.jpg"
SPLASH_BMP_ASSET = ASSET_DIR / "splash_embedded.bmp"

BG_TARGET = Path("/usr/comma/bg.jpg")
SPLASH_TARGET = Path("/dev/block/bootdevice/by-name/splash")
SPLASH_BMP_OFFSET = 16384

PASSWD_PATH = Path("/etc/passwd")
SHADOW_PATH = Path("/etc/shadow")
IQ_USER = "iq"
IQ_GECOS = "IQ.Pilot"
SOURCE_USER = "comma"

STATE_DIR = Path("/data/iqpilot_boot_branding")
BACKUP_DIR = STATE_DIR / "backups"
META_PATH = BACKUP_DIR / "metadata.json"
BG_BACKUP = BACKUP_DIR / "bg.jpg.orig"
SPLASH_BACKUP = BACKUP_DIR / "splash.partition.orig.img"


def sha256_bytes(data: bytes) -> str:
  return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      h.update(chunk)
  return h.hexdigest()


def run(cmd: list[str], capture_output: bool = False) -> str:
  res = subprocess.run(cmd, check=True, text=True, capture_output=capture_output)
  return res.stdout.strip() if capture_output else ""


def get_root_mount_options() -> str:
  return run(["findmnt", "-no", "OPTIONS", "/"], capture_output=True)


def remount_root(mode: str) -> None:
  run(["mount", "-o", mode, "/"])


def splash_size() -> int:
  return int(run(["blockdev", "--getsize64", str(SPLASH_TARGET)], capture_output=True))


def read_splash_bytes(offset: int, size: int) -> bytes:
  with SPLASH_TARGET.open("rb") as f:
    f.seek(offset)
    return f.read(size)


def write_splash_bytes(offset: int, data: bytes) -> None:
  with SPLASH_TARGET.open("r+b", buffering=0) as f:
    f.seek(offset)
    f.write(data)
    f.flush()
    os.fsync(f.fileno())


def backup_if_missing() -> None:
  BACKUP_DIR.mkdir(parents=True, exist_ok=True)

  if not BG_BACKUP.exists():
    shutil.copy2(BG_TARGET, BG_BACKUP)

  if not SPLASH_BACKUP.exists():
    with SPLASH_TARGET.open("rb") as src, SPLASH_BACKUP.open("wb") as dst:
      remaining = splash_size()
      while remaining > 0:
        chunk = src.read(min(1024 * 1024, remaining))
        if not chunk:
          break
        dst.write(chunk)
        remaining -= len(chunk)

  if not META_PATH.exists():
    splash_backup_hash = sha256_path(SPLASH_BACKUP)
    meta = {
      "bg_backup_sha256": sha256_path(BG_BACKUP),
      "splash_backup_sha256": splash_backup_hash,
      "bg_asset_sha256": sha256_path(BG_ASSET) if BG_ASSET.exists() else None,
      "splash_asset_sha256": sha256_path(SPLASH_BMP_ASSET) if SPLASH_BMP_ASSET.exists() else None,
      "splash_bmp_offset": SPLASH_BMP_OFFSET,
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _line_for_user(text: str, user: str) -> str | None:
  prefix = f"{user}:"
  for line in text.splitlines():
    if line.startswith(prefix):
      return line
  return None


def _expected_passwd_line(source_passwd_line: str) -> str:
  """Build the iq passwd line by cloning comma's UID/GID/home/shell."""
  fields = source_passwd_line.split(":")
  if len(fields) < 7:
    raise ValueError(f"malformed passwd line for {SOURCE_USER!r}: {source_passwd_line!r}")
  _name, passwd_x, uid, gid, _gecos, home, shell = fields[:7]
  return f"{IQ_USER}:{passwd_x}:{uid}:{gid}:{IQ_GECOS}:{home}:{shell}"


def _expected_shadow_line(days_since_epoch: int) -> str:
  return f"{IQ_USER}:!:{days_since_epoch}:0:99999:7:::"


def _replace_or_append(text: str, user: str, new_line: str) -> str:
  prefix = f"{user}:"
  out: list[str] = []
  replaced = False
  for line in text.splitlines():
    if line.startswith(prefix):
      if not replaced:
        out.append(new_line)
        replaced = True
      continue
    out.append(line)
  if not replaced:
    out.append(new_line)
  return "\n".join(out) + "\n"


def ensure_iq_user(
  passwd_path: Path | None = None,
  shadow_path: Path | None = None,
  remount: Callable[[str], None] | None = None,
  root_opts: str | None = None,
  now: Callable[[], float] | None = None,
) -> bool:
  """Ensure an `iq` user exists as a UID-1000 alias of `comma`.

  Idempotent: returns False when /etc/passwd and /etc/shadow already have a
  correctly-shaped `iq` entry, True when either file was modified.
  """
  passwd_path = passwd_path if passwd_path is not None else PASSWD_PATH
  shadow_path = shadow_path if shadow_path is not None else SHADOW_PATH
  remount = remount if remount is not None else remount_root
  now = now if now is not None else time.time

  passwd_text = passwd_path.read_text(encoding="utf-8") if passwd_path.exists() else ""
  shadow_text = shadow_path.read_text(encoding="utf-8") if shadow_path.exists() else ""

  source_line = _line_for_user(passwd_text, SOURCE_USER)
  if source_line is None:
    # Without a comma user to clone from we'd create a broken iq entry; bail.
    return False

  expected_passwd = _expected_passwd_line(source_line)
  passwd_line = _line_for_user(passwd_text, IQ_USER)
  shadow_line = _line_for_user(shadow_text, IQ_USER)

  passwd_ok = passwd_line == expected_passwd
  shadow_ok = shadow_line is not None and shadow_line.startswith(f"{IQ_USER}:!:")
  if passwd_ok and shadow_ok:
    return False

  days = int(now() // 86400)
  new_passwd = _replace_or_append(passwd_text, IQ_USER, expected_passwd)
  new_shadow = _replace_or_append(shadow_text, IQ_USER, _expected_shadow_line(days))

  opts = root_opts if root_opts is not None else get_root_mount_options()
  remounted = False
  try:
    remount("remount,rw")
    remounted = True
    if not passwd_ok:
      passwd_path.write_text(new_passwd, encoding="utf-8")
    if not shadow_ok:
      shadow_path.write_text(new_shadow, encoding="utf-8")
  finally:
    if remounted:
      remount(f"remount,{opts}")

  return True


def apply_branding() -> bool:
  if not BG_ASSET.exists() or not SPLASH_BMP_ASSET.exists():
    return False

  backup_if_missing()

  bg_asset_bytes = BG_ASSET.read_bytes()
  splash_asset_bytes = SPLASH_BMP_ASSET.read_bytes()

  current_bg_hash = sha256_path(BG_TARGET)
  current_splash_hash = sha256_bytes(read_splash_bytes(SPLASH_BMP_OFFSET, len(splash_asset_bytes)))

  bg_asset_hash = sha256_bytes(bg_asset_bytes)
  splash_asset_hash = sha256_bytes(splash_asset_bytes)

  if current_bg_hash == bg_asset_hash and current_splash_hash == splash_asset_hash:
    return False

  root_opts = get_root_mount_options()
  remounted = False
  try:
    if current_bg_hash != bg_asset_hash:
      remount_root("remount,rw")
      remounted = True
      BG_TARGET.write_bytes(bg_asset_bytes)

    if current_splash_hash != splash_asset_hash:
      write_splash_bytes(SPLASH_BMP_OFFSET, splash_asset_bytes)
      run(["sync"])
  finally:
    if remounted:
      remount_root(f"remount,{root_opts}")

  return True


def restore_branding() -> bool:
  if not BG_BACKUP.exists() or not SPLASH_BACKUP.exists():
    return False

  root_opts = get_root_mount_options()
  remounted = False
  try:
    remount_root("remount,rw")
    remounted = True
    shutil.copy2(BG_BACKUP, BG_TARGET)

    with SPLASH_BACKUP.open("rb") as src, SPLASH_TARGET.open("r+b", buffering=0) as dst:
      while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
          break
        dst.write(chunk)
      dst.flush()
      os.fsync(dst.fileno())
    run(["sync"])
  finally:
    if remounted:
      remount_root(f"remount,{root_opts}")

  return True


def status() -> dict[str, object]:
  result: dict[str, object] = {
    "bg_asset_exists": BG_ASSET.exists(),
    "splash_asset_exists": SPLASH_BMP_ASSET.exists(),
    "bg_backup_exists": BG_BACKUP.exists(),
    "splash_backup_exists": SPLASH_BACKUP.exists(),
  }
  if BG_ASSET.exists() and BG_TARGET.exists():
    result["bg_asset_sha256"] = sha256_path(BG_ASSET)
    result["bg_current_sha256"] = sha256_path(BG_TARGET)
  if SPLASH_BMP_ASSET.exists() and SPLASH_TARGET.exists():
    splash_asset_bytes = SPLASH_BMP_ASSET.read_bytes()
    result["splash_asset_sha256"] = sha256_bytes(splash_asset_bytes)
    result["splash_current_sha256"] = sha256_bytes(read_splash_bytes(SPLASH_BMP_OFFSET, len(splash_asset_bytes)))
  return result


def main() -> int:
  if os.geteuid() != 0:
    raise SystemExit("apply_boot_branding.py must run as root")

  parser = argparse.ArgumentParser()
  group = parser.add_mutually_exclusive_group()
  group.add_argument("--restore", action="store_true")
  group.add_argument("--status", action="store_true")
  args = parser.parse_args()

  if args.status:
    print(json.dumps(status(), indent=2))
    return 0

  changed = restore_branding() if args.restore else apply_branding()

  try:
    iq_changed = ensure_iq_user()
  except Exception as e:  # noqa: BLE001
    iq_changed = False
    print(_paint(f"ensure_iq_user failed: {e}", "1;38;5;203"))

  if changed or iq_changed:
    print(_paint("changed", "38;5;114"))
  else:
    print(_paint("no-change", "2;38;5;246"))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
