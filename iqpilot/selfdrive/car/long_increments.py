"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass

from openpilot.common.params import Params

# Cruise set-speed step (in the caller's working unit, kph or the imperial increment)
# a user is allowed to dial in for the accel/decel cruise buttons.
MIN_BUTTON_STEP = 1
MAX_BUTTON_STEP = 10

# Once the resolved step reaches this size, we snap the set speed to the nearest
# multiple of the step (e.g. a step of 5 lands on 45/50/55...) instead of just
# adding it on top of whatever odd number the set speed currently sits at.
SNAP_TO_GRID_THRESHOLD = 5

# Stock behavior (feature disabled): tap moves by one unit, a held button moves
# five times faster. This mirrors what every other unmodified button-input car
# already does, so it's kept as the fallback rather than living in this module.
STOCK_HOLD_MULTIPLIER = 5


@dataclass(frozen=True)
class LongIncrementConfig:
  enabled: bool
  tap_step: int
  hold_step: int


def _clamp_step(value) -> int:
  try:
    step = int(value)
  except (TypeError, ValueError):
    return MIN_BUTTON_STEP
  return min(max(step, MIN_BUTTON_STEP), MAX_BUTTON_STEP)


def read_long_increment_config(params: Params) -> LongIncrementConfig:
  return LongIncrementConfig(
    enabled=params.get_bool("LongIncrementsEnabled"),
    tap_step=_clamp_step(params.get("LongIncrementTapStep", return_default=True)),
    hold_step=_clamp_step(params.get("LongIncrementHoldStep", return_default=True)),
  )


def resolve_button_step(config: LongIncrementConfig, held: bool, unit_step: float) -> tuple[bool, float]:
  """
  Turn a single tap/hold cruise button event into a (snap_to_grid, delta) pair,
  where delta is expressed in the same unit as unit_step (kph, or the mph-derived
  increment used for imperial cars).
  """
  if not config.enabled:
    return held, unit_step * (STOCK_HOLD_MULTIPLIER if held else 1)

  multiplier = config.hold_step if held else config.tap_step
  snap_to_grid = multiplier >= SNAP_TO_GRID_THRESHOLD
  return snap_to_grid, unit_step * multiplier
