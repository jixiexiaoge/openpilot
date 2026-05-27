from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Longitudinal",
    "key": "dp_lon_apm",
    "type": "toggle_item",
    "title": lambda: tr("Adaptive Personality Mode (APM)"),
    "description": lambda: tr("Automatically switches personality to \"Aggressive\" below 30 km/h and restores your selected personality above 40 km/h."),
    "condition": "openpilotLongitudinalControl",
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
