"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Candidate-ladder selection checks for get_nn_model_path, driven by a synthetic
model directory so the assertions don't depend on which cars ship a model.
"""
import json
import os

import pytest

from iqdbc.car import structs
import openpilot.selfdrive.controls.lib.latcontrol_torque as locator


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
  """A fake model directory with known fingerprints + a substitute table."""
  models = tmp_path / "models"
  models.mkdir()
  for stem in ("HONDA_CIVIC", "HONDA_CIVIC 12345", "TOYOTA_RAV4_TSS2", "MOCK"):
    (models / f"{stem}.json").write_text("{}")

  sub = tmp_path / "substitute.toml"
  sub.write_text('"CHEVROLET_XX" = "TOYOTA_RAV4_TSS2"\n')

  monkeypatch.setattr(locator, "TORQUE_NN_MODEL_PATH", str(models))
  monkeypatch.setattr(locator, "TORQUE_NN_MODEL_SUBSTITUTE_PATH", str(sub))
  monkeypatch.setattr(locator, "MOCK_MODEL_PATH", str(models / "MOCK.json"))
  return models


def make_cp(fingerprint, eps_fw=b"", angle=False):
  cp = structs.CarParams()
  cp.carFingerprint = fingerprint
  if eps_fw:
    fw = structs.CarParams.CarFw()
    fw.ecu = "eps"
    fw.fwVersion = eps_fw
    cp.carFw = [fw]
  if angle:
    cp.steerControlType = structs.CarParams.SteerControlType.angle
  return cp


def test_exact_fingerprint_match(model_dir):
  path, name, exact = locator.get_nn_model_path(make_cp("TOYOTA_RAV4_TSS2"))
  assert name == "TOYOTA_RAV4_TSS2"
  assert exact is True


def test_fingerprint_plus_eps_fw_prefers_specific_file(model_dir):
  # eps fw steers selection toward the fw-specific file. Note the resolved match
  # is fuzzy, not exact: fwVersion is bytes and the candidate stringifies it as
  # b'12345', so it never scores a perfect 1.0 against the "... 12345" filename.
  path, name, exact = locator.get_nn_model_path(make_cp("HONDA_CIVIC", eps_fw=b"12345"))
  assert name == "HONDA_CIVIC 12345"
  assert exact is False


def test_fuzzy_match_flags_non_exact(model_dir):
  # close but not identical to a shipped fingerprint
  path, name, exact = locator.get_nn_model_path(make_cp("TOYOTA_RAV4_TSS2_XYZ"))
  assert name == "TOYOTA_RAV4_TSS2"
  assert exact is False


def test_substitute_fallback(model_dir):
  # unknown fingerprint that the substitute table redirects
  path, name, exact = locator.get_nn_model_path(make_cp("CHEVROLET_XX"))
  assert name == "TOYOTA_RAV4_TSS2"
  assert exact is False


def test_angle_steer_is_always_mock(model_dir):
  path, name, exact = locator.get_nn_model_path(make_cp("TOYOTA_RAV4_TSS2", angle=True))
  assert name == "MOCK"
  assert path == locator.MOCK_MODEL_PATH
  assert exact is False


def test_short_eps_fw_ignored(model_dir):
  # a 3-char-or-less fw string is not used to build the candidate
  path, name, _ = locator.get_nn_model_path(make_cp("HONDA_CIVIC", eps_fw=b"ab"))
  assert name == "HONDA_CIVIC"
