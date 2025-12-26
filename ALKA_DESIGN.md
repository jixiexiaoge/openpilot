# ALKA (Always-on Lane Keeping Assist) Design v3

## Overview

ALKA enables lateral control (steering) when ACC Main is ON, without requiring cruise to be engaged. This allows lane keeping assist to function independently of longitudinal control.

**Simplified Behavior (v3):**
- All brands use direct tracking: `lkas_on = acc_main_on`
- No button/toggle tracking (removed TJA, LKAS button, LKAS HUD)
- ACC Main ON = ALKA enabled, ACC Main OFF = ALKA disabled

---

## Per-Brand Summary

| Brand | Status | ACC Main Source | Notes |
|-------|--------|-----------------|-------|
| Body | Disabled | - | No steering capability |
| Chrysler | Disabled | - | Needs special handling |
| Ford | Enabled | EngBrakeData (0x165) CcStat | |
| GM | Disabled | - | No ACC Main signal |
| Honda Nidec | Enabled | SCM_FEEDBACK (0x326) MAIN_ON | |
| Honda Bosch | Enabled | SCM_FEEDBACK (0x326) MAIN_ON | |
| Hyundai | Enabled | SCC11 (0x420) bit 0 | |
| Hyundai CAN-FD | Enabled | SCC_CONTROL (0x1A0) bit 66 | |
| Hyundai Legacy | Enabled | SCC11 (0x420) bit 0 | |
| Mazda | Enabled | CRZ_CTRL (0x21C) bit 17 | |
| Nissan | Enabled | CRUISE_THROTTLE (0x239) bit 17 | |
| PSA | Disabled | - | Not implemented |
| Rivian | Disabled | - | Different architecture |
| Subaru | Enabled | CruiseControl (0x240) bit 40 | |
| Subaru Preglobal | Enabled | CruiseControl (0x144) bit 48 | |
| Tesla | Disabled | - | Different architecture |
| Toyota | Enabled | PCM_CRUISE_2 (0x1D3) bit 15 | |
| Toyota (UNSUPPORTED_DSU) | Enabled | DSU_CRUISE (0x365) bit 0 | |
| VW MQB | Enabled | TSK_06 TSK_Status (>=2) | |
| VW PQ | Enabled | Motor_5 (0x480) bit 50 (long) | |

---

## Permission Model

Lateral control requires checks at both layers. Normal path uses `controls_allowed`, ALKA path uses additional checks.

| Check | Panda | openpilot | Notes |
|-------|:-----:|:---------:|-------|
| **Normal Path** |
| `controls_allowed` (cruise engaged) | ✓ | ✓ | Either this OR ALKA path |
| **ALKA Path** |
| `alka_allowed` (brand supports) | ✓ | ✓ | Set per brand in safety init |
| `ALT_EXP_ALKA` (user enabled) | ✓ | ✓ | alternativeExperience flag |
| `lkas_on` (ACC Main ON) | ✓ | ✓ | Tracked via CAN messages |
| `vehicle_moving` / `!standstill` | ✓ | ✓ | |
| **openpilot Additional** |
| `gear_ok` (not P/N/R) | ✗ | ✓ | Python layer only |
| `calibrated` | ✗ | ✓ | Python layer only |
| `seatbelt latched` | ✗ | ✓ | Python layer only |
| `doors closed` | ✗ | ✓ | Python layer only |
| `!steerFaultTemporary` | ✗ | ✓ | Python layer only |
| `!steerFaultPermanent` | ✗ | ✓ | Python layer only |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CAN Bus                                      │
└─────────────────────────────────────────────────────────────────────┘
                    │                              │
                    ▼                              ▼
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│  Safety Layer (panda C code)    │  │  Python Layer                   │
│                                 │  │                                 │
│  rx_hook:                       │  │  carstate.py:                   │
│  - Parse ACC Main signal        │  │  - Parse cruiseState.available  │
│  - Set lkas_on = acc_main_on    │  │  - Set self.lkas_on             │
│                                 │  │                                 │
│  lat_control_allowed():         │  └─────────────┬───────────────────┘
│  - Check lkas_on + other flags  │                │
│  - Gate steering commands       │                ▼
└─────────────────────────────────┘  ┌─────────────────────────────────┐
                                     │  card.py:                       │
                                     │  - Publish carStateExt.lkasOn   │
                                     └─────────────┬───────────────────┘
                                                   │
                                                   ▼
                                     ┌─────────────────────────────────┐
                                     │  controlsd.py:                  │
                                     │  - Read carStateExt.lkasOn      │
                                     │  - Check ALKA conditions        │
                                     │  - Set CC.latActive             │
                                     └─────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `custom.capnp` | Defines `CarStateExt` struct with `lkasOn` field |
| `log.capnp` | Includes `carStateExt` in event union |
| `interfaces.py` | Defines `self.lkas_on = False` default in `CarStateBase` |
| `carstate.py` (per brand) | Tracks `lkas_on` based on ACC Main |
| `card.py` | Publishes `carStateExt.lkasOn` from `CI.CS.lkas_on` |
| `controlsd.py` | Reads `carStateExt.lkasOn` to determine `alka_active` |

---

## ACC Main Tracking

All brands use simple direct tracking:

```c
// Panda (C code)
if (alka_allowed && (alternative_experience & ALT_EXP_ALKA)) {
  lkas_on = acc_main_on;  // or GET_BIT(msg, bit_position)
}
```

```python
# Python carstate.py
self.lkas_on = ret.cruiseState.available
```

This guard ensures:
1. Brand supports ALKA (`alka_allowed`)
2. User enabled ALKA (`ALT_EXP_ALKA`)

Without both conditions, no ACC Main tracking occurs, and ALKA remains disabled.

---

## Testing

Safety tests verify:
- `alka_allowed` flag set correctly per brand
- ACC Main tracking updates `lkas_on` directly
- `lat_control_allowed()` returns true only when all conditions met
- Steering TX blocked when ALKA conditions not met
- Bus routing variants (camera_scc, unsupported_dsu)
