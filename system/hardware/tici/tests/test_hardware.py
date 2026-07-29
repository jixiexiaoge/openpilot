from unittest.mock import MagicMock

from openpilot.system.hardware.tici.hardware import (
  MM_MODEM_ACCESS_TECHNOLOGY_LTE,
  MM_MODEM_STATE,
  NMActiveConnectionState,
  Tici,
)
from cereal import log


def _make_connection(connection_type: str, state: int):
  connection = MagicMock()

  def get_side_effect(_iface, prop, **_kwargs):
    values = {
      "Type": connection_type,
      "State": state,
    }
    return values[prop]

  connection.Get.side_effect = get_side_effect
  return connection


def test_reboot_modem_falls_back_to_direct_at(monkeypatch):
  device = Tici()
  direct_runner = MagicMock()

  monkeypatch.setattr(device, "get_modem", MagicMock(side_effect=ModuleNotFoundError("dbus")))
  monkeypatch.setattr(device, "_run_direct_modem_command", direct_runner)

  device.reboot_modem()

  assert direct_runner.call_args_list == [
    (("AT+CFUN=0",), {}),
    (("AT+CFUN=1",), {}),
  ]


def test_get_network_type_ignores_non_activated_cellular(monkeypatch):
  device = Tici()
  primary = _make_connection("gsm", NMActiveConnectionState.ACTIVATING)
  bus = MagicMock()
  bus.get_object.return_value = primary
  nm = MagicMock()
  nm.Get.return_value = "/primary"

  monkeypatch.setattr(device, "bus", bus)
  monkeypatch.setattr(device, "nm", nm)

  assert device.get_network_type() == log.DeviceState.NetworkType.none


def test_get_network_type_requires_registered_modem(monkeypatch):
  device = Tici()
  primary = _make_connection("gsm", NMActiveConnectionState.ACTIVATED)
  cellular = _make_connection("gsm", NMActiveConnectionState.ACTIVATED)
  bus = MagicMock()
  bus.get_object.side_effect = [primary, cellular]
  nm = MagicMock()
  nm.Get.side_effect = ["/primary", ["/cellular"]]
  modem = MagicMock()

  def modem_get_side_effect(_iface, prop, **_kwargs):
    values = {
      "State": MM_MODEM_STATE.SEARCHING,
      "AccessTechnologies": MM_MODEM_ACCESS_TECHNOLOGY_LTE,
    }
    return values[prop]

  modem.Get.side_effect = modem_get_side_effect

  monkeypatch.setattr(device, "bus", bus)
  monkeypatch.setattr(device, "nm", nm)
  monkeypatch.setattr(device, "get_modem", MagicMock(return_value=modem))

  assert device.get_network_type() == log.DeviceState.NetworkType.none


def test_get_network_type_reports_lte_for_registered_modem(monkeypatch):
  device = Tici()
  primary = _make_connection("gsm", NMActiveConnectionState.ACTIVATED)
  cellular = _make_connection("gsm", NMActiveConnectionState.ACTIVATED)
  bus = MagicMock()
  bus.get_object.side_effect = [primary, cellular]
  nm = MagicMock()
  nm.Get.side_effect = ["/primary", ["/cellular"]]
  modem = MagicMock()

  def modem_get_side_effect(_iface, prop, **_kwargs):
    values = {
      "State": MM_MODEM_STATE.CONNECTED,
      "AccessTechnologies": MM_MODEM_ACCESS_TECHNOLOGY_LTE,
    }
    return values[prop]

  modem.Get.side_effect = modem_get_side_effect

  monkeypatch.setattr(device, "bus", bus)
  monkeypatch.setattr(device, "nm", nm)
  monkeypatch.setattr(device, "get_modem", MagicMock(return_value=modem))

  assert device.get_network_type() == log.DeviceState.NetworkType.cell4G
