from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "UI",
    "key": "dp_ui_hide_hud_speed_kph",
    "type": "spin_button_item",
    "title": lambda: tr("Hide HUD When Moves above:"),
    "description": lambda: tr("To prevent screen burn-in, hide Speed, MAX Speed, and Steering/DM Icons when the car moves.<br>Off = Stock Behavior<br>1 km/h = 0.6 mph"),
    "default": "0",
    "min_val": 0,
    "max_val": 120,
    "step": 5,
    "suffix": lambda: tr("km/h"),
    "special_value_text": lambda: tr("Off"),
    "condition": "not MICI",
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
