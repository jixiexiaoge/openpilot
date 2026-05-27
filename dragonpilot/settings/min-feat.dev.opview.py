from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_opview",
    "type": "toggle_item",
    "title": lambda: tr("Enable opview"),
    "description": lambda: tr("Broadcasts telemetry to the opview App (available on Android). Requires the companion App to be running on an external display."),
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
