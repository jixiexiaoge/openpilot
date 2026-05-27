# Copyright (c) 2026, Rick Lan
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, and/or sublicense,
# for non-commercial purposes only, subject to the following conditions:
#
# - The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
# - Commercial use (e.g. use in a product, service, or activity intended to
#   generate revenue) is prohibited without explicit written permission from
#   the copyright holder.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import ast
import os

from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets.scroller_tici import Scroller
from dragonpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.list_view import toggle_item, simple_item, button_item, spin_button_item, double_spin_button_item, text_spin_button_item
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.hardware import HARDWARE
from dragonpilot.settings import SETTINGS, extract_depends_on_refs

LITE = os.getenv("LITE") is not None
MICI = HARDWARE.get_device_type() == "mici"

class DragonpilotLayout(Widget):
  def __init__(self):
    super().__init__()

    self._scroller: Scroller | None = None
    self._brand = ""

    self._toggles = {}
    self._toggle_metadata = {}
    self._defaults: dict[str, str] = {}                          # key -> default value (fallback when param unset)
    self._reverse_deps: dict[str, list[tuple[str, str]]] = {}    # parent_key -> [(child_key, expr), ...]
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
    self._build_dependency_maps(settings_data)

    for i, section in enumerate(settings_data):
      if not self._check_condition(section.get("condition")):
        continue

      title_key = f"title_{i}"
      self._toggles[title_key] = simple_item(title=f"### {section['title']} ###")
      count_after_title = len(self._toggles)

      for setting in section.get("settings", []):
        if self._check_condition(setting.get("condition")) and self._check_brands(setting.get("brands")):
          self._create_item(setting)

      # Drop the header if nothing rendered under it: all items filtered out
      # (brand/condition) or no device widget factory for the item type
      # (e.g. dashy-only text_display/text_input/action items). Avoids an
      # orphan "### Section ###" with no controls.
      if len(self._toggles) == count_after_title:
        del self._toggles[title_key]

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

  def _build_dependency_maps(self, settings_data):
    """Collect every UI item's default and invert depends_on into a reverse map."""
    for section in settings_data:
      for item in section.get("settings", []):
        if "key" in item and "default" in item:
          self._defaults[item["key"]] = str(item["default"])

    for section in settings_data:
      for item in section.get("settings", []):
        expr = item.get("depends_on")
        if not expr:
          continue
        refs = extract_depends_on_refs(expr)
        if not refs:
          continue
        for parent_key in refs:
          self._reverse_deps.setdefault(parent_key, []).append((item["key"], expr))

  def _eval_depends_on(self, expr):
    """Evaluate a depends_on expression against current param-store values.
    Returns True on any eval error so we fail open (item stays enabled)."""
    refs = extract_depends_on_refs(expr)
    if refs is None:
      return True
    bindings: dict = {}
    for ref in refs:
      raw = ui_state.params.get(ref)
      val = raw.decode() if isinstance(raw, bytes) else raw
      if val is None or val == "":
        val = self._defaults.get(ref, "0")
      try:
        bindings[ref] = ast.literal_eval(val)
      except (ValueError, SyntaxError):
        bindings[ref] = val
    try:
      return bool(eval(expr, bindings))
    except Exception:
      return True

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

    # Initial enabled state from depends_on
    if "depends_on" in setting:
      args["enabled"] = self._eval_depends_on(setting["depends_on"])

    # Handle callback creation
    primary_action = None
    if param_name:
      if item_type == "toggle_item":
        primary_action = lambda val, p=param_name: ui_state.params.put_bool(p, bool(val))
      elif item_type == "double_spin_button_item":
        primary_action = lambda val, p=param_name: ui_state.params.put(p, float(val))
      else: # spin_button_item, text_spin_button_item
        primary_action = lambda val, p=param_name: ui_state.params.put(p, int(val))

    # When this item changes, re-evaluate every child that depends on it
    parent_deps = self._reverse_deps.get(key, [])

    def combined_callback(val, deps=parent_deps):
      if primary_action:
        primary_action(val)
      for child_key, expr in deps:
        widget = self._toggles.get(child_key)
        if widget is not None:
          widget.action_item.set_enabled(self._eval_depends_on(expr))

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

    dialog = ConfirmDialog(tr("Are you sure you want to reset ALL DP SETTINGS to default?"), tr("Reset"), callback=reset_dp_conf)
    gui_app.push_widget(dialog)

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

  def _render(self, rect):
    self._scroller.render(rect)
