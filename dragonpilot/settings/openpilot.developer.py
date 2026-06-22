"""
Mirror of upstream openpilot's DeveloperLayout settings for the dashy web UI.

See openpilot.toggles.py for the rationale (DASHY-gated, no param_type, etc.).

Notes:
- AlphaLongitudinalEnabled / JoystickDebugMode / LongitudinalManeuverMode are
  hidden on release builds in the device UI (DeveloperLayout._update_toggles).
  Mirror them with `condition: "DASHY and not IS_RELEASE"` so release-branch
  dashy hides them too.
- SSH Keys: rendered as a text_input (GithubUsername) + text_display
  (GithubSshKeys) + clear button. The actual github.com fetch is handled by
  the dashy action endpoint /api/action/ssh_key_set since it has side effects
  (HTTP request, atomic two-param write, error handling) that don't fit a
  declarative "set this param" model.
- "Show Last Errors": text_display of dp_dev_last_log — the device modal is
  also still available via the existing DeveloperLayout button.
"""
from dragonpilot.settings import tr
from openpilot.selfdrive.ui.layouts.settings.developer import DESCRIPTIONS as _DEV_DESC

_SEC = "Developer"
_DASHY = "DASHY"
_DASHY_ALPHA = "DASHY and not IS_RELEASE"

ITEMS = [
  {
    "section": _SEC, "key": "AdbEnabled", "type": "toggle_item",
    "title": lambda: tr("Enable ADB"),
    "description": lambda: tr(_DEV_DESC["enable_adb"]),
    "condition": _DASHY,
  },
  {
    "section": _SEC, "key": "SshEnabled", "type": "toggle_item",
    "title": lambda: tr("Enable SSH"),
    "condition": _DASHY,
  },
  {
    "section": _SEC, "key": "JoystickDebugMode", "type": "toggle_item",
    "title": lambda: tr("Joystick Debug Mode"),
    "condition": _DASHY_ALPHA,
  },
  {
    "section": _SEC, "key": "LongitudinalManeuverMode", "type": "toggle_item",
    "title": lambda: tr("Longitudinal Maneuver Mode"),
    "condition": _DASHY_ALPHA,
  },
  {
    "section": _SEC, "key": "AlphaLongitudinalEnabled", "type": "toggle_item",
    "title": lambda: tr("openpilot Longitudinal Control (Alpha)"),
    "description": lambda: tr(_DEV_DESC["alpha_longitudinal"]),
    "condition": _DASHY_ALPHA,
  },
  {
    "section": _SEC, "key": "ShowDebugInfo", "type": "toggle_item",
    "title": lambda: tr("UI Debug Mode"),
    "condition": _DASHY,
  },

  # SSH Keys — typed input + display + clear. github.com fetch lives in the
  # dashy ssh_key_set action; see dragonpilot/dashy/serverd.py.
  {
    "section": _SEC, "key": "GithubUsername", "type": "text_input_item",
    "title": lambda: tr("GitHub Username (SSH Keys)"),
    "description": lambda: tr(_DEV_DESC["ssh_key"]),
    "action": "ssh_key_set",
    "condition": _DASHY,
  },
  {
    "section": _SEC, "key": "GithubSshKeys", "type": "text_display_item",
    "title": lambda: tr("Stored SSH Keys"),
    "condition": _DASHY,
  },
  {
    "section": _SEC, "key": "ssh_key_clear", "type": "action_item",
    "title": lambda: tr("Clear SSH Keys"),
    "action": "ssh_key_clear",
    "condition": _DASHY,
  },

  # Last error log — read-only display of dp_dev_last_log (already declared by
  # core-feat/panel). Device side still has the "Show Last Errors" modal button.
  {
    "section": _SEC, "key": "dp_dev_last_log", "type": "text_display_item",
    "title": lambda: tr("Last Errors"),
    "condition": _DASHY,
  },
]
