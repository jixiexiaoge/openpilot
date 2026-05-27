from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_disable_connect",
    "type": "toggle_item",
    "title": lambda: tr("Disable Comma Connect"),
    "description": lambda: tr("Disable Comma connect service if you do not wish to upload / being tracked by the service."),
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
