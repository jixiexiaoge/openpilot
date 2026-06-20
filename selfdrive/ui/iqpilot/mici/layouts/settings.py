"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

IQ.Pilot MICI settings layout — expands the base SettingsLayout with 8 new
IQ.Pilot-specific panels so that MICI (comma 4) reaches full parity with the
comma 3/x (BIG) settings surface.

Tab order (left → right in the horizontal scroller):
  Toggles | Network | Device | Software | Models | Steering |
  Visuals | Display | Cruise | Trips | Vehicle | Developer
"""
from enum import IntEnum

from openpilot.selfdrive.ui.mici.layouts.settings import settings as OP
from openpilot.selfdrive.ui.mici.widgets.button import NeonBigButton

# ── Import all new MICI layout panels ─────────────────────────────────────────
from .models   import ModelsLayoutMici
from .steering import SteeringLayoutMici
from .visuals  import VisualsLayoutMici
from .display  import DisplayLayoutMici
from .software import SoftwareLayoutMici
from .cruise   import CruiseLayoutMici
from .trips    import TripsLayoutMici
from .vehicle  import VehicleLayoutMici

ICON_SIZE = 70

# ── Extend the base PanelType enum with IQ.Pilot-specific panels ──────────────
# We replace the class-level name so any OP.PanelType reference still works.
OP.PanelType = IntEnum(
  "PanelType",
  [es.name for es in OP.PanelType] + [
    "SOFTWARE",
    "MODELS",
    "STEERING",
    "VISUALS",
    "DISPLAY",
    "CRUISE",
    "TRIPS",
    "VEHICLE",
  ],
  start=0,
)


class IQMiciSettingsLayout(OP.SettingsLayout):
  """
  Extends the base MICI SettingsLayout with 8 IQ.Pilot panels.

  The base __init__ already creates:
    PanelType.TOGGLES → TogglesLayoutMici
    PanelType.NETWORK → NetworkLayoutMici
    PanelType.DEVICE  → DeviceLayoutMici
    PanelType.DEVELOPER → DeveloperLayoutMici
  and places 4 BigButton items in the horizontal scroller.

  We inject our 8 extra buttons and register the corresponding panels.
  """

  def __init__(self):
    OP.SettingsLayout.__init__(self)

    # ── Build new nav buttons ────────────────────────────────────────────────
    software_btn = NeonBigButton("software")
    software_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.SOFTWARE))

    models_btn = NeonBigButton("models")
    models_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.MODELS))

    steering_btn = NeonBigButton("steering")
    steering_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.STEERING))

    visuals_btn = NeonBigButton("visuals")
    visuals_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.VISUALS))

    display_btn = NeonBigButton("display")
    display_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.DISPLAY))

    cruise_btn = NeonBigButton("cruise")
    cruise_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.CRUISE))

    trips_btn = NeonBigButton("trips")
    trips_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.TRIPS))

    vehicle_btn = NeonBigButton("vehicle")
    vehicle_btn.set_click_callback(lambda: self._set_current_panel(OP.PanelType.VEHICLE))

    # ── Register panels ──────────────────────────────────────────────────────
    back = lambda: self._set_current_panel(None)  # noqa: E731
    self._panels.update({
      OP.PanelType.SOFTWARE: OP.PanelInfo("Software",  SoftwareLayoutMici(back_callback=back)),
      OP.PanelType.MODELS:   OP.PanelInfo("Models",    ModelsLayoutMici(back_callback=back)),
      OP.PanelType.STEERING: OP.PanelInfo("Steering",  SteeringLayoutMici(back_callback=back)),
      OP.PanelType.VISUALS:  OP.PanelInfo("Visuals",   VisualsLayoutMici(back_callback=back)),
      OP.PanelType.DISPLAY:  OP.PanelInfo("Display",   DisplayLayoutMici(back_callback=back)),
      OP.PanelType.CRUISE:   OP.PanelInfo("Cruise",    CruiseLayoutMici(back_callback=back)),
      OP.PanelType.TRIPS:    OP.PanelInfo("Trips",     TripsLayoutMici(back_callback=back)),
      OP.PanelType.VEHICLE:  OP.PanelInfo("Vehicle",   VehicleLayoutMici(back_callback=back)),
    })

    # ── Inject buttons into scroller in desired tab order ───────────────────
    # Base scroller already has: [toggles, network, device, (pair), developer]
    # Target:  toggles | network | device | software | models |
    #          steering | visuals | display | cruise | trips | vehicle | developer
    #
    # Grab existing items, remove developer (last), append new ones, re-add developer.
    existing = list(self._scroller._items)

    # Identify the developer button (last item) so we always keep it at the end
    # (The base layout inserts: toggles_btn, network_btn, device_btn, PairBigButton, developer_btn)
    developer_btn = existing[-1] if existing else None

    # Items before developer
    pre_dev = existing[:-1] if developer_btn is not None else existing

    new_order = pre_dev + [
      software_btn,
      models_btn,
      steering_btn,
      visuals_btn,
      display_btn,
      cruise_btn,
      trips_btn,
      vehicle_btn,
    ]
    if developer_btn is not None:
      new_order.append(developer_btn)

    self._scroller._items.clear()
    for item in new_order:
      self._scroller.add_widget(item)
