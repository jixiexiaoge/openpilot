from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_audible_alert_mode",
    "type": "text_spin_button_item",
    "title": lambda: tr("Audible Alert"),
    "description": lambda: tr("Std.: Stock behaviour.<br>Warning: Only emits sound when there is a warning.<br>Off: Does not emit any sound at all."),
    "options": [lambda: tr("Std."), lambda: tr("Warning"), lambda: tr("Off")],
    "default": "0",
    "condition": "not LITE",
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
