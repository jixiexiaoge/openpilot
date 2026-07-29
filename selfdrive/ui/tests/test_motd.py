from types import SimpleNamespace

from openpilot.selfdrive.ui.lib import motd


def test_load_motds_uses_verified_module_and_dongle_override(monkeypatch):
  calls = []

  def import_verified_module(bundle, module):
    calls.append((bundle, module))
    return SimpleNamespace(messages_for_dongle=lambda dongle_id: ("  Staff fleet  ", "", 42))

  monkeypatch.setattr(
    "openpilot.system.proprietary_runtime._verified_import.import_verified_module",
    import_verified_module,
  )

  assert motd.load_motds("0123456789ABCDEF") == ["Staff fleet"]
  assert calls == [(motd._BUNDLE_NAME, motd._MODULE_NAME)]


def test_load_motds_falls_back_when_verified_import_is_unavailable(monkeypatch):
  def fail_import(*_args):
    raise ImportError("bundle unavailable")

  monkeypatch.setattr(
    "openpilot.system.proprietary_runtime._verified_import.import_verified_module",
    fail_import,
  )

  assert motd.load_motds("0123456789abcdef") == list(motd.FALLBACK_MOTDS)
