#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Verify IQ Pilot proprietary bundle manifest")
  p.add_argument("bundle_root", help="Bundle directory containing manifest.json")
  return p.parse_args()


def sha256(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    while True:
      b = f.read(1024 * 1024)
      if not b:
        break
      h.update(b)
  return h.hexdigest()


def main() -> None:
  args = parse_args()
  root = Path(args.bundle_root).resolve()
  manifest_path = root / "manifest.json"
  if not manifest_path.exists():
    raise SystemExit(f"manifest not found: {manifest_path}")

  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  failures: list[str] = []

  for rel, meta in manifest.items():
    if rel == "signatures":
      continue
    f = root / rel
    if not f.exists():
      failures.append(f"missing: {rel}")
      continue

    got = sha256(f)
    exp = str(meta["sha256"])
    if got != exp:
      failures.append(f"sha256 mismatch: {rel}")

    got_size = f.stat().st_size
    exp_size = int(meta["size"])
    if got_size != exp_size:
      failures.append(f"size mismatch: {rel} ({got_size} != {exp_size})")

  if failures:
    print("FAILED")
    for x in failures:
      print(x)
    raise SystemExit(1)

  print("OK")


if __name__ == "__main__":
  main()
