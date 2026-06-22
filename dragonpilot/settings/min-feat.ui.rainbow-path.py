from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "UI",
    "key": "dp_ui_rainbow",
    "type": "toggle_item",
    "title": lambda: tr("Rainbow Driving Path like Tesla"),
    "description": lambda: tr("Why not?"),
    "condition": "not MICI",
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
