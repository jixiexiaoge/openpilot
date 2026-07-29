#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

import pytest

from artifacts.runtime import apply_boot_branding as abb


COMMA_HOME = "/home/comma"

EXISTING_PASSWD = (
  "root:x:0:0:root:/root:/bin/bash\n"
  "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
  f"comma:x:1000:1000:comma:{COMMA_HOME}:/bin/bash\n"
  "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
)

EXISTING_SHADOW = (
  "root:*:19000:0:99999:7:::\n"
  "daemon:*:19000:0:99999:7:::\n"
  "comma:$6$abc$xyz:19000:0:99999:7:::\n"
  "nobody:!:19000:0:99999:7:::\n"
)

EXPECTED_PASSWD_LINE = f"iq:x:1000:1000:IQ.Pilot:{COMMA_HOME}:/bin/bash"


@pytest.fixture
def etc(tmp_path: Path) -> tuple[Path, Path]:
  passwd = tmp_path / "passwd"
  shadow = tmp_path / "shadow"
  passwd.write_text(EXISTING_PASSWD, encoding="utf-8")
  shadow.write_text(EXISTING_SHADOW, encoding="utf-8")
  return passwd, shadow


@pytest.fixture
def fake_remount():
  calls: list[str] = []

  def _remount(mode: str) -> None:
    calls.append(mode)

  _remount.calls = calls
  return _remount


def _frozen_now() -> float:
  return 1779494400.0


def test_fresh_install_adds_iq_user(etc, fake_remount):
  passwd, shadow = etc

  changed = abb.ensure_iq_user(
    passwd_path=passwd,
    shadow_path=shadow,
    remount=fake_remount,
    root_opts="ro,relatime",
    now=_frozen_now,
  )

  assert changed is True
  passwd_text = passwd.read_text(encoding="utf-8")
  shadow_text = shadow.read_text(encoding="utf-8")

  assert EXPECTED_PASSWD_LINE in passwd_text.splitlines()
  assert any(l.startswith("iq:!:") and l.endswith(":0:99999:7:::") for l in shadow_text.splitlines())

  for original_line in EXISTING_PASSWD.splitlines():
    assert original_line in passwd_text.splitlines()
  for original_line in EXISTING_SHADOW.splitlines():
    assert original_line in shadow_text.splitlines()

  assert fake_remount.calls == ["remount,rw", "remount,ro,relatime"]


def test_second_boot_is_noop(etc, fake_remount):
  passwd, shadow = etc

  abb.ensure_iq_user(passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now)
  passwd_after_first = passwd.read_text(encoding="utf-8")
  shadow_after_first = shadow.read_text(encoding="utf-8")
  fake_remount.calls.clear()

  changed = abb.ensure_iq_user(
    passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
  )

  assert changed is False
  assert passwd.read_text(encoding="utf-8") == passwd_after_first
  assert shadow.read_text(encoding="utf-8") == shadow_after_first
  assert fake_remount.calls == []  # no remount when nothing to do


def test_partial_state_self_heals(etc, fake_remount):
  passwd, shadow = etc
  passwd.write_text(EXISTING_PASSWD + EXPECTED_PASSWD_LINE + "\n", encoding="utf-8")
  # shadow lacks iq

  changed = abb.ensure_iq_user(
    passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
  )

  assert changed is True
  iq_passwd_lines = [l for l in passwd.read_text(encoding="utf-8").splitlines() if l.startswith("iq:")]
  iq_shadow_lines = [l for l in shadow.read_text(encoding="utf-8").splitlines() if l.startswith("iq:")]
  assert iq_passwd_lines == [EXPECTED_PASSWD_LINE]  # not duplicated
  assert len(iq_shadow_lines) == 1
  assert iq_shadow_lines[0].startswith("iq:!:")


def test_malformed_iq_passwd_line_replaced(etc, fake_remount):
  passwd, shadow = etc
  wrong = "iq:x:1000:1000:old:/root:/bin/sh"
  passwd.write_text(EXISTING_PASSWD + wrong + "\n", encoding="utf-8")

  changed = abb.ensure_iq_user(
    passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
  )

  assert changed is True
  iq_lines = [l for l in passwd.read_text(encoding="utf-8").splitlines() if l.startswith("iq:")]
  assert iq_lines == [EXPECTED_PASSWD_LINE]


def test_remount_ro_restored_on_write_failure(tmp_path, fake_remount):
  passwd = tmp_path / "ro_passwd"
  passwd.write_text(EXISTING_PASSWD, encoding="utf-8")
  passwd.chmod(0o444)  # force write to raise

  shadow = tmp_path / "shadow"
  shadow.write_text(EXISTING_SHADOW, encoding="utf-8")

  with pytest.raises(PermissionError):
    abb.ensure_iq_user(
      passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
    )

  assert fake_remount.calls == ["remount,rw", "remount,ro"]


def test_does_not_alter_existing_branding_flow(monkeypatch, etc, fake_remount, capsys):
  passwd, shadow = etc

  monkeypatch.setattr(abb, "PASSWD_PATH", passwd)
  monkeypatch.setattr(abb, "SHADOW_PATH", shadow)
  monkeypatch.setattr(abb, "remount_root", fake_remount)
  monkeypatch.setattr(abb, "get_root_mount_options", lambda: "ro,relatime")
  monkeypatch.setattr(abb.os, "geteuid", lambda: 0)
  monkeypatch.setattr(abb, "apply_branding", lambda: False)  # no assets → branding no-op
  monkeypatch.setattr("sys.argv", ["apply_boot_branding.py"])

  rc = abb.main()
  out = capsys.readouterr().out.strip().splitlines()

  assert rc == 0
  assert out[-1] == "changed"  # iq_changed flips combined result
  assert EXPECTED_PASSWD_LINE in passwd.read_text(encoding="utf-8").splitlines()


def test_iq_home_tracks_commas_actual_home(tmp_path, fake_remount):
  passwd = tmp_path / "passwd"
  shadow = tmp_path / "shadow"
  unusual_home = "/data/some/relocated/home/comma"
  passwd.write_text(
    "root:x:0:0:root:/root:/bin/bash\n"
    f"comma:x:1000:1000:comma:{unusual_home}:/bin/zsh\n",
    encoding="utf-8",
  )
  shadow.write_text("comma:$6$x$y:19000:0:99999:7:::\n", encoding="utf-8")

  changed = abb.ensure_iq_user(
    passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
  )

  assert changed is True
  iq_line = [l for l in passwd.read_text(encoding="utf-8").splitlines() if l.startswith("iq:")][0]
  # iq inherits comma's home, shell, UID, GID — not a hardcoded path
  assert iq_line == f"iq:x:1000:1000:IQ.Pilot:{unusual_home}:/bin/zsh"


def test_skips_when_comma_user_absent(tmp_path, fake_remount):
  passwd = tmp_path / "passwd"
  shadow = tmp_path / "shadow"
  passwd.write_text("root:x:0:0:root:/root:/bin/bash\n", encoding="utf-8")
  shadow.write_text("root:*:19000:0:99999:7:::\n", encoding="utf-8")

  changed = abb.ensure_iq_user(
    passwd_path=passwd, shadow_path=shadow, remount=fake_remount, root_opts="ro", now=_frozen_now,
  )

  assert changed is False
  assert "iq:" not in passwd.read_text(encoding="utf-8")
  assert "iq:" not in shadow.read_text(encoding="utf-8")
  assert fake_remount.calls == []


def test_ensure_iq_user_failure_is_swallowed_by_main(monkeypatch, capsys):
  def boom(*a, **kw):
    raise RuntimeError("simulated failure")

  monkeypatch.setattr(abb, "ensure_iq_user", boom)
  monkeypatch.setattr(abb.os, "geteuid", lambda: 0)
  monkeypatch.setattr(abb, "apply_branding", lambda: True)
  monkeypatch.setattr("sys.argv", ["apply_boot_branding.py"])

  rc = abb.main()
  out = capsys.readouterr().out

  assert rc == 0
  assert "ensure_iq_user failed: simulated failure" in out
  assert "changed" in out  # branding ran, so combined result is still "changed"
