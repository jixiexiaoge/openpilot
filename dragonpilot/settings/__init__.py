"""
Copyright (c) 2026, Rick Lan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, and/or sublicense,
for non-commercial purposes only, subject to the following conditions:

- The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
- Commercial use (e.g. use in a product, service, or activity intended to
  generate revenue) is prohibited without explicit written permission from
  the copyright holder.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Dragonpilot settings aggregator.

Each feature branch drops a single `<branch>.py` in this directory. The module
exposes ITEMS - a list of dicts where each dict carries both UI fields (for the
dp settings panel) and param-storage fields (consumed at build time by
generate_settings.py to produce common/params_keys.h).

Param-only entries (no UI) just omit the UI fields - they still get picked up
by the C++ generator but the aggregator skips them.

At import time this module:
  1. Globs every sibling *.py (except __init__.py)
  2. Loads each via spec_from_file_location, collects ITEMS, validates shape
  3. Groups UI items by their "section" field, orders sections per SECTION_ORDER
  4. Exposes the result as SETTINGS, in the shape the UI panel expects

A failing import is logged and skipped - other features still load.
"""
import ast
import importlib.util
import sys
from pathlib import Path

try:
  from dragonpilot.system.ui.lib.multilang import tr  # noqa: F401  (re-export for feature files)
except ImportError:
  from openpilot.system.ui.lib.multilang import tr  # noqa: F401

SECTION_ORDER = [
  "Toyota / Lexus",
  "Honda",
  "HKG",
  "VAG",
  "Mazda",
  "Lateral",
  "Longitudinal",
  "UI",
  "Device",
  # Upstream openpilot toggle mirrors (dashy-only, gated by `condition: "DASHY"`).
  "Openpilot",
  "Developer",
]

# Brand-gated sections: the whole header + its items are hidden when the
# current car's brand doesn't match. Generic sections (Lateral/UI/...) are
# unconditional.
SECTION_CONDITIONS = {
  "Toyota / Lexus": "brand == 'toyota'",
  "Honda":          "brand == 'honda'",
  "HKG":            "brand == 'hyundai'",
  "VAG":            "brand == 'volkswagen'",
  "Mazda":          "brand == 'mazda'",
}

_UI_REQUIRED_KEYS = {"section", "key", "type", "title"}
_KNOWN_ITEM_KEYS = _UI_REQUIRED_KEYS | {
  # UI-side optional fields
  "description", "default", "min_val", "max_val", "step", "suffix",
  "special_value_text", "options", "brands", "condition",
  "depends_on", "param_name", "callback",
  # Dashy-only fields (no factory on the device dp panel; web UI consumes them).
  # text_display_item: read-only render of a param's value.
  # text_input_item: text field that POSTs typed value to the named action endpoint.
  # action_item: button that POSTs to the named action endpoint with no payload.
  "action",
  # Param-storage fields (consumed by generate_settings.py, ignored by UI)
  "flags", "param_type",
}


def extract_depends_on_refs(expr):
  """Pull referenced param keys out of a depends_on expression like 'dp_x > 0 and dp_y == 1'."""
  try:
    tree = ast.parse(expr, mode="eval")
  except SyntaxError:
    return None  # caller handles
  return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _validate_item(item, source):
  """Validate an item for UI rendering. Returns True if the item should be rendered."""
  key = item.get("key", "?")

  unknown = item.keys() - _KNOWN_ITEM_KEYS
  if unknown:
    print(f"[dragonpilot.settings] {source}: item {key} has unknown keys {unknown}")

  # Param-only entries (no "title") aren't rendered - skip silently.
  if "title" not in item:
    return False

  missing = _UI_REQUIRED_KEYS - item.keys()
  if missing:
    print(f"[dragonpilot.settings] {source}: item {key} missing UI keys {missing}")
    return False
  if not callable(item["title"]):
    print(f"[dragonpilot.settings] {source}: item {key} title must be callable, e.g. lambda: tr(...)")
    return False
  return True


def _load_feature(py_file):
  # Filenames mirror branch names (e.g. "min-feat.lat.alka-v2.py"); sanitize for sys.modules.
  safe = py_file.stem.replace("-", "_").replace(".", "_")
  module_name = f"_dp_feature_{safe}"
  spec = importlib.util.spec_from_file_location(module_name, py_file)
  mod = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = mod
  spec.loader.exec_module(mod)
  return getattr(mod, "ITEMS", [])


def _check_dangling_refs(ui_items, all_keys):
  """Warn loudly when a depends_on expression names a key that isn't declared anywhere.
  The UI silently no-ops on missing refs, which lets typos hide forever."""
  for source, item in ui_items:
    expr = item.get("depends_on")
    if not expr:
      continue
    key = item.get("key", "?")
    refs = extract_depends_on_refs(expr)
    if refs is None:
      print(f"[dragonpilot.settings] {source}: {key}.depends_on {expr!r} is not valid Python")
      continue
    for ref in refs:
      if ref not in all_keys:
        print(f"[dragonpilot.settings] {source}: {key}.depends_on references {ref!r} "
              f"which is not defined in any feature file")


def _build_settings():
  settings_dir = Path(__file__).parent
  by_section: dict[str, list] = {}
  all_keys: set[str] = set()
  ui_items: list[tuple[str, dict]] = []  # (source filename, item) for cross-ref check

  for py_file in sorted(settings_dir.glob("*.py")):
    if py_file.name == "__init__.py":
      continue
    try:
      items = _load_feature(py_file)
    except Exception as e:
      print(f"[dragonpilot.settings] Failed to load {py_file.name}: {e}")
      continue

    for item in items:
      if "key" in item:
        all_keys.add(item["key"])
      if not _validate_item(item, py_file.name):
        continue
      ui_items.append((py_file.name, item))
      by_section.setdefault(item["section"], []).append(item)

  _check_dangling_refs(ui_items, all_keys)

  def _section_entry(title, items):
    entry = {"title": title, "settings": items}
    cond = SECTION_CONDITIONS.get(title)
    if cond:
      entry["condition"] = cond
    return entry

  result = []
  for section in SECTION_ORDER:
    if section in by_section:
      result.append(_section_entry(section, by_section[section]))
  for section, items in by_section.items():
    if section not in SECTION_ORDER:
      result.append(_section_entry(section, items))
  return result


SETTINGS = _build_settings()
