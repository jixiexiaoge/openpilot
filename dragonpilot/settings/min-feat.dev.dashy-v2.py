from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_dashy",
    "type": "toggle_item",
    "title": lambda: tr("Enable dashy Visual"),
    "description": lambda: tr("dashy - dragonpilot's all-in-one system hub.<br><br>Visit http://&lt;device_ip&gt;:5088 to access.<br><br>Enable this to use Tesla Visual/HUD."),
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
