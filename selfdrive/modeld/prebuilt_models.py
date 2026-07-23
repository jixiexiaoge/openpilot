#!/usr/bin/env python3
import functools
import hashlib
import json
import sys
from pathlib import Path

MODELD_DIR = Path(__file__).resolve().parent
MODELS_DIR = MODELD_DIR / 'models'
BASEDIR = MODELD_DIR.parents[1]
TINYGRAD_DIR = BASEDIR / 'tinygrad_repo'
METADATA_SCRIPT = MODELD_DIR / 'get_model_metadata.py'

MODEL_NAMES = ['dmonitoring_model']


def _hash_file(h, path: Path) -> None:
  with open(path, 'rb') as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b''):
      h.update(chunk)


def _file_sha256(path: Path) -> str:
  h = hashlib.sha256()
  _hash_file(h, path)
  return h.hexdigest()


@functools.lru_cache(maxsize=1)
def _tinygrad_digest() -> str:
  h = hashlib.sha256()
  # mirror the SConscript glob: no hidden files/dirs (also excludes .git, which differs per clone), no pycache
  def _included(p: Path) -> bool:
    rel = p.relative_to(TINYGRAD_DIR).parts
    return p.is_file() and '__pycache__' not in rel and not any(part.startswith('.') for part in rel)
  files = sorted(p for p in TINYGRAD_DIR.rglob('*') if _included(p))
  for p in files:
    h.update(str(p.relative_to(BASEDIR)).encode())
    _hash_file(h, p)
  return h.hexdigest()


CHECK_PATH = MODELS_DIR / 'prebuilt_check.json'


def _load_checks() -> dict:
  try:
    data = json.loads(CHECK_PATH.read_text())
  except (json.JSONDecodeError, OSError):
    return {}
  return data if isinstance(data, dict) else {}


def _output_names(model_name: str) -> list[str]:
  return [f'{model_name}_tinygrad.pkl', f'{model_name}_metadata.pkl']


def compute_signature(model_name: str, flags: str) -> str:
  h = hashlib.sha256()
  h.update(flags.encode())
  h.update(_tinygrad_digest().encode())
  _hash_file(h, METADATA_SCRIPT)
  _hash_file(h, MODELS_DIR / f'{model_name}.onnx')
  return h.hexdigest()


def outputs_match(model_name: str) -> bool:
  """The committed artifacts on disk are exactly the ones the check file pins."""
  data = _load_checks().get(model_name, {})
  outputs = data.get('outputs', {})
  if set(outputs) != set(_output_names(model_name)):
    return False
  for fn, expected in outputs.items():
    p = MODELS_DIR / fn
    if not p.is_file() or _file_sha256(p) != expected:
      return False
  return True


def packaged_prebuilt_matches(model_name: str) -> bool:
  return not (MODELS_DIR / f'{model_name}.onnx').is_file() and outputs_match(model_name)


def verify_prebuilt(model_name: str, flags: str) -> bool:
  if not (MODELS_DIR / f'{model_name}.onnx').is_file():
    return False
  data = _load_checks().get(model_name, {})
  if data.get('signature') != compute_signature(model_name, flags):
    return False
  return outputs_match(model_name)


def write_check(model_name: str, flags: str) -> None:
  outputs = {}
  for fn in _output_names(model_name):
    p = MODELS_DIR / fn
    if not p.is_file():
      raise FileNotFoundError(f'missing build output: {p}')
    outputs[fn] = _file_sha256(p)
  checks = _load_checks()
  checks[model_name] = {'signature': compute_signature(model_name, flags), 'outputs': outputs}
  CHECK_PATH.write_text(json.dumps(checks, indent=2, sort_keys=True) + '\n')


def _larch64_flags() -> str:
  return "DEV=QCOM IMAGE=2 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1"


if __name__ == '__main__':
  mode = sys.argv[1] if len(sys.argv) > 1 else 'verify'
  flags = _larch64_flags()
  for name in MODEL_NAMES:
    if mode == 'write':
      write_check(name, flags)
      print(f'{name}: check written')
    else:
      print(f'{name}: {"OK" if verify_prebuilt(name, flags) else "STALE"}')
