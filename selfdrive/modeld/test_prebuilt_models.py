import hashlib
import json

from openpilot.selfdrive.modeld import prebuilt_models


def write_outputs(models_dir, check_path):
  outputs = {}
  for name, contents in {
    'dmonitoring_model_tinygrad.pkl': b'tinygrad',
    'dmonitoring_model_metadata.pkl': b'metadata',
  }.items():
    (models_dir / name).write_bytes(contents)
    outputs[name] = hashlib.sha256(contents).hexdigest()
  check_path.write_text(json.dumps({'dmonitoring_model': {'outputs': outputs}}))


def test_packaged_prebuilt_without_onnx(tmp_path, monkeypatch):
  models_dir = tmp_path / 'models'
  models_dir.mkdir()
  check_path = models_dir / 'prebuilt_check.json'
  write_outputs(models_dir, check_path)
  monkeypatch.setattr(prebuilt_models, 'MODELS_DIR', models_dir)
  monkeypatch.setattr(prebuilt_models, 'CHECK_PATH', check_path)

  assert prebuilt_models.packaged_prebuilt_matches('dmonitoring_model')
  assert not prebuilt_models.verify_prebuilt('dmonitoring_model', 'flags')


def test_packaged_prebuilt_rejects_corrupt_output(tmp_path, monkeypatch):
  models_dir = tmp_path / 'models'
  models_dir.mkdir()
  check_path = models_dir / 'prebuilt_check.json'
  write_outputs(models_dir, check_path)
  (models_dir / 'dmonitoring_model_tinygrad.pkl').write_bytes(b'corrupt')
  monkeypatch.setattr(prebuilt_models, 'MODELS_DIR', models_dir)
  monkeypatch.setattr(prebuilt_models, 'CHECK_PATH', check_path)

  assert not prebuilt_models.packaged_prebuilt_matches('dmonitoring_model')


def test_source_checkout_is_not_packaged_prebuilt(tmp_path, monkeypatch):
  models_dir = tmp_path / 'models'
  models_dir.mkdir()
  check_path = models_dir / 'prebuilt_check.json'
  write_outputs(models_dir, check_path)
  (models_dir / 'dmonitoring_model.onnx').write_bytes(b'onnx')
  monkeypatch.setattr(prebuilt_models, 'MODELS_DIR', models_dir)
  monkeypatch.setattr(prebuilt_models, 'CHECK_PATH', check_path)

  assert not prebuilt_models.packaged_prebuilt_matches('dmonitoring_model')
