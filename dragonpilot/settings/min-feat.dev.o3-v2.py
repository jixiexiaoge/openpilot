from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_is_rhd",
    "type": "toggle_item",
    "title": lambda: tr("Enable Right-Hand Drive Mode"),
    "description": lambda: tr("Allow openpilot to obey right-hand traffic conventions on right driver seat."),
    "condition": "LITE",
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
  {
    "section": "Device",
    "key": "dp_dev_beep",
    "type": "toggle_item",
    "title": lambda: tr("Enable Beep (Warning)"),
    "description": lambda: tr("Use Buzzer for audiable alerts."),
    "condition": "LITE",
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
