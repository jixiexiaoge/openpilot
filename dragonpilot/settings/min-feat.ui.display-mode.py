from dragonpilot.settings import tr

ITEMS = [
  {
    "section": "UI",
    "key": "dp_ui_display_mode",
    "type": "text_spin_button_item",
    "title": lambda: tr("Display Mode"),
    "description": lambda: tr("Std.: Stock behavior.<br>MAIN+: ACC MAIN on = Display ON.<br>OP+: OP enabled = Display ON.<br>MAIN-: ACC MAIN on = Display OFF<br>OP-: OP enabled = Display OFF."),
    "options": [lambda: tr("Std."), lambda: tr("MAIN+"), lambda: tr("OP+"), lambda: tr("MAIN-"), lambda: tr("OP-")],
    "default": "0",
    "flags": "PERSISTENT",
    "param_type": "INT",
  },
]
