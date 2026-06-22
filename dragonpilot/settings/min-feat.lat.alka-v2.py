from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Lateral",
    "key": "dp_lat_alka",
    "type": "toggle_item",
    "title": lambda: tr("Always-on Lane Keeping Assist (ALKA)"),
    "description": lambda: tr("Enable lateral control even when ACC/cruise is disengaged, using ACC Main or LKAS button to toggle. Vehicle must be moving."),
    "brands": ["toyota", "hyundai", "honda", "volkswagen", "subaru", "mazda", "nissan", "ford"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
