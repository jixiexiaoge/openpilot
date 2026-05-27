from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Longitudinal",
    "key": "dp_lon_acm",
    "type": "toggle_item",
    "title": lambda: tr("Enable Adaptive Coasting Mode (ACM)"),
    "description": lambda: tr("Adaptive Coasting Mode (ACM) reduces braking to allow smoother coasting when appropriate."),
    "condition": "openpilotLongitudinalControl",
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
