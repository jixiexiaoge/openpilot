#!/usr/bin/env python3
"""
Small standalone check for the mici WiFi menu sort order.

Run with:
  uv run python selfdrive/ui/mici/layouts/settings/network/test_wifi_sort.py
"""

from openpilot.system.ui.lib.wifi_manager import Network, SecurityType, wifi_network_sort_key


def _network(ssid: str, strength: int, connected: bool = False) -> Network:
  return Network(ssid, strength, connected, SecurityType.WPA2, True)


def main() -> None:
  cafe = _network("cafe", 35)
  home = _network("home", 75)
  connected = _network("connected", 20, connected=True)
  missing_saved = _network("missing-saved", 90)
  zero_strength = _network("zero-strength", 0)

  entries = [
    (cafe, False),
    (missing_saved, True),
    (zero_strength, False),
    (connected, False),
    (home, False),
  ]

  ordered = [network.ssid for network, missing in sorted(entries, key=lambda entry: wifi_network_sort_key(*entry))]
  assert ordered == ["connected", "home", "cafe", "missing-saved", "zero-strength"], ordered


if __name__ == "__main__":
  main()
