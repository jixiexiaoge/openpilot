from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Honda",
    "key": "dp_honda_nidec_stock_long",
    "type": "toggle_item",
    "title": lambda: tr("Use Stock Longitudinal (Nidec)"),
    "description": lambda: tr("Let the Honda Nidec ACC handle gas and brake instead of openpilot. Lateral control (steering) still runs through openpilot."),
    "brands": ["honda"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
