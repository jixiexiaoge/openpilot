from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_lon_ext_radar",
    "type": "toggle_item",
    "title": lambda: tr("Use External Radar"),
    "description": lambda: tr("See https://github.com/eFiniLan/openpilot-ext-radar-addon for more information."),
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
