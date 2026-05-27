from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "VAG",
    "key": "dp_vag_avoid_eps_lockout",
    "type": "toggle_item",
    "title": lambda: tr("Avoid EPS Lockout"),
    "description": lambda: tr("Scale steering torque down at low speeds to avoid EPS lockout."),
    "brands": ["volkswagen"],
    "flags": "PERSISTENT",
    "param_type": "BOOL",
    "default": "0",
  },
]
