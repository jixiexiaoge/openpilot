from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "VAG",
    "key": "dp_vag_a0_sng",
    "type": "toggle_item",
    "title": lambda: tr("Enable Stop-and-Go on A0 Platform"),
    "description": lambda: tr("Restores stop-and-go behavior on VAG A0 platform vehicles (Polo, Fabia, Ibiza, etc.), allowing openpilot to resume from a full stop without driver intervention."),
    "brands": ["volkswagen"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
