from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "UI",
    "key": "dp_ui_lead",
    "type": "text_spin_button_item",
    "title": lambda: tr("Display Lead Stats"),
    "description": lambda: tr("Display the statistics of lead car and/or radar tracking points.<br>Lead: Lead stats only<br>Radar: Radar tracking point stats only<br>All: Lead and Radar stats<br>NOTE: Radar option only works on certain vehicle models."),
    "options": [lambda: tr("Off"), lambda: tr("Lead"), lambda: tr("Radar"), lambda: tr("All")],
    "default": "0",
    "condition": "not MICI",
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
