#!/usr/bin/env python3
"""Run lateral_maneuversd against a synthetic lateral plant and write an rlog.

    ./tools/lateral_maneuvers/sim_maneuvers.py --out /tmp/lat_rlog.zst
    ./tools/lateral_maneuvers/generate_report.py /tmp/lat_rlog.zst
"""
import argparse
import re
from pathlib import Path

from openpilot.common.constants import CV
from openpilot.tools.lateral_maneuvers.lateral_maneuversd import MANEUVERS
from openpilot.tools.longitudinal_maneuvers.sim_harness import ManeuverSim, Plant

CURV_TAU = 0.05  # controlsd curvature command tracking
RACK_WN = 8.0    # steering rack + tire natural frequency (rad/s)
RACK_ZETA = 0.7  # underdamped, so achieved curvature overshoots like a real rack
CRUISE_ACCEL = 1.2

SET_SPEED_RE = re.compile(r"Set speed to (\d+) mph")


class LateralPlant(Plant):
  PLAN = 'lateralManeuverPlan'

  def __init__(self):
    super().__init__(v_ego=MANEUVERS[0].initial_speed)
    self.sim = None
    self._rack_rate = 0.0
    self.target_speed = MANEUVERS[0].initial_speed
    self._by_description = {m.description: m.initial_speed for m in MANEUVERS}

  def _update_target(self):
    if self.sim is None:
      return
    speed = self._by_description.get(self.sim.alert2)
    if speed is None:
      match = SET_SPEED_RE.search(self.sim.alert1)
      speed = float(match.group(1)) * CV.MPH_TO_MS if match else None
    if speed is not None:
      self.target_speed = speed

  def step(self, dt, plan):
    self._update_target()

    err = self.target_speed - self.v_ego
    self.a_ego = max(min(err / 1.0, CRUISE_ACCEL), -CRUISE_ACCEL)
    self.v_ego = max(self.v_ego + self.a_ego * dt, 0.0)

    desired_curvature = float(plan.desiredCurvature) if plan is not None else 0.0
    self.curvature += (dt / (CURV_TAU + dt)) * (desired_curvature - self.curvature)

    self._rack_rate += dt * (RACK_WN ** 2 * (self.curvature - self.achieved_curvature) - 2 * RACK_ZETA * RACK_WN * self._rack_rate)
    self.achieved_curvature += dt * self._rack_rate
    self.lat_accel = self.achieved_curvature * max(self.v_ego, 1.0) ** 2


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--out", type=Path, default=Path("/tmp/lateral_maneuvers_sim/rlog.zst"))
  parser.add_argument("--max-maneuvers", type=int, default=0, help="stop after N maneuvers (0 = all)")
  parser.add_argument("--timeout", type=float, default=900.0)
  args = parser.parse_args()

  sim = ManeuverSim("openpilot.tools.lateral_maneuvers.lateral_maneuversd", LateralPlant(),
                    max_maneuvers=args.max_maneuvers, timeout=args.timeout)
  out = sim.run(args.out)
  print(f"\nmaneuvers seen: {sim.seen_maneuvers}")
  print(f"rlog: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
  main()
