from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Lateral",
    "key": "dp_lat_offset_cm",
    "type": "spin_button_item",
    "title": lambda: tr("Position Offset"),
    "description": lambda: tr("Fine-tune where the car drives within the lane. Positive values move the car left, negative values move right.<br>Recommended to start with small values (±5cm) and adjust based on preference."),
    "default": "0",
    "min_val": -15,
    "max_val": 15,
    "step": 1,
    "suffix": lambda: tr("cm"),
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
