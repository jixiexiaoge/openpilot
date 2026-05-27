from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "Toyota / Lexus",
    "key": "dp_toyota_tss1_sng",
    "type": "toggle_item",
    "title": lambda: tr("Enable Stop-and-Go on TSS1"),
    "description": lambda: tr("Restores stop-and-go behavior on Toyota Safety Sense 1.0 vehicles, allowing openpilot to resume from a full stop without driver intervention."),
    "brands": ["toyota"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
