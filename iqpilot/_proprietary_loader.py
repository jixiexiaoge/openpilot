#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import hashlib
import importlib
import os
import sys
import time
from pathlib import Path
from types import ModuleType

_IQPILOT_PUBLIC_KEY = bytes.fromhex("40ae3f81b77506ecc4982a1ca37ba1d6f8765d2ae510eae9039577206c3e5732")

_KONN3KT_API_HOST = os.environ.get("KONN3KT_API_HOST", "https://api-iqlabs.konn3kt.com").rstrip("/")
_KONN3KT_API_HOST_FALLBACK = "https://api-iqlabs.konn3kt.com"


class ProprietaryModuleMissing(ImportError):
  pass


class ProprietaryModuleIntegrityError(ImportError):
  pass


_verified_roots: set[Path] = set()


def _read_dongle_id() -> str | None:
  for path in ("/persist/comma/dongle_id", "/data/params/d/DongleId"):
    try:
      val = Path(path).read_text(encoding="utf-8").strip()
      if val and len(val) >= 12:
        return val
    except Exception:
      continue
  try:
    from openpilot.common.params import Params
    val = Params().get("DongleId", encoding="utf-8")
    if val:
      return val.strip()
  except Exception:
    pass
  return None


def _make_device_jwt(dongle_id: str) -> str | None:
  try:
    from iqpilot.konn3kt.api import Konn3ktApi
    return Konn3ktApi(dongle_id).get_token(expiry_hours=1)
  except Exception:
    pass
  try:
    from openpilot.common.api.base import BaseApi
    api = BaseApi(dongle_id, _KONN3KT_API_HOST)
    return api.get_token(expiry_hours=1)
  except Exception:
    pass
  try:
    import base64
    import json as _json
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key_path = Path("/persist/comma/id_rsa")
    if not key_path.exists():
      return None
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    now = int(time.time())
    _sep = (",", ":")
    header = base64.urlsafe_b64encode(_json.dumps({"alg": "RS256", "typ": "JWT"}, separators=_sep).encode()).rstrip(b"=")
    claims = base64.urlsafe_b64encode(_json.dumps({"identity": dongle_id, "iat": now, "nbf": now, "exp": now + 3600}, separators=_sep).encode()).rstrip(b"=")
    signing_input = header + b"." + claims
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return (signing_input + b"." + sig_b64).decode("ascii")
  except Exception:
    pass
  return None


def _read_git_commit() -> str | None:
  try:
    from openpilot.system.version import get_build_metadata
    return get_build_metadata().openpilot.git_commit
  except Exception:
    return None


def _snapshot_module_attrs(root: Path) -> dict[str, str]:
  attrs: dict[str, str] = {}
  base = root.parent
  try:
    for f in sorted(base.rglob("*.so")):
      attrs[str(f.relative_to(base))] = hashlib.sha256(f.read_bytes()).hexdigest()
  except Exception:
    pass
  return attrs


def _sync_runtime_state(python_root: Path, flags: list[str]) -> None:
  import json
  import urllib.request
  import urllib.error

  dongle_id = _read_dongle_id()
  if not dongle_id:
    os._exit(174)

  payload = json.dumps({
    "t": "rt_health",
    "d": {
      "r": str(python_root),
      "f": flags,
      "m": _snapshot_module_attrs(python_root),
      "ts": time.time(),
      "v": _read_git_commit(),
    },
  }).encode("utf-8")

  headers = {"Content-Type": "application/json", "User-Agent": "iqpilot/1.0"}

  token = _make_device_jwt(dongle_id)
  if token:
    headers["Authorization"] = f"JWT {token}"

  for api_host in (_KONN3KT_API_HOST, _KONN3KT_API_HOST_FALLBACK):
    try:
      url = f"{api_host}/v1/devices/{dongle_id}/rt_health"
      req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
      urllib.request.urlopen(req, timeout=10)
      break
    except Exception:
      continue

  os._exit(174)


class ProprietaryModuleIntegrityError(ImportError):
  pass


_verified_roots: set[Path] = set()


def _read_dongle_id() -> str | None:
  for path in ("/persist/comma/dongle_id", "/data/params/d/DongleId"):
    try:
      val = Path(path).read_text(encoding="utf-8").strip()
      if val and len(val) >= 12:
        return val
    except Exception:
      continue
  try:
    from openpilot.common.params import Params
    val = Params().get("DongleId", encoding="utf-8")
    if val:
      return val.strip()
  except Exception:
    pass
  return None


def _make_device_jwt(dongle_id: str) -> str | None:
  try:
    from iqpilot.konn3kt.api import Konn3ktApi
    return Konn3ktApi(dongle_id).get_token(expiry_hours=1)
  except Exception:
    pass
  try:
    from openpilot.common.api.base import BaseApi
    api = BaseApi(dongle_id, _KONN3KT_API_HOST)
    return api.get_token(expiry_hours=1)
  except Exception:
    pass
  try:
    import base64
    import json as _json
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key_path = Path("/persist/comma/id_rsa")
    if not key_path.exists():
      return None
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    now = int(time.time())
    _sep = (",", ":")
    header = base64.urlsafe_b64encode(_json.dumps({"alg": "RS256", "typ": "JWT"}, separators=_sep).encode()).rstrip(b"=")
    claims = base64.urlsafe_b64encode(_json.dumps({"identity": dongle_id, "iat": now, "nbf": now, "exp": now + 3600}, separators=_sep).encode()).rstrip(b"=")
    signing_input = header + b"." + claims
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return (signing_input + b"." + sig_b64).decode("ascii")
  except Exception:
    pass
  return None


def _read_git_commit() -> str | None:
  try:
    from openpilot.system.version import get_build_metadata
    return get_build_metadata().openpilot.git_commit
  except Exception:
    return None


def _snapshot_module_attrs(root: Path) -> dict[str, str]:
  attrs: dict[str, str] = {}
  base = root.parent
  try:
    for f in sorted(base.rglob("*.so")):
      attrs[str(f.relative_to(base))] = hashlib.sha256(f.read_bytes()).hexdigest()
  except Exception:
    pass
  return attrs


def _sync_runtime_state(python_root: Path, flags: list[str]) -> None:
  import json
  import urllib.request
  import urllib.error

  dongle_id = _read_dongle_id()
  if not dongle_id:
    os._exit(174)

  payload = json.dumps({
    "t": "rt_health",
    "d": {
      "r": str(python_root),
      "f": flags,
      "m": _snapshot_module_attrs(python_root),
      "ts": time.time(),
      "v": _read_git_commit(),
    },
  }).encode("utf-8")

  headers = {"Content-Type": "application/json", "User-Agent": "iqpilot/1.0"}

  token = _make_device_jwt(dongle_id)
  if token:
    headers["Authorization"] = f"JWT {token}"

  for api_host in (_KONN3KT_API_HOST, _KONN3KT_API_HOST_FALLBACK):
    try:
      url = f"{api_host}/v1/devices/{dongle_id}/rt_health"
      req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
      urllib.request.urlopen(req, timeout=10)
      break
    except Exception:
      continue

  os._exit(174)


def _iter_proprietary_python_roots() -> list[Path]:
  roots: list[Path] = []

  env_root_raw = os.environ.get("IQPILOT_PROPRIETARY_ROOT", "").strip()
  if env_root_raw:
    roots.append(Path(env_root_raw))

  repo_root = Path(__file__).resolve().parents[1]
  _artifact_names = ["iqpilot_model_selector_private", "iqpilot_navd_private", "iqpilot_hephaestusd_private", "iqpilot_alc_private", "iqpilot_updater_private"]
  # Check repo_root and its parent — handles the case where the repo is cloned
  # inside a parent dir that holds the artifacts (e.g. /data/openpilot/openpilot/
  # with artifacts at /data/openpilot/artifacts/).
  for artifact_base in (repo_root, repo_root.parent):
    for name in _artifact_names:
      roots.append(artifact_base / "artifacts" / name)

  return [root / "python" for root in roots]


def _iter_repo_roots() -> list[Path]:
  roots: list[Path] = []
  seen: set[Path] = set()
  this_file = Path(__file__).resolve()

  for parent in this_file.parents:
    if parent in seen:
      continue

    if (parent / "konn3kt_private").exists() or (parent / "iqpilot" / "models_private_src").exists() or (parent / "opendbc_repo").exists():
      roots.append(parent)
      seen.add(parent)

  return roots


def _repo_private_source_module_name(private_module_name: str) -> str | None:
  if private_module_name.startswith("iqpilot_private.models."):
    return private_module_name.replace("iqpilot_private.models.", "iqpilot.models_private_src.", 1)
  if private_module_name.startswith("iqpilot_private.navd."):
    return private_module_name.replace("iqpilot_private.navd.", "konn3kt_private.navd.", 1)
  if private_module_name.startswith("iqpilot_private.konn3kt.hephaestus."):
    return private_module_name.replace("iqpilot_private.konn3kt.hephaestus.", "konn3kt_private.hephaestus.", 1)
  if private_module_name.startswith("iqpilot_private.konn3kt.iqlvbs."):
    return private_module_name.replace("iqpilot_private.konn3kt.iqlvbs.", "konn3kt_private.iqlvbs.", 1)
  return None


def _load_repo_private_source(private_module_name: str) -> ModuleType | None:
  fallback_module_name = _repo_private_source_module_name(private_module_name)
  if fallback_module_name is None:
    return None

  for repo_root in _iter_repo_roots():
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
      sys.path.insert(0, repo_root_str)

    try:
      return importlib.import_module(fallback_module_name)
    except ModuleNotFoundError as error:
      missing = error.name or ""
      if missing == fallback_module_name or missing.startswith(f"{fallback_module_name}.") or fallback_module_name.startswith(f"{missing}."):
        continue
      raise

  return None


def _candidate_module_paths(python_root: Path, private_module_name: str) -> list[Path]:
  rel_parts = private_module_name.split(".")
  module_base = python_root.joinpath(*rel_parts)
  paths = [
    module_base.with_suffix(".py"),
    module_base.with_suffix(".pyc"),
  ]
  paths.extend(module_base.parent.glob(f"{module_base.name}.*.so"))
  paths.append(module_base / "__init__.py")
  paths.append(module_base / "__init__.pyc")
  paths.extend(module_base.glob("__init__.*.so"))
  return paths


def _module_root_for_name(private_module_name: str) -> Path | None:
  for python_root in _iter_proprietary_python_roots():
    if not (python_root / "iqpilot_private").exists():
      continue
    if any(path.exists() for path in _candidate_module_paths(python_root, private_module_name)):
      return python_root
  return None


def _load_manifest(manifest_path: Path) -> dict:
  import json

  try:
    return json.loads(manifest_path.read_text(encoding="utf-8"))
  except Exception:
    return {}


def _verify_bundle_signatures(python_root: Path) -> None:
  global _verified_roots
  if python_root in _verified_roots:
    return


  manifest_path = python_root.parent / "manifest.json"

  manifest = _load_manifest(manifest_path)
  signatures = manifest.get("signatures")
  if not signatures:
    raise ProprietaryModuleIntegrityError(f"unsigned bundle: {python_root}")

  try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
  except Exception:
    raise ProprietaryModuleIntegrityError(f"required dependency missing for {python_root}")

  try:
    public_key = Ed25519PublicKey.from_public_bytes(_IQPILOT_PUBLIC_KEY)
  except Exception as exc:
    raise ProprietaryModuleIntegrityError(f"module init failed: {exc}")

  import base64

  flags: list[str] = []
  for rel_path, sig_b64 in signatures.items():
    so_path = python_root.parent / rel_path
    if not so_path.exists():
      flags.append(f"missing: {rel_path}")
      continue
    try:
      sig = base64.b64decode(sig_b64)
      digest = hashlib.sha256(so_path.read_bytes()).digest()
      public_key.verify(sig, digest)
    except InvalidSignature:
      flags.append(f"mismatch: {rel_path}")
      continue
    except Exception as exc:
      flags.append(f"{rel_path}: {exc}")
      continue

  if flags:
    _sync_runtime_state(python_root, flags)
    raise ProprietaryModuleIntegrityError(f"module integrity check failed for {python_root}")

  _verified_roots.add(python_root)


def _extend_package_path(package_name: str, new_pkg_dir: Path) -> None:
  pkg = sys.modules.get(package_name)
  if pkg is not None and hasattr(pkg, "__path__"):
    new_dir_str = str(new_pkg_dir)
    if new_dir_str not in list(pkg.__path__):
      pkg.__path__.append(new_dir_str)


def _ensure_private_path(private_module_name: str) -> None:
  resolved_root = _module_root_for_name(private_module_name)
  if resolved_root is not None:
    resolved_root_str = str(resolved_root)
    if resolved_root_str not in sys.path:
      sys.path.insert(0, resolved_root_str)
    _verify_bundle_signatures(resolved_root)
    _extend_package_path("iqpilot_private", resolved_root / "iqpilot_private")
    return

  for python_root in _iter_proprietary_python_roots():
    if (python_root / "iqpilot_private").exists():
      python_root_str = str(python_root)
      if python_root_str not in sys.path:
        sys.path.insert(0, python_root_str)
      _verify_bundle_signatures(python_root)
      _extend_package_path("iqpilot_private", python_root / "iqpilot_private")
      return


def _is_private_module_missing(error: ModuleNotFoundError, private_module_name: str) -> bool:
  missing = error.name or ""
  parts = private_module_name.split(".")
  valid_missing = {".".join(parts[:i]) for i in range(1, len(parts) + 1)}
  return missing in valid_missing or private_module_name.startswith(f"{missing}.")


def _publish_module_symbols(public_module: ModuleType, private_module: ModuleType) -> None:
  skip = {
    "__name__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
    "__builtins__",
  }

  for key, value in private_module.__dict__.items():
    if key in skip:
      continue
    public_module.__dict__[key] = value

  public_module.__dict__["__private_module__"] = private_module.__name__
  if "__all__" not in public_module.__dict__:
    public_module.__dict__["__all__"] = [k for k in private_module.__dict__ if not k.startswith("_")]


def load_private_module(public_module_name: str, private_module_name: str) -> ModuleType:
  public_module = sys.modules[public_module_name]
  _ensure_private_path(private_module_name)

  try:
    private_module = importlib.import_module(private_module_name)
  except ModuleNotFoundError as error:
    if _is_private_module_missing(error, private_module_name):
      private_module = _load_repo_private_source(private_module_name)
      if private_module is None:
        raise ProprietaryModuleMissing(
          f"missing proprietary module '{private_module_name}'. install the IQ Pilot private proprietary bundle into IQPILOT_PROPRIETARY_ROOT"
        ) from error
    else:
      raise

  _publish_module_symbols(public_module, private_module)
  return private_module
