# Dragonpilot Settings Management

## Problem

When merging feature branches into `full` branch, conflicts in `settings.py` and `params_keys.h` are repetitive and manual despite being trivial (additive entries).

**Root cause:** Both files are additive-only structures. Multiple branches adding entries to the same arrays causes git merge conflicts on every feature merge.

## Solution

Each feature branch has its own YAML file. A generator script scans all YAMLs and produces `settings.py` and `params_keys.h`.

```
dragonpilot/settings/           # directory for YAML files (one per feature branch)
  min-feat-lat-alka.yaml       # from min-feat/lat/alka
  min-feat-ui-torque-bar.yaml  # from min-feat/ui/torque-bar
  brands-toyota.yaml           # from brands/toyota

generate_settings.py           # generator script
```

**Note:** Each YAML file is named after the branch, and can contain settings for ANY section (Lateral, Longitudinal, UI, Device, etc.). One feature branch may need settings in multiple sections - all are defined in that branch's single YAML file.

When building, the generator scans `dragonpilot/settings/*.yaml` and outputs:
```
dragonpilot/settings.py        # generated
common/params_keys.h           # generated
```

## Why No Conflicts

- Each branch has its own YAML file
- Git auto-merges separate files trivially
- Generator reads ALL YAMLs and combines them
- No two branches editing the same file = no conflicts

## Architecture

### core-feat/panel Branch

`core-feat/panel` provides:
- `dragonpilot/settings/` directory (placeholder, YAMLs come from feature branches)
- `generate_settings.py` script
- `dragonpilot/settings.py` with empty section structure
- SConstruct integration

### Feature Branches

Each feature branch adds:
- `dragonpilot/settings/<feature>.yaml` - settings for this feature
- Any feature-specific code

### Full Branch

When merging features into `full`:
1. YAML files merge automatically (git handles)
2. Build runs generator → produces `settings.py` + `params_keys.h`
3. No manual conflict resolution needed for settings

## YAML Schema

A single YAML file (named after the branch) can define settings in ANY number of sections.

### Complete Example

```yaml
# min-feat-lat-alka.yaml - One YAML per branch, can have items in multiple sections

settings:
  # Lateral settings
  - title: "Lateral"
    items:
      - key: dp_lat_alka
        type: toggle_item
        title: "Always-on Lane Keeping Assist (ALKA)"
        description: "Enable lateral control even when ACC/cruise is disengaged."
        brands: ["toyota", "hyundai", "honda"]

  # UI settings (same YAML, different section)
  - title: "UI"
    condition: "not MICI"
    items:
      - key: dp_ui_rainbow
        type: toggle_item
        title: "Rainbow Driving Path"
        description: "Like Tesla's rainbow road."

  # Longitudinal settings
  - title: "Longitudinal"
    condition: "openpilotLongitudinalControl"
    items:
      - key: dp_lon_acm
        type: toggle_item
        title: "Adaptive Coasting Mode"
        description: "Reduce braking for smoother coasting."

params_keys:
  - key: dp_lat_alka
    flags: PERSISTENT
    type: BOOL
    default: "0"

  - key: dp_ui_rainbow
    flags: PERSISTENT
    type: BOOL
    default: "0"

  - key: dp_lon_acm
    flags: PERSISTENT
    type: BOOL
    default: "0"
```

### settings Section

```yaml
settings:
  - title: "Section Name"
    condition: "brand == 'honda'"  # optional, section-level condition
    items:
      - key: dp_something
        type: toggle_item
        title: "My Setting"
        description: "Description text"
        brands: ["toyota", "honda"]  # optional, limit to specific brands
        condition: "LITE"  # optional, item-level condition
        default: 0  # for spin items
        min_val: 0  # for spin items
        max_val: 100  # for spin items
        step: 5  # for spin items
        suffix: "mph"  # for spin items
        special_value_text: "Off"  # for spin items, text for min_val
        options: ["Option1", "Option2"]  # for text_spin_button_item
        on_change:
          - target: dp_other_param
            action: set_enabled
            condition: "value > 0"
        initially_enabled_by:
          param: dp_other_param
          condition: "value > 0"
          default: 20
```

### params_keys Section

```yaml
params_keys:
  - key: dp_something
    flags: PERSISTENT  # PERSISTENT, CLEAR_ON_MANAGER_START, CLEAR_ON_OFFROAD_TRANSITION, etc.
    type: BOOL  # BOOL, INT, FLOAT, STRING, JSON, BYTES, TIME
    default: "0"  # string representation of default
```

Note: A `params_keys` entry does not require a corresponding `settings` entry (for internal params without UI).

## Item Types

| Type | Description | Additional Fields |
|------|-------------|-------------------|
| `toggle_item` | On/off toggle | `brands`, `condition` |
| `spin_button_item` | Integer spinner | `default`, `min_val`, `max_val`, `step`, `suffix`, `special_value_text` |
| `double_spin_button_item` | Float spinner | Same as spin_button_item |
| `text_spin_button_item` | Dropdown/text selector | `default`, `options` |

## Conditions

Conditions use Python-like syntax:

| Condition | Meaning |
|-----------|---------|
| `brand == 'honda'` | Only show for Honda brand |
| `brand == 'toyota'` | Only show for Toyota brand |
| `LITE` | Only show on LITE hardware |
| `not LITE` | Hide on LITE hardware |
| `not MICI` | Hide when using MICI UI |
| `openpilotLongitudinalControl` | When openpilot controls longitudinal |

## on_change

Used to enable/disable another setting based on the current value:

```yaml
on_change:
  - target: dp_lat_lca_auto_sec
    action: set_enabled
    condition: "value > 0"
```

Actions: `set_enabled`, `set_visible`, `set_value`

## initially_enabled_by

Controls whether an item starts enabled based on another param's value:

```yaml
initially_enabled_by:
  param: dp_lat_lca_speed
  condition: "value > 0"
  default: 20
```

## Generator

Scans `dragonpilot/settings/*.yaml`, merges all entries, outputs `settings.py` and `params_keys.h`.

```bash
python generate_settings.py
```

## SConstruct Integration

The generator should run automatically during builds:

```python
# In SConstruct
Command(
    target=['dragonpilot/settings.py', 'common/params_keys.h'],
    source=['generate_settings.py'] + Glob('dragonpilot/settings/*.yaml'),
    action='python generate_settings.py'
)
```

## Workflow

### Development (Feature Branch)

1. Add/edit settings in `dragonpilot/settings/<feature>.yaml`
2. Build/test - SConstruct auto-runs the generator
3. Commit YAML file + any feature code changes

### Creating Full Branch

```bash
# Start from core-feat/panel
git checkout core-feat/panel
git merge min-feat/lat/alka
git merge min-feat/ui/torque-bar
git merge brands/toyota
# ... merge all feature branches

# Resolve code conflicts normally (YAML files merge automatically)

# Build - generator runs automatically via SConstruct
scons
```

### Generated Files

`settings.py` and `params_keys.h` are **build artifacts**:
- Do not edit manually - changes will be overwritten
- Optionally not committed to git - regenerated on build
- Or commit them if you want reproducible builds without rebuilding

## Section Ordering

Generator defines fixed section order. Each YAML contributes to its section:

```python
SECTION_ORDER = [
    "Toyota / Lexus",
    "VAG",
    "Mazda",
    "Lateral",
    "Longitudinal",
    "UI",
    "Device",
]
```

Generator scans all YAMLs, collects items by section title, outputs in fixed order.
