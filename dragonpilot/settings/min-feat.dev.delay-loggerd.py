from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Device",
    "key": "dp_dev_delay_loggerd",
    "type": "spin_button_item",
    "title": lambda: tr("Delay Starting Loggerd for:"),
    "description": lambda: tr("Delays the startup of loggerd and its related processes when the device goes on-road.<br>This prevents the initial moments of a drive from being recorded, protecting location privacy at the start of a trip."),
    "default": "0",
    "min_val": 0,
    "max_val": 300,
    "step": 5,
    "suffix": lambda: tr("sec"),
    "special_value_text": lambda: tr("Off"),
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
