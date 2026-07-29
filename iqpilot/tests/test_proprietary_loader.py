"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from openpilot.iqpilot import _proprietary_loader as loader


def _write(path: Path, content: str = "") -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content)


def _write_bytes(path: Path, content: bytes) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(content)


def test_module_root_for_name_prefers_matching_bundle(tmp_path, monkeypatch):
  repo_root = tmp_path / "repo"
  model_root = repo_root / "artifacts" / "iqpilot_model_selector_private" / "python"
  hepha_root = repo_root / "artifacts" / "iqpilot_hephaestusd_private" / "python"

  _write(model_root / "iqpilot_private" / "__init__.py")
  _write(model_root / "iqpilot_private" / "models" / "__init__.py")
  _write(model_root / "iqpilot_private" / "models" / "manager.py", "VALUE = 'models'\n")

  _write(hepha_root / "iqpilot_private" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "hephaestus" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "hephaestus" / "hephaestusd.py", "VALUE = 'hepha'\n")

  monkeypatch.setattr(loader, "__file__", str(repo_root / "iqpilot" / "_proprietary_loader.py"))

  resolved = loader._module_root_for_name("iqpilot_private.konn3kt.hephaestus.hephaestusd")
  assert resolved == hepha_root


def test_load_private_module_uses_matching_bundle(tmp_path, monkeypatch):
  repo_root = tmp_path / "repo"
  model_root = repo_root / "artifacts" / "iqpilot_model_selector_private" / "python"
  hepha_root = repo_root / "artifacts" / "iqpilot_hephaestusd_private" / "python"

  _write(model_root / "iqpilot_private" / "__init__.py")
  _write(model_root / "iqpilot_private" / "models" / "__init__.py")
  _write(model_root / "iqpilot_private" / "models" / "manager.py", "VALUE = 'models'\n")

  _write(hepha_root / "iqpilot_private" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "hephaestus" / "__init__.py")
  _write(hepha_root / "iqpilot_private" / "konn3kt" / "hephaestus" / "hephaestusd.py", "VALUE = 'hepha'\n")

  monkeypatch.setattr(loader, "__file__", str(repo_root / "iqpilot" / "_proprietary_loader.py"))
  monkeypatch.setenv("IQPILOT_PROPRIETARY_ROOT", "")

  old_sys_path = list(sys.path)
  for key in [k for k in sys.modules if k.startswith("iqpilot_private") or k == "test_public_module"]:
    sys.modules.pop(key, None)

  try:
    sys.modules["test_public_module"] = type(sys)("test_public_module")
    private_module = loader.load_private_module("test_public_module", "iqpilot_private.konn3kt.hephaestus.hephaestusd")
    assert private_module.VALUE == "hepha"
    assert sys.modules["test_public_module"].VALUE == "hepha"
  finally:
    sys.path[:] = old_sys_path
    for key in [k for k in sys.modules if k.startswith("iqpilot_private") or k == "test_public_module"]:
      sys.modules.pop(key, None)


@pytest.fixture
def sig_keypair():
  pytest.importorskip("cryptography")
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

  private_key = Ed25519PrivateKey.generate()
  public_key = private_key.public_key()
  return (
    private_key.private_bytes_raw(),
    public_key.public_bytes_raw(),
  )


def _sign_file(private_key_bytes: bytes, file_path: Path) -> bytes:
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

  private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
  digest = hashlib.sha256(file_path.read_bytes()).digest()
  return private_key.sign(digest)


def test_signature_valid_passes(tmp_path, monkeypatch, sig_keypair):
  priv, pub = sig_keypair
  monkeypatch.setattr(loader, "_IQPILOT_PUBLIC_KEY", pub)
  monkeypatch.setattr(loader, "_verified_roots", set())
  monkeypatch.setenv("IQPILOT_SKIP_SIGNATURE_VERIFY", "")

  bundle_root = tmp_path / "bundle"
  python_root = bundle_root / "python"
  python_root.mkdir(parents=True)
  (python_root / "iqpilot_private").mkdir()

  so_path = python_root / "dummy.so"
  _write_bytes(so_path, b"VALID SO CONTENT")

  sig = _sign_file(priv, so_path)
  manifest = {
    "python/dummy.so": {"sha256": hashlib.sha256(so_path.read_bytes()).hexdigest(), "size": so_path.stat().st_size, "mode": 0o644},
    "signatures": {"python/dummy.so": base64.b64encode(sig).decode("ascii")},
  }
  (bundle_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

  loader._verify_bundle_signatures(python_root)


def test_signature_tampered_raises(tmp_path, monkeypatch, sig_keypair):
  priv, pub = sig_keypair
  monkeypatch.setattr(loader, "_IQPILOT_PUBLIC_KEY", pub)
  monkeypatch.setattr(loader, "_verified_roots", set())
  monkeypatch.setenv("IQPILOT_SKIP_SIGNATURE_VERIFY", "")

  bundle_root = tmp_path / "bundle"
  python_root = bundle_root / "python"
  python_root.mkdir(parents=True)
  (python_root / "iqpilot_private").mkdir()

  so_path = python_root / "dummy.so"
  _write_bytes(so_path, b"VALID SO CONTENT")

  sig = _sign_file(priv, so_path)

  so_path.write_bytes(b"TAMPERED CONTENT")

  manifest = {
    "python/dummy.so": {"sha256": hashlib.sha256(b"VALID SO CONTENT").hexdigest(), "size": 16, "mode": 0o644},
    "signatures": {"python/dummy.so": base64.b64encode(sig).decode("ascii")},
  }
  (bundle_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

  with pytest.raises(loader.ProprietaryModuleIntegrityError):
    loader._verify_bundle_signatures(python_root)


def test_signature_skip_env_warns(tmp_path, monkeypatch, sig_keypair):
  priv, pub = sig_keypair
  monkeypatch.setattr(loader, "_IQPILOT_PUBLIC_KEY", pub)
  monkeypatch.setattr(loader, "_verified_roots", set())
  monkeypatch.setenv("IQPILOT_SKIP_SIGNATURE_VERIFY", "1")

  bundle_root = tmp_path / "bundle"
  python_root = bundle_root / "python"
  python_root.mkdir(parents=True)
  (python_root / "iqpilot_private").mkdir()

  so_path = python_root / "dummy.so"
  _write_bytes(so_path, b"ANY CONTENT")

  sig = _sign_file(priv, so_path)
  manifest = {
    "python/dummy.so": {"sha256": hashlib.sha256(so_path.read_bytes()).hexdigest(), "size": so_path.stat().st_size, "mode": 0o644},
    "signatures": {"python/dummy.so": base64.b64encode(sig).decode("ascii")},
  }
  (bundle_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

  import warnings

  with pytest.warns(RuntimeWarning, match="Skipping signature verification"):
    loader._verify_bundle_signatures(python_root)


def test_signature_no_manifest_backward_compat(tmp_path, monkeypatch):
  """Bundles built before signing support should load without error."""
  monkeypatch.setattr(loader, "_verified_roots", set())
  monkeypatch.setenv("IQPILOT_SKIP_SIGNATURE_VERIFY", "")

  bundle_root = tmp_path / "bundle"
  python_root = bundle_root / "python"
  python_root.mkdir(parents=True)
  (python_root / "iqpilot_private").mkdir()

  loader._verify_bundle_signatures(python_root)


def test_signature_manifest_without_signatures_backward_compat(tmp_path, monkeypatch):
  """Manifests without a 'signatures' key should load without error."""
  monkeypatch.setattr(loader, "_verified_roots", set())
  monkeypatch.setenv("IQPILOT_SKIP_SIGNATURE_VERIFY", "")

  bundle_root = tmp_path / "bundle"
  python_root = bundle_root / "python"
  python_root.mkdir(parents=True)
  (python_root / "iqpilot_private").mkdir()

  manifest = {
    "python/dummy.py": {"sha256": "abc", "size": 3, "mode": 0o644},
  }
  (bundle_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

  loader._verify_bundle_signatures(python_root)
