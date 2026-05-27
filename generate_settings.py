#!/usr/bin/env python3
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

Dragonpilot params_keys.h generator.

Scans dragonpilot/settings/*.py, AST-walks each module's `ITEMS` literal to
extract param-storage fields (key, flags, param_type, default), validates them
against the canonical enum values, and inserts any missing dp_* entries into
common/params_keys.h. Hermetic: no module is imported.

The runtime UI panel reads the same ITEMS via dragonpilot/settings/__init__.py.
"""
import ast
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SETTINGS_DIR = SCRIPT_DIR / "dragonpilot" / "settings"
PARAMS_KEYS_H = SCRIPT_DIR / "common" / "params_keys.h"

# Keep in sync with common/params.h (enum ParamKeyType / enum ParamKeyFlag).
VALID_PARAM_TYPES = {"STRING", "BOOL", "INT", "FLOAT", "TIME", "JSON", "BYTES"}
VALID_FLAGS = {
  "PERSISTENT",
  "CLEAR_ON_MANAGER_START",
  "CLEAR_ON_ONROAD_TRANSITION",
  "CLEAR_ON_OFFROAD_TRANSITION",
  "DONT_LOG",
  "DEVELOPMENT_ONLY",
  "CLEAR_ON_IGNITION_ON",
}

_PARAM_FIELDS = {"key", "flags", "param_type", "default"}


def _extract_items_node(tree: ast.AST) -> ast.List | None:
  for node in tree.body:
    if isinstance(node, ast.Assign):
      for target in node.targets:
        if isinstance(target, ast.Name) and target.id == "ITEMS":
          if not isinstance(node.value, ast.List):
            raise ValueError("ITEMS must be a list literal")
          return node.value
  return None


def _literal_or_none(node: ast.AST):
  """Return the literal value if node is a string/int/float/bool constant, else None."""
  if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
    return node.value
  return None


def _extract_param(dict_node: ast.Dict, source: str) -> dict | None:
  """Pull literal param fields out of an ITEMS dict. Returns None if no param storage declared."""
  fields: dict = {}
  for k_node, v_node in zip(dict_node.keys, dict_node.values):
    if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
      continue
    name = k_node.value
    if name not in _PARAM_FIELDS:
      continue
    lit = _literal_or_none(v_node)
    if lit is None:
      raise ValueError(f"{source}: field {name!r} must be a literal (got {ast.dump(v_node)})")
    fields[name] = lit

  if "key" not in fields:
    return None

  has_flags = "flags" in fields
  has_type = "param_type" in fields
  if has_flags ^ has_type:
    raise ValueError(f"{source}: item {fields['key']!r} must declare both flags and param_type (got one)")
  if not has_flags:
    return None  # UI-only entry (rare; usually every UI item persists)

  param_type = fields["param_type"]
  if param_type not in VALID_PARAM_TYPES:
    raise ValueError(f"{source}: {fields['key']}: unknown param_type {param_type!r}. "
                     f"Valid: {sorted(VALID_PARAM_TYPES)}")

  for flag in str(fields["flags"]).split("|"):
    flag = flag.strip()
    if flag not in VALID_FLAGS:
      raise ValueError(f"{source}: {fields['key']}: unknown flag {flag!r}. "
                       f"Valid: {sorted(VALID_FLAGS)}")

  return fields


def extract_params(py_file: Path) -> list[dict]:
  tree = ast.parse(py_file.read_text())
  items_node = _extract_items_node(tree)
  if items_node is None:
    return []

  out = []
  for entry in items_node.elts:
    if not isinstance(entry, ast.Dict):
      continue
    param = _extract_param(entry, py_file.name)
    if param is not None:
      out.append(param)
  return out


def collect_all_params() -> dict[str, dict]:
  merged: dict[str, dict] = {}
  for py_file in sorted(SETTINGS_DIR.glob("*.py")):
    if py_file.name == "__init__.py":
      continue
    for param in extract_params(py_file):
      merged[param["key"]] = param
  return merged


def render_param_line(param: dict) -> str:
  key = param["key"]
  flags = param["flags"]
  ptype = param["param_type"]
  default = param.get("default", "")
  if default == "":
    return f'    {{"{key}", {{{flags}, {ptype}}}}},'
  return f'    {{"{key}", {{{flags}, {ptype}, "{default}"}}}},'


def update_params_keys_h(params: dict[str, dict]) -> None:
  content = PARAMS_KEYS_H.read_text()
  existing = set(re.findall(r'\{"(dp_[^"]+)"', content))

  new_lines = [render_param_line(p) for k, p in params.items() if k not in existing]
  if not new_lines:
    print("params_keys.h: nothing to add")
    return

  lines = content.split("\n")
  for i, line in enumerate(lines):
    if line.strip() == "};":
      lines[i:i] = new_lines
      break

  PARAMS_KEYS_H.write_text("\n".join(lines))
  print(f"params_keys.h: added {len(new_lines)} dp_ entries")


def main():
  params = collect_all_params()
  print(f"Collected {len(params)} params from {SETTINGS_DIR}")
  update_params_keys_h(params)


if __name__ == "__main__":
  main()
