import os

from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets.scroller_tici import Scroller
from dragonpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.list_view import toggle_item, simple_item, button_item, spin_button_item, double_spin_button_item, text_spin_button_item
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.hardware import HARDWARE
from dragonpilot.settings import SETTINGS

LITE = os.getenv("LITE") is not None
MICI = HARDWARE.get_device_type() == "mici"

class DragonpilotLayout(Widget):
  def __init__(self):
    super().__init__()

    self._scroller: Scroller | None = None
    self._brand = ""

    self._toggles = {}
    self._toggle_metadata = {}
    self._item_factories = {
      "toggle_item": toggle_item,
      "spin_button_item": spin_button_item,
      "double_spin_button_item": double_spin_button_item,
      "text_spin_button_item": text_spin_button_item,
    }

    self._openpilot_longitudinal_control = False
    if ui_state.CP is not None:
      self._brand = ui_state.CP.brand
      self._openpilot_longitudinal_control = ui_state.CP.openpilotLongitudinalControl

    self._load_settings()

    self._reset_dp_conf_btn = button_item(
      lambda: tr("Reset DP Settings"),
      lambda: tr("RESET"),
      lambda: tr("Reset dragonpilot settings to default and restart the device."),
      callback=self._reset_dp_conf)
    self._toggles['btn_reset_dp_conf'] = self._reset_dp_conf_btn

    self._scroller = Scroller(list(self._toggles.values()), line_separator=True, spacing=0)

  def _load_settings(self):
    settings_data = SETTINGS

    for i, section in enumerate(settings_data):
      if self._check_condition(section.get("condition")):
        formatted_title = f"### {section['title']} ###"
        self._toggles[f"title_{i}"] = simple_item(title=formatted_title)
        for setting in section.get("settings", []):
          if self._check_condition(setting.get("condition")) and self._check_brands(setting.get("brands")):
            self._create_item(setting)

  def _check_condition(self, condition):
    if not condition:
      return True

    context = {"LITE": LITE, "MICI": MICI, "brand": self._brand, "openpilotLongitudinalControl": self._openpilot_longitudinal_control}

    try:
      return eval(condition, context)
    except Exception:
      return False

  def _check_brands(self, brands):
    """Check if current brand is in the allowed brands list."""
    if not brands:
      return True  # No brand restriction, show for all
    return self._brand in brands

  def _resolve(self, value):
    """Resolve callable values (lambdas) to their actual values."""
    return value() if callable(value) else value

  def _create_item(self, setting):
    key = setting["key"]
    item_type = setting["type"]
    factory = self._item_factories.get(item_type)
    if not factory:
      return

    # title and description support callables natively in ListItem
    args = {"title": setting["title"]}
    if setting.get("description"):
      args["description"] = setting["description"]

    param_name = setting.get("param_name") or key

    # Handle initial values
    if item_type == "toggle_item":
      args["initial_state"] = ui_state.params.get_bool(param_name)
    else:
      raw_val = ui_state.params.get(param_name)
      initial_val = raw_val.decode() if isinstance(raw_val, bytes) else raw_val
      if initial_val is None:
        initial_val = setting.get("default")

      if item_type == "double_spin_button_item":
        args["initial_value"] = float(initial_val)
      elif item_type == "text_spin_button_item":
        args["initial_index"] = int(initial_val)
      else: # spin_button_item
        args["initial_value"] = int(initial_val)

    # Handle initial enabled state
    if "initially_enabled_by" in setting:
      enabled_by = setting["initially_enabled_by"]
      source_param = enabled_by["param"]
      source_val_raw = ui_state.params.get(source_param)
      source_val = source_val_raw.decode() if isinstance(source_val_raw, bytes) else source_val_raw
      if source_val is None:
        source_val = enabled_by.get("default")

      if source_val is not None:
        condition_str = enabled_by["condition"]
        try:
          is_enabled = eval(condition_str, {"value": int(source_val)})
          args["enabled"] = is_enabled
        except Exception:
          args["enabled"] = True
      else:
        args["enabled"] = True

    # Handle callback creation
    primary_action = None
    if param_name:
      if item_type == "toggle_item":
        primary_action = lambda val, p=param_name: ui_state.params.put_bool(p, bool(val))
      elif item_type == "double_spin_button_item":
        primary_action = lambda val, p=param_name: ui_state.params.put(p, float(val))
      else: # spin_button_item, text_spin_button_item
        primary_action = lambda val, p=param_name: ui_state.params.put(p, int(val))

    side_effects = []
    if "on_change" in setting:
      for effect in setting["on_change"]:
        target_key = effect.get("target")
        action = effect.get("action")
        condition_str = effect.get("condition")

        if target_key and action == "set_enabled" and condition_str:
          def create_side_effect(tk=target_key, cs=condition_str):
            def side_effect_action(val):
              if tk in self._toggles:
                try:
                  is_enabled = eval(cs, {"value": val})
                  self._toggles[tk].action_item.set_enabled(is_enabled)
                except Exception:
                  pass
            return side_effect_action
          side_effects.append(create_side_effect())

    def combined_callback(val):
      if primary_action:
        primary_action(val)
      for effect in side_effects:
        effect(val)

    if "callback" in setting and setting["callback"]:
      args["callback"] = getattr(self, setting["callback"])
    else:
      args["callback"] = combined_callback

    # D. Add other properties from JSON
    for prop in ["min_val", "max_val", "step"]:
      if prop in setting:
        args[prop] = setting[prop]
    # These properties don't support callables in the widgets, so resolve them
    if "special_value_text" in setting:
      args["special_value_text"] = self._resolve(setting["special_value_text"])
    if "suffix" in setting:
      args["suffix"] = self._resolve(setting["suffix"])
    if "options" in setting:
      args["options"] = [self._resolve(opt) for opt in setting["options"]]

    widget = factory(**args)
    self._toggles[key] = widget
    if param_name:
      self._toggle_metadata[key] = {
        "widget": widget,
        "param_name": param_name,
        "item_type": item_type,
        "default": setting.get("default")
      }

  def _reset_dp_conf(self):
    def reset_dp_conf(result: int):
      if result != DialogResult.CONFIRM:
        return
      ui_state.params.put_bool("dp_dev_reset_conf", True)
      ui_state.params.put_bool("DoReboot", True)

    dialog = ConfirmDialog(tr("Are you sure you want to reset ALL DP SETTINGS to default?"), tr("Reset"))
    gui_app.set_modal_overlay(dialog, callback=reset_dp_conf)

  def show_event(self):
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # Refresh toggles from params to mirror external changes
    for _, meta in self._toggle_metadata.items():
      widget = meta["widget"]
      param_name = meta["param_name"]
      item_type = meta["item_type"]
      default = meta.get("default")

      if item_type == "toggle_item":
        widget.action_item.set_state(ui_state.params.get_bool(param_name))
      else:  # Spinners
        raw_val = ui_state.params.get(param_name)
        val_str = None
        if raw_val is not None:
          if isinstance(raw_val, bytes):
            val_str = raw_val.decode()
          else:
            val_str = str(raw_val)
        elif default is not None:
          val_str = str(default)

        if val_str is None:
          continue

        if item_type == "double_spin_button_item":
          widget.action_item.set_value(float(val_str))
        elif item_type == "spin_button_item":
          widget.action_item.set_value(int(val_str))
        elif item_type == "text_spin_button_item":
          widget.action_item.set_index(int(val_str))
        else:  # spin_button_item and text_spin_button_item
          pass

  def _render(self, rect):
    self._scroller.render(rect)
