from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Toyota / Lexus",
    "key": "dp_toyota_door_auto_lock_unlock",
    "type": "toggle_item",
    "title": lambda: tr("Door Auto Lock/Unlock"),
    "description": lambda: tr("Enable openpilot to auto-lock doors above 20 km/h and auto-unlock when shifting to Park."),
    "brands": ["toyota"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
