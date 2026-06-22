from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Lateral",
    "key": "dp_lat_road_edge_detection",
    "type": "toggle_item",
    "title": lambda: tr("Road Edge Detection (RED)"),
    "description": lambda: tr("Block lane change assist when the system detects the road edge.<br>NOTE: This will show 'Car Detected in Blindspot' warning."),
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
