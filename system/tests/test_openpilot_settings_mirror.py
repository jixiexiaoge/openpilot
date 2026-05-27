#!/usr/bin/env python3
"""
Drift detector for the dashy openpilot-settings mirror.

We expose upstream openpilot's TogglesLayout + DeveloperLayout settings via the
dashy web UI by mirroring them into dragonpilot/settings/openpilot.*.py. This
test fails loudly when upstream adds or removes a toggle key — preventing the
mirror from silently going stale on the next openpilot version bump.

If upstream renames a key, add/remove the corresponding entry in the mirror file.
If upstream adds a brand-new toggle, decide whether to mirror it (most should)
and add a new entry. If upstream removes one, remove it from the mirror.
"""
import unittest

from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from dragonpilot.settings import SETTINGS

# Upstream Developer toggles that ARE param-backed booleans (not buttons / SSH key widget).
# Update when upstream's DeveloperLayout changes.
EXPECTED_DEVELOPER_KEYS = {
  "AdbEnabled", "SshEnabled", "JoystickDebugMode", "LongitudinalManeuverMode",
  "AlphaLongitudinalEnabled", "ShowDebugInfo",
}


def _mirror_keys(section_title: str) -> set[str]:
  for s in SETTINGS:
    if s["title"] == section_title:
      return {it["key"] for it in s["settings"]}
  return set()


class TestOpenpilotMirror(unittest.TestCase):
  def test_toggles_mirror_in_sync(self):
    # TogglesLayout() reads params at __init__, so we instantiate it once.
    upstream = set(TogglesLayout()._toggle_defs.keys())
    # Plus LongitudinalPersonality (multi-button widget, exposed alongside toggles in upstream UI).
    upstream.add("LongitudinalPersonality")
    mirror = _mirror_keys("Openpilot")
    missing = upstream - mirror
    extra = mirror - upstream
    self.assertFalse(missing or extra,
                     f"Openpilot mirror drift: missing={missing}, extra={extra}\n"
                     f"Update dragonpilot/settings/openpilot.toggles.py")

  def test_developer_mirror_in_sync(self):
    mirror = _mirror_keys("Developer")
    missing = EXPECTED_DEVELOPER_KEYS - mirror
    extra = mirror - EXPECTED_DEVELOPER_KEYS
    self.assertFalse(missing or extra,
                     f"Developer mirror drift: missing={missing}, extra={extra}\n"
                     f"Update dragonpilot/settings/openpilot.developer.py and EXPECTED_DEVELOPER_KEYS here")


if __name__ == "__main__":
  unittest.main()
