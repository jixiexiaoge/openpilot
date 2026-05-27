from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_auto_shutdown_in",
    "type": "spin_button_item",
    "title": lambda: tr("Auto Shutdown After"),
    "description": lambda: tr("0 min = Immediately"),
    "default": "-5",
    "min_val": -5,
    "max_val": 300,
    "step": 5,
    "suffix": lambda: tr("min"),
    "special_value_text": lambda: tr("Off"),
    "condition": "not MICI",
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
