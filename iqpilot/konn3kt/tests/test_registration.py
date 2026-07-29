from unittest.mock import patch

from openpilot.iqpilot.konn3kt import registration


def test_get_registration_identifiers_uses_serial_without_imei():
  imei_calls = {"count": 0}

  def fake_get_imei(slot: int) -> str | None:
    imei_calls["count"] += 1
    return None

  monotonic_values = iter([0.0, 0.0, 1.0, 2.0])
  with patch.object(registration.HARDWARE, "get_serial", return_value="lite123"), \
       patch.object(registration.HARDWARE, "get_imei", side_effect=fake_get_imei), \
       patch.object(registration.time, "monotonic", side_effect=lambda: next(monotonic_values)), \
       patch.object(registration.time, "sleep", return_value=None):
    serial, imei1, imei2 = registration.get_registration_identifiers(wait_timeout=1.5, show_spinner=False)

  assert serial == "lite123"
  assert imei1 == ""
  assert imei2 == ""
  assert imei_calls["count"] >= 2


def test_get_registration_identifiers_returns_first_available_imei():
  imeis = [None, "123456789012345"]
  monotonic_values = iter([0.0, 0.0, 0.5, 0.5])

  def fake_get_imei(slot: int) -> str | None:
    return imeis.pop(0) if slot == 0 else None

  with patch.object(registration.HARDWARE, "get_serial", return_value="lite123"), \
       patch.object(registration.HARDWARE, "get_imei", side_effect=fake_get_imei), \
       patch.object(registration.time, "monotonic", side_effect=lambda: next(monotonic_values)), \
       patch.object(registration.time, "sleep", return_value=None):
    serial, imei1, imei2 = registration.get_registration_identifiers(wait_timeout=2.0, show_spinner=False)

  assert serial == "lite123"
  assert imei1 == "123456789012345"
  assert imei2 == ""
