from dragonpilot.system.ui.lib.multilang import tr

SETTINGS = [
  {
    "title": "Toyota / Lexus",
    "condition": "brand == 'toyota'",
    "settings": [
      {
        "key": "dp_toyota_door_auto_lock_unlock",
        "type": "toggle_item",
        "title": lambda: tr("Door Auto Lock/Unlock"),
        "description": lambda: tr("Enable openpilot to auto-lock doors above 20 km/h and auto-unlock when shifting to Park."),
      },
      {
        "key": "dp_toyota_tss1_sng",
        "type": "toggle_item",
        "title": lambda: tr("Enable TSS1 SnG Mod"),
        "description": ""
      },
      {
        "key": "dp_toyota_stock_lon",
        "type": "toggle_item",
        "title": lambda: tr("Use Stock Longitudinal Control"),
        "description": ""
      },

    ],
  },
  {
    "title": "VAG",
    "condition": "brand == 'volkswagen'",
    "settings": [
      {
        "key": "dp_vag_a0_sng",
        "type": "toggle_item",
        "title": lambda: tr("MQB A0 SnG Mod"),
        "description": ""
      },
      {
        "key": "dp_vag_pq_steering_patch",
        "type": "toggle_item",
        "title": lambda: tr("PQ Steering Patch"),
        "description": "",
      },
      {
        "key": "dp_vag_avoid_eps_lockout",
        "type": "toggle_item",
        "title": lambda: tr("Avoid EPS Lockout"),
        "description": ""
      },

    ],
  },
  {
    "title": "Mazda",
    "condition": "brand == 'mazda'",
    "settings": [

    ],
  },
  {
    "title": "Lateral",
    "settings": [
      {
        "key": "dp_lat_alka",
        "type": "toggle_item",
        "title": lambda: tr("Always-on Lane Keeping Assist (ALKA)"),
        "description": lambda: tr("Enable lateral control even when ACC/cruise is disengaged, using ACC Main or LKAS button to toggle. Vehicle must be moving."),
        "brands": ["toyota", "hyundai", "honda", "volkswagen", "subaru", "mazda", "nissan", "ford"],
      },
      {
        "key": "dp_lat_lca_speed",
        "type": "spin_button_item",
        "title": lambda: tr("Lane Change Assist At:"),
        "description": lambda: tr("Off = Disable LCA.<br>1 mph = 1.2 km/h."),
        "default": 20,
        "min_val": 0,
        "max_val": 100,
        "step": 5,
        "suffix": lambda: tr("mph"),
        "special_value_text": lambda: tr("Off"),
        "on_change": [{
          "target": "dp_lat_lca_auto_sec",
          "action": "set_enabled",
          "condition": "value > 0"
        }]
      },
      {
        "key": "dp_lat_lca_auto_sec",
        "type": "double_spin_button_item",
        "title": lambda: tr("+ Auto Lane Change after:"),
        "description": lambda: tr("Off = Disable Auto Lane Change."),
        "default": 0.0,
        "min_val": 0.0,
        "max_val": 5.0,
        "step": 0.5,
        "suffix": lambda: tr("sec"),
        "special_value_text": lambda: tr("Off"),
        "initially_enabled_by": {
          "param": "dp_lat_lca_speed",
          "condition": "value > 0",
          "default": 20
        }
      },
      {
        "key": "dp_lat_road_edge_detection",
        "type": "toggle_item",
        "title": lambda: tr("Road Edge Detection (RED)"),
        "description": lambda: tr("Block lane change assist when the system detects the road edge.<br>NOTE: This will show 'Car Detected in Blindspot' warning."),
      },

    ],
  },
  {
    "title": "Longitudinal",
    "condition": "openpilotLongitudinalControl",
    "settings": [
      {
        "key": "dp_lon_acm",
        "type": "toggle_item",
        "title": lambda: tr("Enable Adaptive Coasting Mode (ACM)"),
        "description": lambda: tr("Adaptive Coasting Mode (ACM) reduces braking to allow smoother coasting when appropriate."),
      },
      {
        "key": "dp_lon_aem",
        "type": "toggle_item",
        "title": lambda: tr("Adaptive Experimental Mode (AEM)"),
        "description": lambda: tr("Adaptive mode switcher between ACC and Blended based on driving context."),
      },
      {
        "key": "dp_lon_dtsc",
        "type": "toggle_item",
        "title": lambda: tr("Dynamic Turn Speed Control (DTSC)"),
        "description": lambda: tr("DTSC automatically adjusts the vehicle's predicted speed based on upcoming road curvature and grip conditions.<br>Originally from the openpilot TACO branch."),
      },

    ],
  },
  {
    "title": "UI",
    "settings": [
      {
        "key": "dp_ui_display_mode",
        "type": "text_spin_button_item",
        "title": lambda: tr("Display Mode"),
        "description": lambda: tr("Std.: Stock behavior.<br>MAIN+: ACC MAIN on = Display ON.<br>OP+: OP enabled = Display ON.<br>MAIN-: ACC MAIN on = Display OFF<br>OP-: OP enabled = Display OFF."),
        "default": 0,
        "options": [
          lambda: tr("Std."),
          lambda: tr("MAIN+"),
          lambda: tr("OP+"),
          lambda: tr("MAIN-"),
          lambda: tr("OP-"),
        ],
        "condition": "not MICI",
      },
      {
        "key": "dp_ui_hide_hud_speed_kph",
        "type": "spin_button_item",
        "title": lambda: tr("Hide HUD When Moves above:"),
        "description": lambda: tr("To prevent screen burn-in, hide Speed, MAX Speed, and Steering/DM Icons when the car moves.<br>Off = Stock Behavior<br>1 km/h = 0.6 mph"),
        "default": 0,
        "min_val": 0,
        "max_val": 120,
        "step": 5,
        "suffix": lambda: tr("km/h"),
        "special_value_text": lambda: tr("Off"),
      },
      {
        "key": "dp_ui_rainbow",
        "type": "toggle_item",
        "title": lambda: tr("Rainbow Driving Path like Tesla"),
        "description": lambda: tr("Why not?"),
        "condition": "not MICI",
      },
      {
        "key": "dp_ui_lead",
        "type": "text_spin_button_item",
        "title": lambda: tr("Display Lead Stats"),
        "description": lambda: tr("Display the statistics of lead car and/or radar tracking points.<br>Lead: Lead stats only<br>Radar: Radar tracking point stats only<br>All: Lead and Radar stats<br>NOTE: Radar option only works on certain vehicle models."),
        "default": 0,
        "options": [
          lambda: tr("Off"),
          lambda: tr("Lead"),
          lambda: tr("Radar"),
          lambda: tr("All"),
        ],
        "condition": "not MICI",
      },
      {
        "key": "dp_ui_mici",
        "type": "toggle_item",
        "title": lambda: tr("Use MICI (comma four) UI"),
        "description": lambda: tr("Why not?"),
        "condition": "not MICI",
      },

    ],
  },
  {
    "title": "Device",
    "settings": [
      {
        "key": "dp_dev_is_rhd",
        "type": "toggle_item",
        "title": lambda: tr("Enable Right-Hand Drive Mode"),
        "description": lambda: tr("Allow openpilot to obey right-hand traffic conventions on right driver seat."),
        "condition": "LITE",
      },
      {
        "key": "dp_dev_beep",
        "type": "toggle_item",
        "title": lambda: tr("Enable Beep (Warning)"),
        "description": lambda: tr("Use Buzzer for audiable alerts."),
        "condition": "LITE",
      },
      {
        "key": "dp_lon_ext_radar",
        "type": "toggle_item",
        "title": lambda: tr("Use External Radar"),
        "description": lambda: tr("See https://github.com/eFiniLan/openpilot-ext-radar-addon for more information."),
      },
      {
        "key": "dp_dev_audible_alert_mode",
        "type": "text_spin_button_item",
        "title": lambda: tr("Audible Alert"),
        "description": lambda: tr("Std.: Stock behaviour.<br>Warning: Only emits sound when there is a warning.<br>Off: Does not emit any sound at all."),
        "default": 0,
        "options": [
          lambda: tr("Std."),
          lambda: tr("Warning"),
          lambda: tr("Off"),
        ],
        "condition": "not LITE",
      },
      {
        "key": "dp_dev_auto_shutdown_in",
        "type": "spin_button_item",
        "title": lambda: tr("Auto Shutdown After"),
        "description": lambda: tr("0 min = Immediately"),
        "default": -5,
        "min_val": -5,
        "max_val": 300,
        "step": 5,
        "suffix": lambda: tr("min"),
        "special_value_text": lambda: tr("Off"),
      },
      {
        "key": "dp_dev_dashy",
        "type": "toggle_item",
        "title": lambda: tr("dashy HUD"),
        "description": lambda: tr("dashy - dragonpilot's all-in-one system hub for you.<br><br>Visit http://<device_ip>:5088 to access.<br><br>Enable this to use HUD feature (live streaming)."),
      },
      {
        "key": "dp_dev_delay_loggerd",
        "type": "spin_button_item",
        "title": lambda: tr("Delay Starting Loggerd for:"),
        "description": lambda: tr("Delays the startup of loggerd and its related processes when the device goes on-road.<br>This prevents the initial moments of a drive from being recorded, protecting location privacy at the start of a trip."),
        "default": 0,
        "min_val": 0,
        "max_val": 300,
        "step": 5,
        "suffix": lambda: tr("sec"),
        "special_value_text": lambda: tr("Off"),
      },
      {
        "key": "dp_dev_disable_connect",
        "type": "toggle_item",
        "title": lambda: tr("Disable Comma Connect"),
        "description": lambda: tr("Disable Comma connect service if you do not wish to upload / being tracked by the service."),
      },

    ],
  },
]
